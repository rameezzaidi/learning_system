from django.conf import settings
from django.shortcuts import redirect


class EnforceTwoFactor:
    """If the school requires two-factor for a role (REQUIRE_2FA_ROLES), send those users to set it up first."""

    ALLOWED = ("/security/", "/logout/", "/static/", "/media/", "/password/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        roles = getattr(settings, "REQUIRE_2FA_ROLES", ())
        u = getattr(request, "user", None)
        if roles and u is not None and u.is_authenticated and u.role in roles and not request.path.startswith(self.ALLOWED):
            tf = getattr(u, "twofactor", None)
            if not (tf and tf.enabled):
                return redirect("accounts:twofa_setup")
        return self.get_response(request)
