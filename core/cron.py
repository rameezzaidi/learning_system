"""Daily job endpoint for hosts without a scheduler (Vercel Cron, cron-job.org, ...).

Protected by CRON_SECRET: the caller must send `Authorization: Bearer <CRON_SECRET>`
(Vercel Cron does this automatically when the CRON_SECRET environment variable is set).
With no CRON_SECRET configured the endpoint is disabled.
"""
import hmac
import io

from django.conf import settings
from django.core.management import call_command
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def daily(request):
    secret = getattr(settings, "CRON_SECRET", "")
    sent = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(sent.encode(), f"Bearer {secret}".encode()):
        return JsonResponse({"error": "forbidden"}, status=403)
    out = {}
    for name in ("generate_fees", "scan_risk"):
        buf = io.StringIO()
        try:
            call_command(name, stdout=buf)
            out[name] = buf.getvalue().strip()[:300]
        except Exception as e:  # one failing job must not block the other
            out[name] = f"error: {e.__class__.__name__}"
    return JsonResponse(out)


def _authorized(request):
    secret = getattr(settings, "CRON_SECRET", "")
    sent = request.headers.get("Authorization", "")
    return bool(secret) and hmac.compare_digest(sent.encode(), f"Bearer {secret}".encode())


def setup(request):
    """One-off remote setup for hosts with no shell (Vercel): POST /cron/setup/ runs `migrate`;
    add ?seed=1 to also load the demo data (safe to repeat). Same CRON_SECRET bearer protection."""
    if request.method != "POST":
        return JsonResponse({"error": "use POST"}, status=405)
    if not _authorized(request):
        return JsonResponse({"error": "forbidden"}, status=403)
    out = {}
    steps = [("migrate", {"interactive": False, "verbosity": 0})]
    if request.GET.get("seed") == "1":
        steps.append(("seed_demo", {}))
    for name, kw in steps:
        buf = io.StringIO()
        try:
            call_command(name, stdout=buf, **kw)
            out[name] = "ok"
        except Exception as e:
            out[name] = f"error: {e.__class__.__name__}: {str(e)[:200]}"
            break
    return JsonResponse(out)
