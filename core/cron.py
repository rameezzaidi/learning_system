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
