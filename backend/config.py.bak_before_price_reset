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

# رابط تطبيق Render الأساسي
# نستخدمه لاحقاً في روابط الدفع الداخلية والـ webhook
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://alsaab-ai.onrender.com")


# =========================
# SUBSCRIPTION PACKAGES
# =========================

PACKAGES = {
    "starter": {
        "name_ar": "باقة البداية",
        "price_ar": "599 درهم إماراتي شهرياً",
        "position": "بداية الدخول للنظام",
        "best_for": "للمشاريع الصغيرة أو من يريد تجربة النظام بتكلفة أقل",
        "note": "باقة دخول أساسية، مناسبة للبداية ولا تشمل الاستشارات الخاصة أو ربط الموقع.",
        "monthly_reply_limit": 2000,
        "customer_reply_limit": 2000,
        "base_customer_reply_limit": 2000,
        "gift_reply_limit": 0,
        "total_customer_reply_limit": 2000,
        "owner_advisory_reply_limit": 0,
        "main_channel": "whatsapp",
        "channels": ["whatsapp"],
        "whatsapp_included": True,
        "website_included": False,
        "instagram_included": False,
        "dashboard_advisory_enabled": False,
        "image_catalog_enabled": False,
        "client_payment_links_enabled": False,
        "advisor_level": "none",
        "website_note": "لا تشمل ربط البوت على الموقع. المنفذ الرئيسي هو WhatsApp.",
        "support_level": "دعم أساسي",
        "customization_level": "تخصيص أساسي",
        "reporting_level": "بدون تقارير متقدمة",
        "recommended": False,
        "features": [
            "2000 رد شهري للعملاء",
            "تركيب على WhatsApp",
            "بوت مبيعات أساسي",
            "تدريب مشروع واحد",
            "حفظ بيانات العملاء",
            "حفظ بيانات المشروع",
            "Google Sheets Leads",
            "Google Sheets ClientProfiles",
            "Partner ID + Referral Link",
            "عمولة مباشرة 25% عند الاشتراك النشط"
        ],
        "not_included": [
            "ربط الموقع",
            "Client Dashboard متقدم",
            "استشارات خاصة لصاحب المشروع",
            "إضافة صور المنتجات والكتالوجات",
            "روابط دفع خاصة بالعميل",
            "Instagram",
            "Follow-up أوتوماتيكي كامل",
            "تقارير متقدمة"
        ],
        "sales_recommendation": "لا ترشح هذه الباقة إلا إذا العميل طلب الأرخص أو يريد تجربة بسيطة فقط."
    },

    "growth": {
        "name_ar": "باقة النمو",
        "price_ar": "1099 درهم إماراتي شهرياً",
        "position": "الباقة الموصى بها",
        "best_for": "معظم أصحاب المشاريع والشركاء الذين يريدون بوت مبيعات + مستشار أعمال ومبيعات.",
        "note": "هذه الباقة الأفضل لمعظم المشاريع لأنها تجمع بين ردود العملاء والاستشارات الخاصة لصاحب المشروع.",
        "monthly_reply_limit": 6000,
        "customer_reply_limit": 6000,
        "base_customer_reply_limit": 6000,
        "gift_reply_limit": 0,
        "total_customer_reply_limit": 6000,
        "owner_advisory_reply_limit": 1000,
        "main_channel": "whatsapp + website",
        "channels": ["whatsapp", "website"],
        "whatsapp_included": True,
        "website_included": True,
        "instagram_included": False,
        "dashboard_advisory_enabled": True,
        "image_catalog_enabled": True,
        "client_payment_links_enabled": True,
        "advisor_level": "business_sales_advisor",
        "website_note": "تشمل WhatsApp + إمكانية ربط البوت على الموقع.",
        "support_level": "أولوية أعلى من باقة البداية",
        "customization_level": "تخصيص أفضل حسب المشروع",
        "reporting_level": "تقارير مبدئية لاحقاً",
        "recommended": True,
        "features": [
            "6000 رد شهري للعملاء",
            "1000 رد شهري استشاري لصاحب المشروع من Client Dashboard",
            "تركيب على WhatsApp",
            "إمكانية التركيب على الموقع",
            "بوت مبيعات وخدمة عملاء للمشروع",
            "مستشار ريادة أعمال ومبيعات لصاحب المشروع أو الشريك",
            "إضافة صور المنتجات والكتالوجات",
            "إضافة روابط دفع خاصة بالمنتجات من داخل Client Dashboard",
            "تدريب مشروع واحد",
            "Google Sheets Leads",
            "Google Sheets ClientProfiles",
            "تحسين أسلوب الرد حسب نشاط العميل",
            "معالجة اعتراضات أفضل",
            "Partner ID + Referral Link",
            "مؤهل للوصول إلى Level 2 و Level 3 حسب الشروط"
        ],
        "not_included": [
            "Instagram",
            "Client Dashboard متقدم جداً",
            "Follow-up أوتوماتيكي كامل",
            "ربط أنظمة داخلية متقدمة",
            "Enterprise custom integrations"
        ],
        "sales_recommendation": "هذه هي الباقة الافتراضية الموصى بها لمعظم أصحاب المشاريع والشركاء."
    },

    "elite": {
        "name_ar": "باقة النخبة",
        "price_ar": "2099 درهم إماراتي شهرياً",
        "position": "أقوى باقة",
        "best_for": "المشاريع الجادة والشركاء المتقدمين الذين يريدون حجم ردود أعلى وقنوات أكثر وتخصيص أقوى.",
        "note": "باقة متقدمة للمشاريع الجادة، وتشمل ردود إضافية هدية واستشارات أعمق لصاحب المشروع.",
        "monthly_reply_limit": 15000,
        "customer_reply_limit": 15000,
        "base_customer_reply_limit": 12000,
        "gift_reply_limit": 3000,
        "total_customer_reply_limit": 15000,
        "owner_advisory_reply_limit": 2000,
        "main_channel": "whatsapp + website + instagram",
        "channels": ["whatsapp", "website", "instagram"],
        "whatsapp_included": True,
        "website_included": True,
        "instagram_included": True,
        "dashboard_advisory_enabled": True,
        "image_catalog_enabled": True,
        "client_payment_links_enabled": True,
        "advisor_level": "advanced_business_sales_advisor",
        "website_note": "تشمل WhatsApp + Website + دعم Instagram ضمن الربط المتقدم.",
        "support_level": "أولوية دعم أعلى",
        "customization_level": "تخصيص أعمق للبرومبت وسيناريوهات البيع",
        "reporting_level": "تقارير أفضل لاحقاً",
        "recommended": False,
        "features": [
            "12000 رد شهري للعملاء",
            "3000 رد هدية من شركة الصعب",
            "مجموع ردود العملاء = 15000 رد شهري",
            "2000 رد شهري استشاري لصاحب المشروع من Client Dashboard",
            "تركيب على WhatsApp",
            "تركيب على الموقع",
            "دعم Instagram ضمن الربط المتقدم",
            "بوت مبيعات وخدمة عملاء أقوى",
            "مستشار ريادة أعمال ومبيعات أقوى وأكثر تخصيصاً",
            "إضافة صور المنتجات والكتالوجات",
            "إضافة روابط دفع خاصة بالمنتجات من داخل Client Dashboard",
            "تخصيص أعمق للردود",
            "معالجة اعتراضات أقوى",
            "إعداد سيناريوهات بيع أفضل",
            "Partner ID + Referral Link",
            "شرط أساسي للوصول إلى Level 4 و Level 5"
        ],
        "not_included": [
            "استخدام غير محدود بدون سياسة استخدام عادلة",
            "استلام مبالغ العملاء نيابة عنهم",
            "ربط أنظمة داخلية متقدمة بدون اتفاق خاص",
            "Enterprise custom integrations"
        ],
        "sales_recommendation": "رشح هذه الباقة للعميل الجاد أو الشريك المتقدم أو المشروع الذي يحتاج قنوات أكثر وتخصيص أعلى."
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
        "تم استهلاك حد الردود الشهري لباقتك الحالية ✅\n\n"
        "لإكمال استخدام ALSAAB AI، تقدر ترقي باقتك أو تنتظر تجديد الدورة الشهرية.\n\n"
        "الباقات المتاحة:\n"
        "- باقة النمو: 6000 رد شهري للعملاء + 1000 رد استشاري لصاحب المشروع من Client Dashboard\n"
        "- باقة النخبة: 15000 رد شهري للعملاء + 2000 رد استشاري لصاحب المشروع من Client Dashboard\n\n"
        "إذا استخدامك عالي أو عندك شركة كبيرة، نقدر نجهز لك باقة Enterprise باتفاق خاص."
    ),
    "en": (
        "Your current monthly package limit has been used ✅\n\n"
        "To continue using ALSAAB AI, you can upgrade your package or wait for the next monthly cycle.\n\n"
        "Available options:\n"
        "- Growth Package: 6000 customer replies/month + 1000 owner advisory replies/month from Client Dashboard\n"
        "- Elite Package: 15000 customer replies/month + 2000 owner advisory replies/month from Client Dashboard\n\n"
        "For high usage or larger companies, we can prepare a custom Enterprise plan."
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
        "benefits": "25% عمولة مباشرة + كورس التسويق مجاناً",
        "commission_percent": 25,
        "commission_depth": 1
    },
    "level_2": {
        "name_ar": "المستوى الثاني",
        "title_ar": "شريك النمو",
        "requirements": "الترقية إلى باقة النمو + بيع 2 عملاء مدفوعين",
        "benefits": "+5% عمولة شهرية إضافية",
        "commission_percent": 5,
        "commission_depth": 2
    },
    "level_3": {
        "name_ar": "المستوى الثالث",
        "title_ar": "شريك المبيعات",
        "requirements": "شراء كورس المبيعات 99$ + بيع 5 عملاء",
        "benefits": "+4% عمولة شهرية إضافية",
        "commission_percent": 4,
        "commission_depth": 3
    },
    "level_4": {
        "name_ar": "المستوى الرابع",
        "title_ar": "شريك القيادة",
        "requirements": "شراء ورشة فلسفة الحياة 299$ + إدخال 20 عميل نشط",
        "benefits": "+3% عمولة شهرية إضافية",
        "commission_percent": 3,
        "commission_depth": 4,
        "locked": True,
        "teaser": "الدخل الأكبر يبدأ في المستويات الأعلى 🔐"
    },
    "level_5": {
        "name_ar": "المستوى الخامس",
        "title_ar": "شريك النخبة",
        "requirements": "شراء كورس رحلة التغيير 1099$ + إدخال 50 عميل نشط",
        "benefits": "+2% عمولة شهرية إضافية",
        "commission_percent": 2,
        "commission_depth": 5,
        "locked": True,
        "teaser": "هذا مستوى القمة والدخل الأقوى 🔐"
    }
}


# =========================
# MLM OWNER / SPONSOR RULES
# =========================

COMPANY_OWNER_PARTNER_ID = os.getenv("COMPANY_OWNER_PARTNER_ID", "alsaab")
MLM_OWNER_PARTNER_ID = COMPANY_OWNER_PARTNER_ID

MLM_SPONSOR_RULES = {
    "require_sponsor_for_partner_registration": True,
    "owner_partner_id": COMPANY_OWNER_PARTNER_ID,
    "owner_id_is_company_income": True,
    "owner_id_has_no_external_commission": True,
    "allow_owner_without_sponsor": True,
    "do_not_auto_assign_owner_before_asking_source": True,
    "ask_source_before_owner_assignment": True,
    "prevent_empty_sponsor": True,
    "prevent_invalid_sponsor": True,
    "sponsor_change_after_registration_requires_admin": True,
    "notes": (
        "كل شريك جديد لازم يكون مرتبط بمعرف الشخص الذي عرفه على النظام. "
        "إذا عرف العميل النظام من السوشيال ميديا أو الموقع أو إعلان أو الشركة مباشرة، "
        "يستخدم معرف صاحب الشركة: alsaab. هذا المعرف يمثل دخل الشركة ولا يدخل كعمولة شريك خارجي."
    )
}


MLM_SOURCE_OPTIONS = {
    "direct_partner": {
        "name_ar": "عن طريق شريك",
        "requires_partner_id": True,
        "example": "ALS-P00025"
    },
    "social_media": {
        "name_ar": "السوشيال ميديا",
        "requires_partner_id": False,
        "default_partner_id": COMPANY_OWNER_PARTNER_ID
    },
    "website": {
        "name_ar": "الموقع",
        "requires_partner_id": False,
        "default_partner_id": COMPANY_OWNER_PARTNER_ID
    },
    "advertisement": {
        "name_ar": "إعلان",
        "requires_partner_id": False,
        "default_partner_id": COMPANY_OWNER_PARTNER_ID
    },
    "company_direct": {
        "name_ar": "تواصل مباشر مع الشركة",
        "requires_partner_id": False,
        "default_partner_id": COMPANY_OWNER_PARTNER_ID
    },
    "event_or_seminar": {
        "name_ar": "ندوة أو فعالية",
        "requires_partner_id": False,
        "default_partner_id": COMPANY_OWNER_PARTNER_ID
    }
}


MLM_REGISTRATION_MESSAGES = {
    "ask_source_ar": (
        "قبل ما أكمل تسجيلك كشريك، لازم نربط تسجيلك بالشخص أو المصدر اللي عرّفك على النظام عشان نحفظ الحقوق بدقة.\n\n"
        "من وين عرفت ALSAAB AI؟\n"
        "- عن طريق شخص / شريك\n"
        "- السوشيال ميديا\n"
        "- الموقع\n"
        "- إعلان\n"
        "- ندوة أو فعالية\n"
        "- تواصل مباشر مع الشركة"
    ),
    "ask_sponsor_id_ar": (
        "اكتب Partner ID الخاص بالشخص اللي عرفك على النظام.\n\n"
        "مثال:\n"
        "ALS-P00025\n\n"
        "مهم: بعد التسجيل، تغيير المعرّف يحتاج مراجعة إدارية عشان نحفظ الحقوق."
    ),
    "use_owner_id_ar": (
        "تمام، بما إنك عرفت النظام من مصدر تابع للشركة، بنربط تسجيلك بمعرف الشركة:\n\n"
        f"{COMPANY_OWNER_PARTNER_ID}\n\n"
        "هذا يحفظ التتبع بشكل صحيح داخل النظام."
    ),
    "invalid_sponsor_ar": (
        "لازم يكون عندك Partner ID صحيح للشخص اللي عرفك على النظام.\n\n"
        "إذا عرفتنا من السوشيال ميديا أو الموقع أو إعلان أو من الشركة مباشرة، بنستخدم معرف الشركة."
    )
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
    "starter": "https://buy.stripe.com/aFa28sg7WdxIbEOeRpaEE03",
    "growth": "https://buy.stripe.com/28E6oI9Jy3X810a6kTaEE04",
    "elite": "https://buy.stripe.com/4gMbJ2g7Walw9wGdNlaEE05",
}


# =========================
# STRIPE CONFIG
# =========================

# Stripe Secret Key نحتاجه لاحقاً إذا بنستخدم Stripe API مباشرة.
# حالياً نقدر نبدأ بالـ Payment Links + Webhook.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")

# Stripe Webhook Secret ينضاف من Render Environment Variables.
# لا تحطه داخل GitHub.
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# مدة قبول توقيع Stripe Webhook بالثواني.
STRIPE_WEBHOOK_TOLERANCE_SECONDS = 300

# أحداث Stripe التي نهتم بها حالياً.
STRIPE_ALLOWED_EVENTS = [
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.deleted",
    "customer.subscription.updated",
]

# روابط دفع داخلية تمر عبر Render قبل Stripe.
# الهدف منها نربط session_id بالخطة قبل الدفع.
PAYMENT_ROUTE_LINKS = {
    "starter": f"{APP_BASE_URL}/pay/starter",
    "growth": f"{APP_BASE_URL}/pay/growth",
    "elite": f"{APP_BASE_URL}/pay/elite",
}

# إعدادات ربط الباقات مع Stripe Webhook.
# Webhook سيستخدم plan_name لتفعيل الاشتراك وحد الردود.
STRIPE_PLAN_CONFIG = {
    "starter": {
        "plan_name": "starter",
        "payment_link": PAYMENT_LINKS["starter"],
        "internal_payment_route": PAYMENT_ROUTE_LINKS["starter"],
        "monthly_reply_limit": PACKAGES["starter"]["monthly_reply_limit"],
        "package_amount": "599 AED",
        "subscription_type": "monthly",
    },
    "growth": {
        "plan_name": "growth",
        "payment_link": PAYMENT_LINKS["growth"],
        "internal_payment_route": PAYMENT_ROUTE_LINKS["growth"],
        "monthly_reply_limit": PACKAGES["growth"]["monthly_reply_limit"],
        "package_amount": "1099 AED",
        "subscription_type": "monthly",
    },
    "elite": {
        "plan_name": "elite",
        "payment_link": PAYMENT_LINKS["elite"],
        "internal_payment_route": PAYMENT_ROUTE_LINKS["elite"],
        "monthly_reply_limit": PACKAGES["elite"]["monthly_reply_limit"],
        "package_amount": "2099 AED",
        "subscription_type": "monthly",
    },
}

# مفتاح client_reference_id داخل Stripe Checkout.
# لاحقاً بنرسله بهذا الشكل:
# session_id::plan_name
STRIPE_CLIENT_REFERENCE_SEPARATOR = "::"

# روابط يرجع لها العميل بعد الدفع أو عند الإلغاء.
STRIPE_SUCCESS_URL = f"{APP_BASE_URL}/payment-success"
STRIPE_CANCEL_URL = f"{APP_BASE_URL}/payment-cancel"


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

# ===== ALSAAB_ENTRY_PACKAGE_SAFE_V3 START =====
# Entry package is added safely at the end of config.py.
# This version avoids undefined-variable warnings in VS Code / Pylance.

ENTRY_PACKAGE_PRICE_ID = "price_1TXetrJbltD9Bsg8wnVMaBnZ"
ENTRY_PACKAGE_PAYMENT_LINK = "https://buy.stripe.com/6oU3cw3laalw7oy7oXaEE06"

ENTRY_PACKAGE_CONFIG = {
    "name_ar": "باقة الدخول",
    "name_en": "Entry",
    "price_ar": "299 درهم إماراتي شهرياً",
    "price_en": "299 AED monthly",
    "monthly_reply_limit": 500,
    "customer_reply_limit": 500,
    "owner_advisory_reply_limit": 0,
    "max_payment_links": 1,
    "max_product_images": 1,
    "max_product_image_groups": 1,
    "website_channel": False,
    "instagram_channel": False,
    "smart_whatsapp_entry": True,
    "support_level": "دعم عادي",
    "description_ar": "باقة دخول محدودة للتجربة: 500 رد شهري، رابط دفع واحد، وصورة منتج واحدة فقط، بدون خصائص إضافية.",
    "description_en": "Limited entry package: 500 monthly replies, one payment link, and one product image only.",
}

_packages = globals().get("PACKAGES")
if not isinstance(_packages, dict):
    _packages = {}
    globals()["PACKAGES"] = _packages
_packages["entry"] = ENTRY_PACKAGE_CONFIG

_payment_links = globals().get("PAYMENT_LINKS")
if not isinstance(_payment_links, dict):
    _payment_links = {}
    globals()["PAYMENT_LINKS"] = _payment_links
_payment_links["entry"] = ENTRY_PACKAGE_PAYMENT_LINK

_payment_route_links = globals().get("PAYMENT_ROUTE_LINKS")
if not isinstance(_payment_route_links, dict):
    _payment_route_links = {}
    globals()["PAYMENT_ROUTE_LINKS"] = _payment_route_links

_app_base = globals().get("APP_BASE_URL", "https://alsaab-ai.onrender.com")
_payment_route_links["entry"] = f"{_app_base}/pay/entry"

for _entry_price_dict_name in [
    "UPGRADE_PRICE_IDS",
    "STRIPE_PRICE_IDS",
    "PLAN_PRICE_IDS",
    "PACKAGE_PRICE_IDS",
]:
    _entry_price_dict = globals().get(_entry_price_dict_name)
    if isinstance(_entry_price_dict, dict):
        _entry_price_dict["entry"] = ENTRY_PACKAGE_PRICE_ID

for _entry_limit_dict_name in [
    "PACKAGE_LIMITS",
    "PLAN_LIMITS",
    "USAGE_LIMITS",
    "REPLY_LIMITS",
]:
    _entry_limit_dict = globals().get(_entry_limit_dict_name)
    if isinstance(_entry_limit_dict, dict):
        _entry_limit_dict["entry"] = {
            "monthly_reply_limit": 500,
            "customer_reply_limit": 500,
            "owner_advisory_reply_limit": 0,
            "max_payment_links": 1,
            "max_product_images": 1,
            "max_product_image_groups": 1,
        }

_package_payment_options = globals().get("PACKAGE_PAYMENT_OPTIONS")
if not isinstance(_package_payment_options, dict):
    _package_payment_options = {}
    globals()["PACKAGE_PAYMENT_OPTIONS"] = _package_payment_options

_package_payment_options["entry"] = {
    "plan_name": "entry",
    "payment_link": ENTRY_PACKAGE_PAYMENT_LINK,
    "internal_payment_route": _payment_route_links.get("entry", "https://alsaab-ai.onrender.com/pay/entry"),
    "monthly_reply_limit": 500,
    "package_amount": "299 AED",
}

_package_order = globals().get("PACKAGE_ORDER")
if not isinstance(_package_order, list):
    _package_order = ["entry", "starter", "growth", "elite"]
    globals()["PACKAGE_ORDER"] = _package_order
elif "entry" not in _package_order:
    _package_order.insert(0, "entry")

# ===== ALSAAB_ENTRY_PACKAGE_SAFE_V3 END =====
