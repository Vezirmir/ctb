from django.db import migrations


def rename(apps, schema_editor):
    apps.get_model("directory", "Industry").objects.filter(
        name_en="Home appliances", name_tr="Ev aletleri").update(name_tr="Beyaz Eşya")


class Migration(migrations.Migration):
    dependencies = [("directory", "0002_events_matchmaking")]
    operations = [migrations.RunPython(rename, migrations.RunPython.noop)]
