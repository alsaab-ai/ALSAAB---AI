# brain.py

import re
from openai import OpenAI

from config import OPENAI_API_KEY, MODEL_NAME, REPLY_MAX_TOKENS
from state import create_state, update_state
from prompt_builder import build_prompt
from database import (
    get_last_messages,
    save_message,
    save_lead,
    save_client_profile,
    get_client_profile,
)
from training_engine import start_training, handle_training

client = OpenAI(api_key=OPENAI_API_KEY)

state = create_state()


def format_history(messages):
    history_text = ""
    for role, content in messages:
        if role == "user":
            history_text += f"العميل: {content}\n"
        elif role == "client_data":
            history_text += f"بيانات المشروع: {content}\n"
        else:
            history_text += f"المساعد: {content}\n"
    return history_text


def extract_phone(message):
    cleaned = message.replace(" ", "").replace("-", "").replace("+", "00")

    patterns = [
        r"00971\d{8,9}",
        r"971\d{8,9}",
        r"05\d{8}",
        r"5\d{8}",
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return match.group(0)

    return None


def extract_name(message):
    msg = message.strip()

    name_patterns = [
        r"اسمي\s+(.+)",
        r"أنا\s+(.+)",
        r"انا\s+(.+)",
        r"my name is\s+(.+)",
        r"i am\s+(.+)",
        r"i'm\s+(.+)",
    ]

    for pattern in name_patterns:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            name = name.replace(".", "").replace(",", "").strip()

            if 1 <= len(name.split()) <= 4:
                return name

    return None


def update_lead_data(message, session_id):
    extracted_name = extract_name(message)
    extracted_phone = extract_phone(message)

    if extracted_name:
        state["lead_name"] = extracted_name

    if extracted_phone:
        state["lead_phone"] = extracted_phone

    if state.get("lead_name") and state.get("lead_phone"):
        save_lead(
            session_id=session_id,
            name=state["lead_name"],
            phone=state["lead_phone"],
            state=state
        )


def load_client_profile_into_state(session_id):
    """
    يسترجع بيانات المشروع المدربة من قاعدة البيانات.
    هذا لا يغيّر أسلوب الرد، فقط يضيف معرفة للبوت.
    """
    profile = get_client_profile(session_id)

    if profile:
        clean_profile = {
            key: value
            for key, value in profile.items()
            if value and key != "raw_data"
        }

        if clean_profile:
            state["client_data"] = clean_profile


def think(message, session_id):
    global state

    msg = message.lower().strip()

    # =========================
    # TRAINING MODE START
    # =========================

    if msg in ["تدريب", "تدريب البوت", "/train", "train"]:
        return start_training(state)

    if state.get("mode") == "training":
        reply = handle_training(message, state)

        # لما يخلص التدريب
        if state.get("mode") == "sales":
            client_data = state.get("client_data", {})

            if client_data:
                # نحفظ الملف التدريبي في جدول منظم
                save_client_profile(session_id, client_data)

                # نحفظ نسخة مقروءة داخل سجل المحادثة
                for key, value in client_data.items():
                    save_message(session_id, "client_data", f"{key}: {value}")

        return reply

    # =========================
    # SALES MODE
    # =========================

    state = update_state(message, state)

    # استرجاع بيانات المشروع المدربة إن وجدت
    load_client_profile_into_state(session_id)

    # Lead Capture خلف الكواليس
    update_lead_data(message, session_id)

    history = get_last_messages(session_id, limit=6)
    history_text = format_history(history)

    prompt = build_prompt(message, state, history_text)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": message}
        ],
        temperature=0.7,
        max_tokens=REPLY_MAX_TOKENS
    )

    reply = response.choices[0].message.content.strip()

    return reply