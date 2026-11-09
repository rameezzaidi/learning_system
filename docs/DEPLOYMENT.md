# Deploying EduPulse

**Docker (recommended):** `cp .env.example .env`, fill `SECRET_KEY`, `ALLOWED_HOSTS`, `DB_PASSWORD`, then `docker compose up --build`. Put nginx/Caddy/Cloudflare in front for HTTPS, then set `HTTPS=1` and `SECURE_SSL_REDIRECT=1`.

**Without Docker:** Python 3.12, PostgreSQL 16, `pip install -r requirements.txt`, `DEBUG=0` + the variables in `.env.example`, `python manage.py migrate && python manage.py collectstatic`, run `gunicorn config.wsgi`. Static files are served by WhiteNoise. Serve `/media/` (profile photos, chat files) from your web server or object storage.

**Checks before go-live:** `python manage.py check --deploy` must be clean (the HSTS-preload note is optional); `/healthz/` returns `{"status": "ok"}` for load balancers; set a real `STUDENT_DEFAULT_PASSWORD`; change the demo passwords or never run `seed_demo` in production.

**Scheduled jobs:** run `python manage.py assign_nuggets` daily (cron / Task Scheduler).

**Backups:** daily `pg_dump` plus a copy of `media/`.
