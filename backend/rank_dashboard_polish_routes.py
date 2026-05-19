# ALSAAB_DISABLE_RANK_DASHBOARD_POLISH_TEMP_V1
# Disabled temporarily because polish scripts were hiding / changing dashboard sections.

def register_rank_dashboard_polish_routes(app):
    if getattr(app, "alsaab_rank_dashboard_polish_registered", False):
        return

    app.alsaab_rank_dashboard_polish_registered = True
    print("RANK DASHBOARD POLISH TEMPORARILY DISABLED ✅", flush=True)
    return
