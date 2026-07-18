"""Import the Kidora Telegram-channel catalog export into the inventory tables.

Reads a curated catalog JSON (built from the channel's ChatExport) plus its photos
directory, and creates Product / ProductVariant rows. Codes and supplier notes are kept
verbatim in ``Product.description`` (per the catalog decisions); the chosen photo's raw
JPEG bytes go into ``Product.photo_data``. Stock is seeded empty (quantity 0, no
StockBatch) — real stock is added later through the bot's Stock-In flow.

Catalog JSON shape (one object per product)::

    {
      "name_fa": "کرومی", "name_en": "Kuromi",
      "photo": "photos/photo_90@18-07-2026_13-06-40.jpg",
      "description": "…original caption(s), incl. کد… codes…",
      "variants": [
        {"color": "", "size": "23", "purchase_price": 0, "sale_price": 391000,
         "quantity": 0, "reorder_threshold": 1, "wholesale_price": 340000}
      ]
    }

Usage::

    python manage.py import_catalog --export-dir ChatExport_2026-07-18 --wipe
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import (
    Category,
    DigikalaCode,
    Product,
    ProductVariant,
    StockAllocation,
    StockBatch,
    StockMovement,
)

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "kidora_catalog.json"


class Command(BaseCommand):
    help = "Import the Kidora channel catalog (products + variants + photos) into the DB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--export-dir",
            required=True,
            help="Path to the ChatExport directory (must contain the 'photos/' folder).",
        )
        parser.add_argument(
            "--data",
            default=str(DEFAULT_DATA),
            help="Path to the curated catalog JSON (defaults to the bundled kidora_catalog.json).",
        )
        parser.add_argument(
            "--wipe",
            action="store_true",
            help="Delete ALL existing inventory rows before importing (clean import).",
        )

    def handle(self, *args, **opts):
        import json

        export_dir = Path(opts["export_dir"]).expanduser()
        if not (export_dir / "photos").is_dir():
            raise CommandError(f"No 'photos/' folder under {export_dir}")

        data_path = Path(opts["data"]).expanduser()
        if not data_path.is_file():
            raise CommandError(f"Catalog data file not found: {data_path}")
        catalog = json.loads(data_path.read_text(encoding="utf-8"))

        with transaction.atomic():
            if opts["wipe"]:
                self._wipe()

            n_prod = n_var = n_photo = 0
            for item in catalog:
                photo_bytes = None
                rel = item.get("photo")
                if rel:
                    fp = export_dir / rel
                    if fp.is_file():
                        photo_bytes = fp.read_bytes()
                        n_photo += 1
                    else:
                        self.stderr.write(f"  ! missing photo for {item['name_fa']}: {rel}")

                product = Product.objects.create(
                    name_fa=item["name_fa"],
                    name_en=item.get("name_en", "") or "",
                    description=item.get("description", "") or "",
                    photo_data=photo_bytes,
                )
                n_prod += 1

                for v in item["variants"]:
                    ProductVariant.objects.create(
                        product=product,
                        color=v.get("color", "") or "",
                        size=v.get("size", "") or "",
                        quantity=int(v.get("quantity", 0)),
                        reorder_threshold=int(v.get("reorder_threshold", 1)),
                        purchase_price=int(v.get("purchase_price", 0)),
                        sale_price=int(v["sale_price"]),
                    )
                    n_var += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {n_prod} products, {n_var} variants, {n_photo} photos."
            )
        )

    def _wipe(self):
        """Remove all inventory rows, in FK-safe order."""
        for model in (
            StockAllocation,
            StockMovement,
            StockBatch,
            DigikalaCode,
            ProductVariant,
            Product,
            Category,
        ):
            deleted, _ = model.objects.all().delete()
            self.stdout.write(f"  wiped {model.__name__}: {deleted}")
