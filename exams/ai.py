"""Suggestions for a student or a whole class.

Uses a configured AI provider (free Gemini / Groq / local Ollama, or Claude), and ALWAYS falls back to a
built-in rule-based generator, so the feature works with no key and never breaks if the API is down.
Only anonymised numbers are sent to the API: no names, usernames, emails or ids.
"""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings

API_URL = "https://api.anthropic.com/v1/messages"
LANGS = {"en": "English", "ur": "Urdu"}

# ---------------------------------------------------------------- wording (rule-based)
TXT = {
    "en": {
        "overall": "Overall {pct}% (grade {grade}), position {rank} of {n}.",
        "overall_norank": "Overall {pct}% (grade {grade}).",
        "up": "That is {d} points better than the previous exam.",
        "down": "That is {d} points lower than the previous exam.",
        "best": "Strongest subject: {s}.",
        "attn": "Needs attention: {s}.",
        "all_good": "No weak subject this time.",
        "strength": "{s}: {p}% — {g}. Keep it up.",
        "i_failed": "below the pass marks ({m}/{t})", "i_absent": "was absent", "i_below60": "only {p}%",
        "i_class": "{g} points under the class average", "i_quiz": "quiz scores are also low ({q}%)",
        "i_drop": "dropped {d} points since the last exam",
        "adv_hard": "Go back to the basic chapters, practise 20–30 minutes daily, solve past questions, and ask the teacher about every unclear topic.",
        "adv_med": "Revise the weaker chapters twice a week and attempt 5–10 practice questions each time.",
        "plan_keep": "Keep a regular study routine (30–45 minutes daily) and revise strong subjects weekly so they stay strong.",
        "t_note": "Give extra practice or one-to-one support in: {s}. Re-check progress with a short quiz in 2 weeks.",
        "t_note_ok": "No major concern. Keep encouraging the student and give extension work in the strongest subject.",
        "p_note": "Please set a fixed 30–45 minute study time at home, check the diary daily, and encourage — especially in: {s}.",
        "p_note_ok": "Good result. Please keep the routine going and appreciate the effort.",
        "mot": "Small daily effort beats last-minute cramming — you can improve step by step.",
        "mot_good": "Great work! Stay consistent and aim even higher next time.",
        "pw1_t": "Week 1 — Basics",
        "pw1_a": "List the chapters or topics you find hardest in {s}.",
        "pw1_b": "Re-read your notes and textbook, and write a one-page summary of each topic.",
        "pw1_c": "Solve 5 easy questions every day.",
        "pw2_t": "Week 2 — Practice",
        "pw2_a": "Study the solved examples, then try 10 questions a day without looking at the answers.",
        "pw2_b": "Keep a mistake notebook: write each wrong answer with the correct method.",
        "pw3_t": "Week 3 — Test yourself",
        "pw3_a": "Take a 20-minute self-test twice this week.",
        "pw3_b": "Re-do every question from your mistake notebook.",
        "pw3_c": "Ask your teacher about any topic that is still unclear.",
        "pw3_q": "Retake the {s} quizzes in your course until you score 70% or more.",
        "pw4_t": "Week 4 — Mock paper",
        "pw4_a": "Attempt one full mock paper within the exam time limit.",
        "pw4_b": "Revise your mistake notebook and the key formulas / points.",
        "pcheck": "After 4 weeks ask your teacher for a short test. Goal: reach {t}% in {s}.",
        "tt_off": "Weekly revision + rest",
        "tt_tip": "Study in a quiet place, keep the phone away, and tick each day on this timetable when it is done.",
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        # class
        "c_sum": "{n} students; class average {avg}%, pass rate {pass_pct}%.",
        "c_vs": "Class average is {d} points {dir} than the previous exam.",
        "c_dir_up": "higher", "c_dir_down": "lower",
        "c_best": "Best subject: {s} ({a}%).", "c_worst": "Weakest subject: {s} ({a}%).",
        "c_weak": "{s}: class average {a}%, pass rate {p}%.",
        "c_adv": "Re-teach the key concepts, give a revision test, and arrange extra classes for students scoring below 50%.",
        "c_risk": "{n} student(s) need attention (failed, below 50%, or a big drop). See the list on this page.",
        "c_norisk": "No student is at risk right now.",
        "c_act1": "Hold a revision week for: {s}.",
        "c_act2": "Group students by level and give targeted practice sheets.",
        "c_act3": "Meet the at-risk students and their parents within the next week.",
        "c_act4": "Repeat a short test after 2–3 weeks to measure improvement.",
        "c_nodata": "Not enough marks entered yet for a class summary.",
    },
}


# Urdu (Urdu script) wording: used for the whole Urdu copy of the guidance, and for the subject-specific parts of Urdu / Islamiat.
URS = {
    "overall": "مجموعی {pct}% (گریڈ {grade})، کلاس میں {n} میں سے پوزیشن {rank}۔",
    "overall_norank": "مجموعی {pct}% (گریڈ {grade})۔",
    "up": "یہ پچھلے امتحان سے {d} پوائنٹس بہتر ہے۔", "down": "یہ پچھلے امتحان سے {d} پوائنٹس کم ہے۔",
    "best": "سب سے مضبوط مضمون: {s}۔", "attn": "توجہ درکار ہے: {s}۔", "all_good": "اس بار کوئی کمزور مضمون نہیں۔",
    "strength": "{s}: {p}% — {g}۔ اسی طرح جاری رکھیں۔",
    "i_failed": "پاس مارکس سے کم ({m}/{t})", "i_absent": "غیر حاضر تھا/تھی", "i_below60": "صرف {p}%",
    "i_class": "کلاس اوسط سے {g} پوائنٹس کم", "i_quiz": "کوئز کے نتائج بھی کم ہیں ({q}%)",
    "i_drop": "پچھلے امتحان سے {d} پوائنٹس گر گیا",
    "adv_hard": "بنیادی ابواب دوبارہ پڑھیں، روزانہ 20 سے 30 منٹ مشق کریں، پرانے سوالات حل کریں، اور جو موضوع سمجھ نہ آئے وہ استاد سے پوچھیں۔",
    "adv_med": "کمزور ابواب ہفتے میں دو بار دہرائیں اور ہر بار 5 سے 10 مشقی سوالات حل کریں۔",
    "plan_keep": "روزانہ 30 سے 45 منٹ پڑھائی کا معمول رکھیں اور مضبوط مضامین ہفتے میں ایک بار دہرائیں تاکہ وہ مضبوط رہیں۔",
    "t_note": "ان مضامین میں اضافی مشق یا انفرادی مدد دیں: {s}۔ 2 ہفتوں بعد مختصر کوئز سے پیش رفت جانچیں۔",
    "t_note_ok": "کوئی بڑی تشویش نہیں۔ طالب علم کی حوصلہ افزائی کریں اور سب سے مضبوط مضمون میں اضافی کام دیں۔",
    "p_note": "براہِ کرم گھر پر روزانہ 30 سے 45 منٹ پڑھائی کا مقررہ وقت رکھیں، ڈائری روزانہ دیکھیں، اور خاص طور پر ان مضامین میں حوصلہ بڑھائیں: {s}۔",
    "p_note_ok": "اچھا نتیجہ ہے۔ معمول جاری رکھیں اور محنت کی تعریف کریں۔",
    "mot": "روزانہ تھوڑی محنت آخری وقت کے رٹے سے بہتر ہے — آپ قدم بہ قدم بہتر ہو سکتے ہیں۔",
    "mot_good": "شاباش! تسلسل برقرار رکھیں اور اگلی بار اس سے بھی بہتر کا ہدف رکھیں۔",
    "pw1_t": "پہلا ہفتہ — بنیاد", "pw1_a": "{s} کے وہ ابواب یا موضوعات لکھیں جو سب سے مشکل لگتے ہیں۔",
    "pw1_b": "اپنے نوٹس اور کتاب دوبارہ پڑھیں اور ہر موضوع کا ایک صفحے کا خلاصہ لکھیں۔", "pw1_c": "روزانہ 5 آسان سوالات حل کریں۔",
    "pw2_t": "دوسرا ہفتہ — مشق", "pw2_a": "حل شدہ مثالیں دیکھیں، پھر جواب دیکھے بغیر روزانہ 10 سوالات حل کریں۔",
    "pw2_b": "غلطیوں کی کاپی بنائیں: ہر غلط جواب کو درست طریقے کے ساتھ لکھیں۔",
    "pw3_t": "تیسرا ہفتہ — خود کو آزمائیں", "pw3_a": "اس ہفتے 20 منٹ کا خود امتحان دو بار لیں۔",
    "pw3_b": "غلطیوں کی کاپی کا ہر سوال دوبارہ حل کریں۔", "pw3_c": "جو موضوع اب بھی سمجھ نہ آئے وہ استاد سے پوچھیں۔",
    "pw3_q": "اپنے کورس کے {s} کوئز دوبارہ دیں جب تک 70% یا زیادہ نہ آ جائے۔",
    "pw4_t": "چوتھا ہفتہ — ماک پیپر", "pw4_a": "امتحان کے وقت کے اندر ایک مکمل ماک پیپر حل کریں۔",
    "pw4_b": "غلطیوں کی کاپی اور اہم نکات دہرائیں۔",
    "pcheck": "4 ہفتوں بعد استاد سے مختصر ٹیسٹ لینے کو کہیں۔ ہدف: {s} میں {t}% تک پہنچنا۔",
    "tt_off": "ہفتے بھر کی دہرائی + آرام",
    "tt_tip": "پُرسکون جگہ پر پڑھیں، فون دور رکھیں، اور ہر دن کا کام مکمل ہونے پر اس ٹائم ٹیبل میں نشان لگائیں۔",
    "days": ["پیر", "منگل", "بدھ", "جمعرات", "جمعہ", "ہفتہ", "اتوار"],
    # class
    "c_sum": "{n} طلبہ؛ کلاس اوسط {avg}%، کامیابی کی شرح {pass_pct}%۔",
    "c_vs": "کلاس اوسط پچھلے امتحان سے {d} پوائنٹس {dir} ہے۔", "c_dir_up": "زیادہ", "c_dir_down": "کم",
    "c_best": "بہترین مضمون: {s} ({a}%)۔", "c_worst": "سب سے کمزور مضمون: {s} ({a}%)۔",
    "c_weak": "{s}: کلاس اوسط {a}%، کامیابی کی شرح {p}%۔",
    "c_adv": "اہم تصورات دوبارہ پڑھائیں، دہرائی کا ٹیسٹ لیں، اور 50% سے کم نمبر والے طلبہ کے لیے اضافی کلاس رکھیں۔",
    "c_risk": "{n} طلبہ کو توجہ درکار ہے (فیل، 50% سے کم، یا بڑی کمی)۔ فہرست اسی صفحے پر موجود ہے۔",
    "c_norisk": "فی الحال کوئی طالب علم خطرے میں نہیں۔",
    "c_act1": "ان مضامین کے لیے دہرائی کا ہفتہ رکھیں: {s}۔",
    "c_act2": "طلبہ کو سطح کے لحاظ سے گروپوں میں بانٹیں اور مخصوص مشقی شیٹس دیں۔",
    "c_act3": "خطرے والے طلبہ اور ان کے والدین سے اگلے ہفتے ملاقات کریں۔",
    "c_act4": "2 سے 3 ہفتے بعد مختصر ٹیسٹ دوبارہ لیں تاکہ بہتری ناپی جا سکے۔",
    "c_nodata": "کلاس خلاصے کے لیے ابھی کافی نمبر درج نہیں ہوئے۔",
}
TXT["ur"] = TXT["urs"] = {**TXT["en"], **URS}   # Urdu script everywhere; anything not translated falls back to English
LANGS["ur"] = LANGS["urs"] = "Urdu"


def subject_lang(name):
    """Language used for a subject's own weak-area text and study plan: Urdu script for Urdu/Islamiat, English otherwise."""
    from core.subjects import subject_kind
    return "urs" if subject_kind(name) == "urdu" else "en"


def _t(lang, key, **kw):
    v = TXT.get(lang, TXT["en"])[key]
    return v.format(**kw) if isinstance(v, str) else v


def _issue(lang, s):
    parts = []
    if "absent" in s["reasons"]:
        parts.append(_t(lang, "i_absent"))
    if "failed" in s["reasons"]:
        parts.append(_t(lang, "i_failed", m=s["marks"], t=s["total"]))
    elif "below_60" in s["reasons"]:
        parts.append(_t(lang, "i_below60", p=s["pct"]))
    if "below_class" in s["reasons"]:
        parts.append(_t(lang, "i_class", g=abs(s["gap"])))
    if "weak_quizzes" in s["reasons"]:
        parts.append(_t(lang, "i_quiz", q=s["quiz_avg"]))
    if s["declining"]:
        parts.append(_t(lang, "i_drop", d=abs(s["delta"])))
    return "; ".join(parts) or _t(lang, "i_below60", p=s["pct"])



def study_plans(lang, weak):
    """Week-by-week plan for every weak subject (max 4) plus a daily timetable the student can tick off.
    Each subject's plan is written in that subject's language (Urdu script for Urdu / Islamiat, English otherwise)."""
    plans = []
    for s in weak[:4]:
        pct = s["pct"] or 0
        hard = pct < 50 or "failed" in s["reasons"] or "absent" in s["reasons"]
        name, sl = s["subject"], subject_lang(s["subject"])
        target = int(round(min(100, max(pct + 15, 50))))
        w3 = [_t(sl, "pw3_a"), _t(sl, "pw3_b"), _t(sl, "pw3_c")]
        if "weak_quizzes" in s["reasons"]:
            w3.append(_t(sl, "pw3_q", s=name))
        plans.append({
            "subject": name, "lang": sl, "current": pct, "target": target, "daily_minutes": 45 if hard else 30,
            "weeks": [
                {"title": _t(sl, "pw1_t"), "tasks": [_t(sl, "pw1_a", s=name), _t(sl, "pw1_b"), _t(sl, "pw1_c")]},
                {"title": _t(sl, "pw2_t"), "tasks": [_t(sl, "pw2_a"), _t(sl, "pw2_b")]},
                {"title": _t(sl, "pw3_t"), "tasks": w3},
                {"title": _t(sl, "pw4_t"), "tasks": [_t(sl, "pw4_a"), _t(sl, "pw4_b")]}],
            "checkpoint": _t(sl, "pcheck", s=name, t=target),
        })
    en_days, ur_days, table = _t("en", "days"), _t("ur", "days"), []
    for i in range(6):
        if plans:
            p = plans[i % len(plans)]
            table.append({"day": f"{en_days[i]} · {ur_days[i]}", "subject": p["subject"], "minutes": p["daily_minutes"]})
    if plans:
        table.append({"day": f"{en_days[6]} · {ur_days[6]}", "subject": _t("en", "tt_off") + " · " + _t("ur", "tt_off"), "minutes": 0})
    return plans, table, ((_t("en", "tt_tip"), _t("ur", "tt_tip")) if plans else ("", ""))


def rule_student(ins, lang="en"):
    weak, strong = ins["weak"], ins["strong"]
    names = ", ".join(s["subject"] for s in weak)
    if ins["rank"]:
        head = _t(lang, "overall", pct=ins["overall_pct"], grade=ins["grade"], rank=ins["rank"], n=ins["n_ranked"])
    else:
        head = _t(lang, "overall_norank", pct=ins["overall_pct"], grade=ins["grade"])
    bits = [head]
    if ins["delta"]:
        bits.append(_t(lang, "up" if ins["delta"] > 0 else "down", d=abs(ins["delta"])))
    if strong:
        bits.append(_t(lang, "best", s=strong[0]["subject"]))
    bits.append(_t(lang, "attn", s=names) if weak else _t(lang, "all_good"))
    plan = []  # week-by-week detail now lives in subject_plans; these are general habits only
    plan.append(_t(lang, "plan_keep"))
    subject_plans, timetable, (tip, tip_ur) = study_plans(lang, weak)
    return {
        "summary": " ".join(bits),
        "strengths": [_t(lang, "strength", s=s["subject"], p=s["pct"], g=s["grade"]) for s in strong],
        "weak_areas": [{"subject": s["subject"], "lang": subject_lang(s["subject"]), "issue": _issue(subject_lang(s["subject"]), s),
                        "advice": _t(subject_lang(s["subject"]), "adv_hard" if (s["pct"] is None or s["pct"] < 50 or "failed" in s["reasons"]) else "adv_med")}
                       for s in weak],
        "action_plan": plan,
        "teacher_note": _t(lang, "t_note", s=names) if weak else _t(lang, "t_note_ok"),
        "parent_note": _t(lang, "p_note", s=names) if weak else _t(lang, "p_note_ok"),
        "motivation": _t(lang, "mot" if weak else "mot_good"),
        "subject_plans": subject_plans, "timetable": timetable, "timetable_tip": tip, "timetable_tip_ur": tip_ur,
    }


def rule_class(cins, lang="en"):
    if not cins["n_complete"]:
        return {"summary": _t(lang, "c_nodata"), "key_findings": [], "weak_subjects": [], "teaching_actions": [], "at_risk_note": ""}
    bits = [_t(lang, "c_sum", n=cins["n_complete"], avg=cins["avg_pct"], pass_pct=cins["pass_pct"])]
    if cins["prev_avg"] is not None and cins["avg_pct"] != cins["prev_avg"]:
        d = round(cins["avg_pct"] - cins["prev_avg"], 1)
        bits.append(_t(lang, "c_vs", d=abs(d), dir=_t(lang, "c_dir_up" if d > 0 else "c_dir_down")))
    findings = []
    if cins["best_subject"]:
        findings.append(_t(lang, "c_best", s=cins["best_subject"]["subject"], a=cins["best_subject"]["avg_pct"]))
    if cins["subjects"]:
        w = cins["subjects"][0]
        findings.append(_t(lang, "c_worst", s=w["subject"], a=w["avg_pct"]))
    weak_names = ", ".join(p["subject"] for p in cins["weak_subjects"])
    actions = ([_t(lang, "c_act1", s=weak_names)] if weak_names else []) + [_t(lang, "c_act2")]
    if cins["at_risk"]:
        actions.append(_t(lang, "c_act3"))
    actions.append(_t(lang, "c_act4"))
    return {
        "summary": " ".join(bits), "key_findings": findings,
        "weak_subjects": [{"subject": p["subject"], "issue": _t(lang, "c_weak", s=p["subject"], a=p["avg_pct"], p=p["pass_rate"]),
                           "advice": _t(lang, "c_adv")} for p in cins["weak_subjects"]],
        "teaching_actions": actions,
        "at_risk_note": _t(lang, "c_risk", n=len(cins["at_risk"])) if cins["at_risk"] else _t(lang, "c_norisk"),
    }


# ---------------------------------------------------------------- anonymised payloads
def student_payload(ins):
    return {
        "overall_percent": ins["overall_pct"], "grade": ins["grade"], "gpa": ins["gpa"], "rank": ins["rank"],
        "students_ranked": ins["n_ranked"], "result": ins["result"], "previous_exam_percent": ins["prev_pct"],
        "change_vs_previous": ins["delta"],
        "subjects": [{"subject": s["subject"], "percent": s["pct"], "grade": s["grade"], "class_average_percent": s["class_avg"],
                      "previous_percent": s["prev_pct"], "change": s["delta"], "quiz_average_percent": s["quiz_avg"],
                      "status": s["status"], "flags": s["reasons"]} for s in ins["subjects"]],
    }


def class_payload(cins):
    return {
        "students": cins["n_complete"], "class_average_percent": cins["avg_pct"], "previous_class_average": cins["prev_avg"],
        "pass_percent": cins["pass_pct"],
        "subjects": [{"subject": p["subject"], "average_percent": p["avg_pct"], "pass_rate_percent": p["pass_rate"],
                      "flags": p["flags"]} for p in cins["subjects"]],
        "students_at_risk": len(cins["at_risk"]),
    }


# ---------------------------------------------------------------- Claude call
SCHEMAS = {
    "student": '{"summary": str, "strengths": [str], "weak_areas": [{"subject": str, "issue": str, "advice": str}], '
               '"action_plan": [str], "teacher_note": str, "parent_note": str, "motivation": str}',
    "class": '{"summary": str, "key_findings": [str], "weak_subjects": [{"subject": str, "issue": str, "advice": str}], '
             '"teaching_actions": [str], "at_risk_note": str}',
}


def _system(kind, lang):
    who = "one student's exam result" if kind == "student" else "a whole class's exam results"
    return (f"You are an experienced school academic advisor. You receive anonymised numbers about {who}. "
            f"Give specific, practical, encouraging guidance based ONLY on the data (do not invent marks or facts). "
            f"Write in {LANGS.get(lang, 'English')}" + (" (written in Urdu script, simple everyday words; use short sentences)" if lang in ("ur", "urs") else "") +
            f". Reply with ONE JSON object only, no markdown, exactly in this shape: {SCHEMAS[kind]}. "
            f"Keep every string under 300 characters; at most 6 items per list. action_plan holds general habits (max 4). "
            f"subject_plans: one entry per weak subject (max 3), each with exactly 4 weeks and 2-3 short concrete tasks per week, "
            f"plus a checkpoint sentence; omit it if there is no weak subject.")


DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "gemini": "gemini-2.0-flash", "groq": "llama-3.3-70b-versatile", "ollama": "llama3.1"}
FREE_AUTO_ORDER = ("gemini", "groq", "anthropic")


def provider():
    """Active provider name, or "" when only the built-in rule-based guidance is available."""
    p = (getattr(settings, "AI_PROVIDER", "auto") or "auto").lower()
    keys = {"anthropic": settings.ANTHROPIC_API_KEY, "gemini": getattr(settings, "GEMINI_API_KEY", ""),
            "groq": getattr(settings, "GROQ_API_KEY", ""), "ollama": "local"}
    if p == "auto":
        return next((n for n in FREE_AUTO_ORDER if keys[n]), "")
    return p if keys.get(p) else ""


def enabled():
    return bool(provider())


def model_name():
    return settings.AI_MODEL or DEFAULT_MODELS.get(provider(), "")


def _post(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def call_model(system, user_text):
    """Send the prompt to the active provider (stdlib only). Raises on any problem."""
    prov, model = provider(), model_name()
    if prov == "anthropic":
        data = _post(API_URL, {"model": model, "max_tokens": 3000, "system": system,
                               "messages": [{"role": "user", "content": user_text}]},
                     {"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if prov == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        data = _post(url, {"systemInstruction": {"parts": [{"text": system}]},
                           "contents": [{"role": "user", "parts": [{"text": user_text}]}],
                           "generationConfig": {"maxOutputTokens": 3000, "responseMimeType": "application/json"}},
                     {"x-goog-api-key": settings.GEMINI_API_KEY})
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    if prov == "groq":
        data = _post("https://api.groq.com/openai/v1/chat/completions",
                     {"model": model, "max_tokens": 3000, "response_format": {"type": "json_object"},
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}]},
                     {"authorization": f"Bearer {settings.GROQ_API_KEY}"})
        return data["choices"][0]["message"]["content"]
    if prov == "ollama":
        data = _post(settings.OLLAMA_URL.rstrip("/") + "/api/chat",
                     {"model": model, "stream": False, "format": "json",
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}]}, {})
        return data["message"]["content"]
    raise RuntimeError("no AI provider configured")


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def _s(v, n=400):
    return str(v).strip()[:n] if isinstance(v, (str, int, float)) else ""


def _list(v, n=6):
    return [_s(x) for x in v if _s(x)][:n] if isinstance(v, list) else []


def _issues(v):
    out = []
    for x in (v if isinstance(v, list) else [])[:8]:
        if isinstance(x, dict) and _s(x.get("subject")):
            out.append({"subject": _s(x.get("subject"), 80), "issue": _s(x.get("issue")), "advice": _s(x.get("advice"))})
    return out


def _plans_clean(v, fallback_plans):
    base = {p["subject"].lower(): p for p in fallback_plans}
    out = []
    for x in (v if isinstance(v, list) else [])[:4]:
        if not isinstance(x, dict) or _s(x.get("subject")).lower() not in base:
            continue
        ref = base[_s(x.get("subject")).lower()]
        weeks = [{"title": _s(w.get("title"), 80), "tasks": _list(w.get("tasks"), 4)} for w in (x.get("weeks") or [])[:4]
                 if isinstance(w, dict) and _list(w.get("tasks"), 4)] if isinstance(x.get("weeks"), list) else []
        out.append({**ref, "weeks": weeks or ref["weeks"], "checkpoint": _s(x.get("checkpoint")) or ref["checkpoint"]})
    got = {p["subject"].lower() for p in out}
    return out + [p for p in fallback_plans if p["subject"].lower() not in got]


def clean(kind, data, fallback):
    """Coerce the model's JSON into the exact shape the templates expect (missing parts come from the rule-based text)."""
    if not isinstance(data, dict):
        return fallback
    if kind == "student":
        out = {"summary": _s(data.get("summary")), "strengths": _list(data.get("strengths")), "weak_areas": _issues(data.get("weak_areas")),
               "action_plan": _list(data.get("action_plan"), 8), "teacher_note": _s(data.get("teacher_note")),
               "parent_note": _s(data.get("parent_note")), "motivation": _s(data.get("motivation")),
               "subject_plans": _plans_clean(data.get("subject_plans"), fallback.get("subject_plans", [])),
               "timetable": fallback.get("timetable", []), "timetable_tip": fallback.get("timetable_tip", ""),
               "timetable_tip_ur": fallback.get("timetable_tip_ur", "")}
    else:
        out = {"summary": _s(data.get("summary")), "key_findings": _list(data.get("key_findings")),
               "weak_subjects": _issues(data.get("weak_subjects")), "teaching_actions": _list(data.get("teaching_actions"), 8),
               "at_risk_note": _s(data.get("at_risk_note"))}
    for k, v in fallback.items():
        if not out.get(k):
            out[k] = v
    return out


def generate(kind, payload, fallback_ins, lang="en"):
    """Return (data, source, model_name, error). `fallback_ins` is the insights dict used by the rule-based generator."""
    rules = rule_student(fallback_ins, lang) if kind == "student" else rule_class(fallback_ins, lang)
    if not enabled():
        return rules, "rules", "", ""
    try:
        text = call_model(_system(kind, lang), json.dumps(payload, ensure_ascii=False))
        return clean(kind, parse_json(text), rules), "ai", model_name(), ""
    except Exception as e:  # network, quota, bad JSON ... never break the page
        return rules, "rules", "", f"AI unavailable ({type(e).__name__}); showing rule-based guidance."[:300]


def generate_both(kind, payload, fallback_ins):
    """English + Urdu (script) together; the Urdu copy lives in data["_ur"].

    Subject-specific parts (weak areas, study plans) are written in each subject's own language: Urdu script for
    Urdu / Islamiat subjects, English for the rest. Returns (data, source, model_name, error)."""
    en, src_en, model_en, err_en = generate(kind, payload, fallback_ins, "en")
    ur, src_ur, model_ur, err_ur = generate(kind, payload, fallback_ins, "ur")
    src, err = [src_en, src_ur], [err_en, err_ur]
    if kind == "student":
        urdu = {w["subject"] for w in en.get("weak_areas", []) if subject_lang(w["subject"]) == "urs"} | \
               {p["subject"] for p in en.get("subject_plans", []) if subject_lang(p["subject"]) == "urs"}
        if urdu:
            sub = dict(payload, subjects=[x for x in payload.get("subjects", []) if x["subject"] in urdu])
            us, src_us, model_us, err_us = generate(kind, sub, fallback_ins, "urs")
            src.append(src_us); err.append(err_us); model_en = model_en or model_us
            for key in ("weak_areas", "subject_plans"):
                keep = [x for x in en.get(key, []) if x["subject"] not in urdu]
                swap = [x for x in us.get(key, []) if x["subject"] in urdu]
                order = {w: i for i, w in enumerate(x["subject"] for x in en.get(key, []))}
                en[key] = sorted(keep + swap, key=lambda x: order.get(x["subject"], 99))
        for key in ("weak_areas", "subject_plans"):
            for x in en.get(key, []):
                x["lang"] = subject_lang(x["subject"])
    data = dict(en)
    data["_ur"] = ur
    return data, ("ai" if "ai" in src else "rules"), model_en or model_ur, next((e for e in err if e), "")
