from pathlib import Path

p = Path("backend/main.py")
t = p.read_text(encoding="utf-8")

old = '''        {% for level, count in level_counts.items() %}
        <div class="kv"><span>{{ level }}</span><strong>{{ count }}</strong></div>
        {% else %}'''

new = '''        {% for level_name, count in level_counts.items() %}
        <div class="kv"><span>{{ level_name }}</span><strong>{{ count }}</strong></div>
        {% else %}'''

if old not in t:
    raise SystemExit("TARGET_NOT_FOUND")

p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("PATCH_OK")
