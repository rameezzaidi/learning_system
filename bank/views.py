from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.rbac import perm_required
from core import audit

from . import services
from .models import BankQuestion


def _course(request, pk):
    return get_object_or_404(services.courses_for(request.user), pk=pk)


@login_required
@perm_required("bank.manage")
def index(request):
    rows = []
    for c in services.courses_for(request.user):
        rows.append((c, c.bank_questions.count()))
    return render(request, "bank/index.html", {"rows": rows, "page": "bank"})


@login_required
@perm_required("bank.manage")
def course(request, pk):
    c = _course(request, pk)
    if request.method == "POST":
        act = request.POST.get("action")
        if act == "add":
            p = request.POST
            kind = p.get("kind") if p.get("kind") in ("mcq", "tf", "short") else "mcq"
            opts = [p.get(f"opt{i}", "") for i in range(4)]
            corr = [int(p["correct"])] if p.get("correct", "").isdigit() else []
            if kind == "tf":
                corr = [0 if p.get("tf") == "true" else 1] if p.get("tf") in ("true", "false") else []
            q, err = services.add_question(c, request.user, kind, p.get("text"), p.get("topic"), int(p.get("difficulty") or 2), p.get("explanation"), opts, corr, p.get("accepted", ""))
            messages.error(request, err) if err else messages.success(request, "Question added to the bank.")
        elif act == "import":
            f = request.FILES.get("file")
            if not f:
                messages.error(request, "Choose a CSV file.")
            else:
                n, errs = services.import_csv(c, request.user, f)
                audit.record(request, "bank.import", str(c), f"{n} questions")
                if n:
                    messages.success(request, f"{n} question(s) imported.")
                for e in errs[:6]:
                    messages.error(request, e)
        elif act == "delete":
            BankQuestion.objects.filter(course=c, pk=request.POST.get("id") or 0).delete()
            messages.success(request, "Question removed from the bank.")
        elif act == "generate":
            p = request.POST

            def num(k):
                return max(0, min(int(p.get(k) or 0), 100)) if (p.get(k) or "0").isdigit() else 0
            a, notes = services.generate(c, request.user, p.get("title", ""), num("easy"), num("medium"), num("hard"), p.get("topic", "").strip(), num("duration"), p.get("kind", "quiz"))
            for n in notes:
                messages.warning(request, n)
            if a:
                audit.record(request, "bank.generate", str(c), a.title)
                messages.success(request, "Draft paper created. Review it, then publish when ready.")
                return redirect("assessments:detail", pk=a.pk)
        return redirect("bank:course", pk=c.pk)
    qs = c.bank_questions.prefetch_related("choices")
    topic, diff, q = request.GET.get("topic", ""), request.GET.get("difficulty", ""), request.GET.get("q", "").strip()
    if topic:
        qs = qs.filter(topic__iexact=topic)
    if diff in ("1", "2", "3"):
        qs = qs.filter(difficulty=int(diff))
    if q:
        qs = qs.filter(text__icontains=q)
    topics = list(c.bank_questions.exclude(topic="").values_list("topic", flat=True).distinct().order_by("topic"))
    return render(request, "bank/course.html", {"c": c, "qs": qs[:200], "topics": topics, "topic": topic, "diff": diff, "q": q, "total": c.bank_questions.count(), "page": "bank"})
