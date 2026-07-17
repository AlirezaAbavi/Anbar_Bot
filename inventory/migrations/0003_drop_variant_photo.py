"""Drop the per-variant photo fields; one photo per product is enough.

Before removing the columns, copy any variant photo up to its product when the product
has no photo of its own, so no still-wanted image is lost. Photos live as raw JPEG bytes
in the DB (BinaryField), not on disk, so this is a pure in-DB copy.
"""

from django.db import migrations, models


def copy_variant_photos_up(apps, schema_editor):
    Product = apps.get_model("inventory", "Product")
    ProductVariant = apps.get_model("inventory", "ProductVariant")

    for product in Product.objects.all():
        if product.photo_data:  # already has its own photo — leave it
            continue
        variant = next(
            (v for v in ProductVariant.objects.filter(product=product) if v.photo_data),
            None,
        )
        if variant is not None:
            product.photo_data = variant.photo_data
            if not product.telegram_file_id:
                product.telegram_file_id = variant.telegram_file_id
            product.save(update_fields=["photo_data", "telegram_file_id"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_photo_to_db"),
    ]

    operations = [
        migrations.RunPython(copy_variant_photos_up, noop),
        migrations.RemoveField(model_name="productvariant", name="photo_data"),
        migrations.RemoveField(model_name="productvariant", name="telegram_file_id"),
    ]
