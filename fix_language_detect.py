from pathlib import Path

p = Path("backend/brain.py")
text = p.read_text(encoding="utf-8")
p.with_suffix(".py.bak_language_detect_fix").write_text(text, encoding="utf-8")

text = text.replace(
    "from state import create_state, update_state",
    "from state import create_state, update_state, detect_language"
)

target = '    current_state["session_id"] = session_id\n'
insert = '    current_state["session_id"] = session_id\n\n    # Detect reply language from the latest customer message.\n    current_state["language"] = detect_language(message)\n'

if 'current_state["language"] = detect_language(message)' not in text:
    text = text.replace(target, insert)

p.write_text(text, encoding="utf-8")
print("LANGUAGE_DETECT_FIX_OK")
