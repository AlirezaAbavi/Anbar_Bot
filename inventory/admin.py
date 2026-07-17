import base64

from django import forms
from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html

from . import services
from .models import (
    Category,
    DigikalaCode,
    Product,
    ProductVariant,
    StockAllocation,
    StockBatch,
    StockMovement,
)


def photo_tag(obj):
    """Render an in-DB photo (raw JPEG bytes) as an inline data-URI thumbnail."""
    data = getattr(obj, "photo_data", None)
    if not data:
        return "—"
    b64 = base64.b64encode(bytes(data)).decode("ascii")
    return format_html(
        '<img src="data:image/jpeg;base64,{}" style="max-height:160px;border-radius:6px" />',
        b64,
    )


class PhotoAdminForm(forms.ModelForm):
    """Adds a web upload field that writes raw bytes into the model's photo_data.

    photo_data is a BinaryField (editable=False), so it has no widget of its own;
    admins upload here, or the bot fills it via handlers.products._save_product_photo.
    """

    upload_photo = forms.FileField(required=False, label="Upload / replace photo")


class PhotoAdminMixin:
    """Shared photo handling for the Product/ProductVariant change pages."""

    form = PhotoAdminForm

    def get_queryset(self, request):
        # Keep the (potentially large) blob out of changelist queries.
        return super().get_queryset(request).defer("photo_data")

    def save_model(self, request, obj, form, change):
        uploaded = form.cleaned_data.get("upload_photo")
        if uploaded is not None:
            obj.photo_data = uploaded.read()
        super().save_model(request, obj, form, change)

    @admin.display(description="Current photo")
    def photo_preview(self, obj):
        return photo_tag(obj)


class DigikalaCodeInline(admin.TabularInline):
    model = DigikalaCode
    extra = 1


class StockMovementInline(admin.TabularInline):
    model = StockMovement
    extra = 0
    can_delete = False
    fields = ("created_at", "movement_type", "quantity", "quantity_after", "user", "note")
    readonly_fields = fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        # Stock is only ever changed via services.adjust_stock, never by hand here.
        return False


class StockBatchInline(admin.TabularInline):
    """Editable purchase lots. Add/update/delete are routed through inventory.services
    (see ProductVariantAdmin.save_formset) so ``ProductVariant.quantity`` and the
    StockMovement audit log never drift. Only in-stock lots are shown; a written-off lot
    (remaining 0) drops out and lives on in the movement history."""

    model = StockBatch
    extra = 0
    fields = (
        "received_at",
        "quantity_initial",
        "quantity_remaining",
        "purchase_price",
        "sale_price",
        "note",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(quantity_remaining__gt=0)


class StockAllocationInline(admin.TabularInline):
    """Read-only: which lots this movement drew from, at snapshotted prices (COGS)."""

    model = StockAllocation
    extra = 0
    can_delete = False
    fields = ("batch", "quantity", "unit_purchase_price", "unit_sale_price")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class ProductVariantInline(admin.StackedInline):
    model = ProductVariant
    extra = 1
    show_change_link = True
    fields = (
        ("color", "size"),
        ("quantity", "reorder_threshold"),
        ("purchase_price", "sale_price"),
        ("is_active",),
    )
    # quantity: change via the variant's Stock In/Out, not free edit.
    # Photos live on the Product, not the variant.
    readonly_fields = ("quantity",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name_fa", "name_en", "parent")
    search_fields = ("name_fa", "name_en")


@admin.register(Product)
class ProductAdmin(PhotoAdminMixin, admin.ModelAdmin):
    list_display = ("name_fa", "name_en", "category", "total_stock", "is_active")
    list_filter = ("category", "is_active")
    search_fields = (
        "name_fa",
        "name_en",
        "variants__digikala_codes__code",
    )
    readonly_fields = ("photo_preview",)
    inlines = [ProductVariantInline]

    @admin.display(description="Total stock")
    def total_stock(self, obj):
        return obj.variants.aggregate(n=Sum("quantity"))["n"] or 0


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "variant_label",
        "quantity",
        "reorder_threshold",
        "low_stock_flag",
        "sale_price",
        "is_active",
    )
    list_filter = ("is_active", "product__category")
    search_fields = ("product__name_fa", "product__name_en", "digikala_codes__code")
    readonly_fields = ("quantity",)
    inlines = [DigikalaCodeInline, StockBatchInline, StockMovementInline]

    @admin.display(description="Low stock", boolean=True)
    def low_stock_flag(self, obj):
        return obj.is_low_stock

    def save_formset(self, request, form, formset, change):
        """Route batch add/update/delete through the service layer.

        Adding stock, correcting a remaining count, and 'deleting' (writing off) a lot must
        all go through inventory.services so the StockMovement log and ``variant.quantity``
        stay consistent — never a raw formset save. Price-only edits are safe to persist as
        themselves. Other inlines keep the default behaviour.
        """
        if formset.model is not StockBatch:
            return super().save_formset(request, form, formset, change)

        variant = form.instance
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            if obj.pk:
                services.delete_batch(obj.pk, note="admin: batch removed")
        for obj in instances:
            if obj.pk is None:
                # New lot: create via the service (writes an IN movement, reconciles quantity).
                services.create_batch(
                    variant.pk,
                    obj.quantity_initial or obj.quantity_remaining or 0,
                    obj.purchase_price,
                    obj.sale_price,
                    received_at=obj.received_at,
                    note=obj.note or "admin: batch added",
                )
                continue
            orig = StockBatch.objects.get(pk=obj.pk)
            if obj.quantity_remaining != orig.quantity_remaining:
                services.set_batch_remaining(
                    obj.pk, obj.quantity_remaining, note="admin: correction"
                )
            if (
                obj.purchase_price != orig.purchase_price
                or obj.sale_price != orig.sale_price
            ):
                services.edit_batch_prices(
                    obj.pk, purchase_price=obj.purchase_price, sale_price=obj.sale_price
                )
            if obj.received_at != orig.received_at or obj.note != orig.note:
                # FIFO order / label only — no stock impact, safe to persist directly.
                StockBatch.objects.filter(pk=obj.pk).update(
                    received_at=obj.received_at, note=obj.note
                )


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "variant", "movement_type", "quantity", "quantity_after", "user")
    list_filter = ("movement_type", "created_at")
    search_fields = ("variant__product__name_fa", "variant__product__name_en", "note")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    inlines = [StockAllocationInline]


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = (
        "variant",
        "received_at",
        "quantity_remaining",
        "quantity_initial",
        "purchase_price",
        "sale_price",
    )
    list_filter = ("received_at",)
    search_fields = ("variant__product__name_fa", "variant__product__name_en", "note")
    readonly_fields = ("quantity_initial", "quantity_remaining", "created_at", "updated_at")
    date_hierarchy = "received_at"
