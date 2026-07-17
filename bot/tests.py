"""Duplicate/near-duplicate detection for the add-product flow."""

import pytest
from asgiref.sync import async_to_sync

from bot.handlers.products import _normalize, _similar_products
from inventory.models import Product


def _similar(name):
    return async_to_sync(_similar_products)(name)


class TestNormalize:
    def test_folds_arabic_letters_to_persian(self):
        assert _normalize("كيتي") == _normalize("کیتی")

    def test_folds_zwnj_and_spacing(self):
        assert _normalize("نیم‌فاصله") == _normalize("نیم فاصله")

    def test_casefolds_and_strips(self):
        assert _normalize("  Stitch ") == "stitch"

    def test_drops_punctuation(self):
        assert _normalize("استیچ!") == "استیچ"


@pytest.mark.django_db
class TestSimilarProducts:
    @pytest.fixture(autouse=True)
    def catalog(self):
        Product.objects.create(name_fa="استیچ", name_en="Stich")
        Product.objects.create(name_fa="جوجه")

    def test_exact_name_fa_is_exact(self):
        hits, exact = _similar("استیچ")
        assert exact is True
        assert [p.name_fa for p in hits] == ["استیچ"]

    def test_exact_match_ignores_case_and_spacing(self):
        _, exact = _similar("  استیچ ")
        assert exact is True

    def test_english_name_match_is_not_exact(self):
        # uniq_product_name_fa only covers name_fa, so an English collision is a warning
        # the admin can overrule — not a hard stop.
        hits, exact = _similar("stich")
        assert [p.name_fa for p in hits] == ["استیچ"]
        assert exact is False

    def test_typo_is_flagged_but_not_exact(self):
        hits, exact = _similar("استیج")
        assert [p.name_fa for p in hits] == ["استیچ"]
        assert exact is False

    def test_containment_is_flagged(self):
        hits, _ = _similar("عروسک استیچ")
        assert [p.name_fa for p in hits] == ["استیچ"]

    def test_unrelated_name_is_not_flagged(self):
        hits, exact = _similar("باربی")
        assert hits == []
        assert exact is False

    def test_empty_catalog_names_are_ignored(self):
        # The blank name_en on جوجه must not match every candidate.
        hits, _ = _similar("عروسک")
        assert hits == []
