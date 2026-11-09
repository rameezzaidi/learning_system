from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def notifications(request):
    from reports.engine import page_links
    pg = Paginator(Notification.objects.filter(user=request.user), 20)
    page = pg.get_page(request.GET.get("page"))
    return render(request, "core/notifications.html", {
        "page_obj": page, "page": "notifications", "links": page_links(page.number, pg.num_pages), "qs_page": "",
        "prev_n": max(page.number - 1, 1), "next_n": min(page.number + 1, pg.num_pages)})


@login_required
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    ok = n.url and url_has_allowed_host_and_scheme(n.url, allowed_hosts=None) and n.url.startswith("/")
    return redirect(n.url if ok else "core_notifications")


@login_required
@require_POST
def notifications_read_all(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect(request.POST.get("next") if (request.POST.get("next") or "").startswith("/") else "core_notifications")
