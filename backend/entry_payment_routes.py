from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

ENTRY_PAYMENT_LINK = "https://buy.stripe.com/4gMcN61d2dxI6ku10zaEE07"


def _append_query(url, params):
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query.update({k: v for k, v in params.items() if v})
    return urlunparse(parsed._replace(query=urlencode(query)))


def register_entry_payment_guard(app):
    # Disabled intentionally.
    # /pay/entry must be handled by main.py so it keeps:
    # sid + plan + source_partner_id for MLM / PartnerTree / commissions.
    return app

def register_entry_payment_routes(app):
    return register_entry_payment_guard(app)
