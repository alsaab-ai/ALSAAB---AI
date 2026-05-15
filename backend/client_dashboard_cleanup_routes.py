from flask import request


def register_client_dashboard_cleanup_routes(app):
    if getattr(app, "alsaab_client_dashboard_cleanup_registered", False):
        return

    app.alsaab_client_dashboard_cleanup_registered = True

    def client_dashboard_targeted_cleanup(response):
        try:
            if request.path != "/client-dashboard":
                return response

            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_CLIENT_DASHBOARD_TARGETED_CLEANUP_V3" in html:
                return response

            cleanup = r'''
<!-- ALSAAB_CLIENT_DASHBOARD_TARGETED_CLEANUP_V3 START -->
<script>
(function(){
  try{
    if(window.__ALSAAB_CLIENT_DASHBOARD_TARGETED_CLEANUP_V3__) return;
    window.__ALSAAB_CLIENT_DASHBOARD_TARGETED_CLEANUP_V3__ = true;

    function textOf(el){
      return (el && el.innerText ? el.innerText : "").trim();
    }

    function hasAny(text, items){
      text = String(text || "");
      return items.some(function(item){
        return text.indexOf(item) !== -1;
      });
    }

    function hasAll(text, items){
      text = String(text || "");
      return items.every(function(item){
        return text.indexOf(item) !== -1;
      });
    }

    function isProtectedNewSection(text){
      return hasAny(text, [
        "مدخل واتساب الذكي",
        "أداء مدخل واتساب الذكي",
        "رابط موظف المبيعات الذكي",
        "نسخ رسالة واتساب",
        "طريقة تركيب الرسالة في واتساب بزنس",
        "طلب إلغاء الاشتراك",
        "ترقية الباقة"
      ]);
    }

    function hideOldWhatsAppSetupCard(){
      var candidates = Array.prototype.slice.call(
        document.querySelectorAll("section, article, form, div")
      );

      var best = null;
      var bestLen = 999999;

      candidates.forEach(function(el){
        if(!el || el.tagName === "BODY" || el.tagName === "HTML") return;

        var t = textOf(el);
        if(!t) return;

        if(isProtectedNewSection(t)) return;

        var looksLikeOldSetup =
          hasAll(t, ["إعداد WhatsApp", "رقم WhatsApp Business الحالي"]) ||
          hasAll(t, ["إعداد WhatsApp", "ملاحظات الربط"]) ||
          hasAll(t, ["رقم WhatsApp Business الحالي", "ملاحظات الربط"]);

        if(!looksLikeOldSetup) return;

        // لا نخفي حاوية ضخمة فيها نصف الداشبورد.
        if(t.length > 9000) return;

        if(t.length < bestLen){
          best = el;
          bestLen = t.length;
        }
      });

      if(best){
        best.style.display = "none";
        best.setAttribute("data-alsaab-hidden-old-whatsapp-setup", "1");
      }
    }

    function hideOldWhatsAppButtonsOnly(){
      var buttons = Array.prototype.slice.call(
        document.querySelectorAll("a, button")
      );

      buttons.forEach(function(el){
        var t = textOf(el);
        if(!t) return;

        if(isProtectedNewSection(textOf(el.parentElement || el))) return;

        var oldButton =
          t === "فتح طلبات ربط WhatsApp" ||
          t === "طلبات ربط WhatsApp" ||
          t === "طلب ربط WhatsApp" ||
          t === "فتح طلبات ربط واتساب" ||
          t === "طلبات ربط واتساب" ||
          t === "طلب ربط واتساب";

        if(oldButton){
          el.style.display = "none";
          el.setAttribute("data-alsaab-hidden-old-whatsapp-button", "1");
        }
      });
    }

    function runCleanup(){
      hideOldWhatsAppSetupCard();
      hideOldWhatsAppButtonsOnly();
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", function(){
        setTimeout(runCleanup, 300);
        setTimeout(runCleanup, 1200);
        setTimeout(runCleanup, 2500);
      });
    }else{
      setTimeout(runCleanup, 300);
      setTimeout(runCleanup, 1200);
      setTimeout(runCleanup, 2500);
    }

    try{
      var observer = new MutationObserver(function(){
        setTimeout(runCleanup, 200);
      });

      observer.observe(document.body, {
        childList:true,
        subtree:true
      });
    }catch(e){}
  }catch(e){}
})();
</script>
<!-- ALSAAB_CLIENT_DASHBOARD_TARGETED_CLEANUP_V3 END -->
'''

            if "</body>" in html:
                html = html.replace("</body>", cleanup + "\n</body>", 1)
                response.set_data(html)

            return response

        except Exception as error:
            print(f"CLIENT DASHBOARD TARGETED CLEANUP ERROR ❌ {error}", flush=True)
            return response

    app.after_request(client_dashboard_targeted_cleanup)
