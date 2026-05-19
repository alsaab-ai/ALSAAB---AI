from flask import request, redirect
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse


ENTRY_PAYMENT_LINK = "https://buy.stripe.com/6oU3cw3laalw7oy7oXaEE06"


def _append_query(url, params):
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    for key, value in params.items():
        if value:
            query[key] = str(value)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        )
    )


def register_entry_payment_routes(app):
    if getattr(app, "alsaab_entry_payment_routes_registered", False):
        return

    app.alsaab_entry_payment_routes_registered = True

    @app.before_request
    def entry_payment_redirect_guard():
        path = (request.path or "").strip().lower().rstrip("/")

        if path != "/pay/entry":
            return None

        sid = (
            request.args.get("sid")
            or request.args.get("client_reference_id")
            or request.args.get("partner_id")
            or request.args.get("ref")
            or request.args.get("source_partner_id")
            or ""
        )

        source = request.args.get("source") or request.args.get("src") or "entry_payment"

        redirect_url = _append_query(
            ENTRY_PAYMENT_LINK,
            {
                "client_reference_id": sid,
                "utm_source": source,
                "utm_campaign": "entry_package",
                "utm_content": sid,
            },
        )

        return redirect(redirect_url, code=302)
