# ALSAAB_CLIENT_DASHBOARD_CLEANUP_DISABLED_V2
# Disabled because the old cleanup injector was hiding too much of the unified account dashboard.
# The unified dashboard must remain fully visible.
# We will remove old WhatsApp setup buttons later with a safer targeted selector.

def register_client_dashboard_cleanup_routes(app):
    if getattr(app, "alsaab_client_dashboard_cleanup_registered", False):
        return

    app.alsaab_client_dashboard_cleanup_registered = True
    print("CLIENT DASHBOARD CLEANUP DISABLED ✅", flush=True)
    return
