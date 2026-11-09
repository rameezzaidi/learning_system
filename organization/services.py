"""Oracle -> EduPulse sync.

Oracle is the master for every record it sends (source="oracle"): those are created/updated/deactivated
by the sync. Records added by hand (source="manual") are never touched.
"""
import re
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from accounts.models import User

from .models import Campus, Region, StudentProfile, SyncRun, SyncSettings, validate_readonly_sql

STAT_KEYS = [
    "regions_created", "regions_updated", "regions_deactivated",
    "campuses_created", "campuses_updated", "campuses_deactivated",
    "students_created", "students_updated", "students_deactivated",
]


class SyncBusy(Exception):
    pass


def oracle_configured():
    if settings.ORACLE_MOCK:
        return True
    o = settings.ORACLE
    return bool(o["DSN"] or (o["HOST"] and o["SERVICE"])) and bool(o["USER"] and o["PASSWORD"])


def oracle_target():
    """Human readable (password-free) connection target for the UI."""
    if settings.ORACLE_MOCK:
        return "DEMO MODE (dummy data, no Oracle)"
    o = settings.ORACLE
    return o["DSN"] or (f'{o["HOST"]}:{o["PORT"]}/{o["SERVICE"]}' if o["HOST"] else "")


class OracleConnector:
    """Thin read-only wrapper around python-oracledb (thin mode: no Oracle Client install needed)."""

    def _dsn(self):
        o = settings.ORACLE
        return o["DSN"] or f'{o["HOST"]}:{o["PORT"]}/{o["SERVICE"]}'

    def fetch(self, sql):
        if not oracle_configured():
            raise RuntimeError("Oracle connection is not configured (set the ORACLE_* environment variables).")
        try:
            import oracledb
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Package 'oracledb' is not installed. Run: pip install oracledb") from e
        o = settings.ORACLE
        with oracledb.connect(user=o["USER"], password=o["PASSWORD"], dsn=self._dsn()) as conn:
            cur = conn.cursor()
            cur.execute(sql.strip().rstrip(";"))
            cols = [d[0].lower() for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def ping(self):
        self.fetch("SELECT 1 AS ok FROM dual")


def get_connector():
    """Real Oracle, or the dummy-data stand-in when ORACLE_MOCK=1."""
    if settings.ORACLE_MOCK:
        from .mock import MockOracle

        return MockOracle(settings.ORACLE_MOCK_STUDENTS, settings.ORACLE_MOCK_ROUND)
    return OracleConnector()


# ---------- helpers ----------

def _s(v):
    return "" if v is None else str(v).strip()


def _ext(v):
    s = _s(v)
    return s[:-2] if s.endswith(".0") else s  # Oracle NUMBER may arrive as 12.0


def _unique_username(base, ext):
    base = re.sub(r"[^\w.@+-]", "", base)[:140] or f"std{ext}"
    if not User.objects.filter(username=base).exists():
        return base
    cand = f"{base}-{ext}"[:150]
    n = 1
    while User.objects.filter(username=cand).exists():
        n += 1
        cand = f"{base}-{ext}-{n}"[:150]
    return cand


def _maybe_deactivate(qs, seen, total_rows, enabled, label, errors, key="external_id__in"):
    """Deactivate Oracle records missing from the feed, but only when the feed looks trustworthy."""
    if not enabled:
        return 0
    if total_rows == 0:
        if qs.exists():
            errors.append(f"{label}: Oracle returned 0 rows, so nothing was deactivated.")
        return 0
    if len(seen) < total_rows:
        errors.append(f"{label}: some rows had errors, so deactivation was skipped this run.")
        return 0
    return qs.exclude(**{key: seen}).update(is_active=False)


# ---------- entity syncs ----------

def _sync_regions(rows, stats, errors, deactivate):
    seen = set()
    for r in rows:
        try:
            ext, name = _ext(r.get("external_id")), _s(r.get("name"))
            if not ext or not name:
                raise ValueError("missing external_id or name")
            with transaction.atomic():
                _, created = Region.objects.update_or_create(
                    external_id=ext,
                    defaults={"name": name, "code": _s(r.get("code")), "source": "oracle", "is_active": True},
                )
            seen.add(ext)
            stats["regions_created" if created else "regions_updated"] += 1
        except Exception as e:
            errors.append(f"Region {r.get('external_id')!r}: {e}")
    stats["regions_deactivated"] = _maybe_deactivate(
        Region.objects.filter(source="oracle", is_active=True), seen, len(rows), deactivate, "Regions", errors)


def _sync_campuses(rows, stats, errors, deactivate):
    regions = {r.external_id: r for r in Region.objects.exclude(external_id=None)}
    seen = set()
    for r in rows:
        try:
            ext, name, reg_ext = _ext(r.get("external_id")), _s(r.get("name")), _ext(r.get("region_id"))
            if not ext or not name:
                raise ValueError("missing external_id or name")
            region = regions.get(reg_ext)
            if region is None:
                raise ValueError(f"unknown region {reg_ext!r}")
            with transaction.atomic():
                _, created = Campus.objects.update_or_create(
                    external_id=ext,
                    defaults={"region": region, "name": name, "code": _s(r.get("code")),
                              "source": "oracle", "is_active": True},
                )
            seen.add(ext)
            stats["campuses_created" if created else "campuses_updated"] += 1
        except Exception as e:
            errors.append(f"Campus {r.get('external_id')!r}: {e}")
    stats["campuses_deactivated"] = _maybe_deactivate(
        Campus.objects.filter(source="oracle", is_active=True), seen, len(rows), deactivate, "Campuses", errors)


def _sync_students(rows, stats, errors, deactivate):
    campuses = {c.external_id: c for c in Campus.objects.exclude(external_id=None)}
    profiles = {p.external_id: p for p in StudentProfile.objects.filter(source="oracle").select_related("user")}
    now = timezone.now()
    seen = set()
    for r in rows:
        try:
            ext = _ext(r.get("external_id"))
            first, last = _s(r.get("first_name")), _s(r.get("last_name"))
            if not ext or not (first or last):
                raise ValueError("missing external_id or name")
            campus_ext = _ext(r.get("campus_id"))
            campus = campuses.get(campus_ext) if campus_ext else None
            if campus_ext and campus is None:
                raise ValueError(f"unknown campus {campus_ext!r}")
            adm = _s(r.get("admission_no"))
            with transaction.atomic():
                p = profiles.get(ext)
                if p:
                    u = p.user
                    u.first_name, u.last_name = first, last
                    u.email, u.phone, u.is_active = _s(r.get("email")), _s(r.get("phone")), True
                    u.save()
                    p.campus, p.admission_no, p.last_synced_at = campus, adm, now
                    p.save()
                    stats["students_updated"] += 1
                else:
                    u = User(
                        username=_unique_username(adm or f"std{ext}", ext), first_name=first, last_name=last,
                        email=_s(r.get("email")), phone=_s(r.get("phone")), role=User.Role.STUDENT, is_active=True,
                    )
                    u.set_password(settings.STUDENT_DEFAULT_PASSWORD)
                    u.save()
                    StudentProfile.objects.create(
                        user=u, campus=campus, admission_no=adm, external_id=ext, source="oracle", last_synced_at=now
                    )
                    stats["students_created"] += 1
            seen.add(ext)
        except Exception as e:
            errors.append(f"Student {r.get('external_id')!r}: {e}")
    stats["students_deactivated"] = _maybe_deactivate(
        User.objects.filter(student_profile__source="oracle", is_active=True),
        seen, len(rows), deactivate, "Students", errors, key="student_profile__external_id__in",
    )


# ---------- orchestration ----------

def run_sync(trigger="manual", connector=None):
    """Run one full sync (regions -> campuses -> students). Returns the SyncRun log row."""
    cfg = SyncSettings.load()
    if SyncRun.objects.filter(status="running", started_at__gte=timezone.now() - timedelta(hours=2)).exists():
        raise SyncBusy("A sync is already running.")
    run = SyncRun.objects.create(trigger=trigger, status="running")
    stats = {k: 0 for k in STAT_KEYS}
    errors = []
    try:
        for q in (cfg.sql_regions, cfg.sql_campuses, cfg.sql_students):
            validate_readonly_sql(q)
        conn = connector or get_connector()
        if hasattr(conn, "fetch_dataset"):  # demo / dummy source
            data = conn.fetch_dataset()
        else:
            data = {
                "regions": conn.fetch(cfg.sql_regions),
                "campuses": conn.fetch(cfg.sql_campuses),
                "students": conn.fetch(cfg.sql_students),
            }
        stats.update({f"fetched_{k}": len(v) for k, v in data.items()})
        _sync_regions(data["regions"], stats, errors, cfg.deactivate_missing)
        _sync_campuses(data["campuses"], stats, errors, cfg.deactivate_missing)
        _sync_students(data["students"], stats, errors, cfg.deactivate_missing)
        run.status = "partial" if errors else "success"
    except Exception as e:
        run.status = "failed"
        errors.append(f"{type(e).__name__}: {e}")
    run.stats = stats
    run.errors = "\n".join(errors[:200])
    run.finished_at = timezone.now()
    run.save()
    return run


def start_background_sync(trigger="manual"):
    """Start a sync in a background thread so the web request returns immediately."""

    def target():
        try:
            run_sync(trigger)
        except SyncBusy:
            pass
        finally:
            close_old_connections()

    threading.Thread(target=target, daemon=True).start()


def is_running():
    return SyncRun.objects.filter(status="running", started_at__gte=timezone.now() - timedelta(hours=2)).exists()
