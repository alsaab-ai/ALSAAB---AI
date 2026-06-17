from pathlib import Path
import re

path = Path("backend/level_engine.py")
text = path.read_text(encoding="utf-8")
path.with_suffix(".py.bak_level_engine_safe").write_text(text, encoding="utf-8")

text = re.sub(
    r'PACKAGE_STARTER = "starter"\s+PACKAGE_GROWTH = "growth"\s+PACKAGE_ELITE = "elite"',
    'PACKAGE_ENTRY = "entry"\nPACKAGE_STARTER = "starter"\nPACKAGE_GROWTH = "growth"\nPACKAGE_ELITE = "elite"\nPACKAGE_DIAMOND = "diamond"',
    text
)

text = re.sub(
    r'COURSE_SALES_99 = "sales_course_99"\s+COURSE_LIFE_PHILOSOPHY_299 = "life_philosophy_workshop_299"\s+COURSE_CHANGE_JOURNEY_1099 = "change_journey_course_1099"',
    'COURSE_PRO_MARKETER_MINDSET_69 = "pro_marketer_mindset_69"\nCOURSE_SALES_SKILLS_89 = "sales_skills_89"\nCOURSE_CHANGE_JOURNEY_149 = "change_journey_149"\nCOURSE_LIFE_PHILOSOPHY_FREE = "life_philosophy_workshop_free"',
    text
)

text = re.sub(
    r'1: "Starter Partner",\s+2: "Growth Partner",\s+3: "Sales Partner",\s+4: "Leader Partner",\s+5: "Elite Partner",',
    '1: "Entry Partner",\n    2: "Starter Partner",\n    3: "Growth Partner",\n    4: "Elite Partner",\n    5: "Diamond Partner",',
    text
)

new_req = '''LEVEL_REQUIREMENTS = {
    1: LevelRequirement(
        level=1,
        name="Entry Partner",
        allowed_packages=(PACKAGE_ENTRY, PACKAGE_STARTER, PACKAGE_GROWTH, PACKAGE_ELITE, PACKAGE_DIAMOND),
        min_active_direct_customers=0,
        required_courses=(),
        commission_rate=25.0,
    ),
    2: LevelRequirement(
        level=2,
        name="Starter Partner",
        allowed_packages=(PACKAGE_STARTER, PACKAGE_GROWTH, PACKAGE_ELITE, PACKAGE_DIAMOND),
        min_active_direct_customers=2,
        required_courses=(),
        commission_rate=5.0,
    ),
    3: LevelRequirement(
        level=3,
        name="Growth Partner",
        allowed_packages=(PACKAGE_GROWTH, PACKAGE_ELITE, PACKAGE_DIAMOND),
        min_active_direct_customers=5,
        required_courses=(COURSE_PRO_MARKETER_MINDSET_69,),
        commission_rate=4.0,
    ),
    4: LevelRequirement(
        level=4,
        name="Elite Partner",
        allowed_packages=(PACKAGE_ELITE, PACKAGE_DIAMOND),
        min_active_direct_customers=10,
        required_courses=(COURSE_SALES_SKILLS_89,),
        commission_rate=3.0,
    ),
    5: LevelRequirement(
        level=5,
        name="Diamond Partner",
        allowed_packages=(PACKAGE_DIAMOND,),
        min_active_direct_customers=20,
        required_courses=(COURSE_CHANGE_JOURNEY_149,),
        commission_rate=2.0,
    ),
}'''

text = re.sub(r'LEVEL_REQUIREMENTS = \{.*?\n\}\n\nPACKAGE_ALIASES =', new_req + "\n\nPACKAGE_ALIASES =", text, flags=re.S)

text = re.sub(r'PACKAGE_ALIASES = \{.*?\n\}', '''PACKAGE_ALIASES = {
    "entry": PACKAGE_ENTRY,
    "دخول": PACKAGE_ENTRY,
    "الدخول": PACKAGE_ENTRY,
    "باقة الدخول": PACKAGE_ENTRY,
    "starter": PACKAGE_STARTER,
    "البداية": PACKAGE_STARTER,
    "بداية": PACKAGE_STARTER,
    "growth": PACKAGE_GROWTH,
    "النمو": PACKAGE_GROWTH,
    "باقة النمو": PACKAGE_GROWTH,
    "elite": PACKAGE_ELITE,
    "النخبة": PACKAGE_ELITE,
    "باقة النخبة": PACKAGE_ELITE,
    "diamond": PACKAGE_DIAMOND,
    "دايموند": PACKAGE_DIAMOND,
    "الماسية": PACKAGE_DIAMOND,
    "باقة الماسية": PACKAGE_DIAMOND,
    "الباقة الماسية": PACKAGE_DIAMOND,
}''', text, flags=re.S)

text = re.sub(r'COURSE_ALIASES = \{.*?\n\}', '''COURSE_ALIASES = {
    "marketing_course_free": COURSE_MARKETING_FREE,
    "كورس التسويق": COURSE_MARKETING_FREE,

    "pro_marketer_mindset_69": COURSE_PRO_MARKETER_MINDSET_69,
    "sales_course_99": COURSE_PRO_MARKETER_MINDSET_69,
    "sales": COURSE_PRO_MARKETER_MINDSET_69,
    "عقلية المسوق المحترف": COURSE_PRO_MARKETER_MINDSET_69,
    "كورس عقلية المسوق المحترف": COURSE_PRO_MARKETER_MINDSET_69,
    "المسوق المحترف": COURSE_PRO_MARKETER_MINDSET_69,

    "sales_skills_89": COURSE_SALES_SKILLS_89,
    "مهارات المبيعات": COURSE_SALES_SKILLS_89,
    "كورس مهارات المبيعات": COURSE_SALES_SKILLS_89,

    "life_philosophy_workshop_free": COURSE_LIFE_PHILOSOPHY_FREE,
    "life_philosophy_workshop_299": COURSE_LIFE_PHILOSOPHY_FREE,
    "life_philosophy": COURSE_LIFE_PHILOSOPHY_FREE,
    "ورشة فلسفة الحياة": COURSE_LIFE_PHILOSOPHY_FREE,
    "فلسفة الحياة": COURSE_LIFE_PHILOSOPHY_FREE,

    "change_journey_149": COURSE_CHANGE_JOURNEY_149,
    "change_journey_course_1099": COURSE_CHANGE_JOURNEY_149,
    "change_journey": COURSE_CHANGE_JOURNEY_149,
    "كورس رحلة التغيير": COURSE_CHANGE_JOURNEY_149,
    "رحلة التغيير": COURSE_CHANGE_JOURNEY_149,
}''', text, flags=re.S)

text = text.replace("return COURSE_SALES_99", "return COURSE_PRO_MARKETER_MINDSET_69")
text = text.replace("return COURSE_LIFE_PHILOSOPHY_299", "return COURSE_LIFE_PHILOSOPHY_FREE")
text = text.replace("return COURSE_CHANGE_JOURNEY_1099", "return COURSE_CHANGE_JOURNEY_149")

path.write_text(text, encoding="utf-8")
