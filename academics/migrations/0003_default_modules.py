from django.db import migrations


def forward(apps, schema_editor):
    Course = apps.get_model("academics", "Course")
    Module = apps.get_model("academics", "Module")
    Lesson = apps.get_model("academics", "Lesson")
    for c in Course.objects.all():
        orphans = Lesson.objects.filter(course=c, module__isnull=True)
        if orphans.exists():
            m = Module.objects.filter(course=c).first() or Module.objects.create(course=c, title="Module 1", position=1)
            orphans.update(module=m)


class Migration(migrations.Migration):
    dependencies = [("academics", "0002_modules_items_help")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
