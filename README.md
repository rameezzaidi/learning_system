# EduPulse — Student Assessment & Learning Platform (Python / Django)

Phase 1: project foundation, 4 roles, school-controlled themes.

## Roles
- Super Admin: manages users, links parents to students, controls school appearance
- Teacher, Student, Parent: own dashboard, own profile, optional personal theme

## Theme system
- 7 ready themes (Ocean, Emerald, Royal, Sunset, Rose, Graphite, Midnight dark)
- School can also set own brand colours, font, corner style, sidebar style
- Live preview on Settings > Appearance, saved for the whole school
- New theme = one block in static/css/themes.css + one line in core/themes.py

## Phase 2 (done): academics
- Super Admin: classes, subjects, add subject to class with teacher, enrol / move students
- Teacher: own courses, lessons (text, video/YouTube embed, link, file upload, draft/published), student progress bars
- Student: courses of own class, lessons, mark complete / undo, progress bar per course
- Parent: per-child progress page (read only)

## Organization + Oracle sync
- Structure: Region -> Campus -> Students. Manual add for all three, or Oracle sync.
- Oracle-sourced records are read-only in the UI; manual records are never touched by the sync.
- Credentials via env: ORACLE_HOST / ORACLE_PORT / ORACLE_SERVICE (or ORACLE_DSN), ORACLE_USER, ORACLE_PASSWORD
- Queries are editable in Oracle Sync settings (SELECT only). Required aliases are shown on that page.
- Automation: `python manage.py sync_oracle --loop` (or schedule `sync_oracle` with cron / Task Scheduler)
- New students get STUDENT_DEFAULT_PASSWORD (default Student@123, change it!)

## Dummy data (no Oracle needed)
- `python manage.py load_dummy_data` loads 3 regions (Southern, Central, Northern), 14 campuses, 120 students through the real sync engine
- `--students 500` for more, `--round 2` to simulate the next day (moves, renames, leavers, new joiners)
- `--reset` removes all Oracle-sourced data (run this before connecting your real Oracle)
- Optional: set `ORACLE_MOCK=1` so "Sync now" / "Test connection" / `sync_oracle --loop` use the dummy source

## Roadmap
- Phase 3: assessments, quizzes, gradebook, progress
- Phase 4: AI tutor, auto quiz generation, AI grading
- Phase 5: parent reports, at-risk alerts, analytics

## Run
See the commands in the chat message. Optional env vars: SECRET_KEY, DEBUG, DB_ENGINE=postgres
(DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT), ANTHROPIC_API_KEY (Phase 4).


## Reports (Student Report)
Reports -> Student Report (super admin). Two views of Region -> Campus -> Students:
- **Table view**: sortable columns, 10/25/50/100 per page, numbered pagination + "Go to page".
- **Report view** (Crystal-style): paged report with group tree (click to jump), continued group headers,
  subtotals, grand total, "Page X of Y", rows/page 15/20/25, group by Region+Campus / Region / Campus / none.
- Print (all pages, A4 landscape), PDF download (reportlab) and CSV export. Needs `pip install -r requirements.txt`.
The engine (`reports/engine.py`) is generic and can be reused for other lists.


## Assessments, Gradebook & Progress (Phase 3)
- Teacher/Admin: course -> **New assessment** (quiz/test/exam/homework; time limit, attempts, due date, show-answers on/off).
  Question types: Multiple choice, True/False, Short answer (auto-checked, accepted answers separated by `|`), Long answer (teacher marks).
  Publish only when it has questions. Results page -> Mark/Review each attempt (marks capped at max, feedback per answer).
- Student: Assessments -> Start/Continue/Try again; countdown timer auto-submits; late answers after the limit are not counted.
  Best attempt counts. Result page shows score, grade, correct answers (if enabled) and teacher feedback.
- Gradebook per course (best attempt %, average, letter A+/A/B/C/D/F, `*` = marking pending) + CSV export.
- Student **My Progress** (lessons + grades per subject) and parent's child page show assessment results too.
- Grade scale: 90 A+, 80 A, 70 B, 60 C, 50 D, below F (edit `assessments/grading.py: letter`).
- Demo: `seed_demo` adds a "Fractions Quiz" to Mathematics (login student1 / demo123).

## Coursera-style courses, generic items, games & Help desk (Phase 3b)
- Course = **Modules** (weeks/units) -> **Items**. Students get course cards with progress + Start/Continue,
  a course page with hero, syllabus accordion, instructor card, and a player (module sidebar, prev/next; completion is automatic, no button).
- Teacher builder (course page): add/edit/hide/reorder/delete modules and items. Item kinds are generic:
  Reading, Video (YouTube embed), Web link, File, **Embedded activity** (any https page: H5P, Wordwall, PhET, Genially...),
  **Built-in games** (Flashcards, Memory match, Word scramble - teacher types `front | back` lines) and **Quiz** (from Assessments;
  submitting the quiz completes the item). Finishing a game marks the item complete automatically.
- To add a new item kind: add it to `Lesson.Kind`, create `templates/academics/items/<kind>.html`, and (if needed) form validation.
- **Help desk**: students ask the teacher from any course/item ("Ask Teacher"); teachers/admin see them in "Help desk"
  (badge = open questions). Threads support follow-ups; either side can mark resolved; a new student reply reopens it.
- Existing lessons are moved into a default "Module 1" automatically by the migration.
- **Zero-click completion**: students never press "mark complete". Reading/link/file/embed (and non-YouTube video) complete when opened;
  YouTube videos complete when finished (or ~90% watched); games complete when finished; quizzes when submitted.
  Teacher/admin/parent views never change a student's progress.

## Examinations: marks, grades, report card, weak areas & AI suggestions (Phase 3d)
- **Admin** creates an Exam for a class (Examinations -> New exam), adds a paper per subject (total / pass marks), edits the grade scale (A+ ... F, GPA points) under *Grade scale*.
- **Teacher** enters marks for their own subject: grid (Enter jumps to next row, Absent checkbox) or CSV import (`username,name,marks`, `ABS` = absent; all-or-nothing, template download included).
- **Student-wise entry**: Examinations -> exam -> *Student-wise marks* -> open a student, enter ALL subjects on one page (live % and grade as you type; teachers can only edit their own subject). *Save & print report card* saves, prepares the weak areas + suggestions (English or Urdu (script)) and opens the print page.
- **Suggestions come in English AND Urdu (script) together**, with a study plan for the student: a Mon-Sun timetable (with tick boxes) and, for every weak subject, a 4-week plan (basics, practice, self-test, mock paper), daily minutes, a goal percentage and a checkpoint. Included on the report card, print and PDF. Class analysis is bilingual too.
- **Language per subject**: weak-area text and the study plan of *Urdu / Islamiat* subjects are written in Urdu script (right-to-left); every other subject is in English. The overall summary, strengths, habits and parent note come in English + Urdu (script). The PDF uses the bundled DejaVu font + `arabic-reshaper` / `python-bidi` (in requirements.txt), so run `pip install -r requirements.txt`.
- **Grading** is automatic: marks -> % -> grade/GPA -> pass/fail (each paper's pass mark counts) -> competition rank (1,2,2,4). Absent = 0 and fail.
- **Result sheet** (class-wide, CSV export), **Report card** (HTML, print, PDF) with you-vs-class-average bars and change vs the previous exam.
- **Weak areas**: subject under 60%, 10+ points below class average, big drop since last exam, absent, or poor quiz average.
- **Suggestions**: per student (weak areas, strengths, study plan, parent note, teacher note) and class-wide (weakest subjects, teaching actions, at-risk students). English or Urdu (script).
  AI is optional and can be FREE: set `GEMINI_API_KEY` (Google AI Studio) or `GROQ_API_KEY` (console.groq.com), or run Ollama locally (`AI_PROVIDER=ollama`, no key). `ANTHROPIC_API_KEY` also works. `AI_PROVIDER` = auto|gemini|groq|ollama|anthropic|rules, `AI_MODEL` optional. Without a provider or on any error the built-in rule-based guidance is used. Only anonymised marks are sent (no names/usernames).
- **Publish** makes report cards visible to students/parents; **Lock** freezes marks.


## Subject-aware assessment editor
The question editor adapts to the course's subject (detected from the subject name):
- **Maths / Algebra / Geometry...**: one toolbar (fractions, powers, roots, pi, <=, >=, integrals, angles...) that works on the question, options and explanation; formulas sit between `$ $` and are drawn with KaTeX (loaded from cdnjs, needs internet) in a live preview and on the student's quiz, result and review pages.
- **English / Grammar...**: spell-check on, blank / quote / ellipsis buttons, ready templates (fill in the blank, synonym, passive voice, comprehension...) and a word counter.
- **Urdu / Islamiat...**: right-to-left boxes and an on-screen Urdu keyboard (with Quranic marks); student pages show the questions right-to-left.
- Other subjects keep the standard editor. Kinds come from `core/subjects.py` (edit the word lists to add more).

## Premium UI + mobile (Phase 3e)
- `static/css/premium.css` (loaded after `app.css`): Inter font, glass topbar, refined sidebar, gradient buttons, soft shadows, larger touch targets, 16px inputs (no iOS zoom), safe-area support, reduced-motion support. All colours still follow the school theme.
- Phones/tablets: off-canvas drawer with overlay (tap outside, Esc, swipe left to close, swipe from the left edge to open); every table scrolls sideways inside its card (`static/js/app.js` wraps tables automatically); filters, page headers, report card, marks entry, games and editors re-flow to one column.
- Checked at 390px, 820px and 1440px on all roles: no page-level horizontal scroll.

## Phase 3e-2 — light identity, charts, pagination, animated login
- Light sidebar is now the default (migration `core/0002` switches existing "match theme" schools to light). Any theme still works from Appearance.
- New logo (`templates/partials/logo.html`), aligned in sidebar, topbar and login.
- `static/js/charts.js`: dependency-free SVG charts (donut, bar, hbar, line) driven by `data-chart` JSON. Used on all dashboards, report card and class analysis.
- Every table with more than 10 rows is paginated in the browser (10/25/50/100 rows). Set `data-nopage` on a `<table>` to opt out; tables with entry fields and server-paged lists are left alone.
- Login: animated gradient background, rotating feature line, sample report-card preview (ring and bars animate in). Respects "reduce motion".

## Dashboard v2
Admin dashboard: KPI cards (link to lists), quick-action tiles, setup strip with live Oracle-sync status, charts, "Needs attention" and "Recently added" with avatars. Student and teacher dashboards got quick-action tiles; the "coming soon" roadmap cards were removed.

## Phase 3f — Chat + Student profile

**Messages (Facebook/Messenger style)** — sidebar › Connect › Messages, for every role.
- Direct chats and groups, emoji, file/image attachments (≤ 8 MB, risky extensions blocked), read ticks ("seen") in direct chats, unread badge in the sidebar.
- Who can message whom: Admin → everyone · Teacher → admins, teachers, students & parents of their classes · Student → admins, classmates, class teachers · Parent → admins, teachers of their children's classes.
- Polling based (messages every 2.5 s, list every 6 s) — no websockets/Redis needed. Can be upgraded to Django Channels later.

**Student profile** — `/students/<id>/profile/`
- Cover + photo header, About, guardians, learning progress, KPI cards, term-wise trend chart, latest-term subject chart, subject × term matrix with trend, and an expandable record per term (marks, %, grade, position, result, change vs previous term, strong/weak subjects, report-card link).
- Admin (students list name), teacher of the class, the student themselves (sidebar › My Academic Record) and parents (sidebar › Profile · child) can open it. Students/parents see only **published** exams.
- Profile photo + "About me" can be set in My Profile (needs `Pillow`; uploads go to `media/`).

Setup after update: `pip install -r requirements.txt` then `python manage.py migrate`.

### Quick start (Windows)
Double-click `run.bat` (or `.\run.ps1`). It asks for the Gemini key (never stored in files), installs requirements, migrates, seeds demo data once and starts the server.

## Phase 3g — Nuggets (Century-style micro-lessons) + auto activities

- **Nugget** = one idea in 3–8 minutes: Learn (explanation, key points, optional video) → Practice (flashcards) → Quick check (auto-graded, 70% = mastered).
- **Auto-send:** when results are **published**, every student weak in a subject (<60%, failed or absent) gets nuggets for it automatically; a low quiz score (<60%) sends one too; students can also press "Find nuggets for my weak areas". Limits: max 3 unfinished nuggets per course, 2 new per weak subject per run.
- **Auto-create:** if no nugget exists for the weak topic, one is generated (cached per course+topic): with Gemini/Groq/Ollama when a key is set, otherwise built from the course's own lessons and quiz questions. Teacher-made nuggets are always preferred.
- Teachers/admin: sidebar › Nuggets — create/edit, "Send nuggets for an exam", "Create a nugget automatically", send to whole class, see who mastered it.
- Students: sidebar › My Nuggets (badge), dashboard "Nuggets for you", and the profile page.
- Scheduler: `python manage.py assign_nuggets [--exam ID]`.

### AI key (set once)
Copy `.env.example` to `.env`, write `GEMINI_API_KEY=your_key` (no quotes) and save. It is loaded automatically on every start; `.env` is not part of any zip. Real environment variables override it.

### Nugget editor + AI coach
- Formatting toolbar (heading, bold, italic, lists, note, example) with a live "how students see it" preview; maths courses get a symbol bar (KaTeX), Urdu courses get an Urdu keyboard and right-to-left boxes.
- **AI coach** (side panel): scores the draft out of 10, lists what works and what to fix, and offers one-click improved explanation, extra key points, flashcards and quiz questions. Works with Gemini/Groq/Ollama; with no key it gives rule-based tips.

## Phase 4a — International-standard tranche

**Learning**
- **Review queue**: AI/auto-generated nuggets stay *pending* (hidden from students) until a teacher approves them. Teacher-created nuggets go live at once. Optional auto-approve: Settings › Learning & AI.
- **Spaced revision**: after mastery (>=70%) a nugget returns at 3, 7, 21 and 60 days. Failing a due revision resets it to stage 1.
- **XP, streak, levels, badges** (`LearnerStat`); missed questions are tracked per student.
- **AI tutor** inside each nugget (grounded in the lesson, 20 questions/hour, rules fallback without AI key).
- **Teacher insights** (`/nuggets/insights/`): hardest topics, student x nugget heatmap, CSV export.

**Notifications**: bell + `/notifications/`; results publishing, new nuggets and approvals notify students and parents. Email when `EMAIL_NOTIFICATIONS=1`.

**Hardening**: `.env` loader, DEBUG=0 requires `SECRET_KEY` (32+) and `ALLOWED_HOSTS`, HTTPS/HSTS/secure cookies, login lock after 5 failures, password validators (min 8), audit log, WhiteNoise + gunicorn, `/healthz/`, accessibility (skip link, focus rings, reduced motion).

**Ops**: `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `docs/DEPLOYMENT.md`, `docs/SECURITY.md`.

**Scheduler**: run daily `python manage.py assign_nuggets` (optionally `--exam ID`).

**Not verified in sandbox**: real Gemini/Groq calls, KaTeX CDN rendering, Docker build, CI run, SMTP email.

## Phase 5a — Multi-campus, RBAC, audit, parent portal

**New roles**: Head Office Admin (all campuses), Regional Director (one region), Campus Principal (one campus). Set the region/campus on the user in *Users & Roles*. Super Admin keeps full access.

**Campus scoping** (`core/scope.py`): student list, profiles, edit, reports, exports, campus comparison and dashboards only show records inside the user's campuses. Principals can only create/move students inside their own campus. Classes can now be tied to a campus (`SchoolClass.campus`, empty = whole school).

**Permission matrix** (`accounts/rbac.py`, *Permissions* page, Super Admin only): `module.action` codes (students.view/create/edit/export, campuses.view/manage, reports.view/export, nuggets.insights/review, exams.publish, users.manage, audit.view, rbac.manage). Role defaults live in code; the page stores only overrides (`RolePermission`). Changes apply immediately and are audited.

**Audit log** (`/settings/audit/`, `audit.view`): sign-ins, failed sign-ins, logouts, user create/edit/(de)activate, permission changes, result publish/hide, nugget approve/reject, exports.

**Campus comparison** (`/organization/compare/`): students, teachers, average exam %, pass rate, at-risk students (latest published result < 50%), nugget mastery, ranking, CSV export. Published results only.

**Parent portal** (`/family/`): one overview per child with a child switcher — latest result, change since last exam, lesson completion, nugget mastery, weak/strong subjects, suggested home practice (rule-based), pending short lessons, message-a-teacher. Parents only see their own children, published results and approved nuggets.

**Demo accounts**: `headoffice1`, `regional1`, `principal1` (all `demo123`).

**Migrations**: accounts 0003, academics 0004, core 0004.

**Not done yet (spec items)**: attendance, per-user permission overrides, approval workflows, 2FA/SSO, teacher continuity/handover, curriculum hierarchy + coverage, early-warning intervention plans, learning DNA, Head Office BI exports to Excel/PDF, parent-teacher meetings, fees. Stack stays Django (React/NestJS not used).

## Phase 5b — Curriculum, coverage monitor, teacher continuity

**Curriculum outline** (`/curriculum/`): every course has an outline of topics grouped Unit › Chapter › Topic with a learning outcome. Add topics in bulk (`Unit | Chapter | Topic | Outcome`, shorter lines work), copy an outline from the same subject in another class/campus, and tick topics as taught (date, teacher and an optional note are recorded). Teachers edit their own courses; Super Admin all; a Principal the courses of their campus.

**Coverage monitor** (`/curriculum/coverage/`, permission `curriculum.monitor`): coverage per course and campus average, flags courses not updated for 14+ days or with no outline, and highlights same class + subject that differ by 20+ points between campuses. Scoped by campus/region. CSV export (`reports.export`).

**Teacher continuity** (`/curriculum/handovers/`): whenever the teacher of a course changes (any screen), a handover is created automatically and a snapshot is frozen: topics taught, last topic and date, completed chapters, what is next with learning outcomes, students needing attention (quiz average < 60% or nuggets not mastered after 2+ tries), assessments, lessons, open help requests. The new teacher and the campus Principal are notified. The receiving teacher acknowledges; unacknowledged for 3+ days shows as overdue. Manual handovers: *transfer* (reassigns the course) or *absence cover* (course teacher unchanged; the cover teacher can mark topics until the cover is ended). Full history is kept; the report is printable.

**Permissions added**: `curriculum.monitor`, `handover.view`, `handover.create`.
**Migrations**: curriculum 0001. **Demo data**: seed_demo adds an outline to each demo course (first topics marked taught).

**Still open**: curriculum versioning/approval workflow, competency mapping, academic calendar/term plans, scheme of work, AI lesson plans, classroom observations, teacher appraisal.

## Phase 6 — Student fees and ledger

**How it works**: a *class fee* (Fees › Class fees) is the monthly amount for every student of that class. A student can have their own plan (own amount, fixed monthly discount, start month, stop billing) on their ledger page. Every month a "Monthly fee" entry is added to each student's ledger automatically:
- the first time anyone opens the dashboard each month (at most every 6 hours; set `FEES_AUTO_GENERATE=0` to turn off), and/or
- `python manage.py generate_fees` (schedule it daily; `--month YYYY-MM`, `--no-notify`). Safe to repeat; missed months since the plan's start month are caught up. A database constraint blocks double billing.

**Ledger** (`/fees/student/<id>/`): append-only account book with running balance (charged / paid / balance; negative = advance). Record payments (cash, bank, online, cheque; auto receipt number, printable receipt), add other charges or discounts, change the student's plan. Mistakes are *voided with a reason* (kept in the book, struck through, not counted) — never deleted. Changing a class fee never alters past charges.

**Student profile**: new *Fees* card (outstanding, monthly fee, last payment, recent entries, link to full ledger). Parents see the same card on the child overview and a read-only ledger and receipts in the menu (*Fees · name*); students see *My Fees*. Parents and students are notified when a month is billed and when a payment is received.

**Fees dashboard** (`/fees/`): billed and collected for the chosen month, total outstanding, students with a balance (search, campus filter), defaulter CSV export, *Generate month* button.

**Permissions**: `fees.view` (Head Office, Regional Director, Principal), `fees.collect` (Principal), `fees.manage` (Head Office: class fees, plans, charges, voids, generate). Super Admin all. Everything is scoped to the user's campuses, and audited (payments, charges, voids, plans, class fees, generation, exports).

**Settings**: currency symbol (Appearance › Currency, default Rs). **Migrations**: fees 0001, core 0005. **Demo**: seed_demo adds a class fee, 3 months of billing and sample payments for the demo students.

**Not included yet**: late fines, installments/fee heads (tuition, transport, etc.), online payment gateway, fee vouchers/challans, SMS reminders, family-level combined ledger.

## Phase 7 — Attendance and Early Warning

**Attendance** (`/attendance/`): class teachers (for classes they teach), Principals (own campus) and Super Admin mark a daily register: Present / Absent / Late / Leave, with a note. Everyone starts as Present; change only exceptions. Days with approved leave are pre-filled as Leave. Future dates are not allowed; re-saving never duplicates rows. A student who newly becomes *absent* notifies the student and parents once.
- **Percentage** = (present + late) / (present + late + absent). Approved leave is excused and left out.
- **Leave requests**: parents/students request leave from the attendance page; class teachers (or Principal / Admin in scope) approve or reject with a note; family is notified.
- **Report** (`/attendance/report/`): by class and lowest-attendance students for a date range, scoped to campus/region, CSV export (formula-safe, audited).
- **Teacher attendance** (`/attendance/staff/`): Principal / Admin mark staff; 30-day percentage shown.
- Attendance card on the student profile and parent overview; *Attendance · name* for parents, *My Attendance* for students.

**Early Warning** (`/risk/`): a scan looks at four signals per student — low attendance (window days), low latest published exam, a fall since the previous exam, low quiz average (2+ quizzes), and nuggets tried repeatedly without mastery. 1 sign = Watch, 2 = Medium, 3+ = High. **Your school sets the thresholds** (`/risk/settings/`). Alerts are labelled *possible risk* and are visible to staff only; they are a prompt to look, not a verdict.
- One active alert per student (database constraint). Scans are idempotent; an alert nobody has touched closes itself when signs disappear, but alerts someone is working on are never auto-closed.
- On an alert: add follow-up tasks (assignee, due date, outcome), send a message to the parents, send remedial nuggets, and resolve with a required note. Resolved alerts are frozen and kept as history.
- Run `python manage.py scan_risk` daily (cron / Task Scheduler) or press *Run scan now*.
- Scope: Super Admin all; Head Office all; Regional Director / Principal their campuses; teachers their own students only.

**Permissions** (editable in the matrix): `attendance.view`, `attendance.mark`, `attendance.leave_decide`, `risk.view`, `risk.manage`, `risk.configure`. Defaults: management view; Principal also mark/decide/manage/configure; Head Office manage/configure; teachers mark, decide leave and manage alerts for their own classes.

**Migrations**: attendance 0001, risk 0001. **Demo**: seed_demo adds 4 weeks of register data; student3 is deliberately low so one alert appears.

**Not included yet**: period-wise (subject) attendance, biometric/QR check-in, SMS to parents, timetable-linked registers, predictive (ML) risk models.

## Phase 8 — Timetable and Academic Calendar

**Bell schedule** (`/timetable/periods/`): the school's periods and breaks (name, start/end, order). Every class timetable is built from it.

**Class timetable** (`/timetable/class/<id>/`): weekly grid, Monday–Friday (Saturday appears when used). Principals / Head Office / Super Admin edit it (`Edit timetable`): pick a subject per period. **Clash check**: a teacher cannot be in two classes in the same period; saving is all-or-nothing and tells you exactly which cell clashes. Subjects must belong to that class. Students and parents see their own class; teachers see the classes they teach and **My timetable** (`/timetable/mine/`, all their lessons plus cover duties).

**Substitutions** (`/timetable/substitutions/`): teachers marked absent/on leave in *Teacher attendance* appear with their lessons for that date. Pick a cover teacher — only teachers free in that period (no lesson, not absent, not already covering) are offered. The cover teacher is notified and the class page shows cover for the week.

**Academic calendar** (`/calendar/`): month view of holidays, exams, events and parent-teacher meetings, plus terms. Everyone sees what applies to their campus (all-campus items plus own). Principals add/delete items for their own campus only; Head Office/Admin can add all-campus items. The attendance register warns when the chosen date is a holiday or Sunday (it does not block).

**Permissions**: `timetable.view` (management), `timetable.manage` (Principal, Head Office), `calendar.manage` (Principal, Head Office); Super Admin all. Teachers/students/parents see their own data by relationship. Changes are audited.

**Migrations**: timetable 0001. **Demo**: seed_demo adds 5 periods (one break), a full week for each class, a term, a winter break, a PTM and sports day.

**Not included yet**: period-wise attendance, automatic timetable generation, room/lab booking, exam datesheet clash check, iCal export, recurring events.

## Phase 9 — SIS, Security, Question Bank, Learning Profile, Planner, Executive dashboard, Library, Transport

**Bug fix (Phase 7)**: attendance summary counted *absent* and *late* the wrong way round, which skewed percentages (and therefore the attendance card, report and Early Warning). Fixed with a regression test. Replace any Phase 7/8 copy with this one.

**SIS** — *Admissions* (`/admissions/`): inquiry → applied → interview → admitted/not admitted. *Admit* creates the student account, profile (`ADM-year-nnnn`), enrolment and optionally a parent login; temporary passwords are shown **once**. *Documents* (student profile › Documents): PDF/JPG/PNG up to 5 MB, content-checked, stored **outside** the public media folder (`private/`) and served only through an access-checked view (every view is audited). *Class promotion* (`/promotion/`): move selected students to another class; history, results and fees stay; logged. *Transfer certificate*: numbered `TC-0001`, printable, deactivates the student (confirmation required). Permissions `sis.view` (management), `sis.manage` (Principal, Head Office).

**Security** — *Two-step sign-in* with any authenticator app (TOTP, RFC 6238, no extra package): setup by entering a key (no QR code yet), 8 one-time backup codes, 5-wrong-code lockout, audit entries. Set `REQUIRE_2FA_ROLES=super_admin,head_office,principal` to force it for those roles. *Signed-in devices* (`/security/`): see and sign out sessions. Existing password-failure lockout and password validators remain. **Not included**: SSO (Google/Microsoft) — needs your own OAuth client credentials.

**Question bank** (`/bank/`): per-course pool (MCQ, true/false, short answer; topic; easy/medium/hard), CSV import (formula-safe, ≤500 rows), and **paper generator**: choose how many easy/medium/hard (optionally one topic) → a random *draft* quiz/test/exam in Assessments, choices shuffled, which you review and publish. Shortages are reported, never silently padded. Permission `bank.manage` (teachers for their own courses, Principal/Head Office for their scope).

**Learning profile** (student profile › Learning profile; parents via overview): per-subject score (quiz + latest published exam), lesson progress, attendance, nuggets, strengths (≥70%), focus (<50%), next steps and a draft report-card remark. Built from results only; it is not a personality or "learning style" label.

**Lesson planner** (`/insights/lesson-plan/`): template plan, or AI draft when `AI_PROVIDER` + key are set (only subject, class and topic are sent; any bad AI reply falls back to the template).

**Executive dashboard** (`/insights/executive/`, `bi.view`): per campus students, average exam, pass rate, attendance (30 d), fee collection this month, open warnings; CSV export. **Library** (`/library/`): catalogue for everyone, issue/return for `library.manage` (14-day loan, 5-book limit, fine `LIBRARY_FINE_PER_DAY`, default 5). **Transport** (`/transport/`): routes, vehicle/driver, capacity, student assignment; students and parents see their own route.

**Migrations**: accounts 0004, sis 0001, bank 0001, campusops 0001. **Demo**: books, a route, 6 bank questions, one applicant.

**Not built (needs outside accounts or is a larger separate project)**: SMS/WhatsApp, payment gateway, Google Classroom, biometric devices, SSO, websockets/PWA push; hostel, payroll/HR, inventory; ML-based adaptive paths; library fines are recorded but not posted to the fee ledger.

## Demo data: O Level and A Level (`seed_levels`)

`python manage.py seed_demo` (or `python manage.py seed_levels` on its own, safe to repeat) adds five classes on the first Southern campus: **O Level – Grade 9, 10, 11** (10 subjects each: English Language, Urdu, Islamiyat, Pakistan Studies, Mathematics, Physics, Chemistry, Biology, Computer Science, Principles of Accounts) and **A Level – AS (Grade 12), A2 (Grade 13)** (8 subjects: Mathematics, Physics, Chemistry, Biology, Computer Science, Economics, Business, Accounting).
Each class has 6 students, 2 parents, one teacher per subject, 3 lessons and a 3-question quiz per subject, two published exams (Monthly Test, Mid Term) with marks for every student and subject, 4 weeks of attendance, a clash-free weekly timetable, class fees with 2 months billed and part-paid/paid students, quiz attempts and lesson progress. One student per class (`…_06`) is deliberately weak so Early Warning has real examples.

Logins (password `demo123`): students `ol9_01`…`ol11_06`, `al12_01`…`al13_06`; parents `pol9_a`, `pol9_b`, … ; teachers `tol_<subject>` (O Level) and `tal_<subject>` (A Level), e.g. `tol_mathematic`, `tal_physics`. Marks, attendance and payments are random but fixed (the same every run); quiz questions are real subject questions at the right level but are demo content, not a syllabus.

## Deploy on Vercel (+ Neon Postgres)

Files added: `vercel.json`, `api/index.py` (WSGI entry), `.vercelignore`, `.python-version`, prebuilt `staticfiles/`, `core/cron.py` (`/cron/daily/`).

**Important limits of Vercel (serverless):**
- Disk is read-only/ephemeral: **SQLite does not work**. Use Postgres (Neon) via `DATABASE_URL`.
- **Uploaded files do not persist** (profile/lesson files, SIS student documents are written to `/tmp`). Add object storage (S3 / Cloudflare R2 / Vercel Blob) before using uploads in production.
- Cache is per-instance memory: login lockout and 2FA throttling are weaker. Set `REDIS_URL` (e.g. Upstash) for real protection.
- No background scheduler: the daily fee generation + early-warning scan run through Vercel Cron calling `/cron/daily/` (needs `CRON_SECRET`). Hobby plan: once a day.
- Oracle sync needs `pip install -r requirements-oracle.txt`; it is not installed on Vercel (demo mode `ORACLE_MOCK=1` works).
- Function time limit applies; the first request after idle is slower (cold start).

**Environment variables (Vercel → Settings → Environment Variables):**
`DEBUG=0`, `SECRET_KEY=<50+ random chars>`, `DATABASE_URL=<Neon connection string>`, `CRON_SECRET=<random>`,
optional `ALLOWED_HOSTS=school.example.com` (custom domain), `CSRF_TRUSTED_ORIGINS=https://school.example.com`, `REDIS_URL`, `GEMINI_API_KEY`, `REQUIRE_2FA_ROLES`, `FEES_AUTO_GENERATE=0` (let cron do it).
The `*.vercel.app` host and its CSRF origin are added automatically.

After changing static files run `python manage.py collectstatic --noinput` (with `DEBUG=0`) before deploying.
Run `python manage.py migrate` and `seed_demo` from your computer against the Neon `DATABASE_URL` (not from Vercel).
