from pathlib import Path

path = Path("backend/database.py")
text = path.read_text(encoding="utf-8")
path.with_suffix(".py.bak_diamond_safe_2").write_text(text, encoding="utf-8")

marker = "# ===== ALSAAB_DIAMOND_DATABASE_SAFE_V1 START ====="
if marker not in text:
    block = r'''

# ===== ALSAAB_DIAMOND_DATABASE_SAFE_V1 START =====

DIAMOND_PLAN_KEY = "diamond"

DIAMOND_PLAN_ALIASES = {
    "diamond": "diamond",
    "دايموند": "diamond",
    "الماسية": "diamond",
    "باقة الماسية": "diamond",
    "الباقة الماسية": "diamond",
}

DIAMOND_PLAN_LIMITS = {
    "monthly_reply_limit": 40000,
    "customer_reply_limit": 40000,
    "owner_advisory_reply_limit": 5000,
}

def _alsaab_diamond_normalize_plan(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw_lower = raw.lower()
    if raw_lower in DIAMOND_PLAN_ALIASES:
        return DIAMOND_PLAN_ALIASES[raw_lower]
    if raw in DIAMOND_PLAN_ALIASES:
        return DIAMOND_PLAN_ALIASES[raw]
    return raw_lower

def _alsaab_diamond_wrap_normalizers():
    function_names = [
        "normalize_plan_name",
        "normalize_plan",
        "normalize_package_name",
        "normalize_package",
    ]

    for function_name in function_names:
        old_function = globals().get(function_name)

        if not callable(old_function):
            continue

        if getattr(old_function, "_alsaab_diamond_wrapped", False):
            continue

        def wrapper(value=None, *args, _old_function=old_function, **kwargs):
            normalized = _alsaab_diamond_normalize_plan(value)
            if normalized == "diamond":
                return "diamond"
            return _old_function(value, *args, **kwargs)

        wrapper._alsaab_diamond_wrapped = True
        globals()[function_name] = wrapper

def _alsaab_diamond_wrap_limit_functions():
    function_names = [
        "get_plan_reply_limit",
        "get_plan_owner_advisory_reply_limit",
        "get_customer_reply_limit",
        "get_owner_advisory_reply_limit",
        "get_monthly_reply_limit",
    ]

    for function_name in function_names:
        old_function = globals().get(function_name)

        if not callable(old_function):
            continue

        if getattr(old_function, "_alsaab_diamond_wrapped", False):
            continue

        def wrapper(plan=None, *args, _old_function=old_function, _function_name=function_name, **kwargs):
            normalized = _alsaab_diamond_normalize_plan(plan)
            if normalized == "diamond":
                if "owner_advisory" in _function_name:
                    return 5000
                return 40000
            return _old_function(plan, *args, **kwargs)

        wrapper._alsaab_diamond_wrapped = True
        globals()[function_name] = wrapper

try:
    _alsaab_diamond_wrap_normalizers()
    _alsaab_diamond_wrap_limit_functions()
except Exception as _diamond_database_error:
    print(f"DIAMOND DATABASE PATCH WARNING: {_diamond_database_error}", flush=True)

# ===== ALSAAB_DIAMOND_DATABASE_SAFE_V1 END =====
'''
    text = text.rstrip() + block + "\n"
    path.write_text(text, encoding="utf-8")
