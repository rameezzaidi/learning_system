import csv

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.decorators import role_required
from core.models import SchoolSettings
from organization.models import Campus, Region
from organization.queries import SORTS, sort_queryset, student_queryset

from . import engine
from .pdf import PDF_ROWS_PER_PAGE, render_pdf

TABLE_PAGE_SIZES = (10, 25, 50, 100)
FILTER_KEYS = ("region", "campus", "source", "status", "q")
from accounts.rbac import perm_required
from core import scope
admin_only = lambda v: login_required(perm_required("reports.view")(v))  # noqa: E731
export_only = lambda v: login_required(perm_required("reports.export")(v))  # noqa: E731


def _int(value, default, allowed=None, minimum=1):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if allowed is not None and n not in allowed:
        return default
    return max(n, minimum)


def _qs(params, *drop):
    p = params.copy()
    for k in drop:
        p.pop(k, None)
    return p.urlencode()


def _meta(request, group, g):
    region = Region.objects.filter(pk=g["region"]).first() if g.get("region", "").isdigit() else None
    campus = g.get("campus", "")
    if campus.isdigit():
        c = Campus.objects.filter(pk=campus).first()
        campus = c.name if c else ""
    now = timezone.localtime()
    return {
        "school": SchoolSettings.load().school_name,
        "title": f"Student Roll · {engine.GROUPINGS[group][0]}",
        "filters": engine.filter_summary(g, region.name if region else None, campus),
        "printed_by": request.user.display_name,
        "printed_at": now.strftime("%d %b %Y, %H:%M"),
    }


@admin_only
def students_report(request):
    g = {k: request.GET.get(k, "") for k in FILTER_KEYS}
    view = "report" if request.GET.get("view") == "report" else "table"
    qs = student_queryset(g, request.user)
    ctx = {
        "page": "reports", "view": view, "f": g,
        "regions": Region.objects.filter(campuses__in=scope.campuses_for(request.user)).distinct(),
        "campuses": scope.campuses_for(request.user),
        "qs_filters": _qs(request.GET, "page", "sort", "dir"),
        "qs_base": _qs(request.GET, "page"),
        "qs_view_table": _qs(request.GET, "page", "view"),
        "groupings": [(k, v[0]) for k, v in engine.GROUPINGS.items()],
        "table_sizes": TABLE_PAGE_SIZES, "report_sizes": engine.ROWS_PER_PAGE,
        "hidden": [(k, v) for k, v in request.GET.items() if k not in ("page", "print")],
    }

    if view == "table":
        sort = request.GET.get("sort") if request.GET.get("sort") in SORTS else "name"
        direction = "desc" if request.GET.get("dir") == "desc" else "asc"
        per_page = _int(request.GET.get("per_page"), 25, TABLE_PAGE_SIZES)
        paginator = Paginator(sort_queryset(qs, sort, direction), per_page)
        page_obj = paginator.get_page(request.GET.get("page"))
        heads = []
        for key, label in (("name", "Student"), ("admission", "Admission no"), ("region", "Region"),
                           ("campus", "Campus"), ("status", "Status"), ("source", "Source")):
            active = sort == key
            heads.append({"key": key, "label": label, "active": active, "dir": direction if active else "",
                          "next": "desc" if active and direction == "asc" else "asc"})
        ctx.update(page_obj=page_obj, per_page=per_page, sort=sort, dir=direction, heads=heads,
                   links=engine.page_links(page_obj.number, paginator.num_pages),
                   prev_n=max(page_obj.number - 1, 1), next_n=min(page_obj.number + 1, paginator.num_pages),
                   qs_sort=_qs(request.GET, "page", "sort", "dir"),
                   qs_page=_qs(request.GET, "page"))
        return render(request, "reports/students.html", ctx)

    # ---- Crystal-style report view ----
    group = request.GET.get("group") if request.GET.get("group") in engine.GROUPINGS else "region_campus"
    rpp = _int(request.GET.get("rpp"), 25, engine.ROWS_PER_PAGE)
    printing = request.GET.get("print") == "1"
    rows = engine.student_rows(qs)
    pages, toc = engine.paginate(engine.build_lines(rows, group), rpp)
    total = len(pages)
    current = min(_int(request.GET.get("page"), 1), total)
    ctx.update(
        group=group, rpp=rpp, columns=engine.columns_for(group), meta=_meta(request, group, g),
        total_pages=total, current=current, toc=toc, count=len(rows),
        qs_nav=_qs(request.GET, "page", "print"),
        qs_noview=_qs(request.GET, "page", "print"),
        pages_to_show=[(i, p) for i, p in enumerate(pages, start=1)] if printing else [(current, pages[current - 1])],
        printing=printing,
    )
    return render(request, "reports/print.html" if printing else "reports/students.html", ctx)


@export_only
def students_csv(request):
    g = {k: request.GET.get(k, "") for k in FILTER_KEYS}
    rows = engine.student_rows(student_queryset(g, request.user))
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="students.csv"'
    resp.write("﻿")  # BOM so Excel opens UTF-8 correctly
    w = csv.writer(resp)
    w.writerow(["Region", "Campus", "Admission No", "Student Name", "Username", "Email", "Phone", "Status", "Source"])
    for r in rows:
        w.writerow([r["region"] if not r["_no_campus"] else "", r["campus"] if not r["_no_campus"] else "",
                    r["admission"], r["name"], r["username"], r["email"], r["phone"], r["status"], r["source"]])
    return resp


@export_only
def students_pdf(request):
    g = {k: request.GET.get(k, "") for k in FILTER_KEYS}
    group = request.GET.get("group") if request.GET.get("group") in engine.GROUPINGS else "region_campus"
    rows = engine.student_rows(student_queryset(g, request.user))
    pages, _ = engine.paginate(engine.build_lines(rows, group), PDF_ROWS_PER_PAGE)
    data = render_pdf(pages, engine.columns_for(group), _meta(request, group, g))
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = 'inline; filename="student-report.pdf"'
    return resp
