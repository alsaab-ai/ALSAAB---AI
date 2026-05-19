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


def _walk(value):
    found = []

    def inner(item):
        if isinstance(item, dict):
            found.append(item)
            for child in item.values():
                inner(child)
        elif isinstance(item, list):
            for child in item:
                inner(child)

    inner(value)
    return found


def _first_value(data, keys):
    if not isinstance(data, dict):
        return ""

    all_dicts = _walk(data)

    for item in all_dicts:
        lower = {str(k).strip().lower(): v for k, v in item.items()}

        for key in keys:
            wanted = str(key).strip().lower()

            if wanted in lower and str(lower[wanted] or "").strip():
                return lower[wanted]

    return ""


def _text(value):
    return str(value or "").strip()


def _number(value, default=0):
    raw = _text(value)

    if not raw:
        return default

    match = re.search(r"\d+", raw)

    if not match:
        return default

    try:
        return int(match.group(0))
    except Exception:
        return default


def _normalize_plan(value):
    raw = _text(value).lower()

    mapping = {
        "entry": "entry",
        "دخول": "entry",
        "الدخول": "entry",
        "باقة الدخول": "entry",

        "starter": "starter",
        "start": "starter",
        "بداية": "starter",
        "البداية": "starter",
        "باقة البداية": "starter",

        "growth": "growth",
        "grow": "growth",
        "نمو": "growth",
        "النمو": "growth",
        "باقة النمو": "growth",

        "elite": "elite",
        "نخبة": "elite",
        "النخبة": "elite",
        "باقة النخبة": "elite",
    }

    return mapping.get(raw, raw)


def _plan_rank(plan):
    return {
        "entry": 1,
        "starter": 2,
        "growth": 3,
        "elite": 4,
    }.get(_normalize_plan(plan), 0)


def _plan_at_least(plan, minimum):
    return _plan_rank(plan) >= _plan_rank(minimum)


def _rank_details(level):
    ranks = {
        0: {
            "level": 0,
            "title_ar": "غير مؤهل حاليا",
            "title_en": "Not Qualified",
            "color_ar": "رمادي",
            "color_hex": "#777777",
            "commission_percent": 0,
        },
        1: {
            "level": 1,
            "title_ar": "شريك مباشر",
            "title_en": "Direct Partner",
            "color_ar": "برونزي",
            "color_hex": "#CD7F32",
            "commission_percent": 25,
        },
        2: {
            "level": 2,
            "title_ar": "شريك البداية",
            "title_en": "Starter Partner",
            "color_ar": "فضي",
            "color_hex": "#C0C0C0",
            "commission_percent": 5,
        },
        3: {
            "level": 3,
            "title_ar": "شريك متقدم",
            "title_en": "Advanced Partner",
            "color_ar": "ذهبي",
            "color_hex": "#D7B85A",
            "commission_percent": 4,
        },
        4: {
            "level": 4,
            "title_ar": "شريك النمو",
            "title_en": "Growth Partner",
            "color_ar": "بلاتيني",
            "color_hex": "#E5E4E2",
            "commission_percent": 3,
        },
        5: {
            "level": 5,
            "title_ar": "شريك النخبة",
            "title_en": "Elite Partner",
            "color_ar": "ماسي",
            "color_hex": "#B9F2FF",
            "commission_percent": 2,
        },
    }

    return ranks.get(int(level or 0), ranks[0])


def _req(label, done, current, required):
    return {
        "label": label,
        "done": bool(done),
        "current_value": current,
        "required_value": required,
    }


def _has_course_from_payload(data, keywords):
    raw = str(data or "").lower()

    for keyword in keywords:
        if keyword.lower() in raw:
            return True

    return False


def _requirements(next_level, plan, direct_active, total_active, courses):
    if next_level == 1:
        return [
            _req("اشتراك فعال", True, _plan_label(plan), "Entry أو أعلى"),
        ]

    if next_level == 2:
        return [
            _req("الباقة المطلوبة", _plan_at_least(plan, "starter"), _plan_label(plan), "باقة البداية أو أعلى"),
            _req("الاشتراكات المباشرة الفعالة", direct_active >= 2, direct_active, 2),
            _req("الكورس المطلوب", courses.get("marketer_mindset", False), "مكتمل" if courses.get("marketer_mindset") else "غير مكتمل", "عقلية المسوق المحترف — 69$"),
        ]

    if next_level == 3:
        return [
            _req("الباقة المطلوبة", _plan_at_least(plan, "starter"), _plan_label(plan), "باقة البداية أو أعلى"),
            _req("الاشتراكات المباشرة الفعالة", direct_active >= 5, direct_active, 5),
            _req("الكورس المطلوب", courses.get("marketer_mindset", False), "مكتمل" if courses.get("marketer_mindset") else "غير مكتمل", "عقلية المسوق المحترف — 69$"),
        ]

    if next_level == 4:
        return [
            _req("الباقة المطلوبة", _plan_at_least(plan, "growth"), _plan_label(plan), "باقة النمو أو أعلى"),
            _req("إجمالي الاشتراكات الفعالة في الشبكة", total_active >= 15, total_active, 15),
            _req("الكورس المطلوب", courses.get("sales_skills", False), "مكتمل" if courses.get("sales_skills") else "غير مكتمل", "مهارات المبيعات — 99$"),
        ]

    if next_level == 5:
        return [
            _req("الباقة المطلوبة", _normalize_plan(plan) == "elite", _plan_label(plan), "باقة النخبة"),
            _req("إجمالي الاشتراكات الفعالة في الشبكة", total_active >= 30, total_active, 30),
            _req("الكورس المطلوب", courses.get("change_journey", False), "مكتمل" if courses.get("change_journey") else "غير مكتمل", "رحلة التغيير — 299$"),
        ]

    return []


def _plan_label(plan):
    plan = _normalize_plan(plan)

    return {
        "entry": "باقة الدخول",
        "starter": "باقة البداية",
        "growth": "باقة النمو",
        "elite": "باقة النخبة",
    }.get(plan, plan or "-")


def _fallback_rank_summary(partner_id, raw_data):
    plan = _normalize_plan(
        _first_value(
            raw_data,
            [
                "plan",
                "plan_name",
                "current_plan",
                "current_package",
                "package",
                "Current Package",
                "Package",
            ],
        )
    )

    status = _text(
        _first_value(
            raw_data,
            [
                "subscription_status",
                "Subscription Status",
                "status",
                "Status",
            ],
        )
    ).lower()

    current_level_raw = _first_value(
        raw_data,
        [
            "current_level",
            "Current Level",
            "current_rank_level",
            "level",
            "Level",
            "current_rank",
            "Current Rank",
        ],
    )

    current_level = _number(current_level_raw, 0)

    direct_active = _number(
        _first_value(
            raw_data,
            [
                "direct_active",
                "direct_active_customers",
                "completed_sales",
                "Completed Sales",
                "active_direct",
                "direct_sales",
            ],
        ),
        0,
    )

    total_active = _number(
        _first_value(
            raw_data,
            [
                "total_active_downline",
                "total_active",
                "network_active",
                "active_network",
                "total_sales",
                "Completed Sales",
            ],
        ),
        direct_active,
    )

    raw_text = str(raw_data)

    courses = {
        "marketer_mindset": _has_course_from_payload(raw_text, ["عقلية", "عقليه", "المسوق", "marketer", "marketing mindset"]),
        "sales_skills": _has_course_from_payload(raw_text, ["مهارات المبيعات", "sales skills"]),
        "change_journey": _has_course_from_payload(raw_text, ["رحلة التغيير", "change journey"]),
    }

    if current_level < 1:
        if plan or status in ["active", "trialing", "paid", "approved", "نشط", "فعال"]:
            current_level = 1

    current_level = max(0, min(5, current_level))

    current_rank = _rank_details(current_level)
    next_level = None if current_level >= 5 else max(1, current_level + 1)
    next_rank = _rank_details(next_level) if next_level else None

    next_requirements = _requirements(next_level, plan, direct_active, total_active, courses) if next_level else []

    return {
        "status": "success",
        "action": "partner_rank_summary_2026_fallback",
        "partner_id": partner_id,
        "plan": plan,
        "plan_label": _plan_label(plan),
        "current_rank": current_rank,
        "next_rank": next_rank,
        "next_requirements": next_requirements,
        "completed_requirements": [item for item in next_requirements if item.get("done")],
        "missing_requirements": [item for item in next_requirements if not item.get("done")],
        "direct_active": direct_active,
        "total_active_downline": total_active,
        "courses": courses,
        "commission_rates": {
            "level_1": 25,
            "level_2": 5,
            "level_3": 4,
            "level_4": 3,
            "level_5": 2,
        },
        "note": "لا يوجد دخل مضمون والعمولات تعتمد على الاشتراكات الفعالة واستيفاء الشروط.",
    }


def _has_valid_rank_payload(result):
    if not isinstance(result, dict):
        return False

    if result.get("status") != "success":
        return False

    if not isinstance(result.get("current_rank"), dict):
        return False

    rank = result.get("current_rank") or {}

    return bool(rank.get("title_ar") or rank.get("level") is not None)


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

            if not _has_valid_rank_payload(result):
                fallback_source = database.post_to_google_sheet_json(
                    {
                        "token": os.getenv("GOOGLE_SHEET_TOKEN", ""),
                        "action": "client_dashboard_data",
                        "partner_id": partner_id,
                        "client_id": partner_id,
                        "source": "rank_dashboard_fallback",
                    },
                    label="rank_dashboard_fallback_client_dashboard_data",
                )

                result = _fallback_rank_summary(partner_id, fallback_source)

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

            if not html or "ALSAAB_RANK_DASHBOARD_UI_V2" in html:
                return response

            section = r'''
<!-- ALSAAB_RANK_DASHBOARD_UI_V2 START -->
<div id="alsaabRankDashboardSection" class="alsaab-rank-section" dir="rtl">
  <div class="alsaab-rank-header">
    <div>
      <h2>رتبة الشريك</h2>
      <p>هني تشوف رتبتك الحالية لونك ونواقص المستوى القادم حسب الشروط الجديدة.</p>
    </div>
    <div id="alsaabRankBadge" class="alsaab-rank-badge">جاري التحميل...</div>
  </div>

  <div class="alsaab-rank-grid">
    <div class="alsaab-rank-card">
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
    if(window.__ALSAAB_RANK_DASHBOARD_UI_V2__) return;
    window.__ALSAAB_RANK_DASHBOARD_UI_V2__ = true;

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

    function endpoint(partnerId){
      return "/client/partner-rank-summary?partner_id=" + encodeURIComponent(partnerId);
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
          text.indexOf("المستوى والترقية") !== -1 &&
          (
            text.indexOf("Required Sales") !== -1 ||
            text.indexOf("Commission Eligible") !== -1 ||
            text.indexOf("Required Course") !== -1 ||
            text.indexOf("Missing Requirements") !== -1
          );

        if(isOld && text.length < bestLength && text.length < 9000){
          best = el;
          bestLength = text.length;
        }
      });

      if(best){
        best.style.display = "none";
        best.setAttribute("data-alsaab-hidden-old-rank-section", "1");
      }
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

    function applyRankColor(color){
      var badge = document.getElementById("alsaabRankBadge");
      if(!badge || !color) return;

      badge.style.background = color;
      badge.style.borderColor = color;

      var lightColors = ["#b9f2ff", "#e5e4e2", "#c0c0c0", "#d7b85a"];

      if(lightColors.indexOf(String(color).toLowerCase()) !== -1){
        badge.style.color = "#111";
      }
    }

    function load(){
      hideOldRankSection();

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
          var rankLevel = Number(rank.level || 0);

          document.getElementById("alsaabRankTitle").innerText = safe(rank.title_ar);
          document.getElementById("alsaabRankColor").innerText = safe(rank.color_ar);
          document.getElementById("alsaabRankLevel").innerText = rank.level !== undefined ? "Level " + rank.level : "-";
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
            if(next && next.level){
              nextBox.innerText = "المستوى القادم: " + safe(next.title_ar) + " — العمولة: " + safe(next.commission_percent) + "%";
            }else if(rankLevel >= 5){
              nextBox.innerText = "أنت على أعلى مستوى حاليا.";
            }else{
              nextBox.innerText = "نحتاج تحديث بيانات الرتبة أو الاشتراك حتى نحدد المستوى القادم.";
            }
          }

          renderRequirements(data.next_requirements || []);

          var smartLinkSection = document.getElementById("alsaabSmartLinkDashboardSection");
          var rankSection = document.getElementById("alsaabRankDashboardSection");

          if(smartLinkSection && rankSection && smartLinkSection.parentNode){
            smartLinkSection.parentNode.insertBefore(rankSection, smartLinkSection);
          }

          setTimeout(hideOldRankSection, 500);
          setTimeout(hideOldRankSection, 1500);
        })
        .catch(function(){
          var badge = document.getElementById("alsaabRankBadge");
          if(badge) badge.innerText = "تعذر تحميل الرتبة حاليا";
        });
    }

    if(document.readyState === "loading"){
      document.addEventListener("DOMContentLoaded", function(){
        setTimeout(load, 500);
        setTimeout(hideOldRankSection, 1200);
      });
    }else{
      setTimeout(load, 500);
      setTimeout(hideOldRankSection, 1200);
    }
  }catch(e){}
})();
</script>
<!-- ALSAAB_RANK_DASHBOARD_UI_V2 END -->
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
