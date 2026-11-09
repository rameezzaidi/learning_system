from django.db import migrations

BANDS = [("A+", 90, "4.0", "Outstanding"), ("A", 80, "3.5", "Excellent"), ("B", 70, "3.0", "Very good"),
         ("C", 60, "2.0", "Good"), ("D", 50, "1.0", "Satisfactory"), ("F", 0, "0.0", "Needs improvement")]


def seed(apps, schema_editor):
    GradeBand = apps.get_model("exams", "GradeBand")
    if not GradeBand.objects.exists():
        for g, m, p, r in BANDS:
            GradeBand.objects.create(grade=g, min_percent=m, points=p, remark=r)


class Migration(migrations.Migration):
    dependencies = [("exams", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
