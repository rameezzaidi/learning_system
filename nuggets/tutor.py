"""Nugget tutor: answers a student's question using ONLY the lesson on screen (no student data is sent).

With an AI key it explains step by step and nudges the student to think; without one it finds the most relevant
sentences in the lesson. Always safe to call: it never raises.
"""
import json
import re

from exams import ai

HOURLY_LIMIT = 20
_WORD = re.compile(r"\w+", re.U)


def _lesson_text(n):
    return "\n".join(filter(None, [n.title, n.explanation, "\n".join(n.points()),
                                   "\n".join(f"{a} = {b}" for a, b in n.cards)]))


def _rules(n, question):
    words = {w.lower() for w in _WORD.findall(question) if len(w) > 2}
    chunks = [c.strip() for c in re.split(r"(?<=[.!?۔])\s+|\n+", _lesson_text(n)) if len(c.strip()) > 20]
    scored = sorted(((len(words & {w.lower() for w in _WORD.findall(c)}), i, c) for i, c in enumerate(chunks)), reverse=True)
    best = [c for sc, _, c in scored[:2] if sc > 0]
    if best:
        return "From this lesson: " + " ".join(best) + "\n\nTry explaining it back in your own words, then take the quick check."
    return ("I could not find that in this lesson. Re-read the “Remember” points, and ask your teacher about it using the Help desk — "
            "they can explain it better than I can.")


def _system(n):
    lang = ai.subject_lang(n.course.subject.name)
    language = "Urdu (Urdu script, simple words)" if lang == "urs" else "simple English (you may add a short Roman Urdu hint if the student writes in Roman Urdu)"
    return (f"You are a kind, patient {n.course.subject.name} tutor for a {n.course.school_class.name} student. Answer ONLY about the lesson "
            f"below and its subject. Explain step by step in {language}, in under 120 words. Do not just give quiz answers: guide the student "
            f"to the idea with a small hint or a question. If the question is off-topic or unsafe, politely say you can only help with this lesson. "
            f"Never ask for personal information. Reply with ONE JSON object only: {{\"answer\": \"...\"}}.")


def ask(n, question, history=None):
    """Returns (answer, source) with source 'ai' or 'rules'."""
    if not ai.enabled():
        return _rules(n, question), "rules"
    try:
        convo = [{"role": h.get("role"), "text": str(h.get("text", ""))[:400]} for h in (history or []) if isinstance(h, dict)]
        payload = {"lesson": _lesson_text(n)[:3000], "conversation": convo, "question": question}
        data = ai.parse_json(ai.call_model(_system(n), json.dumps(payload, ensure_ascii=False)))
        answer = str(data.get("answer", "")).strip()[:900]
        return (answer, "ai") if answer else (_rules(n, question), "rules")
    except Exception:
        return _rules(n, question), "rules"
