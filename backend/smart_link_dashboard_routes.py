from flask import request
import os


def register_smart_link_dashboard_routes(app):
    if getattr(app, "alsaab_smart_link_dashboard_registered", False):
        return

    app.alsaab_smart_link_dashboard_registered = True

    def smart_link_client_dashboard_injector(response):
        try:
            if request.path != "/client-dashboard":
                return response

            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_SMART_LINK_CLIENT_DASHBOARD_UI_V1" in html:
                return response

            public_base_url = (
                os.getenv("SMART_LINK_PUBLIC_BASE_URL")
                or "https://alsaab.io"
            ).rstrip("/")

            section = '''
<!-- ALSAAB_SMART_LINK_CLIENT_DASHBOARD_UI_V1 START -->
<div id="alsaabSmartLinkDashboardSection" class="alsaab-smart-link-dashboard" dir="rtl">
  <h2>مدخل واتساب الذكي</h2>
  <p>
    هذا الرابط تستخدمه داخل الرد الآلي في واتساب بزنس. أي شخص يضغط الرابط سيدخل إلى موظف المبيعات الذكي المرتبط بحسابك.
  </p>

  <div class="alsaab-smart-link-alert">
    واتساب هنا يكون مدخل للزائر، والمحادثة والبيع تتم داخل موقع الصعب حتى نتجنب مشاكل ربط واتساب المباشر.
  </div>

  <label>رابط موظف المبيعات الذكي</label>
  <div class="alsaab-smart-link-row">
    <input id="alsaabSmartLinkValue" readonly value="جاري تجهيز الرابط...">
    <button type="button" id="alsaabCopySmartLinkBtn">نسخ الرابط</button>
    <button type="button" id="alsaabTestSmartLinkBtn">اختبار الرابط</button>
  </div>

  <label>رسالة واتساب جاهزة للرد الآلي</label>
  <textarea id="alsaabSmartLinkMessage" readonly>جاري تجهيز الرسالة...</textarea>

  <div class="alsaab-smart-link-actions">
    <button type="button" id="alsaabCopySmartMessageBtn">نسخ رسالة واتساب</button>
  </div>

  <div class="alsaab-smart-link-steps">
    <h3>طريقة تركيب الرسالة في واتساب بزنس</h3>
    <ol>
      <li>افتح تطبيق واتساب بزنس.</li>
      <li>ادخل إلى أدوات النشاط التجاري.</li>
      <li>افتح رسالة الترحيب أو رسالة خارج أوقات العمل.</li>
      <li>فعّل الرسالة.</li>
      <li>الصق الرسالة الجاهزة الموجودة فوق.</li>
      <li>احفظ الإعدادات.</li>
    </ol>
  </div>

  <div id="alsaabSmartLinkStatus" class="alsaab-smart-link-status"></div>
</div>

<style>
.alsaab-smart-link-dashboard{
  max-width:1100px;
  margin:22px auto;
  padding:22px;
  background:#111;
  border:1px solid rgba(215,184,90,.45);
  border-radius:22px;
  color:#f5f0df;
  font-family:Arial,Tahoma,sans-serif;
}

.alsaab-smart-link-dashboard h2{
  color:#d7b85a;
  margin-top:0;
  font-size:28px;
  font-weight:900;
}

.alsaab-smart-link-dashboard p{
  color:#d8cfad;
  line-height:1.8;
}

.alsaab-smart-link-alert{
  margin:14px 0;
  padding:14px;
  border:1px solid rgba(215,184,90,.25);
  border-radius:14px;
  background:#0b0b0b;
  color:#e8dfc2;
  line-height:1.8;
}

.alsaab-smart-link-dashboard label{
  display:block;
  margin-top:14px;
  margin-bottom:7px;
  color:#d7b85a;
  font-weight:900;
}

.alsaab-smart-link-row{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
}

.alsaab-smart-link-dashboard input,
.alsaab-smart-link-dashboard textarea{
  width:100%;
  box-sizing:border-box;
  background:#0b0b0b;
  color:#fff;
  border:1px solid rgba(215,184,90,.35);
  border-radius:14px;
  padding:12px;
  outline:none;
  font-size:14px;
}

.alsaab-smart-link-row input{
  flex:1;
  min-width:280px;
}

.alsaab-smart-link-dashboard textarea{
  min-height:150px;
  line-height:1.8;
  resize:vertical;
}

.alsaab-smart-link-dashboard button{
  border:1px solid rgba(215,184,90,.75);
  background:linear-gradient(135deg,#d7b85a,#a88425);
  color:#0b0b0b;
  border-radius:999px;
  padding:12px 18px;
  font-weight:900;
  cursor:pointer;
}

.alsaab-smart-link-actions{
  margin-top:12px;
}

.alsaab-smart-link-steps{
  margin-top:18px;
  padding:16px;
  border-radius:16px;
  background:#0b0b0b;
  border:1px solid rgba(255,255,255,.08);
}

.alsaab-smart-link-steps h3{
  color:#d7b85a;
  margin-top:0;
}

.alsaab-smart-link-steps li{
  margin:7px 0;
  color:#e8dfc2;
}

.alsaab-smart-link-status{
  margin-top:12px;
  color:#f0cc68;
  font-weight:800;
}

@media(max-width:720px){
  .alsaab-smart-link-row{
    flex-direction:column;
  }

  .alsaab-smart-link-row input{
    min-width:100%;
  }
}
</style>

<script>
(function(){
  try{
    var publicBaseUrl = "__PUBLIC_BASE_URL__";
    var section = document.getElementById("alsaabSmartLinkDashboardSection");
    if(!section) return;

    function findPartnerId(){
      var text = document.body.innerText || "";
      var match = text.match(/ALS-P\\d{5,}/i);
      if(match && match[0]) return match[0].toUpperCase();
      return "";
    }

    function copyText(value, statusText){
      try{
        if(navigator.clipboard && navigator.clipboard.writeText){
          navigator.clipboard.writeText(value || "");
        }else{
          var temp = document.createElement("textarea");
          temp.value = value || "";
          document.body.appendChild(temp);
          temp.select();
          document.execCommand("copy");
          document.body.removeChild(temp);
        }

        var status = document.getElementById("alsaabSmartLinkStatus");
        if(status) status.innerText = statusText || "تم النسخ ✅";
      }catch(e){
        var status2 = document.getElementById("alsaabSmartLinkStatus");
        if(status2) status2.innerText = "تعذر النسخ، انسخ النص يدوياً.";
      }
    }

    function build(){
      var partnerId = findPartnerId();
      var linkInput = document.getElementById("alsaabSmartLinkValue");
      var messageBox = document.getElementById("alsaabSmartLinkMessage");

      if(!partnerId){
        if(linkInput) linkInput.value = "تعذر العثور على معرف الحساب.";
        if(messageBox) messageBox.value = "تعذر تجهيز الرسالة لأن معرف الحساب غير ظاهر في الصفحة.";
        return;
      }

      var smartLink = publicBaseUrl + "/?ref=" + encodeURIComponent(partnerId) + "&src=wa";

      var msg =
"هلا وسهلا 👋\\n\\n" +
"أهلاً بك، عشان نخدمك بسرعة وبأفضل طريقة، اضغط الرابط وتكلم مباشرة مع موظف المبيعات الذكي:\\n" +
smartLink + "\\n\\n" +
"بيفهم طلبك، يرشح لك الأنسب، يجاوب على أسئلتك، ويرسل لك رابط الدفع إذا كنت جاهز.\\n\\n" +
"وإذا احتجت شخص من الفريق، تقدر تطلب التحدث مع شخص من داخل المحادثة.";

      if(linkInput) linkInput.value = smartLink;
      if(messageBox) messageBox.value = msg;

      var copyLink = document.getElementById("alsaabCopySmartLinkBtn");
      var copyMsg = document.getElementById("alsaabCopySmartMessageBtn");
      var testBtn = document.getElementById("alsaabTestSmartLinkBtn");

      if(copyLink){
        copyLink.onclick = function(){
          copyText(smartLink, "تم نسخ الرابط ✅");
        };
      }

      if(copyMsg){
        copyMsg.onclick = function(){
          copyText(msg, "تم نسخ رسالة واتساب ✅");
        };
      }

      if(testBtn){
        testBtn.onclick = function(){
          window.open(smartLink, "_blank");
        };
      }
    }

    function moveUnderWhatsApp(){
      var candidates = Array.prototype.slice.call(document.querySelectorAll("div,section,article"));
      var target = null;

      for(var i=0;i<candidates.length;i++){
        var t = (candidates[i].innerText || "").trim();

        if(
          candidates[i].contains(section) ||
          t.indexOf("مدخل واتساب الذكي") !== -1
        ){
          continue;
        }

        if(
          t.indexOf("WhatsApp") !== -1 ||
          t.indexOf("واتساب") !== -1 ||
          t.indexOf("طلبات ربط") !== -1
        ){
          target = candidates[i];
          break;
        }
      }

      if(target && target.parentNode){
        target.parentNode.insertBefore(section, target.nextSibling);
      }
    }

    build();
    setTimeout(moveUnderWhatsApp, 500);
  }catch(e){}
})();
</script>
<!-- ALSAAB_SMART_LINK_CLIENT_DASHBOARD_UI_V1 END -->
            '''.replace("__PUBLIC_BASE_URL__", public_base_url)

            if "</body>" in html:
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)

            return response

        except Exception as error:
            print(f"SMART LINK DASHBOARD UI ERROR ❌ {error}", flush=True)
            return response

    app.after_request(smart_link_client_dashboard_injector)
