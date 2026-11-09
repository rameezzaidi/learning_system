from functools import wraps

from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Allow only users whose role is in `roles`. Use below @login_required."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
