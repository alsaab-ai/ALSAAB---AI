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

# State منفصل لكل جلسة عشان التدريب ما يضيع بين الرسائل
session_states = {}


def get_session_state(session_id):
    if session_id not in session_states:
        session_states[session_id] = create_state()
    return session_states[session_id]


def set_session_state(session_id, new_state):
    session_states[session_id] = new_state


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


def update_lead_data(message, session_id, current_state):
    extracted_name = extract_name(message)
    extracted_phone = extract_phone(message)

    if extracted_name:
        current_state["lead_name"] = extracted_name

    if extracted_phone:
        current_state["lead_phone"] = extracted_phone

    if current_state.get("lead_name") and current_state.get("lead_phone"):
        save_lead(
            session_id=session_id,
            name=current_state["lead_name"],
            phone=current_state["lead_phone"],
            state=current_state
        )


def load_client_profile_into_state(session_id, current_state):
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
            current_state["client_data"] = clean_profile


def think(message, session_id):
    current_state = get_session_state(session_id)
    msg = message.lower().strip()

    # =========================
    # TRAINING MODE START
    # =========================

    if msg in ["تدريب", "تدريب البوت", "/train", "train"]:
        reply = start_training(current_state)
        set_session_state(session_id, current_state)
        return reply

    # =========================
    # TRAINING MODE LOCKED
    # =========================

    if current_state.get("mode") == "training":
        reply = handle_training(message, current_state)

        # لما يخلص التدريب
        if current_state.get("mode") == "sales":
            client_data = current_state.get("client_data", {})

            if client_data:
                save_client_profile(session_id, client_data)

                for key, value in client_data.items():
                    save_message(session_id, "client_data", f"{key}: {value}")

        set_session_state(session_id, current_state)
        return reply

    # =========================
    # SALES MODE
    # =========================

    current_state = update_state(message, current_state)

    # استرجاع بيانات المشروع المدربة إن وجدت
    load_client_profile_into_state(session_id, current_state)

    # Lead Capture خلف الكواليس
    update_lead_data(message, session_id, current_state)

    history = get_last_messages(session_id, limit=6)
    history_text = format_history(history)

    prompt = build_prompt(message, current_state, history_text)

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

    set_session_state(session_id, current_state)

    return reply