"""XP, daily streak and badges. Small on purpose: rewards effort and revision, never ranks students against each other."""
from django.utils import timezone

from .models import LearnerStat

XP = {"attempt": 5, "mastered": 30, "review": 15, "perfect": 10}
BADGES = {
    "first_try": ("🌱", "First step", "Tried your first nugget"),
    "master_1": ("🎯", "Mastered one", "Mastered a nugget"),
    "master_5": ("🏅", "Five mastered", "Mastered 5 nuggets"),
    "master_10": ("🏆", "Ten mastered", "Mastered 10 nuggets"),
    "perfect": ("💯", "Perfect score", "Scored 100% on a quick check"),
    "streak_3": ("🔥", "3-day streak", "Learned 3 days in a row"),
    "streak_7": ("⚡", "7-day streak", "Learned 7 days in a row"),
    "reviser": ("🔁", "Reviser", "Passed a spaced revision"),
    "xp_500": ("⭐", "500 XP", "Earned 500 XP"),
}


def stat_for(student):
    return LearnerStat.objects.get_or_create(student=student)[0]


def touch(student, xp=0):
    """Count today as a learning day (streak) and add XP. Returns the stat."""
    st = stat_for(student)
    today = timezone.localdate()
    if st.last_day != today:
        st.streak = st.streak + 1 if st.last_day == today - timezone.timedelta(days=1) else 1
        st.best_streak = max(st.best_streak, st.streak)
        st.last_day = today
    st.xp += xp
    st.save()
    return st


def award_badges(student, st, mastered_count, perfect=False, reviewed=False, tried_first=False):
    have, new = set(st.badges or []), []
    checks = [("first_try", tried_first), ("master_1", mastered_count >= 1), ("master_5", mastered_count >= 5),
              ("master_10", mastered_count >= 10), ("perfect", perfect), ("streak_3", st.streak >= 3),
              ("streak_7", st.streak >= 7), ("reviser", reviewed), ("xp_500", st.xp >= 500)]
    for key, ok in checks:
        if ok and key not in have:
            new.append(key)
    if new:
        st.badges = list(have | set(new))
        st.save(update_fields=["badges"])
    return [{"key": k, "emoji": BADGES[k][0], "name": BADGES[k][1], "text": BADGES[k][2]} for k in new]


def badge_list(st):
    return [{"key": k, "emoji": BADGES[k][0], "name": BADGES[k][1], "text": BADGES[k][2]} for k in BADGES if k in (st.badges or [])]
