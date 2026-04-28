# training_engine.py

from database import save_client_profile


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

    print("TRAINING STARTED ✅")

    return "تمام 🔥 خلنا نجهز البوت لمشروعك خطوة خطوة.\n" + FIELDS[0][1]


def handle_training(message, state, session_id=None):
    step = state.get("training_step", 0)

    print(f"TRAINING STEP RECEIVED ✅ step={step}")

    if step < len(FIELDS):
        key = FIELDS[step][0]
        state["training_data"][key] = message.strip()
        state["training_step"] = step + 1

        print(f"TRAINING DATA SAVED IN MEMORY ✅ key={key}")

    if state["training_step"] >= len(FIELDS):
        return finish_training(state, session_id)

    return FIELDS[state["training_step"]][1]


def finish_training(state, session_id=None):
    data = state.get("training_data", {})

    state["mode"] = "sales"
    state["client_data"] = data

    print("TRAINING FINISHED ✅")
    print(f"TRAINING DATA READY ✅ fields={list(data.keys())}")

    if session_id and data:
        print(f"SAVING CLIENT PROFILE ✅ session_id={session_id}")
        save_client_profile(session_id, data)
        print("SAVE CLIENT PROFILE FUNCTION CALLED ✅")
    else:
        print("SAVE CLIENT PROFILE SKIPPED ❌ missing session_id or data")

    return "تم حفظ معلومات مشروعك ✅ الحين البوت جاهز يبيع عنك بشكل مخصص"