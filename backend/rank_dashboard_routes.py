from flask import request, jsonify
import os
import copy


def _db():
    try:
        import database
        return database
    except ImportError:
        from backend import database
        return database


def _clean_client_rank_payload(value):
    """
    Remove internal-only commission cap information before showing rank data to users.
    """
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

            if not html or "ALSAAB_RANK_DASHBOARD_UI_V1" in html:
                return response

            section = r'''
<!-- ALSAAB_RANK_DASHBOARD_UI_V1 START -->
<div id="alsaabRankDashboardSection" class="alsaab-rank-section" dir="rtl">
  <div class="alsaab-rank-header">
    <div>
      <h2>رتبة الشريك</h2>
      <p>هنا تشوف رتبتك الحالية المستوى المفتوح لك والشروط المطلوبة للترقية القادمة.</p>
    </div>
    <div id="alsaabRankBadge" class="alsaab-rank-badge">جاري التحميل...</div>
  </div>

  <div class="alsaab-rank-grid">
    <div class="alsaab-rank-card">
      <span id="alsaabRankTitle">-</span>
      <small>الرتبة الحالية</small>
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
  background:#0b0b0b;
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

.alsaab-rank-next{
  margin-top:18px;
  background:#0b0b0b;
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
    function findPartnerId(){
      var text = document.body.innerText || "";
      var match = text.match(/ALS-P\d{5,}/i);
      return match && match[0] ? match[0].toUpperCase() : "";
    }

    function safe(v, fallback){
      if(v === null || v === undefined || v === "") return fallback || "-";
      return v;
    }

    function endpoint(partnerId){
      return "/client/partner-rank-summary?partner_id=" + encodeURIComponent(partnerId);
    }

    function renderRequirements(items){
      var box = document.getElementById("alsaabRankRequirements");
      if(!box) return;

      items = items || [];

      if(!items.length){
        box.innerHTML = "<div>أنت على أعلى مستوى متاح حاليا.</div>";
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

    function applyRankColor(color){
      var badge = document.getElementById("alsaabRankBadge");
      if(!badge || !color) return;

      badge.style.background = color;
      badge.style.borderColor = color;

      if(color.toLowerCase() === "#b9f2ff" || color.toLowerCase() === "#e5e4e2" || color.toLowerCase() === "#c0c0c0"){
        badge.style.color = "#111";
      }
    }

    function load(){
      var partnerId = findPartnerId();

      if(!partnerId) return;

      fetch(endpoint(partnerId))
        .then(function(r){ return r.json(); })
        .then(function(data){
          if(!data || data.status !== "success"){
            throw new Error("rank summary failed");
          }

          var rank = data.current_rank || {};
          var next = data.next_rank || null;

          document.getElementById("alsaabRankTitle").innerText = safe(rank.title_ar);
          document.getElementById("alsaabRankLevel").innerText = rank.level ? "Level " + rank.level : "-";
          document.getElementById("alsaabRankCommission").innerText = rank.commission_percent ? rank.commission_percent + "%" : "-";
          document.getElementById("alsaabRankPlan").innerText = safe(data.plan_label);
          document.getElementById("alsaabRankDirect").innerText = safe(data.direct_active, 0);
          document.getElementById("alsaabRankTotal").innerText = safe(data.total_active_downline, 0);

          var badge = document.getElementById("alsaabRankBadge");
          if(badge){
            badge.innerText = safe(rank.color_ar) + " — " + safe(rank.title_ar);
          }

          applyRankColor(rank.color_hex);

          var nextBox = document.getElementById("alsaabNextRank");
          if(nextBox){
            if(next){
              nextBox.innerText = "المستوى القادم: " + safe(next.title_ar) + " — العمولة: " + safe(next.commission_percent) + "%";
            }else{
              nextBox.innerText = "أنت على أعلى مستوى حاليا.";
            }
          }

          renderRequirements(data.next_requirements || []);

          var smartLinkSection = document.getElementById("alsaabSmartLinkDashboardSection");
          var rankSection = document.getElementById("alsaabRankDashboardSection");

          if(smartLinkSection && rankSection && smartLinkSection.parentNode){
            smartLinkSection.parentNode.insertBefore(rankSection, smartLinkSection);
          }
        })
        .catch(function(){
          var badge = document.getElementById("alsaabRankBadge");
          if(badge) badge.innerText = "تعذر تحميل الرتبة حاليا";
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
<!-- ALSAAB_RANK_DASHBOARD_UI_V1 END -->
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
