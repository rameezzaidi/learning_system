"""AI coach for teachers: reviews a draft nugget and says how to make it better.

Uses the configured AI (Gemini/Groq/Ollama/Claude). With no AI — or if the call fails — it falls back to rule-based
checks, so the button always works. Only the draft's own text is sent (no student data).
"""
import json
import re

from exams import ai

from .forms import LETTERS


def _s(v, n):
    return str(v or "").strip()[:n]


def _sentences(text):
    return [x for x in re.split(r"(?<=[.!?۔])\s+", text.strip()) if x]


def rules(d):
    """Plain checks → {score, summary, strengths, improvements}."""
    expl, points = d["explanation"].strip(), [p for p in d["key_points"].splitlines() if p.strip()]
    cards, qs = d["cards"], d["questions"]
    good, tips = [], []
    words = len(expl.split())
    sents = _sentences(expl)
    avg = round(words / len(sents)) if sents else 0
    if words == 0:
        tips.append(("Explanation", "Write a short explanation (80–150 words): what it is, why it matters, then one worked example."))
    elif words < 50:
        tips.append(("Explanation", f"The explanation is only {words} words. Add the idea step by step and one worked example."))
    elif words > 220:
        tips.append(("Explanation", f"{words} words is long for a nugget. Keep one idea per nugget (about 80–150 words) and move the rest to a second nugget."))
    else:
        good.append("Explanation has a good length for a 5-minute nugget.")
    if avg > 22:
        tips.append(("Explanation", f"Sentences average {avg} words. Use shorter sentences (10–15 words) so weaker students can follow."))
    if expl and not re.search(r"(example|for instance|e\.g\.|مثال|\$|\d)", expl, re.I):
        tips.append(("Explanation", "Add a worked example with real numbers or a real-life situation."))
    if expl and "**" not in expl and "\n" not in expl and words > 60:
        tips.append(("Explanation", "Break it up: use short paragraphs, a bullet list and **bold** for the key words."))
    if not 3 <= len(points) <= 6:
        tips.append(("Key points", "Write 3–6 key points: the things the student must remember, one short line each."))
    else:
        good.append("Key points are clear and the right number.")
    if len(cards) < 4:
        tips.append(("Flashcards", "Add at least 4–6 flashcards (term → meaning, or question → answer) for quick practice."))
    else:
        good.append("Flashcards give enough practice.")
    if len(qs) < 3:
        tips.append(("Quick check", "Add 3–5 multiple-choice questions so the nugget can be mastered and graded automatically."))
    else:
        good.append("The quick check has enough questions.")
        if any(not q.get("why") for q in qs):
            tips.append(("Quick check", "Add a one-line explanation to every question — students learn from the feedback."))
        if len({q["answer"] for q in qs}) == 1 and len(qs) > 2:
            tips.append(("Quick check", "All correct answers are in the same position. Mix them up."))
    if not d["video_url"]:
        tips.append(("Engagement", "A short video (2–4 minutes) or a diagram helps visual learners. Paste a link in “Video link”."))
    score = max(3, 10 - len(tips))
    summary = ("Good nugget — only small polish needed." if score >= 8 else "Decent start. Fix the points below to make it clearer for struggling students."
               if score >= 6 else "Needs work before sending to students. Start with the first suggestions.")
    return {"score": score, "summary": summary, "strengths": good[:4], "improvements": [{"area": a, "tip": t} for a, t in tips[:7]]}


def _system(d, lang):
    language = "Urdu (Urdu script)" if lang == "urs" else "the same language as the draft (English if unsure)"
    return (f"You are an expert school curriculum coach. A teacher wrote a draft micro-lesson ('nugget', about 5 minutes) for a "
            f"{d['class_name']} {d['subject']} student who is struggling. Review it and give specific, practical, kind advice on how to make it "
            f"clearer, simpler and more engaging. Base everything ONLY on the draft and standard curriculum facts; never invent facts. "
            f"Write feedback in simple English. Write any rewritten or new learning content in {language}. "
            'Reply with ONE JSON object only, no markdown: {"score": 1-10, "summary": "", "strengths": ["max 4"], '
            '"improvements": [{"area": "Explanation|Key points|Flashcards|Quick check|Engagement", "tip": ""}] (max 6), '
            '"improved_explanation": "better version, 80-150 words; you may use **bold**, - bullets and 1. numbers", '
            '"extra_key_points": ["up to 4 new points, or []"], "extra_cards": [["front","back"]] (up to 5), '
            '"extra_questions": [{"q": "", "options": ["4 options"], "answer": 0, "why": ""}] (up to 3, new questions only)}. '
            "answer is the 0-based index of the correct option. Keep every string under 400 characters except improved_explanation (under 1200).")


def _clean(data, fb):
    out = {"score": fb["score"], "summary": fb["summary"], "strengths": fb["strengths"], "improvements": fb["improvements"]}
    try:
        out["score"] = max(1, min(10, int(float(data.get("score")))))
    except (TypeError, ValueError):
        pass
    out["summary"] = _s(data.get("summary"), 400) or out["summary"]
    st = [_s(x, 300) for x in data.get("strengths") or [] if _s(x, 300)][:4]
    imp = [{"area": _s(i.get("area"), 30) or "General", "tip": _s(i.get("tip"), 400)} for i in data.get("improvements") or [] if isinstance(i, dict) and _s(i.get("tip"), 400)][:6]
    out["strengths"], out["improvements"] = st or out["strengths"], imp or out["improvements"]
    out["improved_explanation"] = _s(data.get("improved_explanation"), 1400)
    out["extra_key_points"] = [_s(x, 200) for x in data.get("extra_key_points") or [] if _s(x, 200)][:4]
    out["extra_cards"] = [[_s(c[0], 120), _s(c[1], 200)] for c in data.get("extra_cards") or [] if isinstance(c, (list, tuple)) and len(c) >= 2 and _s(c[0], 120) and _s(c[1], 200)][:5]
    qs = []
    for q in data.get("extra_questions") or []:
        try:
            opts = [_s(o, 160) for o in q["options"] if _s(o, 160)][:4]
            ans = int(q["answer"])
            if _s(q["q"], 300) and 2 <= len(opts) <= 4 and 0 <= ans < len(opts):
                qs.append({"q": _s(q["q"], 300), "options": opts, "answer": ans, "why": _s(q.get("why"), 300)})
        except (KeyError, TypeError, ValueError):
            continue
    out["extra_questions"] = qs[:3]
    return out


def question_line(q):
    opts = list(q["options"]) + [""] * (4 - len(q["options"]))
    return " | ".join([q["q"]] + opts[:4] + [LETTERS[q["answer"]], q.get("why", "")])


def review(d):
    """d: course/subject/class_name/topic/title/explanation/key_points/video_url/cards/questions. Returns (result, source, error)."""
    fb = rules(d)
    if not ai.enabled():
        return fb, "rules", ""
    try:
        text = ai.call_model(_system(d, ai.subject_lang(d["subject"])), json.dumps(
            {k: d[k] for k in ("topic", "title", "explanation", "key_points", "video_url", "cards", "questions")}, ensure_ascii=False))
        return _clean(ai.parse_json(text), fb), "ai", ""
    except Exception as e:
        return fb, "rules", f"AI unavailable ({type(e).__name__}) — showing rule-based tips."[:200]
