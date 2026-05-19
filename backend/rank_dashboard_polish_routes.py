from flask import request


def register_rank_dashboard_polish_routes(app):
    if getattr(app, "alsaab_rank_dashboard_polish_registered", False):
        return

    app.alsaab_rank_dashboard_polish_registered = True

    def rank_dashboard_polish_injector(response):
        try:
            if response.direct_passthrough:
                return response

            if request.path not in ["/client-dashboard", "/partner-dashboard"]:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_RANK_DASHBOARD_POLISH_V1" in html:
                return response

            script = r'''
<!-- ALSAAB_RANK_DASHBOARD_POLISH_V1 START -->
<script>
(function(){
  try{
    if(window.__ALSAAB_RANK_DASHBOARD_POLISH_V1__) return;
    window.__ALSAAB_RANK_DASHBOARD_POLISH_V1__ = true;

    function textOf(el){
      return (el && el.innerText ? el.innerText : "").trim();
    }

    function containsAny(text, items){
      text = String(text || "");
      return items.some(function(item){
        return text.indexOf(item) !== -1;
      });
    }

    function containsAll(text, items){
      text = String(text || "");
      return items.every(function(item){
        return text.indexOf(item) !== -1;
      });
    }

    function hideOldLevelUpgradeBox(){
      var rankSection = document.getElementById("alsaabRankDashboardSection");
      var candidates = Array.prototype.slice.call(document.querySelectorAll("section, article, div"));

      candidates.forEach(function(el){
        if(!el || el.id === "alsaabRankDashboardSection") return;

        if(rankSection && (rankSection.contains(el) || el.contains(rankSection))) return;

        var t = textOf(el);
        if(!t) return;

        var oldSection =
          t.indexOf("المستوى والترقية") !== -1 ||
          containsAll(t, ["Completed Sales", "Required Sales", "Current Package"]) ||
          containsAll(t, ["Commission Eligible", "Required Course", "Missing Requirements"]) ||
          containsAll(t, ["Upgrade package to:", "Need", "Missing courses"]);

        if(!oldSection) return;

        if(t.length > 15000) return;

        el.style.setProperty("display", "none", "important");
        el.setAttribute("data-alsaab-hidden-old-level-upgrade", "1");
      });
    }

    function parseLevel(){
      var levelEl = document.getElementById("alsaabRankLevel");
      var titleEl = document.getElementById("alsaabRankTitle");

      var text = (textOf(levelEl) + " " + textOf(titleEl)).trim();

      var match = text.match(/Level\s*([0-9]+)/i);
      if(match) return parseInt(match[1], 10) || 1;

      if(text.indexOf("شريك مباشر") !== -1) return 1;
      if(text.indexOf("شريك البداية") !== -1) return 2;
      if(text.indexOf("شريك متقدم") !== -1) return 3;
      if(text.indexOf("شريك النمو") !== -1) return 4;
      if(text.indexOf("شريك النخبة") !== -1) return 5;

      return 1;
    }

    function cumulativeCommission(level){
      var map = {
        1: 25,
        2: 30,
        3: 34,
        4: 37,
        5: 39
      };

      return map[level] || 25;
    }

    function rankColor(level){
      var map = {
        1: {name:"برونزي", color:"#CD7F32"},
        2: {name:"فضي", color:"#C0C0C0"},
        3: {name:"ذهبي", color:"#D7B85A"},
        4: {name:"بلاتيني", color:"#E5E4E2"},
        5: {name:"ماسي", color:"#B9F2FF"}
      };

      return map[level] || map[1];
    }

    function hexToRgba(hex, alpha){
      hex = String(hex || "#D7B85A").replace("#","");
      if(hex.length === 3){
        hex = hex.split("").map(function(x){return x+x;}).join("");
      }

      var r = parseInt(hex.substring(0,2),16);
      var g = parseInt(hex.substring(2,4),16);
      var b = parseInt(hex.substring(4,6),16);

      if(isNaN(r) || isNaN(g) || isNaN(b)){
        return "rgba(215,184,90," + alpha + ")";
      }

      return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
    }

    function polishRankSection(){
      var section = document.getElementById("alsaabRankDashboardSection");
      if(!section) return;

      var level = parseLevel();
      var rank = rankColor(level);
      var total = cumulativeCommission(level);

      var commissionEl = document.getElementById("alsaabRankCommission");
      if(commissionEl){
        commissionEl.innerText = total + "%";
        var small = commissionEl.parentElement ? commissionEl.parentElement.querySelector("small") : null;
        if(small) small.innerText = "مجموع عمولات هذا المستوى";
      }

      var nextBox = document.getElementById("alsaabNextRank");
      if(nextBox){
        var nextText = textOf(nextBox);

        if(nextText.indexOf("العمولة:") !== -1){
          var nextLevel = Math.min(level + 1, 5);
          var nextTotal = cumulativeCommission(nextLevel);

          nextBox.innerText = nextText.replace(/العمولة:\s*[0-9]+%/g, "مجموع العمولات: " + nextTotal + "%");
        }
      }

      var badge = document.getElementById("alsaabRankBadge");
      if(badge){
        badge.innerText = rank.name + " — " + textOf(document.getElementById("alsaabRankTitle"));
        badge.style.setProperty("background", rank.color, "important");
        badge.style.setProperty("border-color", rank.color, "important");
        badge.style.setProperty("color", "#111", "important");
      }

      var colorEl = document.getElementById("alsaabRankColor");
      if(colorEl){
        colorEl.innerText = rank.name;
      }

      section.style.setProperty(
        "background",
        "linear-gradient(135deg, " + hexToRgba(rank.color,.32) + " 0%, rgba(17,17,17,.96) 42%, rgba(17,17,17,1) 100%)",
        "important"
      );
      section.style.setProperty("border-color", rank.color, "important");
      section.style.setProperty("box-shadow", "0 0 32px " + hexToRgba(rank.color,.25), "important");

      var mainCard = section.querySelector(".main-rank-card");
      if(mainCard){
        mainCard.style.setProperty("border-color", rank.color, "important");
        mainCard.style.setProperty("box-shadow", "0 0 22px " + hexToRgba(rank.color,.22), "important");
        mainCard.style.setProperty("background", hexToRgba(rank.color,.12), "important");
      }
    }

    function run(){
      hideOldLevelUpgradeBox();
      polishRankSection();
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", function(){
        setTimeout(run, 300);
        setTimeout(run, 1000);
        setTimeout(run, 2500);
        setTimeout(run, 5000);
      });
    }else{
      setTimeout(run, 300);
      setTimeout(run, 1000);
      setTimeout(run, 2500);
      setTimeout(run, 5000);
    }

    try{
      var observer = new MutationObserver(function(){
        setTimeout(run, 250);
      });

      observer.observe(document.body, {
        childList:true,
        subtree:true,
        characterData:true
      });
    }catch(e){}
  }catch(e){}
})();
</script>
<!-- ALSAAB_RANK_DASHBOARD_POLISH_V1 END -->
'''

            if "</body>" in html:
                html = html.replace("</body>", script + "\n</body>", 1)
                response.set_data(html)

            return response

        except Exception as error:
            print(f"RANK DASHBOARD POLISH ERROR ❌ {error}", flush=True)
            return response

    app.after_request(rank_dashboard_polish_injector)
