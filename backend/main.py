print("ALSAAB AI is running 🔥")

from flask import Flask, request, jsonify, render_template_string
from brain import think
from database import init_db, save_message, get_leads
import uuid

app = Flask(__name__)

init_db()

ADMIN_KEY = "alsaab123"

HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ALSAAB AI</title>
<style>
body { font-family: Arial; background:#111; color:white; padding:30px; }
#chat { max-width:760px; margin:auto; }
.msg { padding:12px; margin:10px 0; border-radius:10px; white-space:pre-wrap; line-height:1.6; }
.user { background:#333; text-align:right; }
.bot { background:#0b5; text-align:right; }
.bot a { color:white; font-weight:bold; text-decoration:underline; word-break:break-all; }
input { width:78%; padding:12px; border-radius:8px; border:0; }
button { padding:12px 18px; border-radius:8px; border:0; cursor:pointer; }
</style>
</head>
<body>
<div id="chat">
<h2>ALSAAB AI 🔥</h2>
<div id="messages"></div>
<input id="msg" placeholder="اكتب رسالتك">
<button onclick="sendMsg()">إرسال</button>
</div>

<script>
let sessionId = localStorage.getItem("session_id");

async function sendMsg() {
    const input = document.getElementById("msg");
    const text = input.value.trim();
    if (!text) return;

    addMsg(text, "user");
    input.value = "";

    const res = await fetch("/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message: text, session_id: sessionId})
    });

    const data = await res.json();
    sessionId = data.session_id;
    localStorage.setItem("session_id", sessionId);

    addMsg(data.reply, "bot");
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function linkify(text) {
    let safeText = escapeHtml(text);

    safeText = safeText.replace(
        /(https?:\/\/[^\s<>"']+)/g,
        function(url) {
            let cleanUrl = url.replace(/[،,.؛:!?)]$/, "");
            let tail = url.substring(cleanUrl.length);

            return '<a href="' + cleanUrl + '" target="_blank" rel="noopener noreferrer">' + cleanUrl + '</a>' + tail;
        }
    );

    safeText = safeText.replace(/\n/g, "<br>");
    return safeText;
}

function addMsg(text, type) {
    const box = document.getElementById("messages");
    const div = document.createElement("div");
    div.className = "msg " + type;

    if (type === "bot") {
        div.innerHTML = linkify(text);
    } else {
        div.innerText = text;
    }

    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}
</script>
</body>
</html>
"""

LEADS_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<title>ALSAAB AI Leads</title>
<style>
body { font-family: Arial; background:#111; color:white; padding:30px; }
table { width:100%; border-collapse:collapse; background:#1b1b1b; }
th, td { border:1px solid #444; padding:10px; text-align:right; }
th { background:#0b5; color:white; }
</style>
</head>
<body>
<h2>Leads / العملاء المحفوظين 🔥</h2>

<table>
<tr>
<th>ID</th>
<th>الاسم</th>
<th>الهاتف</th>
<th>النشاط</th>
<th>المشكلة</th>
<th>القناة</th>
<th>الحالة</th>
<th>التاريخ</th>
</tr>
{% for lead in leads %}
<tr>
<td>{{ lead["id"] }}</td>
<td>{{ lead["name"] }}</td>
<td>{{ lead["phone"] }}</td>
<td>{{ lead["business_type"] }}</td>
<td>{{ lead["pain_point"] }}</td>
<td>{{ lead["channel"] }}</td>
<td>{{ lead["status"] }}</td>
<td>{{ lead["created_at"] }}</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HTML)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}

    message = data.get("message", "").strip()
    session_id = data.get("session_id")

    if not session_id:
        session_id = str(uuid.uuid4())

    if not message:
        return jsonify({
            "reply": "اكتب رسالتك عشان أقدر أساعدك.",
            "session_id": session_id
        })

    save_message(session_id, "user", message)

    reply = think(message, session_id)

    save_message(session_id, "bot", reply)

    return jsonify({
        "reply": reply,
        "session_id": session_id
    })


@app.route("/leads", methods=["GET"])
def leads_json():
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify(get_leads())


@app.route("/leads-view", methods=["GET"])
def leads_view():
    key = request.args.get("key")
    if key != ADMIN_KEY:
        return "Unauthorized", 401

    leads = get_leads()
    return render_template_string(LEADS_HTML, leads=leads)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)