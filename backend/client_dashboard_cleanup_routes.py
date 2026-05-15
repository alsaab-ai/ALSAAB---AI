from flask import request


def register_client_dashboard_cleanup_routes(app):
    if getattr(app, "alsaab_client_dashboard_cleanup_registered", False):
        return

    app.alsaab_client_dashboard_cleanup_registered = True

    def client_dashboard_cleanup_injector(response):
        try:
            if request.path != "/client-dashboard":
                return response

            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_CLIENT_DASHBOARD_CLEANUP_V1" in html:
                return response

            cleanup = r'''
<!-- ALSAAB_CLIENT_DASHBOARD_CLEANUP_V1 START -->
<script>
(function(){
  try{
    function textOf(el){
      return (el && el.innerText ? el.innerText : "").trim();
    }

    function isSmartLinkSection(el){
      var t = textOf(el);
      return (
        t.indexOf("مدخل واتساب الذكي") !== -1 ||
        t.indexOf("رابط موظف المبيعات الذكي") !== -1 ||
        t.indexOf("موظف المبيعات الذكي") !== -1 && t.indexOf("نسخ رسالة واتساب") !== -1
      );
    }

    function shouldHideOldWhatsAppSetup(el){
      var t = textOf(el);

      if(!t) return false;
      if(isSmartLinkSection(el)) return false;

      var oldPhrases = [
        "طلب ربط WhatsApp",
        "طلبات ربط WhatsApp",
        "طلب ربط واتساب",
        "طلبات ربط واتساب",
        "ربط WhatsApp",
        "ربط واتساب",
        "WhatsApp setup request",
        "WhatsApp setup",
        "whatsapp setup"
      ];

      var hasOldPhrase = oldPhrases.some(function(p){
        return t.toLowerCase().indexOf(p.toLowerCase()) !== -1;
      });

      if(!hasOldPhrase) return false;

      var newPhrases = [
        "مدخل واتساب الذكي",
        "الرابط الذكي",
        "رسالة واتساب جاهزة",
        "نسخ رسالة واتساب",
        "واتساب بزنس"
      ];

      var hasNewPhrase = newPhrases.some(function(p){
        return t.indexOf(p) !== -1;
      });

      return !hasNewPhrase;
    }

    function hideOldWhatsAppSetup(){
      var candidates = Array.prototype.slice.call(
        document.querySelectorAll("section, article, .card, .box, .panel, form, div, a, button")
      );

      candidates.forEach(function(el){
        if(!shouldHideOldWhatsAppSetup(el)) return;

        var target = el;

        var parent = el;
        for(var i=0;i<5;i++){
          if(!parent || !parent.parentElement) break;

          var pt = textOf(parent);
          if(
            pt.length < 900 &&
            shouldHideOldWhatsAppSetup(parent) &&
            !isSmartLinkSection(parent)
          ){
            target = parent;
          }

          parent = parent.parentElement;
        }

        target.style.display = "none";
        target.setAttribute("data-alsaab-hidden-old-whatsapp-setup", "1");
      });
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", function(){
        setTimeout(hideOldWhatsAppSetup, 300);
        setTimeout(hideOldWhatsAppSetup, 1200);
      });
    }else{
      setTimeout(hideOldWhatsAppSetup, 300);
      setTimeout(hideOldWhatsAppSetup, 1200);
    }
  }catch(e){}
})();
</script>
<!-- ALSAAB_CLIENT_DASHBOARD_CLEANUP_V1 END -->
'''

            if "</body>" in html:
                html = html.replace("</body>", cleanup + "\n</body>", 1)
                response.set_data(html)

            return response

        except Exception as error:
            print(f"CLIENT DASHBOARD CLEANUP ERROR ❌ {error}", flush=True)
            return response

    app.after_request(client_dashboard_cleanup_injector)
