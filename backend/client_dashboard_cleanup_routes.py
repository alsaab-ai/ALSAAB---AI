# ALSAAB_DISABLE_CLIENT_DASHBOARD_CLEANUP_TEMP_V1
# Disabled temporarily because selector-based cleanup affected the unified account dashboard.
# Do not hide dashboard sections with broad JavaScript selectors.

def register_client_dashboard_cleanup_routes(app):
    if getattr(app, "alsaab_client_dashboard_cleanup_registered", False):
        return

    app.alsaab_client_dashboard_cleanup_registered = True
    print("CLIENT DASHBOARD CLEANUP TEMPORARILY DISABLED ✅", flush=True)
    return
