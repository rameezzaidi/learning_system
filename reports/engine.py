"""Crystal-Reports-style engine: group, subtotal, then cut into fixed-size printed pages.

build_lines()  -> flat list of lines: group headers ("g"), detail rows ("d"), subtotals ("s")
paginate()     -> pages (lists of lines). A group that continues on the next page gets its header
                  repeated ("continued"), headers never sit alone at the bottom of a page, and a
                  subtotal always stays with its last detail row.
"""
from itertools import groupby

GROUPINGS = {
    "region_campus": ("Region › Campus", ["region", "campus"]),
    "region": ("Region", ["region"]),
    "campus": ("Campus", ["campus"]),
    "none": ("No grouping", []),
}
ROWS_PER_PAGE = (15, 20, 25)
MIN_ROWS = 8

# key, label, weight (relative width), align
BASE_COLUMNS = [
    ("no", "#", 4, "r"), ("admission", "Admission No", 12, "l"), ("name", "Student Name", 17, "l"),
    ("username", "Username", 12, "l"), ("phone", "Phone", 12, "l"), ("email", "Email", 27, "l"),
    ("status", "Status", 7, "l"), ("source", "Source", 7, "l"),
]
EXTRA = {"region": ("region", "Region", 11, "l"), "campus": ("campus", "Campus", 18, "l")}


def columns_for(group):
    levels = GROUPINGS.get(group, GROUPINGS["region_campus"])[1]
    extra = [EXTRA[k] for k in ("region", "campus") if k not in levels]
    if group == "campus":  # campus group label already carries the region
        extra = [c for c in extra if c[0] != "region"]
    cols = BASE_COLUMNS[:3] + extra + BASE_COLUMNS[3:]
    total = sum(c[2] for c in cols)
    return [{"key": k, "label": lbl, "pct": round(w * 100 / total, 2), "align": a} for k, lbl, w, a in cols]


def student_rows(users):
    rows = []
    for u in users:
        p = getattr(u, "student_profile", None)
        campus = p.campus if p and p.campus_id else None
        rows.append({
            "name": u.display_name, "username": u.username, "email": u.email, "phone": u.phone,
            "admission": p.admission_no if p else "", "active": u.is_active,
            "status": "Active" if u.is_active else "Inactive",
            "source": "Oracle" if p and p.is_external else "Manual",
            "region": campus.region.name if campus else "No region",
            "campus": campus.name if campus else "No campus",
            "_no_campus": campus is None,
        })
    rows.sort(key=lambda r: (r["_no_campus"], r["region"].lower(), r["campus"].lower(), r["name"].lower()))
    return rows


def _group_key(level, levels):
    if level == "campus" and "region" not in levels:
        return lambda r: f'{r["region"]} › {r["campus"]}'
    return lambda r: r[level]


def _emit(rows, levels, depth, lines):
    if depth == len(levels):
        lines.extend({"t": "d", "row": r} for r in rows)
        return
    for label, grp in groupby(rows, key=_group_key(levels[depth], levels)):
        grp = list(grp)
        lines.append({"t": "g", "depth": depth, "label": label, "count": len(grp)})
        _emit(grp, levels, depth + 1, lines)
        lines.append({"t": "s", "depth": depth, "label": label, "count": len(grp),
                      "active": sum(1 for r in grp if r["active"])})


def build_lines(rows, group="region_campus"):
    levels = GROUPINGS.get(group, GROUPINGS["region_campus"])[1]
    lines = []
    _emit(rows, levels, 0, lines)
    n = 0
    for ln in lines:
        if ln["t"] == "d":
            n += 1
            ln["row"] = dict(ln["row"], no=n)
    total = len(rows)
    active = sum(1 for r in rows if r["active"])
    oracle = sum(1 for r in rows if r["source"] == "Oracle")
    lines.append({"t": "grand", "count": total, "active": active, "inactive": total - active,
                  "oracle": oracle, "manual": total - oracle})
    return lines


def paginate(lines, per_page):
    """Return (pages, toc). Each page is a list of lines; toc lists groups with their first page."""
    per_page = max(int(per_page), MIN_ROWS)
    pages, cur, open_groups, toc = [], [], [], []

    def break_page():
        nonlocal cur
        pages.append(cur)
        cur = [dict(g, cont=True) for g in open_groups]

    for i, ln in enumerate(lines):
        if ln["t"] == "g":
            need = 3  # header + at least two following lines
        elif ln["t"] == "d":
            need = 1
            j = i + 1
            while j < len(lines) and lines[j]["t"] == "s":  # keep subtotals with the last row
                need += 1
                j += 1
        elif ln["t"] == "grand":
            need = 2
        else:
            need = 1
        if cur and len(cur) + need > per_page:
            break_page()
        if ln["t"] == "g":
            open_groups.append(ln)
            toc.append({"depth": ln["depth"], "label": ln["label"], "count": ln["count"], "page": len(pages) + 1})
        elif ln["t"] == "s":
            open_groups.pop()
        cur.append(ln)
    pages.append(cur)
    return pages, toc


def page_links(current, total, window=2):
    """[1, None, 4, 5, 6, 7, 8, None, 20] where None is an ellipsis."""
    nums = sorted({1, total} | set(range(max(1, current - window), min(total, current + window) + 1)))
    out, prev = [], 0
    for n in nums:
        if n - prev > 1:
            out.append(None)
        out.append(n)
        prev = n
    return out


def filter_summary(params, region=None, campus=None):
    bits = []
    if region:
        bits.append(f"Region: {region}")
    if campus == "none":
        bits.append("Campus: none assigned")
    elif campus:
        bits.append(f"Campus: {campus}")
    if params.get("source"):
        bits.append("Source: " + params["source"].title())
    if params.get("status"):
        bits.append("Status: " + params["status"].title())
    if params.get("q"):
        bits.append(f'Search: "{params["q"]}"')
    return " · ".join(bits) if bits else "All students"
