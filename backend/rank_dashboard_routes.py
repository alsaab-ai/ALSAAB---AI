from flask import request, jsonify
import os
import copy
import re


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def _clean_client_rank_payload(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_lower = str(key).lower()

            if key_lower in ["max_total", "max_total_commission_percent"]:
                continue

            if key_lower == "note" and "39" in str(item):
                continue

            cleaned[key] = _clean_client_rank_payload(item)

        return cleaned

    if isinstance(value, list):
        return [_clean_client_rank_payload(item) for item in value]

    if isinstance(value, str):
        return value.replace("39%", "").replace("39٪", "")

    return value


def register_rank_dashboard_routes(app):
    if getattr(app, "alsaab_rank_dashboard_registered", False):
        return

    app.alsaab_rank_dashboard_registered = True

    def client_partner_rank_summary():
        try:
            partner_id = (
                request.args.get("partner_id")
                or request.args.get("client_id")
                or request.args.get("ref")
                or ""
            ).strip().upper()

            if not partner_id:
                return jsonify({
                    "status": "error",
                    "message": "partner_id/client_id is required"
                }), 400

            database = _db()

            result = database.post_to_google_sheet_json(
                {
                    "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                    "action": "partner_rank_summary_2026",
                    "partner_id": partner_id,
                    "client_id": partner_id,
                    "source": "client_dashboard",
                },
                label="partner_rank_summary_2026",
            )

            safe_result = _clean_client_rank_payload(copy.deepcopy(result))
            return jsonify(safe_result)

        except Exception as error:
            print(f"CLIENT PARTNER RANK SUMMARY ERROR ❌ {error}", flush=True)
            return jsonify({
                "status": "error",
                "message": str(error)
            }), 500

    def rank_dashboard_injector(response):
        try:
            if request.path not in ["/client-dashboard", "/partner-dashboard"]:
                return response

            if response.direct_passthrough:
                return response

            content_type = response.headers.get("Content-Type", "")

            if "text/html" not in content_type:
                return response

            html = response.get_data(as_text=True)

            if not html or "ALSAAB_RANK_DASHBOARD_UI_V3" in html:
                return response

            section = r'''
<!-- ALSAAB_RANK_DASHBOARD_UI_V3 START -->
<div id="alsaabRankDashboardSection" class="alsaab-rank-section" dir="rtl">
  <div class="alsaab-rank-header">
    <div>
      <h2>رتبة الشريك</h2>
      <p>هني تشوف رتبتك الحالية لونك ونواقص المستوى القادم حسب الشروط الجديدة.</p>
    </div>
    <div id="alsaabRankBadge" class="alsaab-rank-badge">جاري التحميل...</div>
  </div>

  <div class="alsaab-rank-grid">
    <div class="alsaab-rank-card main-rank-card">
      <span id="alsaabRankTitle">-</span>
      <small>الرتبة الحالية</small>
    </div>
    <div class="alsaab-rank-card">
      <span id="alsaabRankColor">-</span>
      <small>لون الرتبة</small>
    </div>
    <div class="alsaab-rank-card">
      <span id="alsaabRankLevel">-</span>
      <small>المستوى</small>
    </div>
    <div class="alsaab-rank-card">
      <span id="alsaabRankCommission">-</span>
      <small>عمولة هذا المستوى</small>
    </div>
    <div class="alsaab-rank-card">
      <span id="alsaabRankPlan">-</span>
      <small>الباقة الحالية</small>
    </div>
    <div class="alsaab-rank-card">
      <span id="alsaabRankDirect">-</span>
      <small>اشتراكات مباشرة فعالة</small>
    </div>
    <div class="alsaab-rank-card">
      <span id="alsaabRankTotal">-</span>
      <small>إجمالي الشبكة الفعال</small>
    </div>
  </div>

  <div class="alsaab-rank-next">
    <h3>المستوى القادم</h3>
    <div id="alsaabNextRank">جاري التحميل...</div>
    <div id="alsaabRankRequirements" class="alsaab-rank-requirements"></div>
  </div>

  <div class="alsaab-rank-note">
    ملاحظة: العمولات تعتمد على الاشتراكات الفعالة حالة الحساب واستكمال شروط كل مستوى. لا يوجد دخل مضمون.
  </div>
</div>

<style>
.alsaab-rank-section{
  max-width:1100px;
  margin:22px auto;
  padding:22px;
  background:#111;
  border:1px solid rgba(215,184,90,.45);
  border-radius:22px;
  color:#f5f0df;
  font-family:Arial,Tahoma,sans-serif;
  transition:background .3s ease,border-color .3s ease,box-shadow .3s ease;
}

.alsaab-rank-header{
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  gap:14px;
  margin-bottom:16px;
}

.alsaab-rank-section h2{
  margin:0;
  color:#d7b85a;
  font-size:28px;
  font-weight:900;
}

.alsaab-rank-section p{
  color:#d8cfad;
  line-height:1.8;
  margin:8px 0 0;
}

.alsaab-rank-badge{
  border:1px solid rgba(215,184,90,.65);
  color:#111;
  background:#d7b85a;
  border-radius:999px;
  padding:10px 14px;
  font-weight:900;
  white-space:nowrap;
}

.alsaab-rank-grid{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px;
  margin-top:14px;
}

.alsaab-rank-card{
  background:rgba(0,0,0,.38);
  border:1px solid rgba(215,184,90,.22);
  border-radius:16px;
  padding:16px;
  text-align:center;
}

.alsaab-rank-card span{
  display:block;
  font-size:24px;
  font-weight:900;
  color:#d7b85a;
}

.alsaab-rank-card small{
  color:#e8dfc2;
}

.main-rank-card{
  border-width:2px;
}

.alsaab-rank-next{
  margin-top:18px;
  background:rgba(0,0,0,.38);
  border:1px solid rgba(255,255,255,.08);
  border-radius:16px;
  padding:16px;
}

.alsaab-rank-next h3{
  margin-top:0;
  color:#d7b85a;
}

.alsaab-rank-requirements{
  margin-top:12px;
  display:grid;
  gap:9px;
}

.alsaab-rank-req{
  display:flex;
  justify-content:space-between;
  gap:10px;
  padding:10px 12px;
  border-radius:12px;
  background:#111;
  border:1px solid rgba(255,255,255,.08);
  line-height:1.6;
}

.alsaab-rank-req.done{
  border-color:rgba(80,220,130,.35);
  color:#caffdd;
}

.alsaab-rank-req.missing{
  border-color:rgba(255,170,80,.35);
  color:#ffe0bd;
}

.alsaab-rank-note{
  margin-top:14px;
  padding:13px;
  border-radius:14px;
  line-height:1.8;
  background:rgba(215,184,90,.08);
  border:1px solid rgba(215,184,90,.22);
  color:#e8dfc2;
}

@media(max-width:720px){
  .alsaab-rank-header{
    flex-direction:column;
  }

  .alsaab-rank-grid{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }

  .alsaab-rank-card span{
    font-size:20px;
  }
}
</style>

<script>
(function(){
  try{
    if(window.__ALSAAB_RANK_DASHBOARD_UI_V3__) return;
    window.__ALSAAB_RANK_DASHBOARD_UI_V3__ = true;

    function findPartnerId(){
      var url = new URLSearchParams(window.location.search || "");
      var fromUrl = url.get("partner_id") || url.get("client_id") || "";

      if(fromUrl) return String(fromUrl).toUpperCase();

      var text = document.body.innerText || "";
      var match = text.match(/ALS-P\d{5,}/i);
      return match && match[0] ? match[0].toUpperCase() : "";
    }

    function safe(v, fallback){
      if(v === null || v === undefined || v === "") return fallback || "-";
      return v;
    }

    function num(v, fallback){
      var n = parseInt(String(v || "").replace(/[^\d]/g,""),10);
      return isNaN(n) ? (fallback || 0) : n;
    }

    function normalizePlan(v){
      v = String(v || "").toLowerCase().trim();
      if(v.indexOf("entry") !== -1 || v.indexOf("دخول") !== -1) return "entry";
      if(v.indexOf("starter") !== -1 || v.indexOf("بداية") !== -1) return "starter";
      if(v.indexOf("growth") !== -1 || v.indexOf("نمو") !== -1) return "growth";
      if(v.indexOf("elite") !== -1 || v.indexOf("نخبة") !== -1) return "elite";
      return v;
    }

    function planLabel(plan){
      plan = normalizePlan(plan);
      if(plan === "entry") return "باقة الدخول";
      if(plan === "starter") return "باقة البداية";
      if(plan === "growth") return "باقة النمو";
      if(plan === "elite") return "باقة النخبة";
      return plan || "-";
    }

    function planRank(plan){
      plan = normalizePlan(plan);
      return {entry:1,starter:2,growth:3,elite:4}[plan] || 0;
    }

    function planAtLeast(plan, minPlan){
      return planRank(plan) >= planRank(minPlan);
    }

    function rankDetails(level){
      level = num(level, 1);
      if(level < 1) level = 1;

      var ranks = {
        1:{level:1,title_ar:"شريك مباشر",color_ar:"برونزي",color_hex:"#CD7F32",commission_percent:25},
        2:{level:2,title_ar:"شريك البداية",color_ar:"فضي",color_hex:"#C0C0C0",commission_percent:5},
        3:{level:3,title_ar:"شريك متقدم",color_ar:"ذهبي",color_hex:"#D7B85A",commission_percent:4},
        4:{level:4,title_ar:"شريك النمو",color_ar:"بلاتيني",color_hex:"#E5E4E2",commission_percent:3},
        5:{level:5,title_ar:"شريك النخبة",color_ar:"ماسي",color_hex:"#B9F2FF",commission_percent:2}
      };

      return ranks[level] || ranks[1];
    }

    function req(label, done, current, required){
      return {label:label, done:!!done, current_value:current, required_value:required};
    }

    function requirements(nextLevel, plan, directActive, totalActive, courses){
      nextLevel = num(nextLevel, 2);
      plan = normalizePlan(plan);
      courses = courses || {};

      if(nextLevel === 2){
        return [
          req("الباقة المطلوبة", planAtLeast(plan,"starter"), planLabel(plan), "باقة البداية أو أعلى"),
          req("الاشتراكات المباشرة الفعالة", directActive >= 2, directActive, 2),
          req("الكورس المطلوب", !!courses.marketer_mindset, courses.marketer_mindset ? "مكتمل" : "غير مكتمل", "عقلية المسوق المحترف — 69$")
        ];
      }

      if(nextLevel === 3){
        return [
          req("الباقة المطلوبة", planAtLeast(plan,"starter"), planLabel(plan), "باقة البداية أو أعلى"),
          req("الاشتراكات المباشرة الفعالة", directActive >= 5, directActive, 5),
          req("الكورس المطلوب", !!courses.marketer_mindset, courses.marketer_mindset ? "مكتمل" : "غير مكتمل", "عقلية المسوق المحترف — 69$")
        ];
      }

      if(nextLevel === 4){
        return [
          req("الباقة المطلوبة", planAtLeast(plan,"growth"), planLabel(plan), "باقة النمو أو أعلى"),
          req("إجمالي الاشتراكات الفعالة في الشبكة", totalActive >= 15, totalActive, 15),
          req("الكورس المطلوب", !!courses.sales_skills, courses.sales_skills ? "مكتمل" : "غير مكتمل", "مهارات المبيعات — 99$")
        ];
      }

      if(nextLevel === 5){
        return [
          req("الباقة المطلوبة", normalizePlan(plan) === "elite", planLabel(plan), "باقة النخبة"),
          req("إجمالي الاشتراكات الفعالة في الشبكة", totalActive >= 30, totalActive, 30),
          req("الكورس المطلوب", !!courses.change_journey, courses.change_journey ? "مكتمل" : "غير مكتمل", "رحلة التغيير — 299$")
        ];
      }

      return [];
    }

    function findOldRankSectionText(){
      var candidates = Array.prototype.slice.call(document.querySelectorAll("section, article, div"));
      var best = "";

      candidates.forEach(function(el){
        if(!el || el.id === "alsaabRankDashboardSection") return;

        var t = (el.innerText || "").trim();

        if(!t) return;

        var looksOld =
          t.indexOf("المستوى والترقية") !== -1 ||
          t.indexOf("Required Sales") !== -1 ||
          t.indexOf("Commission Eligible") !== -1 ||
          t.indexOf("Required Course") !== -1 ||
          t.indexOf("Missing Requirements") !== -1;

        if(looksOld && t.length > best.length && t.length < 12000){
          best = t;
        }
      });

      return best;
    }

    function extractLegacyData(){
      var t = findOldRankSectionText();
      var out = {
        level: 1,
        plan: "",
        direct_active: 0,
        total_active: 0,
        courses:{}
      };

      if(!t) return out;

      var levels = [];
      var re = /Level\s*([0-9]+)/ig;
      var m;

      while((m = re.exec(t)) !== null){
        levels.push(num(m[1],0));
      }

      if(levels.length){
        out.level = Math.max(1, levels[0]);
      }

      if(t.toLowerCase().indexOf("growth") !== -1 || t.indexOf("النمو") !== -1){
        out.plan = "growth";
      }else if(t.toLowerCase().indexOf("elite") !== -1 || t.indexOf("النخبة") !== -1){
        out.plan = "elite";
      }else if(t.toLowerCase().indexOf("starter") !== -1 || t.indexOf("البداية") !== -1){
        out.plan = "starter";
      }else if(t.toLowerCase().indexOf("entry") !== -1 || t.indexOf("الدخول") !== -1){
        out.plan = "entry";
      }

      var completedMatch = t.match(/(\d+)\s*Completed Sales/i) || t.match(/Completed Sales\s*(\d+)/i);
      if(completedMatch){
        out.direct_active = num(completedMatch[1],0);
        out.total_active = out.direct_active;
      }

      if(t.indexOf("عقلية") !== -1 || t.indexOf("المسوق") !== -1 || t.toLowerCase().indexOf("marketer") !== -1){
        out.courses.marketer_mindset = true;
      }

      if(t.indexOf("مهارات المبيعات") !== -1 || t.toLowerCase().indexOf("sales skills") !== -1){
        out.courses.sales_skills = true;
      }

      if(t.indexOf("رحلة التغيير") !== -1 || t.toLowerCase().indexOf("change journey") !== -1){
        out.courses.change_journey = true;
      }

      return out;
    }

    function hideOldRankSection(){
      var candidates = Array.prototype.slice.call(document.querySelectorAll("section, article, div"));

      var best = null;
      var bestLength = 999999;

      candidates.forEach(function(el){
        if(!el || el.id === "alsaabRankDashboardSection") return;

        var text = (el.innerText || "").trim();

        if(!text) return;

        var isOld =
          (
            text.indexOf("المستوى والترقية") !== -1 ||
            text.indexOf("Required Sales") !== -1 ||
            text.indexOf("Commission Eligible") !== -1 ||
            text.indexOf("Required Course") !== -1 ||
            text.indexOf("Missing Requirements") !== -1
          ) &&
          text.indexOf("رتبة الشريك") === -1;

        if(isOld && text.length < bestLength && text.length < 12000){
          best = el;
          bestLength = text.length;
        }
      });

      if(best){
        best.style.display = "none";
        best.setAttribute("data-alsaab-hidden-old-rank-section", "1");
      }
    }

    function endpoint(partnerId){
      return "/client/partner-rank-summary?partner_id=" + encodeURIComponent(partnerId);
    }

    function renderRequirements(items){
      var box = document.getElementById("alsaabRankRequirements");
      if(!box) return;

      items = items || [];

      if(!items.length){
        box.innerHTML = "<div>ما في شروط ناقصة حاليا.</div>";
        return;
      }

      box.innerHTML = items.map(function(item){
        var cls = item.done ? "done" : "missing";
        var icon = item.done ? "✅" : "⏳";

        return '<div class="alsaab-rank-req '+cls+'">' +
          '<div>' + icon + ' ' + safe(item.label, "-") + '</div>' +
          '<div>' + safe(item.current_value, "-") + ' / ' + safe(item.required_value, "-") + '</div>' +
        '</div>';
      }).join("");
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

    function applyRankTheme(rank){
      var section = document.getElementById("alsaabRankDashboardSection");
      var badge = document.getElementById("alsaabRankBadge");
      var mainCard = document.querySelector(".main-rank-card");

      var color = rank.color_hex || "#D7B85A";

      if(section){
        section.style.background =
          "linear-gradient(135deg, " + hexToRgba(color,.22) + " 0%, rgba(17,17,17,.96) 35%, rgba(17,17,17,1) 100%)";
        section.style.borderColor = color;
        section.style.boxShadow = "0 0 28px " + hexToRgba(color,.20);
      }

      if(badge){
        badge.style.background = color;
        badge.style.borderColor = color;
        badge.style.color = "#111";
      }

      if(mainCard){
        mainCard.style.borderColor = color;
        mainCard.style.boxShadow = "0 0 18px " + hexToRgba(color,.18);
      }
    }

    function buildSafeRankData(data){
      var legacy = extractLegacyData();

      data = data || {};

      var rank = data.current_rank || {};
      var rankLevel = num(rank.level,0);

      if(rankLevel < 1){
        rankLevel = legacy.level || 1;
      }

      rank = rankDetails(rankLevel);

      var plan = normalizePlan(data.plan || legacy.plan || "");
      if(!plan){
        plan = legacy.plan || "";
      }

      var directActive = num(data.direct_active, legacy.direct_active || 0);
      var totalActive = num(data.total_active_downline, legacy.total_active || directActive);

      var courses = data.courses || {};
      courses.marketer_mindset = !!(courses.marketer_mindset || legacy.courses.marketer_mindset);
      courses.sales_skills = !!(courses.sales_skills || legacy.courses.sales_skills);
      courses.change_journey = !!(courses.change_journey || legacy.courses.change_journey);

      var nextLevel = rankLevel >= 5 ? null : rankLevel + 1;
      var nextRank = nextLevel ? rankDetails(nextLevel) : null;
      var reqs = nextLevel ? requirements(nextLevel, plan, directActive, totalActive, courses) : [];

      return {
        rank: rank,
        plan: plan,
        plan_label: planLabel(plan),
        direct_active: directActive,
        total_active_downline: totalActive,
        next_rank: nextRank,
        next_requirements: reqs
      };
    }

    function load(){
      var partnerId = findPartnerId();

      if(!partnerId) return;

      fetch(endpoint(partnerId))
        .then(function(r){ return r.json(); })
        .then(function(data){
          var safeData = buildSafeRankData(data || {});

          var rank = safeData.rank;
          var next = safeData.next_rank;

          document.getElementById("alsaabRankTitle").innerText = safe(rank.title_ar);
          document.getElementById("alsaabRankColor").innerText = safe(rank.color_ar);
          document.getElementById("alsaabRankLevel").innerText = "Level " + safe(rank.level, 1);
          document.getElementById("alsaabRankCommission").innerText = rank.commission_percent ? rank.commission_percent + "%" : "-";
          document.getElementById("alsaabRankPlan").innerText = safe(safeData.plan_label);
          document.getElementById("alsaabRankDirect").innerText = safe(safeData.direct_active, 0);
          document.getElementById("alsaabRankTotal").innerText = safe(safeData.total_active_downline, 0);

          var badge = document.getElementById("alsaabRankBadge");
          if(badge){
            badge.innerText = safe(rank.color_ar) + " — " + safe(rank.title_ar);
          }

          applyRankTheme(rank);

          var nextBox = document.getElementById("alsaabNextRank");
          if(nextBox){
            if(next && next.level){
              nextBox.innerText = "المستوى القادم: " + safe(next.title_ar) + " — العمولة: " + safe(next.commission_percent) + "%";
            }else{
              nextBox.innerText = "أنت على أعلى مستوى حاليا.";
            }
          }

          renderRequirements(safeData.next_requirements || []);

          var smartLinkSection = document.getElementById("alsaabSmartLinkDashboardSection");
          var rankSection = document.getElementById("alsaabRankDashboardSection");

          if(smartLinkSection && rankSection && smartLinkSection.parentNode){
            smartLinkSection.parentNode.insertBefore(rankSection, smartLinkSection);
          }

          setTimeout(hideOldRankSection, 300);
          setTimeout(hideOldRankSection, 1000);
          setTimeout(hideOldRankSection, 2200);
        })
        .catch(function(){
          var legacy = buildSafeRankData({});
          var rank = legacy.rank;

          document.getElementById("alsaabRankTitle").innerText = safe(rank.title_ar);
          document.getElementById("alsaabRankColor").innerText = safe(rank.color_ar);
          document.getElementById("alsaabRankLevel").innerText = "Level " + safe(rank.level, 1);
          document.getElementById("alsaabRankCommission").innerText = rank.commission_percent ? rank.commission_percent + "%" : "-";
          document.getElementById("alsaabRankPlan").innerText = safe(legacy.plan_label);
          document.getElementById("alsaabRankDirect").innerText = safe(legacy.direct_active, 0);
          document.getElementById("alsaabRankTotal").innerText = safe(legacy.total_active_downline, 0);

          var badge = document.getElementById("alsaabRankBadge");
          if(badge){
            badge.innerText = safe(rank.color_ar) + " — " + safe(rank.title_ar);
          }

          applyRankTheme(rank);
          renderRequirements(legacy.next_requirements || []);
          hideOldRankSection();
        });
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", function(){
        setTimeout(load, 500);
      });
    }else{
      setTimeout(load, 500);
    }
  }catch(e){}
})();
</script>
<!-- ALSAAB_RANK_DASHBOARD_UI_V3 END -->
'''

            if "</body>" in html:
                html = html.replace("</body>", section + "\n</body>", 1)
                response.set_data(html)

            return response

        except Exception as error:
            print(f"RANK DASHBOARD INJECTOR ERROR ❌ {error}", flush=True)
            return response

    existing_rules = {str(rule.rule) for rule in app.url_map.iter_rules()}

    if "/client/partner-rank-summary" not in existing_rules:
        app.add_url_rule(
            "/client/partner-rank-summary",
            "client_partner_rank_summary",
            client_partner_rank_summary,
            methods=["GET"],
        )

    app.after_request(rank_dashboard_injector)
