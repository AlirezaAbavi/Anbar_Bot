"""Public read-only views. Currently: serve variant/product photo bytes over HTTP.

Photos live as raw JPEG bytes in the DB (BinaryField), not on disk. The bot needs a URL
(not a Telegram file_id) for inline-search thumbnails, so this endpoint streams the bytes.
"""

from django.http import Http404, HttpResponse

from .models import ProductVariant


def variant_photo(request, pk):
    """Return the variant's product JPEG, or 404 if it has none.

    Photos live on the Product (shared by all its variants); the URL is keyed by variant
    id because that is what the bot's inline-search results reference.
    """
    v = ProductVariant.objects.select_related("product").filter(pk=pk).first()
    if not v:
        raise Http404("variant not found")
    data = v.product.photo_data if v.product_id else None
    if not data:
        raise Http404("no photo")
    resp = HttpResponse(bytes(data), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp
