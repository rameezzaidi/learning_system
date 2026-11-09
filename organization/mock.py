"""Demo stand-in for Oracle. Produces the same rows a real Oracle query would, so the whole
sync flow can be tried without a database. Data is deterministic (same input -> same output).

round=1  the first load
round=2  simulates changes a day later: a few students move campus, a few change surname,
         the last 3 students leave (disappear from the feed) and 5 new students join.
"""
import random

REGIONS = [(1, "Southern", "SOU"), (2, "Central", "CEN"), (3, "Northern", "NOR")]
CAMPUSES = [  # (id, region_id, name, code)
    (101, 1, "Karachi Clifton Campus", "SOU-CLF"), (102, 1, "Karachi Gulshan Campus", "SOU-GUL"),
    (103, 1, "Karachi DHA Campus", "SOU-DHA"), (104, 1, "Hyderabad Campus", "SOU-HYD"),
    (105, 1, "Quetta Campus", "SOU-QTA"),
    (201, 2, "Lahore Gulberg Campus", "CEN-GUL"), (202, 2, "Lahore Johar Town Campus", "CEN-JHT"),
    (203, 2, "Faisalabad Campus", "CEN-FSD"), (204, 2, "Multan Campus", "CEN-MUL"),
    (301, 3, "Islamabad F-10 Campus", "NOR-F10"), (302, 3, "Islamabad G-11 Campus", "NOR-G11"),
    (303, 3, "Rawalpindi Campus", "NOR-RWP"), (304, 3, "Peshawar University Town Campus", "NOR-PUT"),
    (305, 3, "Peshawar Hayatabad Campus", "NOR-HYT"),
]
FIRST = ["Ahmed", "Ali", "Hamza", "Bilal", "Usman", "Zain", "Hassan", "Fahad", "Omar", "Saad", "Danish", "Talha",
         "Ayesha", "Fatima", "Sara", "Zainab", "Maryam", "Hira", "Noor", "Iqra", "Mahnoor", "Laiba", "Areeba", "Dua"]
LAST = ["Khan", "Ahmed", "Malik", "Sheikh", "Qureshi", "Siddiqui", "Raza", "Hussain", "Baig", "Chaudhry",
        "Ansari", "Butt", "Mirza", "Farooqi", "Javed", "Iqbal", "Rehman", "Shah"]
CAMPUS_WEIGHTS = [4, 3, 3, 2, 1, 4, 3, 2, 2, 3, 2, 2, 2, 2]  # bigger campuses have more students
assert len(CAMPUS_WEIGHTS) == len(CAMPUSES)
_REGION_CODE = {r[0]: r[2] for r in REGIONS}
_CAMPUS_REGION = {c[0]: c[1] for c in CAMPUSES}


def _student(rng, n, campus_id):
    first, last = rng.choice(FIRST), rng.choice(LAST)
    return {
        "external_id": 1000 + n,
        "admission_no": f"{_REGION_CODE[_CAMPUS_REGION[campus_id]]}-26-{n:04d}",
        "first_name": first,
        "last_name": last,
        "email": f"{first}.{last}{n}@example.com".lower(),
        "phone": f"03{rng.choice([0, 1, 2, 3, 4])}{rng.randint(0, 9)}-{rng.randint(1000000, 9999999)}",
        "campus_id": campus_id,
    }


def generate(students=120, round=1):
    rng = random.Random(42)
    ids = [c[0] for c in CAMPUSES]
    rows = [_student(rng, n, rng.choices(ids, CAMPUS_WEIGHTS)[0]) for n in range(1, students + 1)]
    if round >= 2:
        for i, s in enumerate(rows, start=1):
            if i % 20 == 0:
                s["campus_id"] = rng.choice([c for c in ids if c != s["campus_id"]])
            if i % 25 == 0:
                s["last_name"] = rng.choice(LAST)
        rows = rows[:-3] if len(rows) > 3 else rows
        extra_rng = random.Random(7)
        for n in range(students + 1, students + 6):
            rows.append(_student(extra_rng, n, extra_rng.choice(ids)))
    return {
        "regions": [{"external_id": i, "name": n, "code": c} for i, n, c in REGIONS],
        "campuses": [{"external_id": i, "region_id": r, "name": n, "code": c} for i, r, n, c in CAMPUSES],
        "students": rows,
    }


class MockOracle:
    """Drop-in for OracleConnector. run_sync() asks it for the whole dataset at once."""

    def __init__(self, students=120, round=1):
        self.students, self.round = students, round

    def fetch_dataset(self):
        return generate(self.students, self.round)

    def fetch(self, sql):  # pragma: no cover - only used if someone calls it directly
        raise RuntimeError("MockOracle serves whole datasets via fetch_dataset().")

    def ping(self):
        return True
