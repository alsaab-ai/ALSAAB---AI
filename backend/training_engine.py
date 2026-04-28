# training_engine.py

FIELDS = [
    ("business_name", "شو اسم مشروعك؟"),
    ("business_type", "شو نوع النشاط؟"),

    (
        "general_description",
        "عطني وصف عام ومفصل عن مشروعك. اكتب كل شيء مهم حتى لو بشكل طويل أو ممل: شو تبيع، من جمهورك، شو يميزك، طريقة شغلك، الأسعار العامة، العروض، المشاكل اللي تواجهها، طريقة البيع، وأي معلومة تبغي البوت يعرفها عشان يبيع عنك صح."
    ),

    ("products", "شو المنتجات أو الخدمات اللي تقدمها؟"),
    ("prices", "شو الأسعار أو متوسط الأسعار؟"),
    ("offers", "هل عندك عروض حالياً؟"),
    ("ordering", "كيف يتم الطلب أو الحجز؟"),
    ("whatsapp", "رقم الواتساب الخاص بالمشروع؟"),
    ("areas", "وين تخدم؟ أي مناطق أو مدن؟"),
    ("faqs", "أكثر الأسئلة اللي يسألونك العملاء؟"),
    ("objections", "أكثر اعتراض يجيك من العملاء؟"),
    ("tone", "كيف تبغي أسلوب الرد؟ (رسمي / خفيف / خليجي / قوي)")
]


def start_training(state):
    state["mode"] = "training"
    state["training_step"] = 0
    state["training_data"] = {}
    return "تمام 🔥 خلنا نجهز البوت لمشروعك خطوة خطوة.\n" + FIELDS[0][1]


def handle_training(message, state):
    step = state.get("training_step", 0)

    if step < len(FIELDS):
        key = FIELDS[step][0]
        state["training_data"][key] = message.strip()
        state["training_step"] = step + 1

    if state["training_step"] >= len(FIELDS):
        return finish_training(state)

    return FIELDS[state["training_step"]][1]


def finish_training(state):
    data = state.get("training_data", {})

    state["mode"] = "sales"
    state["client_data"] = data

    return "تم حفظ معلومات مشروعك ✅ الحين البوت جاهز يبيع عنك بشكل مخصص"