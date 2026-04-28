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

    print("TRAINING STARTED ✅", flush=True)

    return "تمام 🔥 خلنا نجهز البوت لمشروعك خطوة خطوة.\n" + FIELDS[0][1]


def handle_training(message, state, session_id=None):
    step = state.get("training_step", 0)

    print(f"TRAINING STEP RECEIVED ✅ step={step}", flush=True)
    print(f"TRAINING SESSION ✅ session_id={session_id}", flush=True)

    if step < len(FIELDS):
        key = FIELDS[step][0]
        value = message.strip()

        state["training_data"][key] = value
        state["training_step"] = step + 1

        print(f"TRAINING DATA SAVED IN MEMORY ✅ key={key}", flush=True)
        print(f"TRAINING NEXT STEP ✅ next_step={state['training_step']} / total={len(FIELDS)}", flush=True)

    if state.get("training_step", 0) >= len(FIELDS):
        print("TRAINING COMPLETED CONDITION HIT ✅", flush=True)
        return finish_training(state, session_id)

    next_question = FIELDS[state["training_step"]][1]
    return next_question


def finish_training(state, session_id=None):
    data = state.get("training_data", {})

    state["mode"] = "sales"
    state["client_data"] = data
    state["training_step"] = len(FIELDS)

    print("TRAINING FINISHED ✅", flush=True)
    print(f"TRAINING DATA READY ✅ fields={list(data.keys())}", flush=True)

    if not session_id:
        print("SAVE CLIENT PROFILE SKIPPED ❌ missing session_id", flush=True)
        return "تم تجهيز معلومات مشروعك، لكن لم يتم الحفظ لأن رقم الجلسة غير موجود. جرّب التدريب مرة ثانية."

    if not data:
        print("SAVE CLIENT PROFILE SKIPPED ❌ missing data", flush=True)
        return "تم إنهاء التدريب، لكن لا توجد بيانات للحفظ. جرّب التدريب مرة ثانية."

    try:
        print(f"SAVING CLIENT PROFILE ✅ session_id={session_id}", flush=True)
        save_client_profile(session_id, data)
        print("SAVE CLIENT PROFILE FUNCTION CALLED ✅", flush=True)

        return "تم حفظ معلومات مشروعك ✅ الحين البوت جاهز يبيع عنك بشكل مخصص"

    except Exception as error:
        print(f"SAVE CLIENT PROFILE ERROR ❌ {error}", flush=True)
        return "تم جمع معلومات مشروعك، لكن صار خطأ أثناء الحفظ. بنراجعه تقنياً."