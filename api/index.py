"""Vercel entry point: exposes the Django WSGI app as `app`."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402

PREFIX = "/api/index"


def app(environ, start_response):
    """Vercel may hand us the function path (/api/index...) instead of the URL the visitor used. Strip it."""
    path = environ.get("PATH_INFO", "")
    if path == PREFIX or path.startswith(PREFIX + "/"):
        environ["PATH_INFO"] = path[len(PREFIX):] or "/"
        if "REQUEST_URI" in environ:
            environ["REQUEST_URI"] = environ["PATH_INFO"]
    return application(environ, start_response)
