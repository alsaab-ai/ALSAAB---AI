print("ALSAAB AI is running 🔥")

from flask import Flask, request, jsonify, render_template_string
from brain import think
from database import init_db, save_message, get_leads
import uuid
import os

app = Flask(__name__)

init_db()

ADMIN_KEY = "alsaab123"

HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ALSAAB AI</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">

<style>
* {
    box-sizing: border-box;
}

:root {
    --bg-main: #05070d;
    --bg-card: rgba(12, 16, 26, 0.92);
    --bg-card-soft: rgba(255, 255, 255, 0.045);
    --border-soft: rgba(255, 255, 255, 0.08);
    --gold: #d6a84f;
    --gold-2: #f3d37b;
    --gold-3: #a97824;
    --green: #22c55e;
    --text-main: #f8fafc;
    --text-soft: #cbd5e1;
    --text-muted: #94a3b8;
    --shadow: 0 24px 80px rgba(0,0,0,0.55);
}

html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    height: 100%;
    background: var(--bg-main);
    font-family: "Cairo", Arial, sans-serif;
    color: var(--text-main);
    overflow: hidden;
}

.luxury-bg {
    position: fixed;
    inset: 0;
    background:
        radial-gradient(circle at 15% 15%, rgba(214, 168, 79, 0.16), transparent 28%),
        radial-gradient(circle at 85% 85%, rgba(214, 168, 79, 0.12), transparent 32%),
        linear-gradient(135deg, #03050a 0%, #0a0f1d 42%, #060810 100%);
    z-index: -3;
}

.luxury-bg::before {
    content: "";
    position: absolute;
    inset: 0;
    background-image:
        linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
    background-size: 42px 42px;
    mask-image: radial-gradient(circle at center, black, transparent 78%);
    opacity: 0.55;
}

.luxury-bg::after {
    content: "";
    position: absolute;
    inset: 0;
    background:
        radial-gradient(circle at 55% 115%, rgba(214,168,79,0.22), transparent 35%),
        radial-gradient(circle at 95% 10%, rgba(255,255,255,0.05), transparent 25%);
    opacity: 0.9;
}

.page {
    width: 100%;
    height: 100vh;
    padding: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
}

.chat-shell {
    width: min(1040px, 100%);
    height: min(880px, calc(100vh - 36px));
    min-height: 620px;
    display: grid;
    grid-template-columns: 280px 1fr;
    border: 1px solid rgba(214, 168, 79, 0.38);
    border-radius: 28px;
    background:
        linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.01)),
        rgba(7, 10, 18, 0.92);
    box-shadow:
        var(--shadow),
        0 0 0 1px rgba(255,255,255,0.025) inset,
        0 0 80px rgba(214, 168, 79, 0.08);
    overflow: hidden;
    backdrop-filter: blur(18px);
}

.sidebar {
    position: relative;
    padding: 24px 18px;
    border-left: 1px solid rgba(255,255,255,0.07);
    background:
        radial-gradient(circle at top, rgba(214,168,79,0.13), transparent 34%),
        linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.01));
    overflow-y: auto;
}

.sidebar::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
        linear-gradient(145deg, transparent 0%, rgba(214,168,79,0.045) 45%, transparent 80%);
    pointer-events: none;
}

.brand-block {
    position: relative;
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 28px;
}

.logo-mark {
    width: 58px;
    height: 58px;
    border-radius: 18px;
    display: grid;
    place-items: center;
    background:
        linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)),
        radial-gradient(circle at top, rgba(243,211,123,0.25), transparent 60%);
    border: 1px solid rgba(214,168,79,0.45);
    box-shadow:
        0 12px 30px rgba(0,0,0,0.35),
        0 0 24px rgba(214,168,79,0.12);
    color: white;
    font-weight: 900;
    font-size: 30px;
    line-height: 1;
}

.logo-mark span {
    background: linear-gradient(180deg, #ffffff, #d6a84f);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.brand-text h1 {
    margin: 0;
    font-size: 22px;
    font-weight: 900;
    letter-spacing: 0.4px;
}

.brand-text p {
    margin: 3px 0 0;
    color: var(--text-muted);
    font-size: 12px;
    line-height: 1.6;
}

.side-card {
    position: relative;
    padding: 18px;
    border-radius: 22px;
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(255,255,255,0.07);
    margin-bottom: 16px;
}

.side-card.gold {
    border-color: rgba(214,168,79,0.35);
    background:
        radial-gradient(circle at top right, rgba(214,168,79,0.13), transparent 45%),
        rgba(255,255,255,0.04);
}

.side-label {
    color: var(--gold-2);
    font-size: 12px;
    font-weight: 800;
    margin-bottom: 8px;
}

.side-title {
    margin: 0;
    font-size: 22px;
    font-weight: 900;
    line-height: 1.35;
}

.side-text {
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.8;
    margin: 8px 0 0;
}

.side-list {
    display: grid;
    gap: 12px;
    margin-top: 16px;
}

.side-item {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--text-soft);
    font-size: 13px;
}

.side-icon {
    width: 32px;
    height: 32px;
    border-radius: 12px;
    display: grid;
    place-items: center;
    border: 1px solid rgba(214,168,79,0.28);
    color: var(--gold-2);
    background: rgba(214,168,79,0.07);
    flex-shrink: 0;
}

.mini-cta {
    margin-top: 18px;
    width: 100%;
    border: none;
    border-radius: 16px;
    background: linear-gradient(135deg, var(--gold-2), var(--gold));
    color: #111827;
    font-family: "Cairo", Arial, sans-serif;
    font-weight: 900;
    font-size: 14px;
    padding: 13px 14px;
    cursor: pointer;
    box-shadow: 0 12px 28px rgba(214,168,79,0.22);
}

.main-chat {
    display: flex;
    flex-direction: column;
    min-width: 0;
    height: 100%;
    overflow: hidden;
}

.chat-header {
    min-height: 92px;
    padding: 18px 22px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    border-bottom: 1px solid rgba(214,168,79,0.26);
    background:
        radial-gradient(circle at top left, rgba(214,168,79,0.09), transparent 35%),
        linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.015));
    flex-shrink: 0;
}

.header-title {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
}

.header-logo {
    width: 52px;
    height: 52px;
    border-radius: 17px;
    display: grid;
    place-items: center;
    border: 1px solid rgba(214,168,79,0.45);
    background: rgba(255,255,255,0.045);
    box-shadow: 0 10px 24px rgba(0,0,0,0.25);
    flex-shrink: 0;
    font-size: 26px;
    font-weight: 900;
}

.header-logo span {
    background: linear-gradient(180deg, #ffffff, #d6a84f);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.header-copy h2 {
    margin: 0;
    font-size: 21px;
    font-weight: 900;
}

.header-copy p {
    margin: 4px 0 0;
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.5;
}

.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 9px;
    padding: 10px 13px;
    border-radius: 999px;
    background: rgba(34,197,94,0.10);
    border: 1px solid rgba(34,197,94,0.24);
    color: #bbf7d0;
    font-size: 12px;
    font-weight: 800;
    white-space: nowrap;
}

.status-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 0 6px rgba(34,197,94,0.16);
}

.messages-wrap {
    flex: 1;
    min-height: 0;
    position: relative;
    display: flex;
    flex-direction: column;
    background:
        radial-gradient(circle at 85% 15%, rgba(214,168,79,0.06), transparent 34%),
        radial-gradient(circle at 12% 88%, rgba(34,197,94,0.04), transparent 28%);
    overflow: hidden;
}

.messages {
    flex: 1;
    min-height: 0;
    overflow-y: scroll;
    overflow-x: hidden;
    padding: 22px;
    scroll-behavior: smooth;
    scrollbar-width: thin;
    scrollbar-color: rgba(214,168,79,0.55) rgba(255,255,255,0.06);
}

.messages::-webkit-scrollbar {
    width: 11px;
}

.messages::-webkit-scrollbar-track {
    background: rgba(255,255,255,0.05);
    border-radius: 999px;
}

.messages::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, rgba(243,211,123,0.75), rgba(214,168,79,0.35));
    border-radius: 999px;
    border: 2px solid rgba(7,10,18,0.85);
}

.welcome-card {
    margin-bottom: 20px;
    padding: 18px;
    border-radius: 24px;
    background:
        linear-gradient(145deg, rgba(255,255,255,0.055), rgba(255,255,255,0.025));
    border: 1px solid rgba(214,168,79,0.24);
    box-shadow: 0 18px 40px rgba(0,0,0,0.18);
}

.welcome-title {
    margin: 0;
    color: #ffffff;
    font-size: 18px;
    font-weight: 900;
}

.welcome-text {
    margin: 8px 0 0;
    color: var(--text-soft);
    font-size: 14px;
    line-height: 1.9;
}

.quick-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 14px;
}

.quick-chip {
    border: 1px solid rgba(214,168,79,0.35);
    color: var(--gold-2);
    background: rgba(214,168,79,0.07);
    border-radius: 999px;
    padding: 9px 12px;
    font-family: "Cairo", Arial, sans-serif;
    font-size: 12px;
    font-weight: 800;
    cursor: pointer;
}

.msg-row {
    display: flex;
    margin-bottom: 14px;
}

.msg-row.user-row {
    justify-content: flex-start;
}

.msg-row.bot-row {
    justify-content: flex-end;
}

.msg-bubble {
    max-width: min(82%, 720px);
    padding: 14px 16px;
    border-radius: 18px;
    line-height: 1.9;
    font-size: 15px;
    overflow-wrap: break-word;
    word-wrap: break-word;
    white-space: normal;
    box-shadow: 0 10px 26px rgba(0,0,0,0.22);
}

.user {
    background:
        linear-gradient(145deg, rgba(255,255,255,0.08), rgba(255,255,255,0.035));
    border: 1px solid rgba(214,168,79,0.30);
    color: var(--text-main);
    border-bottom-right-radius: 7px;
}

.bot {
    background:
        linear-gradient(145deg, rgba(22,163,74,0.95), rgba(21,128,61,0.95));
    border: 1px solid rgba(255,255,255,0.09);
    color: white;
    border-bottom-left-radius: 7px;
}

.bot a {
    color: #ffffff;
    font-weight: 900;
    text-decoration: underline;
    word-break: break-all;
}

.meta-line {
    margin-top: 8px;
    color: rgba(255,255,255,0.65);
    font-size: 11px;
}

.user .meta-line {
    color: rgba(203,213,225,0.68);
}

.typing-wrap {
    display: none;
    padding: 0 22px 14px;
    flex-shrink: 0;
}

.typing {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-radius: 999px;
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(214,168,79,0.24);
    color: var(--text-soft);
    font-size: 13px;
    font-weight: 700;
}

.typing-dots {
    display: inline-flex;
    gap: 5px;
}

.typing-dots span {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--gold-2);
    animation: pulseDot 1.2s infinite ease-in-out;
}

.typing-dots span:nth-child(2) { animation-delay: 0.15s; }
.typing-dots span:nth-child(3) { animation-delay: 0.30s; }

@keyframes pulseDot {
    0%, 80%, 100% { opacity: 0.35; transform: translateY(0) scale(0.9); }
    40% { opacity: 1; transform: translateY(-3px) scale(1); }
}

.chat-footer {
    padding: 18px 22px 20px;
    border-top: 1px solid rgba(255,255,255,0.07);
    background:
        linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.04));
    flex-shrink: 0;
}

.composer {
    display: flex;
    align-items: flex-end;
    gap: 12px;
    padding: 10px;
    border-radius: 22px;
    background: rgba(255,255,255,0.045);
    border: 1px solid rgba(214,168,79,0.30);
    box-shadow: 0 12px 34px rgba(0,0,0,0.18);
}

.input-area {
    flex: 1;
    min-width: 0;
}

textarea {
    width: 100%;
    min-height: 54px;
    max-height: 150px;
    resize: none;
    border: none;
    outline: none;
    background: transparent;
    color: var(--text-main);
    font-family: "Cairo", Arial, sans-serif;
    font-size: 15px;
    line-height: 1.8;
    padding: 9px 10px;
}

textarea::placeholder {
    color: #94a3b8;
}

.send-btn {
    width: 58px;
    height: 58px;
    border: none;
    border-radius: 18px;
    background: linear-gradient(145deg, var(--gold-2), var(--gold));
    color: #111827;
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: 0 14px 32px rgba(214,168,79,0.28);
    transition: 0.18s ease;
    flex-shrink: 0;
    font-size: 22px;
    font-weight: 900;
}

.send-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 18px 38px rgba(214,168,79,0.36);
}

.send-btn:disabled {
    opacity: 0.58;
    cursor: not-allowed;
    transform: none;
}

.footer-note {
    margin-top: 10px;
    color: rgba(148,163,184,0.9);
    font-size: 11px;
    text-align: center;
}

@media (max-width: 860px) {
    .page {
        padding: 0;
    }

    .chat-shell {
        width: 100%;
        height: 100vh;
        min-height: 100vh;
        border-radius: 0;
        grid-template-columns: 1fr;
        border: none;
    }

    .sidebar {
        display: none;
    }

    .chat-header {
        min-height: 78px;
        padding: 14px 14px;
    }

    .header-logo {
        width: 46px;
        height: 46px;
        border-radius: 15px;
        font-size: 23px;
    }

    .header-copy h2 {
        font-size: 18px;
    }

    .header-copy p {
        font-size: 12px;
    }

    .status-pill {
        display: none;
    }

    .messages {
        padding: 14px;
    }

    .msg-bubble {
        max-width: 92%;
        font-size: 14px;
        line-height: 1.85;
    }

    .chat-footer {
        padding: 12px;
    }

    .composer {
        border-radius: 18px;
        gap: 8px;
        padding: 8px;
    }

    textarea {
        min-height: 50px;
        font-size: 14px;
    }

    .send-btn {
        width: 52px;
        height: 52px;
        border-radius: 16px;
        font-size: 20px;
    }

    .welcome-card {
        padding: 15px;
        border-radius: 20px;
    }

    .welcome-title {
        font-size: 16px;
    }

    .welcome-text {
        font-size: 13px;
    }
}
</style>
</head>

<body>
<div class="luxury-bg"></div>

<div class="page">
    <div class="chat-shell">

        <aside class="sidebar">
            <div class="brand-block">
                <div class="logo-mark"><span>A</span></div>
                <div class="brand-text">
                    <h1>ALSAAB AI</h1>
                    <p>Smart Sales Assistant</p>
                </div>
            </div>

            <div class="side-card gold">
                <div class="side-label">نظام مبيعات ذكي</div>
                <h2 class="side-title">أقوى نظام مبيعات ذكي يرفع المبيعات بشكل صاروخي 🚀</h2>
                <p class="side-text">
                    مساعد مبيعات ذكي، يفهم و يحلل العميل و يشخّص و يحل المشكلة و يساعدك في إغلاق الصفقات و اتخاذ القرار مع العملاء.
                </p>

                <div class="side-list">
                    <div class="side-item">
                        <div class="side-icon">⚡</div>
                        <span>ردود ذكية وسريعة</span>
                    </div>
                    <div class="side-item">
                        <div class="side-icon">🎯</div>
                        <span>بيع وإقناع وإغلاق</span>
                    </div>
                    <div class="side-item">
                        <div class="side-icon">📈</div>
                        <span>مصمم لزيادة المبيعات</span>
                    </div>
                </div>

                <button class="mini-cta" onclick="sendQuick('أبغي أعرف الباقات')">
                    عرض الباقات
                </button>
            </div>

            <div class="side-card">
                <div class="side-label">الوضع الحالي</div>
                <p class="side-text">
                    اكتب رسالتك، والبوت بيساعدك تفهم أفضل خطوة لمشروعك أو دخلك.
                </p>
            </div>
        </aside>

        <main class="main-chat">
            <header class="chat-header">
                <div class="header-title">
                    <div class="header-logo"><span>A</span></div>
                    <div class="header-copy">
                        <h2>ALSAAB AI</h2>
                        <p>مساعدك الذكي للمبيعات، الرد، الإقناع، والإغلاق</p>
                    </div>
                </div>

                <div class="status-pill">
                    <span class="status-dot"></span>
                    <span>Online 24/7</span>
                </div>
            </header>

            <section class="messages-wrap">
                <div id="messages" class="messages">
                    <div class="welcome-card">
                        <h3 class="welcome-title">هلا وسهلا 👋</h3>
                        <p class="welcome-text">
                            أنا ALSAAB AI. أقدر أساعدك في زيادة المبيعات، اختيار الباقة المناسبة،
                            تدريب البوت لمشروعك، أو معرفة نظام الشراكة والدخل الإضافي.
                        </p>

                        <div class="quick-actions">
                            <button class="quick-chip" onclick="sendQuick('أبغي أعرف الباقات')">عرض الباقات</button>
                            <button class="quick-chip" onclick="sendQuick('تدريب البوت')">تدريب البوت</button>
                            <button class="quick-chip" onclick="sendQuick('عندي مشروع وأبغي أرفع المبيعات')">عندي مشروع</button>
                            <button class="quick-chip" onclick="sendQuick('محتاج دخل إضافي')">دخل إضافي</button>
                        </div>
                    </div>
                </div>

                <div id="typingWrap" class="typing-wrap">
                    <div class="typing">
                        <div class="typing-dots">
                            <span></span><span></span><span></span>
                        </div>
                        <strong>ALSAAB AI يكتب الآن...</strong>
                    </div>
                </div>
            </section>

            <footer class="chat-footer">
                <div class="composer">
                    <div class="input-area">
                        <textarea id="msg" placeholder="اكتب رسالتك هنا..."></textarea>
                    </div>
                    <button id="sendBtn" class="send-btn" onclick="sendMsg()" title="إرسال">➤</button>
                </div>

                <div class="footer-note">
                    Powered by ALSAAB AI • Sales Automation
                </div>
            </footer>
        </main>

    </div>
</div>

<script>
let sessionId = localStorage.getItem("session_id");
let isSending = false;

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

function currentTime() {
    const now = new Date();

    return now.toLocaleTimeString("ar-AE", {
        hour: "numeric",
        minute: "2-digit"
    });
}

function scrollToBottom() {
    const box = document.getElementById("messages");

    if (!box) return;

    requestAnimationFrame(function() {
        box.scrollTop = box.scrollHeight;

        setTimeout(function() {
            box.scrollTop = box.scrollHeight;
        }, 80);

        setTimeout(function() {
            box.scrollTop = box.scrollHeight;
        }, 250);
    });
}

function addMsg(text, type) {
    const box = document.getElementById("messages");

    const row = document.createElement("div");
    row.className = "msg-row " + (type === "bot" ? "bot-row" : "user-row");

    const div = document.createElement("div");
    div.className = "msg-bubble " + type;

    if (type === "bot") {
        div.innerHTML = linkify(text) + '<div class="meta-line">' + currentTime() + '</div>';
    } else {
        div.innerHTML = escapeHtml(text).replace(/\n/g, "<br>") + '<div class="meta-line">' + currentTime() + '</div>';
    }

    row.appendChild(div);
    box.appendChild(row);
    scrollToBottom();
}

function showTyping(show) {
    const typingWrap = document.getElementById("typingWrap");

    typingWrap.style.display = show ? "block" : "none";
    scrollToBottom();
}

function sendQuick(text) {
    const input = document.getElementById("msg");
    input.value = text;
    sendMsg();
}

async function sendMsg() {
    if (isSending) return;

    const input = document.getElementById("msg");
    const button = document.getElementById("sendBtn");
    const text = input.value.trim();

    if (!text) return;

    isSending = true;
    button.disabled = true;

    addMsg(text, "user");
    input.value = "";
    input.style.height = "54px";
    showTyping(true);

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                message: text,
                session_id: sessionId
            })
        });

        const data = await res.json();

        sessionId = data.session_id;
        localStorage.setItem("session_id", sessionId);

        showTyping(false);
        addMsg(data.reply, "bot");
        scrollToBottom();

    } catch (error) {
        showTyping(false);
        addMsg("صار خطأ مؤقت في الاتصال. جرّب مرة ثانية.", "bot");
        console.error(error);
    }

    isSending = false;
    button.disabled = false;
    input.focus();
}

const textarea = document.getElementById("msg");

textarea.addEventListener("input", function() {
    this.style.height = "54px";
    this.style.height = Math.min(this.scrollHeight, 150) + "px";
});

textarea.addEventListener("keydown", function(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMsg();
    }
});

window.addEventListener("load", function() {
    textarea.focus();
    scrollToBottom();
});
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
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)