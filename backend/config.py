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
        "note": "ليست الباقة الأقوى، لكنها مدخل ممتاز للبدء.",
        "monthly_reply_limit": 2000,
        "main_channel": "whatsapp",
        "whatsapp_included": True,
        "website_included": False,
        "website_note": "لا تشمل ربط البوت على الموقع. المنفذ الرئيسي هو WhatsApp.",
        "support_level": "دعم أساسي",
        "customization_level": "تخصيص أساسي",
        "reporting_level": "بدون تقارير متقدمة",
        "recommended": False,
        "features": [
            "2000 رد شهرياً",
            "بوت مبيعات على WhatsApp",
            "تدريب مشروع واحد",
            "حفظ بيانات العملاء",
            "حفظ بيانات المشروع",
            "Google Sheets Leads",
            "Google Sheets ClientProfiles",
            "ردود مبيعات أساسية",
            "روابط دفع داخل المحادثة"
        ],
        "not_included": [
            "ربط الموقع",
            "Dashboard كامل",
            "Follow-up أوتوماتيكي",
            "تقارير متقدمة",
            "تخصيص عميق",
            "أولوية دعم"
        ],
        "sales_recommendation": "لا ترشح هذه الباقة إلا إذا العميل طلب الأرخص، ميزانيته محدودة، أو يريد تجربة بسيطة فقط."
    },

    "growth": {
        "name_ar": "باقة النمو",
        "price_ar": "799 درهم إماراتي شهرياً",
        "position": "الباقة الموصى بها",
        "best_for": "معظم المشاريع اللي تريد تحسين الرد والمتابعة والتحويل",
        "note": "هذه الباقة الأفضل لمعظم المشاريع.",
        "monthly_reply_limit": 6000,
        "main_channel": "whatsapp",
        "whatsapp_included": True,
        "website_included": True,
        "website_note": "تشمل إمكانية ربط البوت على الموقع بالإضافة إلى WhatsApp.",
        "support_level": "أولوية أعلى من باقة البداية",
        "customization_level": "تخصيص أفضل حسب المشروع",
        "reporting_level": "تقارير مبدئية لاحقاً",
        "recommended": True,
        "features": [
            "6000 رد شهرياً",
            "بوت مبيعات على WhatsApp",
            "إمكانية ربط البوت على الموقع",
            "تدريب مشروع واحد",
            "Google Sheets Leads",
            "Google Sheets ClientProfiles",
            "Prompt مبيعات أقوى",
            "تحسين أسلوب الرد حسب نشاط العميل",
            "معالجة اعتراضات أفضل",
            "ربط البوت بأسلوب المشروع",
            "روابط دفع داخل المحادثة"
        ],
        "not_included": [
            "Dashboard كامل متقدم",
            "Follow-up أوتوماتيكي كامل",
            "ربط أنظمة داخلية",
            "تخصيص Enterprise"
        ],
        "sales_recommendation": "هذه هي الباقة الافتراضية الموصى بها لصاحب المشروع الذي يريد رفع المبيعات وتحسين الردود والتحويل."
    },

    "elite": {
        "name_ar": "باقة النخبة",
        "price_ar": "1499 درهم إماراتي شهرياً",
        "position": "أقوى باقة",
        "best_for": "المشاريع الجادة اللي عندها عملاء وتريد إغلاق ومتابعة أقوى",
        "note": "هذه للعميل الجاد الذي يريد نتيجة قوية.",
        "monthly_reply_limit": 12000,
        "main_channel": "whatsapp",
        "whatsapp_included": True,
        "website_included": True,
        "website_note": "تشمل WhatsApp + Website Bot مع تخصيص أقوى.",
        "support_level": "أولوية دعم أعلى",
        "customization_level": "تخصيص أعمق للبرومبت وسيناريوهات البيع",
        "reporting_level": "تقارير أفضل لاحقاً",
        "recommended": False,
        "features": [
            "12000 رد شهرياً",
            "بوت مبيعات على WhatsApp",
            "بوت مبيعات على الموقع",
            "تخصيص أعمق للبرومبت",
            "Objection Handling أقوى",
            "إعداد سيناريوهات بيع أفضل",
            "أولوية دعم",
            "قابلية أعلى للتوسع",
            "Google Sheets Leads",
            "Google Sheets ClientProfiles",
            "روابط دفع داخل المحادثة"
        ],
        "not_included": [
            "استخدام غير محدود بدون سياسة استخدام عادلة",
            "ربط أنظمة داخلية متقدمة بدون اتفاق خاص",
            "Enterprise custom integrations"
        ],
        "sales_recommendation": "رشح هذه الباقة للعميل الجاد، أو المشروع الذي عنده حجم محادثات أعلى ويريد تخصيص أقوى."
    }
}


# =========================
# ENTERPRISE / CUSTOM PLAN
# =========================

ENTERPRISE_PACKAGE = {
    "name_ar": "باقة الشركات / Enterprise",
    "price_ar": "فاتورة شهرية منفصلة حسب الاستخدام",
    "position": "للشركات الكبيرة والاستخدام العالي",
    "best_for": "الشركات الكبيرة، الفروع المتعددة، أو المشاريع التي تحتاج حجم ردود عالي وربط خاص",
    "monthly_reply_limit": "custom",
    "main_channel": "whatsapp + website + custom integrations",
    "whatsapp_included": True,
    "website_included": True,
    "custom_invoice": True,
    "stripe_invoice_required": True,
    "note": "إذا عند العميل شركة كبيرة أو استخدامات عديدة، يتم تجهيز فاتورة شهرية منفصلة من Stripe بسعر أعلى حسب الاستخدام والربط المطلوب.",
    "features": [
        "عدد ردود مخصص حسب الاتفاق",
        "WhatsApp Bot",
        "Website Bot",
        "تخصيص متقدم",
        "إمكانية ربط أكثر من فرع أو أكثر من مشروع",
        "دعم أعلى",
        "تقارير مخصصة لاحقاً",
        "ربط أنظمة داخلية لاحقاً حسب الاتفاق"
    ],
    "sales_recommendation": "إذا العميل شركة كبيرة أو عنده حجم محادثات عالي، لا تحصره في الباقات العادية. اعرض عليه باقة Enterprise بفاتورة شهرية منفصلة."
}


# =========================
# USAGE LIMIT RULES
# =========================

USAGE_LIMIT_RULES = {
    "enabled": False,
    "note": "هذا النظام سيتم تفعيله لاحقاً بعد بناء usage counter وربط الباقة بالعميل.",
    "reply_count_unit": "bot_reply",
    "reset_cycle": "monthly",
    "stop_when_limit_reached": True,
    "allow_admin_manual_increase": True,
    "allow_enterprise_custom_limit": True,
}


USAGE_LIMIT_MESSAGES = {
    "ar": (
        "تم استهلاك باقتك الحالية لهذا الشهر ✅\n\n"
        "لإكمال استخدام ALSAAB AI، تقدر ترقّي باقتك أو تنتظر تجديد الدورة الشهرية.\n\n"
        "الباقات المتاحة:\n"
        "- باقة النمو: 6000 رد شهرياً\n"
        "- باقة النخبة: 12000 رد شهرياً\n\n"
        "وإذا استخدامك عالي أو عندك شركة كبيرة، نقدر نجهز لك باقة خاصة للشركات بفاتورة شهرية منفصلة."
    ),
    "en": (
        "Your current monthly package limit has been used ✅\n\n"
        "To continue using ALSAAB AI, you can upgrade your package or wait for the next monthly cycle.\n\n"
        "Available options:\n"
        "- Growth Package: 6000 replies/month\n"
        "- Elite Package: 12000 replies/month\n\n"
        "For high-volume usage or large companies, we can prepare a custom Enterprise monthly invoice."
    )
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