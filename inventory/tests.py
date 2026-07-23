import pytest

from bot.models import Role, TelegramUser
from inventory.models import (
    DigikalaCode,
    Product,
    ProductVariant,
    StockAllocation,
    StockBatch,
    StockMovement,
)
from inventory.services import (
    InsufficientStock,
    InventoryError,
    adjust_stock,
    create_batch,
    delete_batch,
    edit_batch_prices,
    find_variant_by_dkp,
    inventory_summary,
    low_stock_variants,
    search_products,
    search_variants,
    set_batch_remaining,
)


@pytest.fixture
def variant(db):
    product = Product.objects.create(name_fa="عروسک", name_en="Doll")
    return ProductVariant.objects.create(
        product=product, color="Red", size="S",
        quantity=0, reorder_threshold=5,
        purchase_price=100, sale_price=180,
    )


@pytest.fixture
def user(db):
    return TelegramUser.objects.create(
        telegram_id=999, role=Role.STAFF, is_active=True
    )


def test_stock_in_increases_and_logs(variant, user):
    v, low = adjust_stock(variant.id, StockMovement.Type.IN, 10, user=user)
    assert v.quantity == 10
    assert low is False
    mv = StockMovement.objects.get(variant=variant)
    assert mv.movement_type == StockMovement.Type.IN
    assert mv.quantity == 10
    assert mv.quantity_after == 10
    assert mv.user == user


def test_stock_out_decreases(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 10, user=user)
    v, low = adjust_stock(variant.id, StockMovement.Type.OUT, 4, user=user)
    assert v.quantity == 6
    assert StockMovement.objects.count() == 2


def test_stock_out_below_zero_raises_and_rolls_back(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 3, user=user)
    with pytest.raises(InsufficientStock) as exc:
        adjust_stock(variant.id, StockMovement.Type.OUT, 5, user=user)
    assert exc.value.available == 3
    # The failed OUT must not have been recorded, and quantity unchanged.
    variant.refresh_from_db()
    assert variant.quantity == 3
    assert StockMovement.objects.filter(movement_type=StockMovement.Type.OUT).count() == 0


def test_non_positive_quantity_raises(variant, user):
    with pytest.raises(InventoryError):
        adjust_stock(variant.id, StockMovement.Type.IN, 0, user=user)
    with pytest.raises(InventoryError):
        adjust_stock(variant.id, StockMovement.Type.OUT, -2, user=user)


def test_low_stock_flag_and_report(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user)  # == threshold
    v, low = adjust_stock(variant.id, StockMovement.Type.OUT, 1, user=user)  # 4 <= 5
    assert v.quantity == 4
    assert low is True
    assert variant in low_stock_variants()


def test_search_by_name_and_dkp(variant):
    DigikalaCode.objects.create(variant=variant, code="1234567")
    assert list(search_variants("Doll")) == [variant]
    assert list(search_variants("عروسک")) == [variant]
    assert list(search_variants("1234567")) == [variant]
    assert find_variant_by_dkp("1234567") == variant
    assert find_variant_by_dkp("0000000") is None


def test_search_folds_persian_transliteration(db):
    """Typing one spelling of a foreign name finds the other: استیچ (چ) <-> استیج (ج)."""
    cheh = Product.objects.create(name_fa="استیچ", name_en="Stitch")
    jeem = Product.objects.create(name_fa="استیج اورجینال", name_en="Stitch orig")
    for p in (cheh, jeem):
        ProductVariant.objects.create(
            product=p, quantity=0, reorder_threshold=1, purchase_price=1, sale_price=1
        )
    # Either spelling of the query surfaces both products.
    for q in ("استیچ", "استیج"):
        found = set(search_products(q).values_list("id", flat=True))
        assert found == {cheh.id, jeem.id}, q


def test_search_folds_arabic_ye_kaf(db):
    """Arabic ye/kaf query matches a name stored with Persian ye/kaf (and vice versa)."""
    p = Product.objects.create(name_fa="کیتی", name_en="Kitty")  # Persian ye/kaf
    ProductVariant.objects.create(
        product=p, quantity=0, reorder_threshold=1, purchase_price=1, sale_price=1
    )
    assert list(search_products("كيتي")) == [p]  # Arabic ye/kaf


def test_inventory_summary(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 10, user=user)
    s = inventory_summary()
    assert s["variant_count"] == 1
    assert s["total_units"] == 10
    assert s["purchase_value"] == 100 * 10
    assert s["sale_value"] == 180 * 10


# --- batch / FIFO pricing ----------------------------------------------------------
def test_stock_in_creates_batch_with_prices(variant, user):
    adjust_stock(
        variant.id, StockMovement.Type.IN, 5, user=user,
        purchase_price=200000, sale_price=500000,
    )
    batch = variant.batches.get()
    assert batch.quantity_initial == 5
    assert batch.quantity_remaining == 5
    assert batch.purchase_price == 200000
    assert batch.sale_price == 500000
    # The variant's default prices are refreshed to the latest batch (next prefill).
    variant.refresh_from_db()
    assert variant.purchase_price == 200000
    assert variant.sale_price == 500000


def test_fifo_drain_spans_lots(variant, user):
    # Two lots at different prices; the cheap one is older.
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user,
                 purchase_price=200000, sale_price=500000)
    adjust_stock(variant.id, StockMovement.Type.IN, 12, user=user,
                 purchase_price=600000, sale_price=700000)

    v, _low = adjust_stock(variant.id, StockMovement.Type.OUT, 8, user=user)
    assert v.quantity == 9

    old, new = list(variant.batches.order_by("received_at", "id"))
    assert old.quantity_remaining == 0   # 5 taken from the cheap lot
    assert new.quantity_remaining == 9   # 3 taken from the expensive lot

    out = StockMovement.objects.get(movement_type=StockMovement.Type.OUT)
    allocs = list(out.allocations.order_by("id"))
    assert [(a.quantity, a.unit_sale_price) for a in allocs] == [
        (5, 500000), (3, 700000)
    ]


def test_active_batch_price_follows_fifo(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user,
                 purchase_price=200000, sale_price=500000)
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user,
                 purchase_price=600000, sale_price=700000)
    # Next lot to sell is the cheap/older one.
    assert variant.active_batch().sale_price == 500000
    # Drain the cheap lot; the active price flips to the newer lot.
    adjust_stock(variant.id, StockMovement.Type.OUT, 5, user=user)
    assert variant.active_batch().sale_price == 700000


def test_summary_values_lots_independently(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user,
                 purchase_price=200000, sale_price=500000)
    adjust_stock(variant.id, StockMovement.Type.IN, 10, user=user,
                 purchase_price=600000, sale_price=700000)
    s = inventory_summary()
    assert s["total_units"] == 15
    assert s["purchase_value"] == 200000 * 5 + 600000 * 10
    assert s["sale_value"] == 500000 * 5 + 700000 * 10


def test_edit_batch_prices_only(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user,
                 purchase_price=200000, sale_price=500000)
    batch = variant.batches.get()
    edit_batch_prices(batch.id, purchase_price=210000, sale_price=550000)
    batch.refresh_from_db()
    variant.refresh_from_db()
    assert batch.purchase_price == 210000
    assert batch.sale_price == 550000
    assert variant.quantity == 5  # no stock change
    assert StockMovement.objects.count() == 1  # no new movement


def test_delete_batch_writes_off_remaining(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user,
                 purchase_price=200000, sale_price=500000)
    batch = variant.batches.get()
    v, _low = delete_batch(batch.id, user=user)
    batch.refresh_from_db()
    assert batch.quantity_remaining == 0
    assert v.quantity == 0
    adj = StockMovement.objects.get(movement_type=StockMovement.Type.ADJUST)
    assert adj.quantity == 5
    assert StockBatch.objects.filter(pk=batch.id).exists()  # row kept for history


def test_create_batch_adds_stock_and_movement(variant, user):
    # The admin "add batch" path.
    create_batch(variant.id, 7, 300000, 650000, note="admin: batch added")
    variant.refresh_from_db()
    assert variant.quantity == 7
    batch = variant.batches.get()
    assert (batch.quantity_remaining, batch.purchase_price, batch.sale_price) == (
        7, 300000, 650000
    )
    assert StockMovement.objects.filter(movement_type=StockMovement.Type.IN).count() == 1


def test_set_batch_remaining_reconciles_quantity(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 10, user=user,
                 purchase_price=200000, sale_price=500000)
    batch = variant.batches.get()
    # Correct a lot down to 6 — variant total and an ADJUST movement follow.
    set_batch_remaining(batch.id, 6)
    batch.refresh_from_db()
    variant.refresh_from_db()
    assert batch.quantity_remaining == 6
    assert variant.quantity == 6
    assert StockMovement.objects.filter(movement_type=StockMovement.Type.ADJUST).count() == 1


def test_quantity_equals_sum_of_remainders(variant, user):
    adjust_stock(variant.id, StockMovement.Type.IN, 5, user=user,
                 purchase_price=200000, sale_price=500000)
    adjust_stock(variant.id, StockMovement.Type.IN, 12, user=user,
                 purchase_price=600000, sale_price=700000)
    adjust_stock(variant.id, StockMovement.Type.OUT, 9, user=user)
    variant.refresh_from_db()
    remainder = sum(b.quantity_remaining for b in variant.batches.all())
    assert variant.quantity == remainder == 8
