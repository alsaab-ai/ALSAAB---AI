# ALSAAB_DISABLE_RANK_DASHBOARD_TEMP_V1
# Disabled temporarily because rank UI injections affected the unified account dashboard.
# We will rebuild the partner rank section later as a clean standalone component.

def register_rank_dashboard_routes(app):
    if getattr(app, "alsaab_rank_dashboard_registered", False):
        return

    app.alsaab_rank_dashboard_registered = True
    print("RANK DASHBOARD TEMPORARILY DISABLED ✅", flush=True)
    return
