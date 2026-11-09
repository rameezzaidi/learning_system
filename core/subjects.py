"""Decide what *kind* of subject a name is, so editors, languages and layouts can adapt to it.

Heuristic on the subject name (no database change): works for "Mathematics", "Maths", "Urdu", "Islamiat", "English Grammar"...
"""
URDU_WORDS = ("urdu", "islamiat", "islamyat", "islamic", "quran", "nazra", "deeniyat", "diniyat", "اردو", "اسلامیات", "قرآن", "دینیات")
MATH_WORDS = ("math", "algebra", "geometry", "calculus", "arithmetic", "trigonometry", "statistics", "ریاضی")
ENGLISH_WORDS = ("english", "grammar", "literature", "phonics", "vocabulary", "composition")


def subject_kind(name):
    n = (name or "").strip().lower()
    if any(w in n for w in URDU_WORDS):
        return "urdu"
    if any(w in n for w in MATH_WORDS):
        return "math"
    if any(w in n for w in ENGLISH_WORDS):
        return "english"
    return "general"
