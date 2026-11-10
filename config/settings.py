import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Optional local secrets file (never commit/share it): create `.env` next to manage.py with lines like
#   GEMINI_API_KEY=your_key_here        (no quotes needed)
# Real environment variables always win over the file.
_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# On Vercel the default is production mode (DEBUG off) even if the variable was forgotten.
DEBUG = os.environ.get("DEBUG", "0" if os.environ.get("VERCEL") else "1") == "1"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me-in-production")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*" if DEBUG else "").split(",") if h.strip()]
# Vercel reads settings by running manage.py at build time, before runtime secrets matter: skip the strict
# checks there. The deployed web function (not manage.py) still enforces them.
_BUILD_INTROSPECTION = bool(os.environ.get("VERCEL")) and os.path.basename(__import__("sys").argv[0]) == "manage.py"
if not DEBUG and not _BUILD_INTROSPECTION:
    from django.core.exceptions import ImproperlyConfigured
    if SECRET_KEY.startswith("dev-insecure") or len(SECRET_KEY) < 32:
        raise ImproperlyConfigured("Set a long random SECRET_KEY (32+ characters) when DEBUG=0.")
    if not ALLOWED_HOSTS and not os.environ.get("VERCEL"):
        raise ImproperlyConfigured("Set ALLOWED_HOSTS (comma separated) when DEBUG=0.")
SITE_NAME = os.environ.get("SITE_NAME", "EduPulse")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# Vercel: the platform sets VERCEL=1 and the deployment host names. Add them automatically.
ON_VERCEL = bool(os.environ.get("VERCEL"))
if ON_VERCEL:
    for _h in (os.environ.get("VERCEL_URL"), os.environ.get("VERCEL_BRANCH_URL"), os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")):
        if _h:
            if _h not in ALLOWED_HOSTS:
                ALLOWED_HOSTS.append(_h)
            if "https://" + _h not in CSRF_TRUSTED_ORIGINS:
                CSRF_TRUSTED_ORIGINS.append("https://" + _h)

try:  # optional: serves static files in production without nginx
    import whitenoise  # noqa: F401
    _has_whitenoise = True
except ImportError:
    _has_whitenoise = False

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "academics",
    "organization",
    "assessments",
    "exams",
    "reports",
    "chat",
    "nuggets",
    "curriculum",
    "fees",
    "attendance",
    "risk",
    "timetable",
    "sis",
    "bank",
    "insights",
    "campusops",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if _has_whitenoise else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.EnforceTwoFactor",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.school",
                "core.context_processors.bell",
                "chat.context.unread",
                "nuggets.context.badge",
                "academics.context.help_badge",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database: SQLite by default (zero setup). Set DATABASE_URL (Neon / Supabase / Render ...) or DB_ENGINE=postgres.
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url.startswith(("postgres://", "postgresql://")):
    from urllib.parse import parse_qs, unquote, urlparse
    _u = urlparse(_db_url)
    _q = {k: v[0] for k, v in parse_qs(_u.query).items()}
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": unquote(_u.path.lstrip("/")),
            "USER": unquote(_u.username or ""),
            "PASSWORD": unquote(_u.password or ""),
            "HOST": _u.hostname or "",
            "PORT": str(_u.port or 5432),
            "CONN_MAX_AGE": 0,   # serverless: do not keep connections open between invocations
            "DISABLE_SERVER_SIDE_CURSORS": True,   # needed behind the Neon pooler (pgbouncer)
            "OPTIONS": {"sslmode": _q.get("sslmode", "require")},
        }
    }
elif os.environ.get("DB_ENGINE", "sqlite") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "edupulse"),
            "USER": os.environ.get("DB_USER", "postgres"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# Brute-force protection on the login page (per username + IP)
LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCK_SECONDS = int(os.environ.get("LOGIN_LOCK_SECONDS", "900"))

# Roles that must use two-factor, e.g. REQUIRE_2FA_ROLES=super_admin,head_office,principal (empty = optional for everyone)
REQUIRE_2FA_ROLES = tuple(r.strip() for r in os.environ.get("REQUIRE_2FA_ROLES", "").split(",") if r.strip())

# Secret for /cron/daily/ (fee generation + risk scan). Empty = endpoint disabled.
CRON_SECRET = os.environ.get("CRON_SECRET", "")

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_ROOT = BASE_DIR / "private"  # student documents (never served directly)
if ON_VERCEL:
    # The deployment disk is read-only and uploads would vanish anyway. /tmp keeps the app from crashing,
    # but uploaded files are NOT permanent. Use object storage before relying on uploads (see README).
    MEDIA_ROOT = Path("/tmp/media")
    PRIVATE_ROOT = Path("/tmp/private")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Oracle (third-party student data). Credentials come from environment variables only.
# Use either ORACLE_DSN ("host:1521/service") or ORACLE_HOST + ORACLE_PORT + ORACLE_SERVICE.
ORACLE = {
    "DSN": os.environ.get("ORACLE_DSN", ""),
    "HOST": os.environ.get("ORACLE_HOST", ""),
    "PORT": os.environ.get("ORACLE_PORT", "1521"),
    "SERVICE": os.environ.get("ORACLE_SERVICE", ""),
    "USER": os.environ.get("ORACLE_USER", ""),
    "PASSWORD": os.environ.get("ORACLE_PASSWORD", ""),
}
# Demo mode: no Oracle needed. Sync / Test connection use generated dummy data instead.
ORACLE_MOCK = os.environ.get("ORACLE_MOCK", "0") == "1"
ORACLE_MOCK_STUDENTS = int(os.environ.get("ORACLE_MOCK_STUDENTS", "120"))
ORACLE_MOCK_ROUND = int(os.environ.get("ORACLE_MOCK_ROUND", "1"))
# Initial password given to students created by the Oracle sync. CHANGE THIS in production.
STUDENT_DEFAULT_PASSWORD = os.environ.get("STUDENT_DEFAULT_PASSWORD", "Student@123")

# AI (used from Phase 4 onward)
# AI provider: "auto" (first one whose key is set), "gemini" (free), "groq" (free), "ollama" (free, local), "anthropic", or "rules" (no AI)
AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto").lower()
AI_MODEL = os.environ.get("AI_MODEL", "")  # empty = sensible default for the provider
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


# ---------------------------------------------------------------- production hardening
# Cache (rate limits, tutor quota). Set REDIS_URL for several servers; the default in-memory cache is per process.
if os.environ.get("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": os.environ["REDIS_URL"]}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Email (notifications). Console in development; set EMAIL_HOST for real mail.
EMAIL_NOTIFICATIONS = os.environ.get("EMAIL_NOTIFICATIONS", "0") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "EduPulse <no-reply@localhost>")
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", str(60 * 60 * 12)))
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = os.environ.get("HTTPS", "1") == "1"
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", str(60 * 60 * 24 * 30)))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    if os.environ.get("BEHIND_PROXY", "1") == "1":   # nginx / load balancer terminates TLS
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    if _has_whitenoise:
        STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"}}

LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {"audit": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}

# Fees: bill the current month automatically the first time anyone opens the dashboard (at most every 6 hours).
# Also schedule `python manage.py generate_fees` daily. Disabled while running the test suite.
import sys as _sys
FEES_AUTO_GENERATE = os.environ.get("FEES_AUTO_GENERATE", "1") == "1"
if "test" in _sys.argv:
    FEES_AUTO_GENERATE = False
