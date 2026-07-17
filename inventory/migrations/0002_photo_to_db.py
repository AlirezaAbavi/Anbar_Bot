"""Move product/variant photos from on-disk ImageField files into an in-DB BinaryField.

Order matters: add the new column, copy bytes from the existing files, then drop the
old column. The reverse is a no-op — going back would need the files, which are gone.
"""

from django.db import migrations, models


def copy_photos_into_db(apps, schema_editor):
    for model_name in ("Product", "ProductVariant"):
        Model = apps.get_model("inventory", model_name)
        for obj in Model.objects.all():
            f = obj.photo
            if not f:
                continue
            try:
                f.open("rb")
                obj.photo_data = f.read()
                f.close()
            except (FileNotFoundError, ValueError, OSError):
                # File missing/unreadable — leave photo_data null and move on.
                continue
            obj.save(update_fields=["photo_data"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="photo_data",
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="productvariant",
            name="photo_data",
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(copy_photos_into_db, noop),
        migrations.RemoveField(model_name="product", name="photo"),
        migrations.RemoveField(model_name="productvariant", name="photo"),
    ]
