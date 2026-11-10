from django.core.management.base import BaseCommand

from accounts.models import User
from core.models import SchoolSettings


class Command(BaseCommand):
    help = "Create demo school settings and one user per role (safe to run repeatedly)."

    def seed_academics(self, teacher, students):
        from academics.models import Course, Enrollment, Lesson, SchoolClass, Subject

        from organization.models import Campus, Region, StudentProfile

        # Regions (Southern / Central / Northern) and campuses come from the dummy Oracle feed.
        if not Region.objects.filter(source="oracle").exists():
            from organization.mock import MockOracle
            from organization.services import SyncBusy, run_sync

            try:
                run_sync("command", MockOracle(120, 1))
            except SyncBusy:
                pass
        campus = Campus.objects.filter(region__name="Southern").order_by("pk").first()
        cls, _ = SchoolClass.objects.get_or_create(name="Class 8", section="A", academic_year="2026-27")
        for s in students:
            Enrollment.objects.get_or_create(student=s, defaults={"school_class": cls})
            StudentProfile.objects.get_or_create(
                user=s, defaults={"campus": campus, "admission_no": f"DEMO-{s.pk}", "source": "manual"})
        lessons = {
            "Mathematics": [
                ("Fractions: the basics", "text", "A fraction shows a part of a whole.\n\nThe top number is the numerator, the bottom number is the denominator.\n\nExample: 3/4 means 3 parts out of 4."),
                ("Adding fractions (web lesson)", "link", "Open the link, read the lesson and try the practice questions."),
                ("Practice sheet", "text", "1) 1/2 + 1/4\n2) 2/3 + 1/6\n3) 3/5 - 1/10"),
            ],
            "English": [
                ("Parts of speech", "text", "Nouns name things, verbs show actions, adjectives describe nouns."),
                ("Reading comprehension tips", "text", "Read the passage twice. Underline key words. Answer in full sentences."),
            ],
            "Science": [],
        }
        for name, items in lessons.items():
            subject, _ = Subject.objects.get_or_create(name=name)
            course, _ = Course.objects.get_or_create(
                school_class=cls, subject=subject,
                defaults={"teacher": teacher if name != "Science" else None},
            )
            if not course.lessons.exists():
                for title, kind, content in items:
                    url = "https://www.khanacademy.org/math/arithmetic/fraction-arithmetic" if kind == "link" else ""
                    Lesson.objects.create(course=course, title=title, kind=kind, content=content, url=url)
            first = course.modules.first()
            if first and first.title == "Module 1":
                first.title, first.description = "Week 1 · Getting started", "Core ideas and introductory material."
                first.save()
            if name == "Mathematics":
                self.seed_quiz(course)
                self.seed_activities(course, teacher)
            if name == "English":
                self.seed_english(course)
        self.seed_exams(cls)

    def seed_exams(self, school_class):
        import datetime
        from accounts.models import User
        from academics.models import Course
        from exams.models import Exam, ExamPaper, Mark
        if Exam.objects.filter(school_class=school_class).exists():
            return
        names = ["student1", "student2", "student3"]
        users = {u.username: u for u in User.objects.filter(username__in=names)}
        data = {  # subject -> marks per student, (October monthly test, Mid term)
            "Mathematics": [(72, 48), (85, 91), (40, 30)],
            "English": [(65, 78), (90, 87), (55, 62)],
            "Science": [(58, 52), (88, 93), (35, 41)],
        }
        for title, when, idx, publish in (("Monthly Test (Oct)", datetime.date(2026, 10, 10), 0, True),
                                          ("Mid Term 2026", datetime.date(2026, 11, 2), 1, True)):
            exam = Exam.objects.create(name=title, school_class=school_class, start_date=when, is_published=publish, marks_locked=True)
            for course in Course.objects.filter(school_class=school_class).select_related("subject"):
                if course.subject.name not in data:
                    continue
                paper = ExamPaper.objects.create(exam=exam, course=course, total_marks=100, pass_marks=33, date=when)
                for i, uname in enumerate(names):
                    if uname in users:
                        Mark.objects.create(paper=paper, student=users[uname], marks=data[course.subject.name][i][idx])

    def seed_english(self, course):
        from academics.models import Lesson, Module
        if course.modules.count() > 1:
            return
        m = Module.objects.create(course=course, title="Week 2 · Vocabulary play", description="Learn new words by playing.")
        Lesson.objects.create(course=course, module=m, title="Word scramble: everyday words", kind="game", game_type="scramble", minutes=5,
                              game_data="school | where you learn\nteacher | someone who teaches\nlibrary | place full of books\nfriend | someone you like")
        Lesson.objects.create(course=course, module=m, title="Flashcards: opposites", kind="game", game_type="flashcards", minutes=5,
                              game_data="hot | cold\nbig | small\nfast | slow\nhappy | sad")

    def seed_activities(self, course, teacher):
        from academics.models import HelpMessage, HelpRequest, Lesson, Module
        from accounts.models import User
        from assessments.models import Assessment
        if course.modules.count() > 1:
            return
        m = Module.objects.create(course=course, title="Week 2 · Practice time", description="Games and a quiz to check what you learned.")
        Lesson.objects.create(course=course, module=m, title="Flashcards: fraction facts", kind="game", game_type="flashcards", minutes=5,
                              game_data="1/2 | 0.5\n1/4 | 0.25\n3/4 | 0.75\n1/5 | 0.2")
        Lesson.objects.create(course=course, module=m, title="Memory match: fractions and decimals", kind="game", game_type="memory", minutes=8,
                              game_data="1/2 | 0.5\n1/4 | 0.25\n3/4 | 0.75\n1/10 | 0.1\n2/5 | 0.4\n1/5 | 0.2")
        Lesson.objects.create(course=course, module=m, title="Interactive fraction bars", kind="embed", minutes=10,
                              url="https://phet.colorado.edu/sims/html/fractions-intro/latest/fractions-intro_all.html",
                              content="Explore fractions with the interactive simulation below.")
        quiz = Assessment.objects.filter(course=course).first()
        if quiz:
            Lesson.objects.create(course=course, module=m, title="Check yourself: Fractions Quiz", kind="quiz", assessment=quiz, minutes=10)
        student = User.objects.filter(username="student1").first()
        if student and not HelpRequest.objects.exists():
            lesson = course.lessons.first()
            r = HelpRequest.objects.create(course=course, lesson=lesson, student=student, subject="How do I add fractions with different bottoms?", status="answered")
            HelpMessage.objects.create(request=r, author=student, body="I don't understand how to add 1/2 and 1/3. Which number do I use at the bottom?")
            HelpMessage.objects.create(request=r, author=teacher, body="Find a common denominator — here 6. Then 1/2 = 3/6 and 1/3 = 2/6, so the answer is 5/6. Try 1/4 + 1/6 next!")

    def seed_quiz(self, course):
        from assessments.models import Assessment, Choice, Question
        if course.assessments.exists():
            return
        a = Assessment.objects.create(
            course=course, title="Fractions Quiz", kind="quiz", duration_minutes=10, max_attempts=2,
            instructions="Answer all questions. Written answers are marked by your teacher.", is_published=True)

        def mcq(text, opts, correct, explanation=""):
            q = Question.objects.create(assessment=a, kind="mcq", text=text, points=2, explanation=explanation)
            for i, o in enumerate(opts, start=1):
                Choice.objects.create(question=q, text=o, position=i, is_correct=(i == correct))

        mcq("What is 1/2 + 1/4?", ["1/6", "3/4", "2/6", "1/8"], 2, "Make the denominators equal: 2/4 + 1/4 = 3/4.")
        mcq("Which fraction is the largest?", ["2/5", "3/8", "1/2", "1/3"], 3)
        q = Question.objects.create(assessment=a, kind="tf", text="3/4 is equal to 0.75.", points=1)
        Choice.objects.create(question=q, text="True", position=1, is_correct=True)
        Choice.objects.create(question=q, text="False", position=2, is_correct=False)
        Question.objects.create(assessment=a, kind="short", text="Simplify 6/8 (write as a/b).", points=2, accepted="3/4")
        Question.objects.create(assessment=a, kind="long", text="Explain, in your own words, how to add two fractions with different denominators.", points=5)

    def seed_fees(self):
        """Demo fees (clearly demo data): class fee, three months billed, some payments."""
        from decimal import Decimal

        from django.utils import timezone

        from academics.models import SchoolClass
        from fees import services
        from fees.models import FeeDefault, LedgerEntry, StudentFeePlan
        cls = SchoolClass.objects.filter(name="Class 8", section="A").first()
        if not cls or LedgerEntry.objects.exists():
            return
        FeeDefault.objects.get_or_create(school_class=cls, defaults={"monthly_amount": Decimal("5000")})
        start = services.first_of(timezone.localdate())
        for _ in range(2):
            start = start.replace(day=1) - __import__("datetime").timedelta(days=1)
            start = start.replace(day=1)
        for st in User.objects.filter(username__in=["student1", "student2", "student3"]):
            StudentFeePlan.objects.get_or_create(student=st, defaults={"start_month": start})
        services.generate(notify=False)
        s1, s2 = User.objects.get(username="student1"), User.objects.get(username="student2")
        admin = User.objects.filter(username="admin").first()
        services.record_payment(s1, Decimal("10000"), "cash", by=admin, entry_date=start, note="Demo payment")
        services.record_payment(s1, Decimal("5000"), "bank", reference="DEMO-TRX-1", by=admin)
        services.record_payment(s2, Decimal("5000"), "cash", by=admin, entry_date=start)

    def seed_attendance(self):
        """Four weeks of register data. student3 is deliberately low so Early Warning has something to show."""
        from datetime import timedelta

        from django.utils import timezone

        from academics.models import Enrollment
        from attendance.models import AttendanceRecord
        today = timezone.localdate()
        days = [today - timedelta(days=i) for i in range(1, 29) if (today - timedelta(days=i)).weekday() < 5]
        for e in Enrollment.objects.select_related("student", "school_class"):
            for i, d in enumerate(days):
                low = e.student.username == "student3"
                st = "absent" if (low and i % 3 != 0) or (not low and i == 7) else ("late" if i == 3 else "present")
                AttendanceRecord.objects.get_or_create(student=e.student, date=d, defaults={"school_class": e.school_class, "status": st})

    def seed_timetable(self):
        from datetime import date, time, timedelta

        from django.utils import timezone

        from academics.models import SchoolClass
        from timetable.models import CalendarEvent, Period, Slot, Term
        spec = [("Period 1", 8, 0, 8, 45, False), ("Period 2", 8, 45, 9, 30, False), ("Break", 9, 30, 9, 50, True),
                ("Period 3", 9, 50, 10, 35, False), ("Period 4", 10, 35, 11, 20, False)]
        for i, (n, h1, m1, h2, m2, b) in enumerate(spec, start=1):
            Period.objects.get_or_create(order=i, defaults={"name": n, "start_time": time(h1, m1), "end_time": time(h2, m2), "is_break": b})
        pers = [p for p in Period.objects.filter(is_break=False)]
        for cls in SchoolClass.objects.all():
            courses = list(cls.courses.all())
            for wd in range(5):
                for j, p in enumerate(pers):
                    if courses and not Slot.objects.filter(school_class=cls, weekday=wd, period=p).exists():
                        c = courses[(wd + j) % len(courses)]
                        if c.teacher and Slot.objects.filter(course__teacher=c.teacher, weekday=wd, period=p).exists():
                            continue
                        Slot.objects.create(school_class=cls, weekday=wd, period=p, course=c, room=f"R{j + 1}")
        t = timezone.localdate()
        y = t.year if t.month >= 8 else t.year - 1
        Term.objects.get_or_create(name=f"Term 1 {y}-{str(y + 1)[2:]}", defaults={"start_date": date(y, 8, 1), "end_date": date(y, 12, 20)})
        CalendarEvent.objects.get_or_create(title="Winter break", defaults={"kind": "holiday", "start_date": date(y, 12, 21), "end_date": date(y + 1, 1, 3)})
        CalendarEvent.objects.get_or_create(title="Parent-teacher meeting", defaults={"kind": "meeting", "start_date": t + timedelta(days=10), "end_date": t + timedelta(days=10)})
        CalendarEvent.objects.get_or_create(title="Annual sports day", defaults={"kind": "event", "start_date": t + timedelta(days=21), "end_date": t + timedelta(days=21)})

    def seed_phase9(self):
        from academics.models import Course
        from bank.services import add_question
        from campusops.models import Book, Route, RouteStudent
        from organization.models import Campus
        from sis.models import Admission
        for t, a in (("Oliver Twist", "Charles Dickens"), ("A Brief History of Time", "Stephen Hawking"), ("Python for Kids", "Jason Briggs")):
            Book.objects.get_or_create(title=t, defaults={"author": a, "copies": 2, "shelf": "A1"})
        campus = Campus.objects.first()
        r, _ = Route.objects.get_or_create(name="North route", defaults={"campus": campus, "vehicle_no": "KHI-1234", "driver_name": "Mr. Karim", "capacity": 20})
        st = User.objects.filter(username="student1").first()
        if st:
            RouteStudent.objects.get_or_create(student=st, defaults={"route": r, "stop": "Main Market"})
        Admission.objects.get_or_create(applicant_name="Ayaan Raza", defaults={"guardian_name": "Raza Khan", "guardian_phone": "0300-0000000", "status": "applied", "campus": campus})
        course = Course.objects.filter(subject__name__icontains="math").first() or Course.objects.first()
        if course and not course.bank_questions.exists():
            for i in range(1, 7):
                add_question(course, None, "mcq", f"What is {i} + {i}?", "Addition", 1 if i < 4 else 2, "", [str(i * 2), str(i * 2 + 1), str(i), str(i * 3)], [0])

    def seed_curriculum(self):
        """Demo outline (clearly demo data): a few topics per course, the first ones already taught."""
        from datetime import timedelta

        from django.utils import timezone

        from academics.models import Course
        from curriculum.models import Topic
        plan = [("Unit 1", "Getting started", ["Key ideas", "Worked examples", "Common mistakes"]),
                ("Unit 1", "Practice", ["Guided practice", "Independent practice"]),
                ("Unit 2", "Going further", ["New concept", "Applying it", "Review"])]
        for course in Course.objects.all():
            if course.topics.exists():
                continue
            pos = 0
            for unit, chapter, titles in plan:
                for title in titles:
                    pos += 1
                    Topic.objects.create(course=course, unit=unit, chapter=chapter, title=f"{course.subject}: {title}",
                                         outcome=f"Student can explain and use: {title.lower()}", position=pos,
                                         is_covered=pos <= 4, covered_on=(timezone.localdate() - timedelta(days=20 - pos)) if pos <= 4 else None,
                                         covered_by=course.teacher if pos <= 4 else None)

    def handle(self, *args, **opts):
        # Demo accounts share a few passwords: hash each distinct password once (a full PBKDF2 per user made the
        # seed take ~40 s of CPU). Django re-hashes automatically if the hasher settings change later.
        from django.contrib.auth.hashers import make_password
        _hashes = {}

        def _set_password(user, raw):
            if raw not in _hashes:
                _hashes[raw] = make_password(raw)
            user.password = _hashes[raw]
            user._password = None
        _orig_set_password = User.set_password
        User.set_password = _set_password
        try:
            return self._handle(*args, **opts)
        finally:
            User.set_password = _orig_set_password

    def _handle(self, *args, **opts):
        SchoolSettings.load()

        def make(username, first, last, role, password, **extra):
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "role": role,
                          "email": f"{username}@edupulse.local", **extra},
            )
            if created:
                u.set_password(password)
                if role == User.Role.SUPER_ADMIN:
                    u.is_staff = u.is_superuser = True
                u.save()
            return u

        make("admin", "School", "Admin", User.Role.SUPER_ADMIN, "admin123")
        make("teacher1", "Ayesha", "Khan", User.Role.TEACHER, "demo123")
        s1 = make("student1", "Hamza", "Ali", User.Role.STUDENT, "demo123")
        s2 = make("student2", "Sara", "Ali", User.Role.STUDENT, "demo123")
        make("student3", "Bilal", "Ahmed", User.Role.STUDENT, "demo123")
        p1 = make("parent1", "Imran", "Ali", User.Role.PARENT, "demo123")
        p1.children.set([s1, s2])

        self.seed_academics(
            User.objects.get(username="teacher1"),
            User.objects.filter(username__in=["student1", "student2", "student3"]),
        )

        # Management accounts (demo): Head Office sees everything, the Regional Director one region, the Principal one campus.
        from organization.models import Campus
        campus = Campus.objects.filter(region__name="Southern").order_by("pk").first()
        if campus:
            make("headoffice1", "Hina", "Qureshi", User.Role.HEAD_OFFICE, "demo123")
            make("regional1", "Omar", "Farooq", User.Role.REGIONAL, "demo123", region=campus.region)
            make("principal1", "Nadia", "Siddiqui", User.Role.PRINCIPAL, "demo123", campus=campus)
            User.objects.filter(username="teacher1", campus__isnull=True).update(campus=campus)

        self.seed_curriculum()
        self.seed_fees()
        self.seed_attendance()
        self.seed_timetable()
        self.seed_phase9()
        from django.core.management import call_command
        call_command("seed_levels", verbosity=0)
        from risk import services as risk_services
        risk_services.scan()
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write("  Head Office : headoffice1 / demo123   Regional: regional1 / demo123   Principal: principal1 / demo123")
        self.stdout.write("  Super Admin : admin     / admin123")
        self.stdout.write("  Teacher     : teacher1  / demo123")
        self.stdout.write("  Student     : student1  / demo123")
        self.stdout.write("  Parent      : parent1   / demo123  (linked to student1, student2)")
