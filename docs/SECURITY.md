# Security & privacy notes

- Roles are enforced on the server for every page (admin / teacher / student / parent); chat, profiles and nuggets have extra per-object checks.
- Passwords: 8+ characters, common/numeric/similar passwords rejected. Login is locked for 15 minutes after 5 failures (per username + IP). Sessions last 12 hours.
- Production mode (`DEBUG=0`) refuses to start without a strong `SECRET_KEY` and `ALLOWED_HOSTS`, and turns on HTTPS redirect, secure cookies, HSTS, no-sniff and clickjacking protection.
- AI: only anonymised numbers (exam percentages) or the teacher's own lesson text are sent to the AI provider — never names, emails or ids. AI-made nuggets stay hidden until a teacher approves them (Settings › Learning & AI can switch that off). The tutor is limited to 20 questions per student per hour.
- Uploads: avatars ≤ 3 MB images; chat files ≤ 8 MB with dangerous extensions blocked.
- Audit trail: approvals/rejections of nuggets and publishing of results are written to the `audit` log.
- API keys live only in `.env` / environment variables. Rotate any key that was ever pasted into chat, email or screenshots.

Known limits (planned): no two-factor sign-in yet, no Content-Security-Policy header yet (templates use inline scripts), chat is polling not websockets, antivirus scanning of uploads is not included.
