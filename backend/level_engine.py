from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable, Optional


PACKAGE_STARTER = "starter"
PACKAGE_GROWTH = "growth"
PACKAGE_ELITE = "elite"

COURSE_MARKETING_FREE = "marketing_course_free"
COURSE_SALES_99 = "sales_course_99"
COURSE_LIFE_PHILOSOPHY_299 = "life_philosophy_workshop_299"
COURSE_CHANGE_JOURNEY_1099 = "change_journey_course_1099"

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "paid", "trialing"}

LEVEL_NAMES = {
    0: "Inactive / Not Qualified",
    1: "Starter Partner",
    2: "Growth Partner",
    3: "Sales Partner",
    4: "Leader Partner",
    5: "Elite Partner",
}

COMMISSION_RATES_BY_DEPTH = {
    1: 25.0,
    2: 5.0,
    3: 4.0,
    4: 3.0,
    5: 2.0,
}


@dataclass(frozen=True)
class LevelRequirement:
    level: int
    name: str
    allowed_packages: tuple[str, ...]
    min_active_direct_customers: int
    required_courses: tuple[str, ...]
    commission_rate: float


LEVEL_REQUIREMENTS = {
    1: LevelRequirement(
        level=1,
        name="Starter Partner",
        allowed_packages=(PACKAGE_STARTER, PACKAGE_GROWTH, PACKAGE_ELITE),
        min_active_direct_customers=0,
        required_courses=(),
        commission_rate=25.0,
    ),
    2: LevelRequirement(
        level=2,
        name="Growth Partner",
        allowed_packages=(PACKAGE_GROWTH, PACKAGE_ELITE),
        min_active_direct_customers=2,
        required_courses=(),
        commission_rate=5.0,
    ),
    3: LevelRequirement(
        level=3,
        name="Sales Partner",
        allowed_packages=(PACKAGE_GROWTH, PACKAGE_ELITE),
        min_active_direct_customers=5,
        required_courses=(COURSE_SALES_99,),
        commission_rate=4.0,
    ),
    4: LevelRequirement(
        level=4,
        name="Leader Partner",
        allowed_packages=(PACKAGE_ELITE,),
        min_active_direct_customers=15,
        required_courses=(COURSE_LIFE_PHILOSOPHY_299,),
        commission_rate=3.0,
    ),
    5: LevelRequirement(
        level=5,
        name="Elite Partner",
        allowed_packages=(PACKAGE_ELITE,),
        min_active_direct_customers=30,
        required_courses=(COURSE_CHANGE_JOURNEY_1099,),
        commission_rate=2.0,
    ),
}

PACKAGE_ALIASES = {
    "starter": PACKAGE_STARTER,
    "البداية": PACKAGE_STARTER,
    "بداية": PACKAGE_STARTER,
    "growth": PACKAGE_GROWTH,
    "النمو": PACKAGE_GROWTH,
    "باقة النمو": PACKAGE_GROWTH,
    "elite": PACKAGE_ELITE,
    "النخبة": PACKAGE_ELITE,
    "باقة النخبة": PACKAGE_ELITE,
}

COURSE_ALIASES = {
    "marketing_course_free": COURSE_MARKETING_FREE,
    "كورس التسويق": COURSE_MARKETING_FREE,
    "sales_course_99": COURSE_SALES_99,
    "sales": COURSE_SALES_99,
    "كورس المبيعات": COURSE_SALES_99,
    "life_philosophy_workshop_299": COURSE_LIFE_PHILOSOPHY_299,
    "life_philosophy": COURSE_LIFE_PHILOSOPHY_299,
    "ورشة فلسفة الحياة": COURSE_LIFE_PHILOSOPHY_299,
    "فلسفة الحياة": COURSE_LIFE_PHILOSOPHY_299,
    "change_journey_course_1099": COURSE_CHANGE_JOURNEY_1099,
    "change_journey": COURSE_CHANGE_JOURNEY_1099,
    "كورس رحلة التغيير": COURSE_CHANGE_JOURNEY_1099,
    "رحلة التغيير": COURSE_CHANGE_JOURNEY_1099,
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def normalize_package_name(value: Any) -> str:
    raw = _clean_text(value)
    lowered = raw.lower()

    if not lowered:
        return ""

    if lowered in PACKAGE_ALIASES:
        return PACKAGE_ALIASES[lowered]

    if "النمو" in raw or "نمو" in raw:
        return PACKAGE_GROWTH

    if "النخبة" in raw or "نخبة" in raw:
        return PACKAGE_ELITE

    if "البداية" in raw or "بداية" in raw:
        return PACKAGE_STARTER

    return lowered


def normalize_course_code(value: Any) -> str:
    raw = _clean_text(value)
    lowered = raw.lower()

    if not lowered:
        return ""

    if lowered in COURSE_ALIASES:
        return COURSE_ALIASES[lowered]

    if "مبيعات" in raw:
        return COURSE_SALES_99

    if "فلسفة" in raw:
        return COURSE_LIFE_PHILOSOPHY_299

    if "تغيير" in raw:
        return COURSE_CHANGE_JOURNEY_1099

    if "تسويق" in raw:
        return COURSE_MARKETING_FREE

    return lowered


def normalize_courses(values: Optional[Iterable[Any]]) -> set[str]:
    if not values:
        return set()

    output = set()

    for value in values:
        code = normalize_course_code(value)
        if code:
            output.add(code)

    return output


def normalize_subscription_status(value: Any) -> str:
    return _clean_text(value).lower()


def is_subscription_active(status: Any) -> bool:
    return normalize_subscription_status(status) in ACTIVE_SUBSCRIPTION_STATUSES


def evaluate_level_requirement(
    level: int,
    package_name: Any,
    active_direct_customers: Any,
    purchased_courses: Optional[Iterable[Any]],
) -> dict:
    if level not in LEVEL_REQUIREMENTS:
        raise ValueError(f"Unsupported level: {level}")

    requirement = LEVEL_REQUIREMENTS[level]
    package = normalize_package_name(package_name)
    active_customers = _safe_int(active_direct_customers)
    courses = normalize_courses(purchased_courses)

    package_ok = package in requirement.allowed_packages
    customers_ok = active_customers >= requirement.min_active_direct_customers
    courses_ok = all(course in courses for course in requirement.required_courses)

    missing_courses = [
        course for course in requirement.required_courses
        if course not in courses
    ]

    missing_active_direct_customers = max(
        requirement.min_active_direct_customers - active_customers,
        0,
    )

    return {
        "level": requirement.level,
        "name": requirement.name,
        "commission_rate": requirement.commission_rate,
        "allowed_packages": list(requirement.allowed_packages),
        "current_package": package,
        "package_ok": package_ok,
        "min_active_direct_customers": requirement.min_active_direct_customers,
        "active_direct_customers": active_customers,
        "customers_ok": customers_ok,
        "missing_active_direct_customers": missing_active_direct_customers,
        "required_courses": list(requirement.required_courses),
        "purchased_courses": sorted(courses),
        "courses_ok": courses_ok,
        "missing_courses": missing_courses,
        "qualified": bool(package_ok and customers_ok and courses_ok),
    }


def calculate_partner_level_progress(
    package_name: Any,
    active_direct_customers: Any = 0,
    purchased_courses: Optional[Iterable[Any]] = None,
    subscription_status: Any = "active",
) -> dict:
    package = normalize_package_name(package_name)
    status = normalize_subscription_status(subscription_status)
    subscription_active = is_subscription_active(status)
    active_customers = _safe_int(active_direct_customers)
    courses = normalize_courses(purchased_courses)

    achieved_level = 0
    level_details = []

    for level in range(1, 6):
        detail = evaluate_level_requirement(
            level=level,
            package_name=package,
            active_direct_customers=active_customers,
            purchased_courses=courses,
        )

        if detail["qualified"] and achieved_level == level - 1:
            achieved_level = level

        level_details.append(detail)

    next_level = achieved_level + 1 if achieved_level < 5 else None
    missing_requirements = []

    if next_level:
        next_detail = level_details[next_level - 1]

        if not next_detail["package_ok"]:
            missing_requirements.append({
                "type": "package",
                "current": package,
                "required": next_detail["allowed_packages"],
            })

        if not next_detail["customers_ok"]:
            missing_requirements.append({
                "type": "active_direct_customers",
                "current": active_customers,
                "required": next_detail["min_active_direct_customers"],
                "missing": next_detail["missing_active_direct_customers"],
            })

        if not next_detail["courses_ok"]:
            missing_requirements.append({
                "type": "courses",
                "current": sorted(courses),
                "required": next_detail["required_courses"],
                "missing": next_detail["missing_courses"],
            })

    return {
        "current_package": package,
        "subscription_status": status,
        "subscription_active": subscription_active,
        "active_direct_customers": active_customers,
        "purchased_courses": sorted(courses),
        "achieved_level": achieved_level,
        "current_level": achieved_level,
        "current_level_name": LEVEL_NAMES.get(achieved_level, "Unknown"),
        "commission_eligible": bool(subscription_active and achieved_level >= 1),
        "next_level": next_level,
        "next_level_name": LEVEL_NAMES.get(next_level) if next_level else None,
        "missing_requirements": missing_requirements,
        "level_details": level_details,
    }


def is_partner_eligible_for_commission_depth(
    current_level: Any,
    commission_depth: Any,
    subscription_status: Any = "active",
) -> bool:
    level = _safe_int(current_level)
    depth = _safe_int(commission_depth)

    if depth < 1 or depth > 5:
        return False

    if not is_subscription_active(subscription_status):
        return False

    return level >= depth


def get_commission_rate_for_depth(commission_depth: Any) -> float:
    depth = _safe_int(commission_depth)
    return float(COMMISSION_RATES_BY_DEPTH.get(depth, 0.0))


def summarize_next_level_requirement(progress: dict) -> str:
    next_level = progress.get("next_level")

    if not next_level:
        return "You already reached the highest level."

    missing = progress.get("missing_requirements") or []

    if not missing:
        return f"You are eligible for Level {next_level}."

    parts = []

    for item in missing:
        if item.get("type") == "package":
            parts.append("upgrade package")
        elif item.get("type") == "active_direct_customers":
            parts.append(f"{item.get('missing', 0)} more active direct customers")
        elif item.get("type") == "courses":
            parts.append("complete required course purchase")
        else:
            parts.append("missing requirement")

    return f"To reach Level {next_level}, you need: " + ", ".join(parts)


def export_level_requirements() -> list[dict]:
    return [
        asdict(LEVEL_REQUIREMENTS[level])
        for level in sorted(LEVEL_REQUIREMENTS)
    ]
