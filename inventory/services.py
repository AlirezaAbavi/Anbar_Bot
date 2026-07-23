"""Business logic for inventory. The ONLY place stock quantities are mutated.

Both the Telegram bot and the Django admin should route stock changes through
``adjust_stock`` so that ``ProductVariant.quantity``, the ``StockMovement`` audit log,
and low-stock detection stay consistent.

These functions are synchronous (they use the Django ORM). Async callers (the PTB
handlers) wrap them with ``asgiref.sync.sync_to_async``.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F, Prefetch, Sum
from django.utils import timezone

from .models import (
    DigikalaCode,
    Product,
    ProductVariant,
    StockAllocation,
    StockBatch,
    StockMovement,
)
from .text import search_fold


class InventoryError(Exception):
    """Base class for expected, user-facing inventory errors."""


class InsufficientStock(InventoryError):
    def __init__(self, available, requested):
        self.available = available
        self.requested = requested
        super().__init__(f"Insufficient stock: have {available}, requested {requested}.")


@transaction.atomic
def adjust_stock(
    variant_id,
    movement_type,
    quantity,
    user=None,
    note="",
    purchase_price=None,
    sale_price=None,
    received_at=None,
):
    """Apply a stock change and record it. Returns (variant, low_stock: bool).

    Locks the variant row (``select_for_update``) for the duration of the transaction so
    concurrent stock changes can't race. Because every stock op locks the variant row first,
    the per-batch locking below can't interleave with another op on the same variant.

    IN creates a :class:`StockBatch` at ``purchase_price``/``sale_price`` (falling back to,
    and refreshing, the variant's default prices). OUT/ADJUST drains batches oldest-first
    (FIFO), writing one :class:`StockAllocation` per lot touched. An OUT/ADJUST that would
    drive stock below zero raises InsufficientStock and rolls back.
    """
    if quantity <= 0:
        raise InventoryError("Quantity must be a positive number.")

    variant = ProductVariant.objects.select_for_update().get(pk=variant_id)

    delta = quantity if movement_type == StockMovement.Type.IN else -quantity
    new_qty = variant.quantity + delta
    if new_qty < 0:
        raise InsufficientStock(available=variant.quantity, requested=quantity)

    variant.quantity = new_qty
    update_fields = ["quantity", "updated_at"]

    if movement_type == StockMovement.Type.IN and (
        purchase_price is not None or sale_price is not None
    ):
        # Remember the latest prices as the variant's defaults (next prefill / card fallback).
        if purchase_price is not None:
            variant.purchase_price = purchase_price
            update_fields.append("purchase_price")
        if sale_price is not None:
            variant.sale_price = sale_price
            update_fields.append("sale_price")

    variant.save(update_fields=update_fields)

    movement = StockMovement.objects.create(
        variant=variant,
        movement_type=movement_type,
        quantity=quantity,
        quantity_after=new_qty,
        user=user,
        note=note,
    )

    if movement_type == StockMovement.Type.IN:
        StockBatch.objects.create(
            variant=variant,
            purchase_price=(
                purchase_price if purchase_price is not None else variant.purchase_price
            ),
            sale_price=sale_price if sale_price is not None else variant.sale_price,
            quantity_initial=quantity,
            quantity_remaining=quantity,
            received_at=received_at or timezone.now(),
            note=note,
        )
    else:
        _consume_fifo(variant, quantity, movement)

    return variant, variant.is_low_stock


def _consume_fifo(variant, quantity, movement):
    """Drain ``quantity`` units from ``variant``'s batches, oldest first.

    Writes a :class:`StockAllocation` per lot touched (prices snapshotted). The caller
    already holds the variant lock and has verified there is enough total stock, so the loop
    is guaranteed to satisfy ``quantity`` before running out of lots.
    """
    remaining = quantity
    batches = (
        variant.batches.select_for_update()
        .filter(quantity_remaining__gt=0)
        .order_by("received_at", "id")
    )
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= take
        batch.save(update_fields=["quantity_remaining", "updated_at"])
        StockAllocation.objects.create(
            movement=movement,
            batch=batch,
            quantity=take,
            unit_purchase_price=batch.purchase_price,
            unit_sale_price=batch.sale_price,
        )
        remaining -= take


def find_variant_by_dkp(code):
    """Return the ProductVariant for a DigiKala code, or None."""
    dkp = (
        DigikalaCode.objects.filter(code=code.strip())
        .select_related("variant", "variant__product")
        .first()
    )
    return dkp.variant if dkp else None


def _fold_hit(nq, *texts):
    """True if the folded query ``nq`` is a substring of any folded ``texts``."""
    return bool(nq) and any(nq in search_fold(t) for t in texts if t)


def search_variants(query, limit=20):
    """Search variants by product name (fa/en), colour/size, or exact DigiKala code.

    Matching is folded (:func:`inventory.text.search_fold`) so Persian typing variants —
    Arabic vs Persian ye/kaf, ZWNJ, and چ↔ج ("استیچ"/"استیج") — all match. Done in Python
    over the active set (small catalog; no portable DB-side fuzzy match). Returns a
    queryset of active ProductVariants (product prefetched).
    """
    query = (query or "").strip()
    qs = ProductVariant.objects.filter(is_active=True).select_related("product")
    if not query:
        return qs[:limit]

    nq = search_fold(query)
    candidates = qs.prefetch_related("digikala_codes")
    ids = [
        v.id
        for v in candidates
        if _fold_hit(nq, v.product.name_fa, v.product.name_en, v.color, v.size)
        or any(query == c.code for c in v.digikala_codes.all())
    ]
    return qs.filter(id__in=ids)[:limit]


def list_products(limit=20, offset=0):
    """Active products that have at least one active variant (for the browse list).

    ``offset``/``limit`` page the list; fetch ``limit + 1`` to detect a next page.
    """
    return (
        Product.objects.filter(is_active=True, variants__is_active=True)
        .distinct()
        .order_by("name_fa")[offset : offset + limit]
    )


def search_products(query, limit=20, offset=0):
    """Search products by name (fa/en), or by a variant's color/size/DigiKala code.

    Returns distinct active products (each with ≥1 active variant). Mirrors the match set
    of ``search_variants`` but collapsed to the product level. ``offset``/``limit`` page it.
    """
    query = (query or "").strip()
    qs = Product.objects.filter(is_active=True, variants__is_active=True)
    if not query:
        return qs.distinct().order_by("name_fa")[offset : offset + limit]

    nq = search_fold(query)
    active_variants = ProductVariant.objects.filter(is_active=True).prefetch_related(
        "digikala_codes"
    )
    candidates = (
        qs.distinct()
        .only("id", "name_fa", "name_en")
        .prefetch_related(Prefetch("variants", queryset=active_variants))
    )
    ids = []
    for p in candidates:
        variants = p.variants.all()  # active only (prefetched above)
        if (
            _fold_hit(nq, p.name_fa, p.name_en)
            or any(_fold_hit(nq, v.color, v.size) for v in variants)
            or any(query == c.code for v in variants for c in v.digikala_codes.all())
        ):
            ids.append(p.id)
    # Re-query so callers keep a QuerySet (e.g. inline mode chains .prefetch_related/.defer).
    return Product.objects.filter(id__in=ids).order_by("name_fa")[offset : offset + limit]


def active_batches_prefetch():
    """A Prefetch loading each variant's in-stock lots FIFO-first into ``active_batches``.

    Lets the card read ``variant.active_batches[0]`` (the next lot FIFO will sell) without an
    extra query per variant. Shared by the card loader and the product variant list.
    """
    return Prefetch(
        "batches",
        queryset=StockBatch.objects.filter(quantity_remaining__gt=0).order_by(
            "received_at", "id"
        ),
        to_attr="active_batches",
    )


def product_variants(product_id, limit=None, offset=0):
    """Active variants of one product, with what the card/picker needs loaded.

    Ordered for stable pagination. With ``limit`` set, returns the ``offset``-based page
    (fetch ``limit + 1`` to detect a next page); without it, the full ordered set.
    """
    qs = (
        ProductVariant.objects.filter(product_id=product_id, is_active=True)
        .select_related("product")
        .prefetch_related("digikala_codes", active_batches_prefetch())
        .order_by("color", "size", "id")
    )
    if limit is None:
        return qs[offset:] if offset else qs
    return qs[offset : offset + limit]


def low_stock_variants():
    """Active variants at or below their reorder threshold, most urgent first."""
    return (
        ProductVariant.objects.filter(is_active=True, quantity__lte=F("reorder_threshold"))
        .select_related("product")
        .order_by("quantity")
    )


def inventory_summary():
    """Aggregate totals for the reports screen."""
    variants = ProductVariant.objects.filter(is_active=True)
    total_units = variants.aggregate(n=Sum("quantity"))["n"] or 0
    # Value each on-hand lot at its own prices (stock can span batches bought at different
    # prices). Computed in Python to stay DB-agnostic (SQLite/MySQL).
    purchase_value = Decimal(0)
    sale_value = Decimal(0)
    batches = StockBatch.objects.filter(
        variant__is_active=True, quantity_remaining__gt=0
    ).only("quantity_remaining", "purchase_price", "sale_price")
    for b in batches:
        purchase_value += b.purchase_price * b.quantity_remaining
        sale_value += b.sale_price * b.quantity_remaining
    return {
        "variant_count": variants.count(),
        "total_units": total_units,
        "purchase_value": purchase_value,
        "sale_value": sale_value,
        "low_stock_count": low_stock_variants().count(),
    }


def variant_batches(variant_id):
    """All lots of a variant, FIFO order (for the batch editor and admin)."""
    return StockBatch.objects.filter(variant_id=variant_id).order_by("received_at", "id")


def edit_batch_prices(batch_id, purchase_price=None, sale_price=None):
    """Update a lot's prices only — no stock change, no movement. Returns the batch."""
    batch = StockBatch.objects.get(pk=batch_id)
    fields = ["updated_at"]
    if purchase_price is not None:
        batch.purchase_price = purchase_price
        fields.append("purchase_price")
    if sale_price is not None:
        batch.sale_price = sale_price
        fields.append("sale_price")
    batch.save(update_fields=fields)
    return batch


@transaction.atomic
def delete_batch(batch_id, user=None, note="batch removed"):
    """Write off a lot's remaining units and keep the row for history.

    'Deleting' a batch can't be a raw row delete (a lot that has sourced sales is PROTECTed,
    and doing so would desync the variant total). Instead we drain the remainder through an
    ADJUST movement so the audit log and ``variant.quantity`` stay consistent. Returns
    (variant, low_stock).
    """
    batch = StockBatch.objects.select_related("variant").get(pk=batch_id)
    variant = ProductVariant.objects.select_for_update().get(pk=batch.variant_id)
    remaining = batch.quantity_remaining
    if remaining <= 0:
        return variant, variant.is_low_stock

    variant.quantity -= remaining
    variant.save(update_fields=["quantity", "updated_at"])
    movement = StockMovement.objects.create(
        variant=variant,
        movement_type=StockMovement.Type.ADJUST,
        quantity=remaining,
        quantity_after=variant.quantity,
        user=user,
        note=note,
    )
    StockAllocation.objects.create(
        movement=movement,
        batch=batch,
        quantity=remaining,
        unit_purchase_price=batch.purchase_price,
        unit_sale_price=batch.sale_price,
    )
    batch.quantity_remaining = 0
    batch.note = note
    batch.save(update_fields=["quantity_remaining", "note", "updated_at"])
    return variant, variant.is_low_stock


@transaction.atomic
def set_batch_remaining(batch_id, new_remaining, user=None, note="manual correction"):
    """Correct a lot's remaining count, reconciling ``variant.quantity`` via an ADJUST.

    Used by the admin inline when someone edits ``quantity_remaining`` directly. An increase
    records an IN movement, a decrease an ADJUST; the batch's ``quantity_initial`` grows if
    the new remaining exceeds it. Returns (variant, low_stock).
    """
    if new_remaining < 0:
        raise InventoryError("Remaining quantity cannot be negative.")
    batch = StockBatch.objects.get(pk=batch_id)
    variant = ProductVariant.objects.select_for_update().get(pk=batch.variant_id)
    delta = new_remaining - batch.quantity_remaining
    if delta == 0:
        return variant, variant.is_low_stock

    variant.quantity += delta
    variant.save(update_fields=["quantity", "updated_at"])
    StockMovement.objects.create(
        variant=variant,
        movement_type=(
            StockMovement.Type.IN if delta > 0 else StockMovement.Type.ADJUST
        ),
        quantity=abs(delta),
        quantity_after=variant.quantity,
        user=user,
        note=note,
    )
    batch.quantity_remaining = new_remaining
    fields = ["quantity_remaining", "updated_at"]
    if new_remaining > batch.quantity_initial:
        batch.quantity_initial = new_remaining
        fields.append("quantity_initial")
    batch.save(update_fields=fields)
    return variant, variant.is_low_stock


# --- catalog review / supervision walkthrough -------------------------------------
# The bot's admin review op (bot/handlers/review.py) walks every product in id order to
# supervise the imported catalog. Progress is a per-product ``reviewed`` flag, so the pass
# resumes at the first unreviewed product across sessions rather than storing a cursor.


def next_unreviewed_product(after_id=None):
    """First product still needing review, in id order; None when the pass is complete.

    ``after_id`` walks strictly forward within a pass (Save/Skip → next product by id).
    Called with no argument (Start / resume) it returns the first unreviewed product
    overall — which, after a Cancel, is the one the admin was last on.
    """
    qs = Product.objects.filter(reviewed=False)
    if after_id is not None:
        qs = qs.filter(id__gt=after_id)
    return qs.order_by("id").first()


def review_counts():
    """(reviewed, total) product counts for the walkthrough's progress line."""
    total = Product.objects.count()
    reviewed = Product.objects.filter(reviewed=True).count()
    return reviewed, total


def mark_product_reviewed(product_id, user=None):
    """Flag a product as supervised, stamping who did it and when."""
    Product.objects.filter(pk=product_id).update(
        reviewed=True, reviewed_at=timezone.now(), reviewed_by=user
    )


def reset_reviews():
    """Clear every product's reviewed flag so the pass starts over. Returns the count."""
    return Product.objects.filter(reviewed=True).update(
        reviewed=False, reviewed_at=None, reviewed_by=None
    )


def review_product_detail(product_id):
    """Load a product with everything the review card renders, or None.

    Shows *all* variants (active or not) and their codes — the whole point of supervision is
    to surface whatever the import left behind, including variants hidden from browse.
    """
    return (
        Product.objects.select_related("category")
        .prefetch_related("variants__digikala_codes")
        .filter(pk=product_id)
        .first()
    )


def rename_product(product_id, name_fa=None, name_en=None):
    """Edit a product's names. Returns (product, error) — error is a message key or None.

    Guards ``uniq_product_name_fa``: a blank or already-taken Persian name is rejected so the
    walkthrough can show the admin why rather than raising. ``name_en`` is free-form.
    """
    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return None, "common.not_found"
    if name_fa is not None:
        name_fa = name_fa.strip()
        if not name_fa:
            return None, "review.err_name_blank"
        if (
            Product.objects.filter(name_fa=name_fa).exclude(pk=product_id).exists()
        ):
            return None, "review.err_name_taken"
        product.name_fa = name_fa
    if name_en is not None:
        product.name_en = name_en.strip()
    product.save(update_fields=["name_fa", "name_en", "updated_at"])
    return product, None


# Review-editable variant fields → (attribute, is_price). Quantity is deliberately absent:
# it must move through adjust_stock, never a direct write.
_VARIANT_FIELDS = {
    "color": ("color", False),
    "size": ("size", False),
    "buy": ("purchase_price", True),
    "sell": ("sale_price", True),
    "thr": ("reorder_threshold", False),
}


def update_variant_field(variant_id, field, value):
    """Set one review-editable variant field. Returns (variant, error) — error is a key/None.

    ``color``/``size`` are trimmed text; ``buy``/``sell``/``thr`` are ints. A color/size edit
    that would collide with a sibling variant (uniq_variant_per_product) is rejected. Never
    touches ``quantity`` — that is adjust_stock's job.
    """
    attr, _is_price = _VARIANT_FIELDS[field]
    variant = ProductVariant.objects.filter(pk=variant_id).first()
    if variant is None:
        return None, "common.not_found"
    if field in ("color", "size"):
        new_val = (value or "").strip()
        color = new_val if field == "color" else variant.color
        size = new_val if field == "size" else variant.size
        clash = (
            ProductVariant.objects.filter(
                product_id=variant.product_id, color=color, size=size
            )
            .exclude(pk=variant_id)
            .exists()
        )
        if clash:
            return None, "review.err_variant_dupe"
        setattr(variant, attr, new_val)
    else:
        setattr(variant, attr, int(value))
    variant.save(update_fields=[attr, "updated_at"])
    return variant, None


def set_variant_quantity(variant_id, target, user=None, note="review correction"):
    """Set a variant's on-hand quantity to ``target`` during catalog review.

    Returns (variant, error) — error is an i18n key or None, matching update_variant_field so
    the review handler can treat every field uniformly. Never writes ``quantity`` directly:
    the correction is reconciled through :func:`adjust_stock`, so it still row-locks, records a
    :class:`StockMovement`, and keeps batches consistent. An increase records an IN (a new batch
    at the variant's default prices), a decrease an ADJUST (FIFO drain), like set_batch_remaining.
    """
    if target < 0:
        return None, "review.bad_num"
    variant = ProductVariant.objects.filter(pk=variant_id).first()
    if variant is None:
        return None, "common.not_found"
    delta = target - variant.quantity
    if delta == 0:
        return variant, None
    mtype = StockMovement.Type.IN if delta > 0 else StockMovement.Type.ADJUST
    variant, _low = adjust_stock(variant_id, mtype, abs(delta), user=user, note=note)
    return variant, None


def add_dkp(variant_id, code):
    """Attach a DigiKala code to a variant. Returns (code_obj, error) — error is a key/None.

    ``code`` is globally unique (one DKP → one variant), so a code already in use anywhere is
    rejected rather than raising IntegrityError.
    """
    code = (code or "").strip()
    if not code:
        return None, "review.err_dkp_blank"
    if DigikalaCode.objects.filter(code=code).exists():
        return None, "review.err_dkp_taken"
    obj = DigikalaCode.objects.create(variant_id=variant_id, code=code)
    return obj, None


def remove_dkp(dkp_id):
    """Delete a DigiKala code by id. Silent no-op if it's already gone."""
    DigikalaCode.objects.filter(pk=dkp_id).delete()


@transaction.atomic
def create_batch(
    variant_id, quantity, purchase_price, sale_price, received_at=None, note="", user=None
):
    """Add a new purchase lot (admin 'add batch'), routed through adjust_stock so the
    movement log and ``variant.quantity`` stay consistent. Returns (variant, low_stock)."""
    return adjust_stock(
        variant_id,
        StockMovement.Type.IN,
        quantity,
        user=user,
        note=note or "batch added",
        purchase_price=purchase_price,
        sale_price=sale_price,
        received_at=received_at,
    )
