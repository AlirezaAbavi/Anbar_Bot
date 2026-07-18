from django.db import models
from django.utils import timezone


class Category(models.Model):
    name_fa = models.CharField("نام (فارسی)", max_length=128)
    name_en = models.CharField("Name (English)", max_length=128, blank=True)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["name_fa"]

    def __str__(self):
        return self.name_fa or self.name_en


class Product(models.Model):
    """An item/model. Stock is tracked on its variants, not here."""

    name_fa = models.CharField("نام (فارسی)", max_length=200)
    name_en = models.CharField("Name (English)", max_length=200, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    description = models.TextField(blank=True)

    # Product image (raw JPEG bytes, stored in-DB); shared by all of the product's variants.
    photo_data = models.BinaryField(blank=True, null=True, editable=False)
    telegram_file_id = models.CharField(max_length=256, blank=True)

    is_active = models.BooleanField(default=True)

    # Admin supervision pass over the imported catalog: the review walkthrough
    # (bot/handlers/review.py) steps through products in id order, flipping ``reviewed`` on
    # Save so it can resume at the first still-unreviewed product across sessions.
    reviewed = models.BooleanField(default=False, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "bot.TelegramUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Two products cannot share a Persian name. Near-duplicates ("استیچ" vs
        # "عروسک استیچ") are caught earlier, in the bot's add-product flow.
        constraints = [
            models.UniqueConstraint(fields=["name_fa"], name="uniq_product_name_fa")
        ]
        ordering = ["name_fa"]

    def __str__(self):
        return self.name_fa or self.name_en

    def display_name(self, lang="fa"):
        if lang == "en":
            return self.name_en or self.name_fa
        return self.name_fa or self.name_en

    def list_name(self):
        """Label for list views: '{English} - {Persian}'.

        Falls back to whichever name exists when the other is blank.
        """
        if self.name_en and self.name_fa:
            return f"{self.name_en} - {self.name_fa}"
        return self.name_en or self.name_fa


class ProductVariant(models.Model):
    """The sellable/stocked unit: a product in a specific color and/or size."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    color = models.CharField(max_length=64, blank=True)
    size = models.CharField(max_length=64, blank=True)

    # Mutated ONLY by inventory.services.adjust_stock (inside a transaction).
    quantity = models.IntegerField(default=0)
    reorder_threshold = models.IntegerField(
        default=0, help_text="Low-stock alert fires when quantity <= this value."
    )

    # Default buy/sell prices for the *next* purchase batch: the prefill for Stock-In, the
    # prices stamped onto the initial batch at variant creation, and the card's fallback
    # when the variant has no batch with stock left. Live valuation reads StockBatch, not
    # these — see inventory.services.inventory_summary and .active_batch.
    purchase_price = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    sale_price = models.DecimalField(max_digits=12, decimal_places=0, default=0)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # A product cannot have two variants with the same color+size combination.
        constraints = [
            models.UniqueConstraint(
                fields=["product", "color", "size"], name="uniq_variant_per_product"
            )
        ]
        ordering = ["product", "color", "size"]

    def __str__(self):
        return f"{self.product} · {self.variant_label() or 'default'}"

    def variant_label(self):
        """Human label like 'Red / L', or '' for a plain (default) variant."""
        return " / ".join(p for p in (self.color, self.size) if p)

    @property
    def is_low_stock(self) -> bool:
        return self.quantity <= self.reorder_threshold

    def active_batch(self):
        """The next lot FIFO will consume (earliest received with stock left), or None."""
        return (
            self.batches.filter(quantity_remaining__gt=0)
            .order_by("received_at", "id")
            .first()
        )


class DigikalaCode(models.Model):
    """A DigiKala product code (DKP). One code -> one variant; a variant may have many."""

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="digikala_codes"
    )
    code = models.CharField(max_length=32, unique=True, db_index=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        verbose_name = "DigiKala code"
        ordering = ["-is_primary", "code"]

    def __str__(self):
        return self.code


class StockMovement(models.Model):
    """Immutable audit-log entry for every stock change."""

    class Type(models.TextChoices):
        IN = "IN", "Stock In"
        OUT = "OUT", "Stock Out"
        ADJUST = "ADJUST", "Adjustment"

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="movements"
    )
    movement_type = models.CharField(max_length=6, choices=Type.choices)
    quantity = models.PositiveIntegerField(help_text="Magnitude of the change (always positive).")
    quantity_after = models.IntegerField(help_text="Stock level after this movement.")
    user = models.ForeignKey(
        "bot.TelegramUser", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="movements",
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        sign = "+" if self.movement_type == self.Type.IN else "-"
        return f"{self.variant} {sign}{self.quantity} → {self.quantity_after}"


class StockBatch(models.Model):
    """One purchase lot of a variant, carrying its own buy/sell price.

    A Stock-In creates a batch; a Stock-Out drains batches oldest-first (FIFO by
    ``received_at``). ``quantity_remaining`` reaches 0 when the lot is exhausted — the row is
    kept for history (a naturally-drained lot and one written off via ``delete_batch`` both
    read as 0 remaining, told apart by ``note``). Only mutated by inventory.services.
    """

    variant = models.ForeignKey(
        ProductVariant, on_delete=models.CASCADE, related_name="batches"
    )
    purchase_price = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    sale_price = models.DecimalField(max_digits=12, decimal_places=0, default=0)
    quantity_initial = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField()
    # FIFO sort key. Admin-editable so a lot can be re-ordered; defaults to now.
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["received_at", "id"]

    def __str__(self):
        return (
            f"{self.variant} · {self.quantity_remaining}/{self.quantity_initial} "
            f"@ {self.purchase_price}/{self.sale_price}"
        )


class StockAllocation(models.Model):
    """Which lot(s) one OUT/ADJUST movement drew from, at prices snapshotted at sale time.

    Recorded per lot touched, so a sale spanning two price lots yields two rows. The unit
    prices are copied here so a later batch-price edit can't rewrite past margins/COGS.
    ``batch`` is PROTECT: the DB refuses to row-delete a lot that has sourced a sale — which
    is why 'deleting' a batch means writing off its remainder (services.delete_batch).
    """

    movement = models.ForeignKey(
        StockMovement, on_delete=models.CASCADE, related_name="allocations"
    )
    batch = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT, related_name="allocations"
    )
    quantity = models.PositiveIntegerField()
    unit_purchase_price = models.DecimalField(max_digits=12, decimal_places=0)
    unit_sale_price = models.DecimalField(max_digits=12, decimal_places=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.movement_id} ← batch {self.batch_id} ×{self.quantity}"
