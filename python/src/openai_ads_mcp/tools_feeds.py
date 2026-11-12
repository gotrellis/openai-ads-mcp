"""Product feed MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *


def _variant_payload(variant: Any, where: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(variant, dict):
        return None, _bad_request(f"{where} must be an object.")
    if id_err := _validate_non_empty(f"{where}.id", variant.get("id")):
        return None, id_err
    out: dict[str, Any] = {"id": variant["id"].strip()}
    if variant.get("title") is not None:
        if not isinstance(variant["title"], str):
            return None, _bad_request(f"{where}.title must be a string.")
        out["title"] = variant["title"]
    price = variant.get("price")
    if price is not None:
        if not isinstance(price, dict):
            return None, _bad_request(f"{where}.price must be an object with amount and currency.")
        amount = price.get("amount")
        currency = price.get("currency")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            return None, _bad_request(f"{where}.price.amount must be a non-negative integer.")
        if not isinstance(currency, str) or len(currency) != 3:
            return None, _bad_request(f"{where}.price.currency must be a 3-letter currency code.")
        out["price"] = {"amount": amount, "currency": currency}
    availability = variant.get("availability")
    if availability is not None:
        if not isinstance(availability, dict):
            return None, _bad_request(f"{where}.availability must be an object.")
        if "available" in availability and not isinstance(availability["available"], bool):
            return None, _bad_request(f"{where}.availability.available must be true or false.")
        if "status" in availability and not isinstance(availability["status"], str):
            return None, _bad_request(f"{where}.availability.status must be a string.")
        out["availability"] = {
            key: availability[key] for key in ("available", "status") if key in availability
        }
    return out, None


def _products_payload(products: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    items, err = _coerce_json(products, "products")
    if err:
        return None, err
    if not isinstance(items, list) or not items:
        return None, _bad_request("products must be a non-empty list.")
    out: list[dict[str, Any]] = []
    for index, product in enumerate(items):
        where = f"products[{index}]"
        if not isinstance(product, dict):
            return None, _bad_request(f"{where} must be an object.")
        if id_err := _validate_non_empty(f"{where}.id", product.get("id")):
            return None, id_err
        variants = product.get("variants")
        if not isinstance(variants, list) or not variants:
            return None, _bad_request(f"{where}.variants must be a non-empty list.")
        parsed_variants = []
        for variant_index, variant in enumerate(variants):
            parsed, variant_err = _variant_payload(variant, f"{where}.variants[{variant_index}]")
            if variant_err:
                return None, variant_err
            parsed_variants.append(parsed)
        out.append({"id": product["id"].strip(), "variants": parsed_variants})
    return out, None


_FEED_QUERY_OPERATORS = ("in", "not_in", "gt", "gte", "lt", "lte", "contains", "not_contains", "starts_with")


def _feed_query_filters(filters: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    items, err = _coerce_list(filters, "filters")
    if err or items is None:
        return None, err
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        where = f"filters[{index}]"
        if not isinstance(item, dict):
            return None, _bad_request(f"{where} must be an object with field, operator and values.")
        if field_err := _validate_non_empty(f"{where}.field", item.get("field") if isinstance(item.get("field"), str) else None):
            return None, field_err
        operator = item.get("operator")
        if not isinstance(operator, str) or operator.strip() not in _FEED_QUERY_OPERATORS:
            return None, _bad_request(f"{where}.operator must be one of: {', '.join(_FEED_QUERY_OPERATORS)}.")
        values, values_err = _coerce_string_list(item.get("values"), f"{where}.values")
        if values_err:
            return None, values_err
        if not values:
            return None, _bad_request(f"{where}.values must include at least one value.")
        out.append({"field": item["field"].strip(), "operator": operator.strip(), "values": values})
    return out, None


@ads_tool(open_world=True)
async def list_product_feeds(
    include_product_count: bool = True,
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
) -> str:
    """List the product feeds in the authenticated ad account.

    Each feed has feed_id, name, countries, currencies, campaign_count and whether a hosted
    URL or SFTP is configured. Use the feed_id with the other product feed tools and in an
    ad group's product_set.product_feed_id.

    Args:
        include_product_count: Also return product_count per feed. Default true.
        limit: Results per page, 1-500. Default 20.
        after: Optional cursor for forward pagination (last_id of the previous page).
        before: Optional cursor for backward pagination.
    """
    if limit_err := _validate_int_range("limit", limit, 1, 500):
        return limit_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    params = _optional_params(
        include=["product_count"] if include_product_count else None, limit=limit, after=after, before=before
    )
    try:
        return _ok(await client.get("/feeds", params=params))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(open_world=True)
async def list_product_feed_uploads(
    limit: int = 20,
    after: str | None = None,
    before: str | None = None,
) -> str:
    """List recent product feed uploads across the ad account, with their processing result.

    Each upload has feed_id, upload_id, status (scanning, received, processing, completed,
    completed_with_errors, skipped, failed), uploaded_at, completed_at, rows_accepted,
    rows_rejected, rows_ads_eligible and diagnostics (code, severity, field, rows_affected).
    Use it to explain why a feed is missing products. Uploads are not filterable by feed
    upstream; match on feed_id in the result.

    Args:
        limit: Results per page, 1-100. Default 20.
        after: Optional cursor for forward pagination.
        before: Optional cursor for backward pagination.
    """
    if limit_err := _validate_int_range("limit", limit, 1, 100):
        return limit_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    params = _optional_params(paginate=True, limit=limit, after=after, before=before)
    try:
        return _ok(await client.get("/feeds/uploads", params=params))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(open_world=True)
async def query_product_feed_products(
    feed_id: str,
    filters: Any = None,
    limit: int = 20,
    after: str | None = None,
) -> str:
    """Preview the products in a product feed, optionally narrowed by ad group product filters.

    Returns product_id, item_id, offer_id, brand, title, body, target_url, image_url, price,
    variant, availability and filter_values per product, plus total_count (products in the
    feed) and matched_count (products matching the filters). Use it to check what a
    product_set filter would select before putting it on an ad group.

    Args:
        feed_id: Product feed id, from list_product_feeds.
        filters: Optional list of {"field": "...", "operator": "...", "values": ["..."]}.
            operator is one of in, not_in, gt, gte, lt, lte, contains, not_contains,
            starts_with. Field names are the keys of a product's filter_values; query once
            without filters to see them. Omit to list every product.
        limit: Results per page, 1-500. Default 20.
        after: Optional cursor for the next page (last_id of the previous page).
    """
    if feed_err := _validate_non_empty("feed_id", feed_id, maximum=255):
        return feed_err
    if limit_err := _validate_int_range("limit", limit, 1, 500):
        return limit_err
    parsed_filters, filters_err = _feed_query_filters(filters)
    if filters_err:
        return filters_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    body = _optional_params(filters=parsed_filters or None, limit=limit, after=after)
    try:
        return _ok(await client.post(f"/feeds/{feed_id.strip()}/products/query", json=body))
    except OpenAIAdsAPIError as e:
        return _err(e)


@ads_tool(open_world=True)
async def get_product_feed_settings(feed_id: str) -> str:
    """Get a product feed's settings: name, countries and is_search_eligible_respected.

    Args:
        feed_id: Product feed id, from list_product_feeds.
    """
    if feed_err := _validate_non_empty("feed_id", feed_id, maximum=255):
        return feed_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.get(f"/feeds/{feed_id.strip()}/settings"))
    except OpenAIAdsAPIError as e:
        return _err(e)


# The price unit is unverified, so a wrong guess would reprice live ads 100x: off unless the operator opts in.
@ads_tool(
    writes=True,
    destructive=True,
    idempotent=True,
    open_world=True,
    enabled=_truthy(os.environ.get("OPENAI_ADS_ENABLE_FEED_WRITES")),
)
async def update_product_feed_products(feed_id: str, products: Any) -> str:
    """Patch price, title, or availability on products in a product feed.

    Only the fields you send change. Price changes show up in live product ads.
    The price unit is UNVERIFIED (see products below). Listed only when the
    server sets OPENAI_ADS_ENABLE_FEED_WRITES=1.

    Args:
        feed_id: Product feed id, as in an ad group's product_set.product_feed_id.
        products: Non-empty list of {"id": "<product id>", "variants": [{"id": "<variant id>",
            "title": "...", "price": {"amount": 2500, "currency": "USD"},
            "availability": {"available": true, "status": "in_stock"}}]}. price.amount is a
            non-negative integer; the spec does not state its unit, minor units are assumed
            (2500 = 25.00 USD), so verify on one product before a bulk change.
    """
    if feed_err := _validate_non_empty("feed_id", feed_id, maximum=255):
        return feed_err
    payload, payload_err = _products_payload(products)
    if payload_err:
        return payload_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.patch(f"/feeds/{feed_id.strip()}/products", json={"products": payload}))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = (
    "list_product_feeds",
    "list_product_feed_uploads",
    "query_product_feed_products",
    "get_product_feed_settings",
    "update_product_feed_products",
)
