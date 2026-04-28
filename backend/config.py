# config.py

# =========================
# OPENAI
# =========================

import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = "gpt-4o-mini"
REPLY_MAX_TOKENS = 350
TEMPERATURE = 0.65


# =========================
# ALSAAB AI INFO
# =========================

SYSTEM_NAME = "نظامنا الذكي"
COMPANY_NAME = "ALSAAB AI"
WEBSITE_URL = "https://www.alsaab.io"
WHATSAPP_LINK = "https://wa.me/971523288001"


# =========================
# SUBSCRIPTION PACKAGES
# =========================

PACKAGES = {
    "starter": {
        "name_ar": "باقة البداية",
        "price_ar": "399 درهم إماراتي شهرياً",
        "position": "تجربة ذكية للدخول",
        "best_for": "اللي ميزانيته محدودة أو يريد يجرب النظام أولاً",
        "note": "ليست الباقة الأقوى، لكنها مدخل ممتاز للبدء."
    },
    "growth": {
        "name_ar": "باقة النمو",
        "price_ar": "799 درهم إماراتي شهرياً",
        "position": "الباقة الموصى بها",
        "best_for": "معظم المشاريع اللي تريد تحسين الرد والمتابعة والتحويل",
        "note": "هذه الباقة الأفضل لمعظم المشاريع."
    },
    "elite": {
        "name_ar": "باقة النخبة",
        "price_ar": "1499 درهم إماراتي شهرياً",
        "position": "أقوى باقة",
        "best_for": "المشاريع الجادة اللي عندها عملاء وتريد إغلاق ومتابعة أقوى",
        "note": "هذه للعميل الجاد الذي يريد نتيجة قوية."
    }
}


# =========================
# MLM LEVELS
# =========================

MLM_LEVELS = {
    "level_1": {
        "name_ar": "المستوى الأول",
        "title_ar": "شريك البداية",
        "requirements": "الاشتراك بأي باقة",
        "benefits": "25% عمولة مباشرة + كورس التسويق مجاناً"
    },
    "level_2": {
        "name_ar": "المستوى الثاني",
        "title_ar": "شريك النمو",
        "requirements": "الترقية إلى باقة النمو + بيع 2 عملاء مدفوعين",
        "benefits": "+5% عمولة شهرية إضافية"
    },
    "level_3": {
        "name_ar": "المستوى الثالث",
        "title_ar": "شريك المبيعات",
        "requirements": "شراء كورس المبيعات 99$ + بيع 5 عملاء",
        "benefits": "+4% عمولة شهرية إضافية"
    },
    "level_4": {
        "name_ar": "المستوى الرابع",
        "title_ar": "شريك القيادة",
        "locked": True,
        "teaser": "الدخل الأكبر يبدأ في المستويات الأعلى 🔐"
    },
    "level_5": {
        "name_ar": "المستوى الخامس",
        "title_ar": "شريك النخبة",
        "locked": True,
        "teaser": "هذا مستوى القمة والدخل الأقوى 🔐"
    }
}


# =========================
# CORE RULES
# =========================

CORE_RULES = {
    "main_language": "Arabic Gulf / Emirati",
    "secondary_language": "English",
    "do_not_sell_first_message": True,
    "do_not_show_price_before_discovery": True,
    "sell_client_product_first": True,
    "mention_mlm_after_interest_only": True,
    "never_insult": True,
    "human_style": True
}
# =========================
# FOUNDER INFO
# =========================

FOUNDER_INFO = {
    "name_ar": "المستشار مصعب البلوشي",
    "role_ar": "مؤسس وقيادي في شركة الصعب لإدارة المشاريع",
    "summary_ar": (
        "مدرب ومستشار في ريادة الأعمال وإدارة المشاريع، "
        "ومستشار في التنمية البشرية وتطوير الذات، "
        "ومحاضر دولي معتمد، شغل عدة مناصب في عدة مؤسسات، "
        "حائز على أكثر من 11 جائزة في المبيعات، "
        "مختص في تطوير الشركات، ومؤسس ورشة فلسفة الحياة ورحلة التغيير."
    ),
    "sales_record_ar": "خبرة قوية في المبيعات وتطوير الأعمال، مع سجل إنجازات ومبيعات كبيرة.",
}


# =========================
# PAYMENT LINKS
# ضع روابط Stripe / Ziina هنا لاحقاً
# =========================

PAYMENT_LINKS = {
    "starter": "https://buy.stripe.com/00w6oI08YctEdMW8t1aEE00",
    "growth": "https://buy.stripe.com/6oU3cw08Yalw24eeRpaEE01",
    "elite": "https://buy.stripe.com/28E14o3la79k7oyfVtaEE02",
}


# =========================
# CLOSING RULES
# =========================

CLOSING_RULES = {
    "website_closes_with_payment": True,
    "whatsapp_only_for_human_handoff": True,
    "do_not_repeat_whatsapp": True,
}
# =========================
# GOOGLE SHEETS WEBHOOK
# =========================

GOOGLE_SHEET_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbyzkc4XmHk9xWXXqx1O6MERc1NGzuyB1R2txElenks7yZEJrV8c5BRI5LVGtj8mj2BcCA/exec"
GOOGLE_SHEET_TOKEN = "alsaab_sheet_2026"