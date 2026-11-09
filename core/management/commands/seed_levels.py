"""Demo data for Cambridge-style O Level (Grades 9-11) and A Level (AS, A2): classes, subjects, teachers, students, parents,
lessons, quizzes, exam results, attendance, timetable and fees. Safe to run repeatedly."""
import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User

YEAR = "2026-27"

# subject -> (3 topics with a short note, 3 quiz questions: (text, options, index of correct option))
O_LEVEL = {
    "English Language": ([("Writing a formal letter", "Use a formal address, clear paragraphs and a formal ending. 'Yours sincerely' follows a named person; 'Yours faithfully' follows 'Dear Sir or Madam'."),
                          ("Summary writing", "Select the key points, use your own words, and stay within the word limit. Do not copy whole sentences."),
                          ("Persuasive techniques", "Use rhetorical questions, the rule of three, emotive language and facts to convince the reader.")],
                         [("Choose the correct word: ___ going to the market.", ["Their", "There", "They're", "Thier"], 2), ("A good summary is", ["longer than the text", "in your own words and short", "a copy of the first paragraph", "full of opinions"], 1),
                          ("Which ending suits 'Dear Mr Khan'?", ["Yours faithfully", "Yours sincerely", "Cheers", "Best wishes always"], 1)]),
    "Urdu": ([("اسم، فعل اور حرف", "اسم کسی چیز کا نام ہے، فعل کام یا حالت کو ظاہر کرتا ہے اور حرف جملے کے الفاظ کو جوڑتا ہے۔"),
              ("مضمون نویسی", "مضمون میں تمہید، تفصیل اور خاتمہ ہوتا ہے۔ ہر پیراگراف میں ایک خیال بیان کریں۔"),
              ("علامہ اقبال کی شاعری", "اقبال کی شاعری میں خودی، عمل اور امید کا پیغام ملتا ہے۔")],
             [("علامہ اقبال کو کس لقب سے یاد کیا جاتا ہے؟", ["شاعرِ مشرق", "بابائے اردو", "شاعرِ فطرت", "حکیم الامت نہیں"], 0), ("پاکستان کا قومی ترانہ کس نے لکھا؟", ["فیض احمد فیض", "حفیظ جالندھری", "احمد فراز", "جوش ملیح آبادی"], 1),
              ("'کتاب' کی جمع کیا ہے؟", ["کتابوں", "کتابیں", "کتابا", "کتب خانہ"], 1)]),
    "Islamiyat": ([("Revelation of the Quran", "The first revelation came to the Prophet (PBUH) in the Cave of Hira. The Quran was revealed over about 23 years."),
                   ("The Hijrah", "The migration from Makkah to Madinah in 622 CE marks the start of the Islamic calendar."),
                   ("Pillars of Islam", "Shahadah, Salah, Zakah, Sawm and Hajj are the five pillars.")],
                  [("How many Surahs are in the Quran?", ["99", "114", "120", "30"], 1), ("The first revelation was received in which cave?", ["Thawr", "Hira", "Uhud", "Safa"], 1), ("The Hijrah was a migration from Makkah to", ["Taif", "Madinah", "Jerusalem", "Damascus"], 1)]),
    "Pakistan Studies": ([("The Lahore Resolution", "Passed in March 1940 at Lahore, it demanded separate homelands for the Muslims of South Asia."),
                          ("Geography of Pakistan", "Pakistan has mountains in the north, the Indus plains, plateaus in Balochistan and a coastline on the Arabian Sea."),
                          ("Constitutional development", "Pakistan has had constitutions in 1956, 1962 and 1973; the 1973 Constitution is in force.")],
                         [("What is the capital of Pakistan?", ["Karachi", "Lahore", "Islamabad", "Peshawar"], 2), ("The Lahore Resolution was passed in", ["1930", "1940", "1947", "1956"], 1), ("The longest river of Pakistan is the", ["Jhelum", "Ravi", "Indus", "Sutlej"], 2)]),
    "Mathematics": ([("Quadratic equations", "Solve by factorising, completing the square or the formula x = (-b ± √(b²-4ac)) / 2a."),
                     ("Trigonometry basics", "In a right triangle sin = opposite/hypotenuse, cos = adjacent/hypotenuse, tan = opposite/adjacent."),
                     ("Statistics: averages", "Mean = sum ÷ count. The median is the middle value; the mode is the most frequent.")],
                    [("Solve x² - 5x + 6 = 0", ["x = 1, 6", "x = 2, 3", "x = -2, -3", "x = 5, 1"], 1), ("sin 30° equals", ["0.5", "1", "0.866", "0"], 0), ("The mean of 2, 4, 6, 8 is", ["4", "5", "6", "20"], 1)]),
    "Physics": ([("Forces and motion", "Force = mass × acceleration (F = ma). The SI unit of force is the newton."),
                 ("Speed, velocity and acceleration", "Speed = distance ÷ time. Velocity has direction; acceleration is the change in velocity per second."),
                 ("Electric circuits", "Current is measured in amperes, voltage in volts. V = IR (Ohm's law).")],
                [("The SI unit of force is the", ["joule", "newton", "watt", "pascal"], 1), ("Speed is", ["distance × time", "distance ÷ time", "mass ÷ volume", "force ÷ area"], 1), ("Which of these is a vector?", ["speed", "mass", "velocity", "time"], 2)]),
    "Chemistry": ([("Atomic structure", "Atoms have protons and neutrons in the nucleus and electrons in shells. The atomic number is the number of protons."),
                   ("Acids, bases and pH", "pH below 7 is acidic, 7 is neutral, above 7 is alkaline. Indicators change colour with pH."),
                   ("Reactivity series", "More reactive metals displace less reactive ones. Metals above hydrogen react with acids to give hydrogen gas.")],
                  [("The chemical symbol of sodium is", ["So", "Na", "S", "Sd"], 1), ("The pH of a neutral solution is", ["0", "7", "10", "14"], 1), ("Zinc reacting with hydrochloric acid gives which gas?", ["oxygen", "carbon dioxide", "hydrogen", "chlorine"], 2)]),
    "Biology": ([("Cell structure", "Animal and plant cells have a nucleus, cytoplasm and cell membrane. Plant cells also have a cell wall and chloroplasts."),
                 ("Photosynthesis", "Plants make glucose from carbon dioxide and water using light energy, releasing oxygen."),
                 ("Human circulatory system", "The heart pumps blood through arteries, veins and capillaries. Red blood cells carry oxygen.")],
                [("The powerhouse of the cell is the", ["nucleus", "mitochondrion", "ribosome", "vacuole"], 1), ("Plants make food by", ["respiration", "digestion", "photosynthesis", "transpiration"], 2), ("Which cells carry oxygen?", ["white blood cells", "platelets", "red blood cells", "neurons"], 2)]),
    "Computer Science": ([("Binary and data representation", "Computers use binary (0 and 1). Each place value doubles: 8, 4, 2, 1. Decimal 5 is 101 in binary."),
                          ("Algorithms and flowcharts", "An algorithm is a step-by-step solution. Flowcharts use shapes for start/end, process, decision and input/output."),
                          ("Hardware and software", "The CPU fetches, decodes and executes instructions. Input, output and storage devices connect to it.")],
                         [("Decimal 5 in binary is", ["110", "101", "011", "111"], 1), ("Which is an output device?", ["keyboard", "mouse", "monitor", "scanner"], 2), ("CPU stands for", ["Central Processing Unit", "Computer Personal Unit", "Central Program Utility", "Control Process Unit"], 0)]),
    "Principles of Accounts": ([("The accounting equation", "Assets = Liabilities + Capital. Every transaction keeps the equation balanced."),
                                ("Double entry and the ledger", "Every transaction has a debit and an equal credit entry in the ledger accounts."),
                                ("Trial balance", "A trial balance lists all ledger balances. Total debits must equal total credits.")],
                               [("The accounting equation is", ["Assets = Capital − Liabilities", "Assets = Liabilities + Capital", "Capital = Assets + Liabilities", "Profit = Assets"], 1), ("Which is a current asset?", ["Building", "Machinery", "Inventory", "Loan"], 2), ("In a trial balance, total debits", ["exceed credits", "equal credits", "are halved", "are ignored"], 1)]),
}
A_LEVEL = {
    "Mathematics": ([("Differentiation", "The derivative gives the gradient. d/dx of xⁿ is n·xⁿ⁻¹. Use the chain, product and quotient rules."),
                     ("Integration", "Integration reverses differentiation: ∫xⁿ dx = xⁿ⁺¹/(n+1) + c. Definite integrals give areas."),
                     ("Sequences and series", "An arithmetic series has a common difference; a geometric series has a common ratio. A GP converges when |r| < 1.")],
                    [("d/dx of x³ is", ["x²", "3x²", "3x", "x⁴/4"], 1), ("∫ 2x dx =", ["x² + c", "2 + c", "x + c", "2x² + c"], 0), ("The sum to infinity of a geometric series exists when", ["r > 1", "|r| < 1", "r = 1", "r < -2"], 1)]),
    "Physics": ([("Waves", "Transverse waves oscillate perpendicular to the direction of travel. Light is a transverse wave; sound is longitudinal."),
                 ("Capacitors", "Capacitance C = Q/V, measured in farads. Energy stored = ½CV²."),
                 ("Kinetic theory and energy", "Kinetic energy = ½mv². Internal energy is the sum of random kinetic and potential energies of particles.")],
                [("The unit of capacitance is the", ["henry", "farad", "tesla", "ohm"], 1), ("Which wave is transverse?", ["sound", "light", "ultrasound", "P-waves"], 1), ("Kinetic energy equals", ["mv", "½mv²", "mgh", "Fd²"], 1)]),
    "Chemistry": ([("Chemical bonding and shapes", "Electron-pair repulsion decides shape: methane is tetrahedral, water is bent, ammonia is pyramidal."),
                   ("Reaction kinetics", "Catalysts speed up reactions by providing a route with lower activation energy."),
                   ("Periodic trends", "Electronegativity increases across a period and decreases down a group; fluorine is the most electronegative element.")],
                  [("The most electronegative element is", ["oxygen", "chlorine", "fluorine", "nitrogen"], 2), ("A catalyst increases rate by", ["raising temperature", "lowering activation energy", "increasing concentration", "changing ΔH"], 1), ("The shape of methane is", ["linear", "trigonal planar", "tetrahedral", "octahedral"], 2)]),
    "Biology": ([("DNA replication", "Helicase unwinds the double helix and DNA polymerase builds the new strands. Replication is semi-conservative."),
                 ("Respiration", "Glycolysis occurs in the cytoplasm; the Krebs cycle in the mitochondrial matrix; oxidative phosphorylation on the inner membrane."),
                 ("Meiosis and inheritance", "Meiosis halves the chromosome number, giving four genetically different gametes.")],
                [("Which enzyme unwinds DNA?", ["ligase", "helicase", "amylase", "protease"], 1), ("The Krebs cycle occurs in the", ["cytoplasm", "nucleus", "mitochondrial matrix", "ribosome"], 2), ("A human gamete has how many chromosomes?", ["46", "23", "92", "44"], 1)]),
    "Computer Science": ([("Data structures", "A stack is last-in-first-out; a queue is first-in-first-out. Linked lists and trees store data using pointers."),
                          ("Algorithm efficiency", "Big-O describes growth. Linear search is O(n); binary search on sorted data is O(log n)."),
                          ("Databases and normalisation", "Normalisation removes redundancy and anomalies by splitting data into related tables.")],
                         [("Binary search has time complexity", ["O(n)", "O(log n)", "O(n²)", "O(1)"], 1), ("Which structure is LIFO?", ["queue", "stack", "array", "heap"], 1), ("Normalisation mainly reduces", ["data redundancy", "network speed", "file size on disk only", "user accounts"], 0)]),
    "Economics": ([("Demand and supply", "The law of demand: as price rises, quantity demanded falls, other things equal."),
                   ("Opportunity cost", "The value of the next best alternative given up when a choice is made."),
                   ("National income", "GDP measures the value of output in an economy. Real GDP removes the effect of price changes.")],
                  [("As price rises, quantity demanded", ["rises", "falls", "is unchanged", "doubles"], 1), ("Opportunity cost is", ["the money price", "the next best alternative forgone", "total cost", "a tax"], 1), ("GDP stands for", ["Gross Domestic Product", "General Demand Price", "Gross Dollar Profit", "Global Domestic Power"], 0)]),
    "Business": ([("SWOT analysis", "Strengths and Weaknesses are internal; Opportunities and Threats are external."),
                  ("Costs and break-even", "Fixed costs do not change with output; variable costs do. Break-even is where total revenue equals total cost."),
                  ("Marketing mix", "Product, price, place and promotion are the four Ps.")],
                 [("In SWOT, 'O' stands for", ["Objectives", "Opportunities", "Output", "Operations"], 1), ("Which is a fixed cost?", ["raw materials", "rent", "piece-rate wages", "packaging"], 1), ("Break-even occurs when", ["profit is maximum", "total revenue = total cost", "price = 0", "sales are zero"], 1)]),
    "Accounting": ([("Depreciation", "Straight-line depreciation = (cost − residual value) ÷ useful life."),
                    ("Accruals and prepayments", "Under the accruals concept, income and expenses are recorded when earned or incurred, not when cash moves."),
                    ("Financial statements", "The income statement shows profit; the statement of financial position shows assets, liabilities and equity.")],
                   [("Straight-line depreciation divides (cost − residual value) by", ["useful life", "selling price", "capital", "tax rate"], 0), ("The accruals concept records items when they are", ["paid", "earned or incurred", "budgeted", "audited"], 1), ("The statement of financial position shows", ["profit only", "assets, liabilities and equity", "cash receipts only", "sales only"], 1)]),
}

# (class name, subjects, fee per month)
LEVELS = [("O Level - Grade 9", O_LEVEL, 12000), ("O Level - Grade 10", O_LEVEL, 12000), ("O Level - Grade 11", O_LEVEL, 12500),
          ("A Level - AS (Grade 12)", A_LEVEL, 16000), ("A Level - A2 (Grade 13)", A_LEVEL, 16500)]

FIRST_M = ["Ahmed", "Hassan", "Ali", "Usman", "Zain", "Hamza", "Bilal", "Danish", "Faizan", "Rayyan", "Saad", "Taha", "Umer", "Waleed", "Yahya"]
FIRST_F = ["Ayesha", "Fatima", "Zainab", "Maryam", "Hira", "Sana", "Noor", "Areeba", "Mahnoor", "Laiba", "Iqra", "Khadija", "Rida", "Sidra", "Anaya"]
LAST = ["Khan", "Ahmed", "Malik", "Sheikh", "Qureshi", "Siddiqui", "Raza", "Hussain", "Farooqi", "Baig", "Chaudhry", "Ansari", "Memon", "Butt", "Javed"]
T_FIRST = ["Imran", "Sadia", "Kamran", "Rabia", "Naveed", "Samina", "Tariq", "Uzma", "Adnan", "Farah", "Rashid", "Bushra", "Salman", "Nargis", "Irfan", "Shazia", "Junaid", "Lubna"]
STUDENTS_PER_CLASS = 6


def slug(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())[:10]


class Command(BaseCommand):
    help = "Create demo O Level and A Level classes with subjects, teachers, students, results, attendance, timetable and fees."

    def handle(self, *args, **opts):
        with transaction.atomic():
            self.run()
        from risk import services as risk
        r = risk.scan()
        self.stdout.write(self.style.SUCCESS(f"O/A Level demo data ready ({r['flagged']} early-warning flags)."))
        self.stdout.write("  Logins (password demo123): teachers tol_mathematics / tal_physics …, students ol9_01 … al13_06, parents pol9_a …")

    # ------------------------------------------------------------------
    def run(self):
        from academics.models import Course, Enrollment, Lesson, SchoolClass, Subject
        from organization.models import Campus, StudentProfile
        campus = Campus.objects.filter(region__name="Southern").order_by("pk").first() or Campus.objects.order_by("pk").first()
        teachers = {}
        for level_key, subjects in (("tol", O_LEVEL), ("tal", A_LEVEL)):
            for i, name in enumerate(subjects):
                un = f"{level_key}_{slug(name)}"
                fn = T_FIRST[(i + (0 if level_key == "tol" else 10)) % len(T_FIRST)]
                u, created = User.objects.get_or_create(username=un, defaults={"first_name": fn, "last_name": LAST[(i * 3) % len(LAST)], "role": User.Role.TEACHER,
                                                                             "email": f"{un}@edupulse.local", "campus": campus})
                if created:
                    u.set_password("demo123")
                    u.save()
                teachers[(level_key, name)] = u
        self.classes = []
        for ci, (cname, subjects, fee) in enumerate(LEVELS):
            level_key = "tol" if subjects is O_LEVEL else "tal"
            cls, _ = SchoolClass.objects.get_or_create(name=cname, section="A", academic_year=YEAR, defaults={"campus": campus})
            if campus and cls.campus_id is None:
                cls.campus = campus
                cls.save()
            code = ("ol" + cname.split("Grade ")[1].rstrip(")")) if subjects is O_LEVEL else ("al" + cname.split("Grade ")[1].rstrip(")"))
            students = self.students(cls, code, campus, ci)
            courses = []
            for name, (topics, qs) in subjects.items():
                subj, _ = Subject.objects.get_or_create(name=name)
                course, _ = Course.objects.get_or_create(school_class=cls, subject=subj, defaults={"teacher": teachers[(level_key, name)]})
                if not course.lessons.exists():
                    for t, note in topics:
                        Lesson.objects.create(course=course, title=t, kind="text", content=note, minutes=15)
                self.quiz(course, name, qs)
                courses.append(course)
            self.classes.append((cls, subjects, courses, students, fee, level_key))
        self.exams()
        self.attendance()
        self.attempts_and_progress()
        self.timetable()
        self.fees()

    def ability(self, student):
        r = random.Random(student.username)
        a = r.uniform(42, 95)
        if student.username.endswith("_06"):  # one student per class who needs support
            a = r.uniform(25, 40)
        return a

    def students(self, cls, code, campus, ci):
        from academics.models import Enrollment
        from organization.models import StudentProfile
        r = random.Random(f"names-{code}")
        out = []
        for i in range(1, STUDENTS_PER_CLASS + 1):
            un = f"{code}_{i:02d}"
            first = (FIRST_M if i % 2 else FIRST_F)[(ci * 3 + i) % 15]
            u, created = User.objects.get_or_create(username=un, defaults={"first_name": first, "last_name": LAST[(ci * 5 + i * 2) % 15], "role": User.Role.STUDENT, "email": f"{un}@edupulse.local"})
            if created:
                u.set_password("demo123")
                u.save()
            Enrollment.objects.get_or_create(student=u, defaults={"school_class": cls})
            StudentProfile.objects.get_or_create(user=u, defaults={"campus": campus, "admission_no": f"{code.upper()}-{i:03d}", "source": "manual"})
            out.append(u)
        for k in (0, 1):  # two parents per class, two children each
            pu = f"p{code}_{'ab'[k]}"
            p, created = User.objects.get_or_create(username=pu, defaults={"first_name": T_FIRST[(ci + k) % len(T_FIRST)], "last_name": out[k * 2].last_name, "role": User.Role.PARENT, "email": f"{pu}@edupulse.local"})
            if created:
                p.set_password("demo123")
                p.save()
                p.children.set(out[k * 2:k * 2 + 2])
        return out

    def quiz(self, course, subject, qs):
        from assessments.models import Assessment, Choice, Question
        if course.assessments.exists():
            return
        a = Assessment.objects.create(course=course, title=f"{subject} Quick Quiz", kind="quiz", duration_minutes=10, max_attempts=2, is_published=True,
                                      instructions="Choose the best answer for each question.")
        for text, opts, correct in qs:
            q = Question.objects.create(assessment=a, kind="mcq", text=text, points=2)
            for i, o in enumerate(opts, start=1):
                Choice.objects.create(question=q, text=o, position=i, is_correct=(i - 1 == correct))

    def exams(self):
        from exams.models import Exam, ExamPaper, Mark
        for cls, subjects, courses, students, fee, key in self.classes:
            if Exam.objects.filter(school_class=cls).exists():
                continue
            for title, when, shift in (("Monthly Test (Oct)", date(2026, 10, 10), 0), ("Mid Term 2026", date(2026, 11, 2), 3)):
                exam = Exam.objects.create(name=title, school_class=cls, start_date=when, is_published=True, marks_locked=True)
                marks = []
                for course in courses:
                    paper = ExamPaper.objects.create(exam=exam, course=course, total_marks=100, pass_marks=40 if key == "tal" else 33, date=when)
                    for s in students:
                        r = random.Random(f"{s.username}-{course.subject.name}-{title}")
                        m = max(5, min(100, round(self.ability(s) + r.uniform(-12, 12) + shift)))
                        marks.append(Mark(paper=paper, student=s, marks=m))
                Mark.objects.bulk_create(marks)

    def attendance(self):
        from attendance.models import AttendanceRecord
        today = timezone.localdate()
        days = [today - timedelta(days=i) for i in range(1, 29) if (today - timedelta(days=i)).weekday() < 5]
        for cls, subjects, courses, students, fee, key in self.classes:
            if AttendanceRecord.objects.filter(school_class=cls).exists():
                continue
            rows = []
            for s in students:
                r = random.Random(f"att-{s.username}")
                rate = 0.72 + 0.27 * (self.ability(s) - 25) / 70
                for d in days:
                    x = r.random()
                    st = "present" if x < rate else ("late" if x < rate + 0.04 else "absent")
                    rows.append(AttendanceRecord(student=s, school_class=cls, date=d, status=st))
            AttendanceRecord.objects.bulk_create(rows, ignore_conflicts=True)

    def attempts_and_progress(self):
        from academics.models import Lesson, LessonProgress
        from assessments.models import Assessment, Attempt
        for cls, subjects, courses, students, fee, key in self.classes:
            for s in students:
                r = random.Random(f"prog-{s.username}")
                ab = self.ability(s) / 100
                for course in courses:
                    for a in Assessment.objects.filter(course=course, is_published=True):
                        if not Attempt.objects.filter(assessment=a, student=s).exists() and r.random() < 0.85:
                            total = float(sum(q.points for q in a.questions.all()))
                            score = round(total * max(0, min(1, ab + r.uniform(-0.2, 0.2))) / 2) * 2
                            Attempt.objects.create(assessment=a, student=s, submitted_at=timezone.now() - timedelta(days=r.randint(1, 20)), score=Decimal(str(min(score, total))), total=Decimal(str(total)))
                    for lesson in course.lessons.all():
                        if r.random() < ab:
                            LessonProgress.objects.get_or_create(student=s, lesson=lesson)

    def timetable(self):
        from timetable.models import Period, Slot
        if not Period.objects.exists():
            for i, (n, h1, m1, h2, m2, b) in enumerate([("Period 1", 8, 0, 8, 45, False), ("Period 2", 8, 45, 9, 30, False), ("Break", 9, 30, 9, 50, True),
                                                       ("Period 3", 9, 50, 10, 35, False), ("Period 4", 10, 35, 11, 20, False)], start=1):
                Period.objects.create(order=i, name=n, start_time=time(h1, m1), end_time=time(h2, m2), is_break=b)
        pers = list(Period.objects.filter(is_break=False))
        for ci, (cls, subjects, courses, students, fee, key) in enumerate(self.classes):
            if Slot.objects.filter(school_class=cls).exists():
                continue
            n = len(courses)
            offset = (ci if key == "tol" else ci - 3) * (3 if key == "tol" else 4)  # offsets differ per class of the same level: no teacher clashes
            for d in range(5):
                for p_i, p in enumerate(pers):
                    course = courses[(2 * p_i + d + offset) % n]
                    if Slot.objects.filter(course__teacher=course.teacher, weekday=d, period=p).exists():
                        continue
                    Slot.objects.create(school_class=cls, weekday=d, period=p, course=course, room=f"R{ci + 1}{p_i + 1}")

    def fees(self):
        from fees import services
        from fees.models import FeeDefault, LedgerEntry, StudentFeePlan
        start = services.first_of(timezone.localdate())
        for _ in range(2):
            start = (start.replace(day=1) - timedelta(days=1)).replace(day=1)
        admin = User.objects.filter(username="admin").first()
        fresh = []
        for cls, subjects, courses, students, fee, key in self.classes:
            FeeDefault.objects.get_or_create(school_class=cls, defaults={"monthly_amount": Decimal(fee)})
            for s in students:
                _, created = StudentFeePlan.objects.get_or_create(student=s, defaults={"start_month": start})
                if created:
                    fresh.append(s)
        services.generate(notify=False)
        for s in fresh:
            r = random.Random(f"pay-{s.username}")
            x = r.random()
            if x < 0.55:  # paid in full so far
                bal = services.balance(s)
                if bal > 0:
                    services.record_payment(s, bal, r.choice(["cash", "bank"]), by=admin, entry_date=start, note="Demo payment")
            elif x < 0.8:  # paid part
                services.record_payment(s, Decimal(str(services.monthly_amount(s))), "cash", by=admin, entry_date=start, note="Demo part payment")
