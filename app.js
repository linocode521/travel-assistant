/* 智能旅行助手 · 前端逻辑
 * 纯原生 JS，无构建步骤。负责：表单、行程渲染、Leaflet 地图、预算联动、CRUD、导出。
 */
(function () {
  "use strict";

  var API = (location.protocol === "file:" || !location.port) ? "http://127.0.0.1:8766" : "";
  // 与 tokens.css 的 Wayfind 色板对应（oklch 换算成 canvas 可用的 hex）
  var C = {
    paper: "#F1F3F6", paperRaised: "#FDFDFE", paperSunk: "#E5E8ED",
    ink: "#171C26", ink2: "#333A47", muted: "#5F6672", faint: "#7C8490",
    rule: "#C4C9D2", ruleStrong: "#3F4755",
    accent: "#1050E0", accentDeep: "#0B3AA8", accentWash: "#DDE6FB",
    warn: "#E8A93A", warnWash: "#F5EBD6", ok: "#3F6248",
    white: "#FFFFFF"
  };
  var DAY_COLORS = [C.accent, C.ink2, C.ink2, C.ink2, C.ink2, C.accentDeep, C.ink2];
  var SRC_LABEL = { llm: "大模型生成", rule: "本地规则引擎" };
  var KIND_LABEL = { spot: "景点", meal: "餐饮", hotel: "酒店" };
  var MEAL_LABEL = { breakfast: "早餐", lunch: "午餐", dinner: "晚餐" };

  var state = {
    options: null,
    trip: null,
    mapProvider: "leaflet",   // amap | leaflet
    amapConfig: null,
    map: null,
    layers: [],
    markers: {},
    tileMode: "street",
    tileOk: true,
    tileLayer: null,
    mapError: "",
    showMeals: false,
    busy: false
  };

  // 高德坐标系（GCJ-02）与 OSM（WGS-84）的字段名不同：这里统一取点的函数
  function ptOf(it) {
    if (state.mapProvider === "amap" && it.lon_g != null) return [it.lon_g, it.lat_g];
    return [it.lon, it.lat];
  }
  function dayPoints(day) {
    var out = [];
    day.items.forEach(function (it) {
      if (it.kind === "hotel") return;
      var p = ptOf(it);
      out.push(p);
    });
    return out;
  }

  // ---------------------------------------------------------------- 小工具
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function money(v) {
    var n = Math.round(Number(v) || 0);
    return "¥" + n.toLocaleString("zh-CN");
  }
  function toast(msg, isErr) {
    var t = $("toast");
    t.textContent = msg;
    t.className = "toast on" + (isErr ? " err" : "");
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.className = "toast" + (isErr ? " err" : ""); }, 3200);
  }
  function busy(on, title, msgs) {
    state.busy = on;
    var ov = $("overlay");
    ov.className = "overlay" + (on ? " on" : "");
    if (!on) return;
    $("loadTitle").textContent = title || "正在规划行程…";
    var list = msgs || ["正在理解你的偏好", "正在挑选景点并排时间轴", "正在核算门票与交通", "正在校准地图坐标"];
    var i = 0, pct = 8;
    $("loadMsg").textContent = list[0];
    $("loadBar").style.transform = "scaleX(" + (pct / 100) + ")";
    clearInterval(busy._h);
    busy._h = setInterval(function () {
      i = Math.min(i + 1, list.length - 1);
      pct = Math.min(pct + 18, 92);
      $("loadMsg").textContent = list[i];
      $("loadBar").style.transform = "scaleX(" + (pct / 100) + ")";
    }, 1300);
  }
  function stopBusy() {
    clearInterval(busy._h);
    $("loadBar").style.transform = "scaleX(1)";
    setTimeout(function () { $("overlay").className = "overlay"; }, 260);
    state.busy = false;
  }

  // ---------------------------------------------------------------- API
  function api(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(API + path, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok || data.ok === false) {
          throw new Error(data.error || ("HTTP " + r.status));
        }
        return data;
      });
    });
  }


  // ---------------------------------------------------------------- 表单
  function initForm() {
    var o = state.options;
    var citySel = $("fCity");
    citySel.innerHTML = o.cities.map(function (c) {
      return '<option value="' + esc(c.city) + '">' + esc(c.city) + "（" + c.spots + " 个候选景点）</option>";
    }).join("");
    citySel.value = o.defaults.city;

    var today = new Date();
    var d = new Date(today.getTime() + 7 * 864e5);
    $("fDate").value = d.toISOString().slice(0, 10);
    $("fDate").min = today.toISOString().slice(0, 10);

    var styles = $("fStyles");
    styles.innerHTML = "";
    o.styles.forEach(function (s) {
      var c = el("div", "chip" + (o.defaults.styles.indexOf(s.key) >= 0 ? " on" : ""), esc(s.label));
      c.dataset.key = s.key;
      c.onclick = function () { c.classList.toggle("on"); };
      styles.appendChild(c);
    });

    var pace = $("fPace");
    pace.innerHTML = o.paces.map(function (p) {
      return '<button data-key="' + p.key + '"' + (p.key === o.defaults.pace ? ' class="on"' : "") + ">" + esc(p.label) + "</button>";
    }).join("");
    pace.querySelectorAll("button").forEach(function (b) {
      b.onclick = function () {
        pace.querySelectorAll("button").forEach(function (x) { x.classList.remove("on"); });
        b.classList.add("on");
        var p = o.paces.filter(function (x) { return x.key === b.dataset.key; })[0];
        $("paceHint").textContent = p ? p.hint : "";
      };
    });
    var dp = o.paces.filter(function (x) { return x.key === o.defaults.pace; })[0];
    $("paceHint").textContent = dp ? dp.hint : "";

    var tier = $("fTier");
    tier.innerHTML = o.tiers.map(function (t) {
      return '<button data-key="' + t.key + '"' + (t.key === o.defaults.tier ? ' class="on"' : "") + ">" + esc(t.label.replace("型", "")) + "</button>";
    }).join("");
    tier.querySelectorAll("button").forEach(function (b) {
      b.onclick = function () {
        tier.querySelectorAll("button").forEach(function (x) { x.classList.remove("on"); });
        b.classList.add("on");
      };
    });

    $("fAdults").innerHTML = range(1, 8).map(function (n) {
      return '<option value="' + n + '"' + (n === 2 ? " selected" : "") + ">" + n + " 人</option>";
    }).join("");
    $("fChildren").innerHTML = range(0, 5).map(function (n) {
      return '<option value="' + n + '">' + n + " 人</option>";
    }).join("");

  }
  function range(a, b) { var r = []; for (var i = a; i <= b; i++) r.push(i); return r; }

  function readForm() {
    var styles = [];
    $("fStyles").querySelectorAll(".chip.on").forEach(function (c) { styles.push(c.dataset.key); });
    if (!styles.length) styles = ["history"];
    var pace = $("fPace").querySelector("button.on");
    var tier = $("fTier").querySelector("button.on");
    return {
      city: $("fCity").value,
      start_date: $("fDate").value,
      days: Number($("fDays").value),
      styles: styles,
      pace: pace ? pace.dataset.key : "moderate",
      tier: tier ? tier.dataset.key : "comfort",
      party: { adults: Number($("fAdults").value), children: Number($("fChildren").value) },
      origin: $("fOrigin").value.trim(),
      budget: $("fBudget").value ? Number($("fBudget").value) : null,
      preference: $("fPref").value.trim(),
      mode: $("fRule").checked ? "rule" : "auto"
    };
  }
  function fillForm(req) {
    if (!req) return;
    $("fCity").value = req.city || "北京";
    $("fDate").value = req.start_date || $("fDate").value;
    $("fDays").value = String(req.days || 3);
    $("fStyles").querySelectorAll(".chip").forEach(function (c) {
      c.classList.toggle("on", (req.styles || []).indexOf(c.dataset.key) >= 0);
    });
    $("fPace").querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("on", b.dataset.key === req.pace);
    });
    $("fTier").querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("on", b.dataset.key === req.tier);
    });
    var p = req.party || {};
    $("fAdults").value = String(p.adults || 2);
    $("fChildren").value = String(p.children || 0);
    $("fOrigin").value = req.origin || "";
    $("fBudget").value = req.budget || "";
    $("fPref").value = req.preference || "";
  }

  // ---------------------------------------------------------------- 生成 / 读取
  function generate() {
    if (state.busy) return;
    var req = readForm();
    if (req.mode === "rule") {
      busy(true, "正在用本地规则排行程…", ["读取城市景点库", "按地理位置聚类选点", "排布时间轴", "核算预算"]);
    } else {
      busy(true, "AI 正在规划行程…", ["正在理解你的偏好", "正在挑选景点与餐厅", "正在排布每日时间轴", "正在校准坐标与预算"]);
    }
    api("/api/plan", { method: "POST", body: req }).then(function (d) {
      stopBusy();
      setTrip(d.trip);
      toast("行程已生成：" + (d.trip.stats ? d.trip.stats.spots : 0) + " 个景点，共 " + d.trip.days.length + " 天");
      loadHistory();
    }).catch(function (e) {
      stopBusy();
      toast("生成失败：" + e.message, true);
    });
  }

  // ---------------------------------------------------------------- 视图
  function showView(name) {
    var home = $("home"), res = $("result");
    if (!home || !res) return;
    if (name === "result") {
      home.classList.add("hidden");
      res.classList.remove("hidden");
      res.style.display = "block";
    } else {
      res.classList.add("hidden");
      res.style.display = "";
      home.classList.remove("hidden");
    }
    window.scrollTo(0, 0);
  }

  function setTrip(trip) {
    state.trip = trip;
    fillForm(trip.req);
    showView("result");
    renderAll();
  }

  function loadHistory() {
    api("/api/trips").then(function (d) {
      var box = $("hist");
      $("histCount").textContent = d.trips.length ? d.trips.length + " 条" : "";
      if (!d.trips.length) { box.innerHTML = '<div class="empty">暂无记录</div>'; return; }
      box.innerHTML = "";
      d.trips.forEach(function (t) {
        var node = el("div", "hist-item",
          '<div style="min-width:0"><div class="t">' + esc(t.title) + '</div>' +
          '<div class="m">' + esc(t.city) + "　" + t.days + " 天　" + (t.spots || 0) + " 个景点</div></div>" +
          '<div class="amt">' + money(t.total) + "</div>");
        node.onclick = function () {
          api("/api/trips/" + encodeURIComponent(t.id)).then(function (r) {
            setTrip(r.trip);
            window.scrollTo({ top: 0, behavior: "smooth" });
          }).catch(function (e) { toast(e.message, true); });
        };
        box.appendChild(node);
      });
    }).catch(function () {});
  }

  // ---------------------------------------------------------------- 渲染
  function renderAll() {
    renderToolbar();
    renderKpis();
    renderOverview();
    renderDays();
    renderBudget();
    renderTips();
    renderMap();
    $("btnAddDay2").style.display = state.trip.days.length >= 7 ? "none" : "";
  }

  function renderToolbar() {
    var t = state.trip;
    $("tTitle").textContent = t.title || "我的行程";
    var p = t.party || {};
    var first = t.days[0] || {};
    $("tMeta").textContent = [
      t.city, first.date ? first.date + " 起" : "", t.days.length + " 天",
      p.heads + " 人" + (p.children ? "（含 " + p.children + " 儿童）" : "")
    ].filter(Boolean).join("　");
    var s = $("tSrc");
    s.textContent = SRC_LABEL[t.source] || t.source || "";
    s.className = "srcflag" + (t.source === "llm" ? " llm" : "");
    s.title = t.fallback_reason || (t.model ? "模型：" + t.model : "");
  }

  function renderKpis() {
    var t = state.trip, b = t.budget || {}, st = t.stats || {};
    var tiles = [
      { v: money(b.total), l: "总预算" + (b.limit ? "（上限 " + money(b.limit) + "）" : ""), cls: "accent" },
      { v: money(b.per_person), l: "人均花费", cls: "" },
      { v: st.spots + " 个", l: "景点 " + st.spots + " 个，餐 " + st.meals + " 次", cls: "" },
      { v: Math.round(st.km) + " km", l: "市内移动距离", cls: "" }
    ];
    $("kpis").innerHTML = tiles.map(function (x) {
      return '<div class="kpi ' + x.cls + '"><b>' + esc(x.v) + "</b><span>" + esc(x.l) + "</span></div>";
    }).join("");
  }

  function itemPriceText(it) {
    if (it.kind === "spot") {
      return Number(it.ticket) > 0 ? "门票 " + money(it.ticket) : "免费";
    }
    if (it.kind === "meal") {
      return "人均 " + money(it.price);
    }
    return it.price ? money(it.price) + " /晚" : "";
  }

  function renderDays() {
    var box = $("days");
    box.innerHTML = "";
    state.trip.days.forEach(function (day) {
      var d = document.createElement("details");
      d.className = "day";
      if (day.index === 1) d.open = true;

      var s = document.createElement("summary");
      s.innerHTML =
        '<span class="dnum">' + (day.index < 10 ? "0" + day.index : day.index) + "</span>" +
        '<span class="dtxt">' + esc(day.theme || "第 " + day.index + " 天") + "</span>" +
        '<span class="dmeta">' + esc(day.date) + " " + esc(day.weekday || "") +
        (day.start_time ? "　" + day.start_time + "–" + day.end_time : "") + "　" + day.items.length + " 站</span>" +
        '<span class="dchev">›</span>';
      var stop = function (e) { e.stopPropagation(); e.preventDefault(); };
      var bAdd = el("button", "btn sm", "添加");
      bAdd.onclick = function (e) { stop(e); openPoi(day.index, "spot"); };
      var bDel = el("button", "btn sm ghost", "删除当天");
      bDel.onclick = function (e) { stop(e); deleteDay(day.index); };
      s.appendChild(bAdd);
      s.appendChild(bDel);
      d.appendChild(s);

      if (day.warning) d.appendChild(el("div", "warn", esc(day.warning)));

      var items = el("div", "items");
      day.items.forEach(function (it, idx) { items.appendChild(renderItem(day, it, idx)); });
      d.appendChild(items);
      box.appendChild(d);
    });
  }

  function renderItem(day, it, idx) {
    var node = el("div", "item" + (it.fixed ? " locked" : "") + (it.shortened ? " shortened" : ""));
    var timeHtml = esc(it.time || "") +
      (it.duration ? "<small>" + fmtDur(it.duration) + "</small>" : "");
    if (it.shortened) timeHtml += '<small style="color:' + C.warn + '">已压缩</small>';
    var left = el("div", "time", timeHtml);

    var right = el("div", "content");
    var body = el("div", "ibody");
    // 景点：左侧一张实拍缩略图（高德 POI 图，异步补上，拿不到就留空）
    var thumb = null;
    if (it.kind === "spot") {
      thumb = el("img", "thumb");
      thumb.alt = "";
      thumb.loading = "lazy";
      thumb.style.display = "none";
      right.appendChild(thumb);
    }
    var name = el("div", "name",
      '<span class="k ' + it.kind + '">' + (it.meal ? MEAL_LABEL[it.meal] || KIND_LABEL[it.kind] : KIND_LABEL[it.kind]) + "</span>" +
      "<span>" + esc(it.name) + "</span>");
    body.appendChild(name);
    if (it.note) body.appendChild(el("div", "note", esc(it.note)));
    var tags = [];
    if (it.tags) tags = tags.concat(it.tags.slice(0, 4));
    if (it.cuisine) tags.push(it.cuisine);
    if (it.open) tags.push(it.open);
    if (tags.length) {
      var tg = el("div", "tags");
      tags.forEach(function (t) { tg.appendChild(el("span", "tag", esc(t))); });
      body.appendChild(tg);
    }
    var price = itemPriceText(it);
    var metaBits = [];
    if (price) metaBits.push(price);
    if (it.transfer) {
      metaBits.push(esc(it.transfer.mode) + " " + it.transfer.minutes + " 分钟");
    }
    if (metaBits.length) body.appendChild(el("div", "price", metaBits.join("　")));
    right.appendChild(body);
    node.appendChild(left);
    node.appendChild(right);

    // 实拍图 + 地址 + 评分：只有景点才查
    if (thumb) {
      var addrSlot = el("div", "addr");
      api("/api/poi-info?city=" + encodeURIComponent(state.trip.city) +
          "&name=" + encodeURIComponent(it.name))
        .then(function (d) {
          if (d.photo && thumb.isConnected) {
            thumb.src = d.photo;
            thumb.style.display = "";
            thumb.title = "点击查看大图";
            thumb.addEventListener("click", function (e) {
              e.stopPropagation();
              openLightbox(d.photo, it.name + (d.address ? "　" + d.address : ""));
            });
            thumb.onerror = function () { thumb.remove(); };
          } else if (thumb.isConnected) {
            thumb.remove();
          }
          if (d.address || d.rating) {
            var bits = [];
            if (d.address) bits.push(d.address);
            if (d.rating) bits.push(d.rating + " 分");
            addrSlot.textContent = bits.join("　");
            if (body.isConnected) body.appendChild(addrSlot);
          }
        })
        .catch(function () { if (thumb.isConnected) thumb.remove(); });
    }

    var acts = el("div", "acts");
    var up = el("button", "iconbtn", "↑");
    up.title = "上移";
    up.onclick = function (e) { e.stopPropagation(); move(it.key, "up"); };
    var down = el("button", "iconbtn", "↓");
    down.title = "下移";
    down.onclick = function (e) { e.stopPropagation(); move(it.key, "down"); };
    var lock = el("button", "iconbtn", it.fixed ? "●" : "○");
    lock.title = it.fixed ? "取消锁定（重排时可被替换）" : "锁定此项（重排时保留）";
    lock.onclick = function (e) { e.stopPropagation(); patchItem(it.key, { fixed: !it.fixed }); };
    var del = el("button", "iconbtn danger", "✕");
    del.title = "删除";
    del.onclick = function (e) { e.stopPropagation(); removeItem(it.key, it.name); };
    if (it.kind === "hotel") { up.disabled = false; }
    acts.appendChild(up); acts.appendChild(down); acts.appendChild(lock); acts.appendChild(del);
    node.appendChild(acts);
    return node;
  }

  function fmtDur(h) {
    var m = Math.round(Number(h) * 60);
    if (m >= 60) {
      var hh = Math.floor(m / 60), mm = m % 60;
      return hh + " 小时" + (mm ? " " + mm + " 分" : "");
    }
    return m + " 分钟";
  }

  // ---------------------------------------------------------------- 预算
  var BUDGET_COLORS = { ticket: C.ink, hotel: C.ink2, meal: C.accent, transit: C.ruleStrong, intercity: C.accentDeep };
  function renderBudget() {
    var b = state.trip.budget || {};
    var heads = (state.trip.party || {}).heads || 2;
    $("bTotal").textContent = money(b.total);
    $("bPer").textContent = "人均 " + money(b.per_person) + (b.per_day ? "　日均 " + money(b.per_day) : "");
    $("bMeta").textContent = heads + " 人";

    var items = (b.items || []).filter(function (x) { return x.amount > 0; });
    $("budgetGrid").innerHTML = items.map(function (it) {
      return '<div class="bcard"><span>' + esc(it.label) + "</span><b>" + money(it.amount) + "</b></div>";
    }).join("");

    var d = b.detail || {};
    var rows = [];
    (d.ticket || []).forEach(function (x) { rows.push([x.name + "（" + x.qty + "人）", x.amount]); });
    (d.hotel || []).forEach(function (x) { rows.push([x.name, x.amount]); });
    (d.meal || []).forEach(function (x) { rows.push([x.name, x.amount]); });
    $("bDetail").innerHTML = rows.map(function (r) {
      return '<div class="drow"><span class="n">' + esc(r[0]) + '</span><span class="a">' + money(r[1]) + "</span></div>";
    }).join("") + (d.intercity ? '<div class="drow"><span class="n">' + esc(d.intercity) + "</span></div>" : "");

    if (b.over !== undefined) {
      var warn = el("div", "", b.over
        ? "超出预算 " + money(b.diff)
        : "在预算内，剩余 " + money(-b.diff));
      warn.style.cssText = "margin-top:12px;font-size:11.5px;padding:7px 10px;letter-spacing:.02em;" +
        "background:" + (b.over ? C.accentWash : C.warnWash) + ";color:" + (b.over ? C.accentDeep : C.ok);
      $("bDetail").appendChild(warn);
    }
  }

  function renderOverview() {
    var t = state.trip;
    var days = t.days || [];
    var p = t.party || {};
    if (days.length) {
      var d0 = days[0], dN = days[days.length - 1];
      $("ovDate").textContent = d0.date === dN.date
        ? d0.date
        : d0.date + " — " + dN.date;
    }
    $("ovParty").textContent = (p.heads || 2) + " 人" + (p.children ? "（含 " + p.children + " 儿童）" : "");
    $("ovBudget").textContent = money((t.budget || {}).total || 0);
    $("ovNote").textContent = t.summary || "";
  }

  function renderTips() {
    var t = state.trip.tips || [];
    $("tipsList").innerHTML = t.length
      ? t.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("")
      : '<li style="color:' + C.faint + '">暂无贴士</li>';
    if (state.trip.fallback_reason) {
      $("tipsList").innerHTML += '<li style="color:' + C.warn + '">' + esc(state.trip.fallback_reason) + "</li>";
    }
  }


  // ---------------------------------------------------------------- 灯箱
  function openLightbox(src, caption) {
    if (!src) return;
    var lb = $("lightbox");
    $("lightboxImg").src = src;
    $("lightboxCap").textContent = caption || "";
    lb.classList.add("on");
    lb.setAttribute("aria-hidden", "false");
  }
  function closeLightbox() {
    var lb = $("lightbox");
    lb.classList.remove("on");
    lb.setAttribute("aria-hidden", "true");
    $("lightboxImg").src = "";
  }

  // ---------------------------------------------------------------- 地图
  // 两种底图：高德（AMap，GCJ-02，需要 Key）与 Leaflet+OSM（WGS-84，兑底/离线）。
  // 对外只暴露 renderMap()，内部分派；点的取法用 ptOf() 自动选坐标系。
  var AMAP_URL = "https://webapi.amap.com/maps?v=2.0&key=";
  var AMAP_BLUE = C.accent;

  function loadScript(src, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.async = true;
      var done = false;
      var timer = setTimeout(function () {
        if (!done) { done = true; reject(new Error("加载超时：" + src)); }
      }, timeoutMs || 12000);
      s.onload = function () { if (!done) { done = true; clearTimeout(timer); resolve(); } };
      s.onerror = function () { if (!done) { done = true; clearTimeout(timer); reject(new Error("加载失败：" + src)); } };
      document.head.appendChild(s);
    });
  }

  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var css = document.createElement("link");
      css.rel = "stylesheet";
      css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(css);
      loadScript("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js", 12000).then(resolve).catch(reject);
    });
  }

  function initMapProvider() {
    var conf = state.amapConfig || {};
    if (conf.provider === "amap" && conf.amap && conf.amap.key) {
      // 安全密钥必须在 JS API 加载前挂到 window 上
      if (conf.amap.securityCode) {
        window._AMapSecurityConfig = { securityJsCode: conf.amap.securityCode };
      }
      state.mapProvider = "amap";
      // script.onload 只代表文件下载完；window.AMap 是异步 bootstrap 上去的，必须轮询等待，
      // 否则会在 AMap 就绪前误判失败、白白回落到 Leaflet。
      return loadScript(AMAP_URL + encodeURIComponent(conf.amap.key), 14000).then(function () {
        return new Promise(function (resolve, reject) {
          var t0 = Date.now();
          (function poll() {
            if (window.AMap && window.AMap.Map) return resolve();
            if (Date.now() - t0 > 12000) return reject(new Error("AMap 就绪超时"));
            setTimeout(poll, 80);
          })();
        });
      }).catch(function (err) {
        state.mapError = "高德地图加载失败（" + err.message + "），已自动切到 OSM 底图";
        state.mapProvider = "leaflet";
        return loadLeaflet();
      });
    }
    state.mapProvider = "leaflet";
    return loadLeaflet();
  }

  function renderMap() {
    if (state.mapProvider === "amap" && window.AMap) renderAmap();
    else renderLeaflet();
  }

  // ---------------------------- 高德渲染 ----------------------------
  // 高德标记：蓝色水滴 + 右上角编号小牌子（复刻参考图）；餐饮/酒店用另一种形状区分
  function dropIcon(AMap, label, color, size, isNumber, side) {
    var w = size, h = Math.round(size * 1.4);
    var badge = "";
    if (isNumber) {
      // 相邻点很容易重叠，按序号轮流把编号牌摆到右上/左上/右下/左下
      var pos = [
        "right:-7px;top:-7px",
        "left:-7px;top:-7px",
        "right:-7px;bottom:4px",
        "left:-7px;bottom:4px"
      ][(side || 0) % 4];
      badge = '<div style="position:absolute;' + pos + ';min-width:17px;height:17px;padding:0 3px;' +
        "border-radius:5px;background:" + C.white + ";border:1.6px solid " + color + ";color:" + color +
        ";font:700 10.5px/14px 'Segoe UI',sans-serif;text-align:center;" +
        'box-shadow:0 1px 4px rgba(20,40,80,.25)">' + label + "</div>";
    }
    var html =
      '<div style="position:relative;width:' + w + "px;height:" + h + 'px">' +
      '<svg width="' + w + '" height="' + h + '" viewBox="0 0 26 37">' +
      '<path d="M13 0C5.8 0 0 5.7 0 12.8 0 22.4 13 37 13 37S26 22.4 26 12.8C26 5.7 20.2 0 13 0Z" fill="' + color + '"/>' +
      '<circle cx="13" cy="12.8" r="6.2" fill=C.white opacity="0.96"/></svg>' +
      (isNumber ? "" : '<div style="position:absolute;left:0;top:0;width:' + w + "px;height:" +
        Math.round(w * 0.95) + 'px;display:grid;place-items:center;font:700 ' +
        Math.round(size * 0.4) + "px/1 'Microsoft YaHei',sans-serif;color:" + color + '">' + label + "</div>") +
      badge + "</div>";
    return new AMap.Marker({ content: html, anchor: "bottom-center", offset: new AMap.Pixel(0, 0) });
  }

  // 高德没有"自动适配到这几个点"的可靠接口，自己按墨卡托反算缩放级别：
  // 先算所有点的经纬度外接矩形，再根据容器像素尺寸求出"刚好装下"的 zoom。
  function fitAmapView(map, points) {
    if (!map || !points || !points.length) return;
    var lons = points.map(function (p) { return p[0]; });
    var lats = points.map(function (p) { return p[1]; });
    var lngMin = Math.min.apply(null, lons), lngMax = Math.max.apply(null, lons);
    var latMin = Math.min.apply(null, lats), latMax = Math.max.apply(null, lats);
    var midLat = (latMin + latMax) / 2;
    var sz = map.getSize ? map.getSize() : null;
    var W = (sz && (sz.getWidth ? sz.getWidth() : sz.width)) || 780;
    var H = (sz && (sz.getHeight ? sz.getHeight() : sz.height)) || 360;
    // 留 26% 边距给标记牌和名称标签
    var padF = 0.62;
    var dLng = Math.max(0.0035, lngMax - lngMin);
    var dLat = Math.max(0.0030, latMax - latMin);
    var cosLat = Math.cos(midLat * Math.PI / 180);
    var zx = Math.log(360 * W * padF / (256 * dLng)) / Math.LN2;
    var zy = Math.log(360 * H * padF * cosLat / (256 * dLat)) / Math.LN2;
    var z = Math.floor(Math.min(zx, zy));
    z = Math.max(9, Math.min(z, 17));
    if (points.length === 1) z = Math.min(z, 15);
    map.setZoomAndCenter(z, [(lngMin + lngMax) / 2, (latMin + latMax) / 2], false, 220);
  }

  function renderAmap() {
    var AMap = window.AMap;
    var box = $("map");
    // 首次创建
    if (!state.map || !state.map.__amap) {
      if (state.map && state.map.remove) { try { state.map.remove(); } catch (e) {} }
      box.innerHTML = "";
      state.map = new AMap.Map("map", {
        zoom: 12,
        viewMode: "2D",
        mapStyle: "amap://styles/light",
        showLabel: true,
        zoomControl: true,
        renderer: "dom",
        zooms: [4, 18],
        resizeEnable: true,
        doubleClickZoom: true
      });
      state.map.__amap = true;
      state.map.__markers = [];
      state.map.__windows = [];
      state.map.__lines = [];
      state.map.on("complete", function () {
        state.tileOk = true;
        $("mapNote").textContent = "高德地图，路线按经纬度绘制";
      });
    }
    var map = state.map;
    map.clearMap();

    var all = [];
    var spotSeq = 0;   // 全局游览序号：跨天连续，对应"第几站"
    state.trip.days.forEach(function (day) {
      var color = AMAP_BLUE;
      var seq = [];
      day.items.forEach(function (it) {
        if (it.kind === "hotel") return;
        if (it.kind === "meal" && !state.showMeals) return;
        var p = ptOf(it);
        seq.push(p);
        all.push(p);
        var label = it.kind === "spot" ? String(++spotSeq)
          : (it.meal === "breakfast" ? "早" : it.meal === "lunch" ? "午" : "晚");
        var mk = dropIcon(AMap, label, it.kind === "spot" ? AMAP_BLUE : C.warn, it.kind === "spot" ? 26 : 24, it.kind === "spot", spotSeq);
        mk.setPosition(p);
        mk.setMap(map);
        mk.on("click", function () {
          new AMap.InfoWindow({
            isCustom: false,
            offset: new AMap.Pixel(0, -34),
            content: '<div style="font:12px/1.7 \'Microsoft YaHei\',sans-serif;min-width:160px;padding:2px 4px">' +
              "<b>" + esc(it.name) + "</b><br>" +
              "<span style='color:" + C.muted + "'>" + esc((it.meal ? MEAL_LABEL[it.meal] : KIND_LABEL[it.kind]) + "　" + it.time) + "</span>" +
              (it.note ? "<br><span style='color:" + C.ink2 + "'>" + esc(it.note) + "</span>" : "") + "</div>"
          }).open(map, p);
        });
      });
      // 当日虚线路线
      if (seq.length > 1) {
        var line = new AMap.Polyline({
          path: seq,
          strokeColor: AMAP_BLUE,
          strokeOpacity: 0.92,
          strokeWeight: 4.5,
          strokeStyle: "dashed",
          strokeDasharray: [12, 8],
          lineJoin: "round",
          showDir: false,
          zIndex: 60
        });
        line.setMap(map);
      }
    });
    // 酒店
    var seen = {};
    state.trip.days.forEach(function (day) {
      day.items.forEach(function (it) {
        if (it.kind !== "hotel") return;
        var p = ptOf(it);
        var k = p[0] + "," + p[1];
        if (seen[k]) return;
        seen[k] = 1;
        all.push(p);
        var mk = new AMap.Marker({
          position: p,
          content: '<div style="width:26px;height:26px;border-radius:8px;background:' + C.ink + ";color:" + C.white + ';' +
            "font:700 13px/26px 'Segoe UI',sans-serif;text-align:center;border:2px solid " + C.white + ";" +
            'box-shadow:0 3px 8px rgba(20,30,60,.35)">H</div>',
          anchor: "center",
          offset: new AMap.Pixel(0, 0),
          zIndex: 120
        });
        mk.setMap(map);
      });
    });

    $("legend").innerHTML =
      '<span>●　景点，编号为游览顺序</span>' +
      '<span>▪　酒店</span>' +
      (state.showMeals ? '<span>○　餐饮，早／午／晚</span>' : '<span>虚线为当日路线</span>');

    if (all.length) fitAmapView(map, all);
    else map.setZoomAndCenter(12, state.trip.center.slice());
    setTimeout(function () { if (map && map.resize) map.resize(); }, 80);
    $("mapNote").textContent = "高德地图，路线按经纬度绘制";
  }

  function setAmapStyle() {
    if (!state.map || !state.map.setMapStyle) return;
    state.map.setMapStyle(state.tileMode === "satellite"
      ? "amap://styles/satellite" : "amap://styles/light");
    $("btnLayer").textContent = state.tileMode === "street" ? "底图：纸" : "底图：卫星";
  }

  // ---------------------------- Leaflet 渲染（兑底） ----------------------------
  function renderLeaflet() {
    var box = $("map");
    if (!window.L) {
      box.innerHTML = '<div style="height:100%;display:grid;place-items:center;color:' + C.faint + ';font-size:12px;text-align:center;padding:20px">' +
        "地图库未能从 CDN 加载。<br>仍可使用「导出地图 PNG」查看离线示意路线。</div>";
      $("mapNote").textContent = "离线示意图可用";
      return;
    }
    if (!state.map || state.map.__amap) {
      if (state.map && state.map.remove) { try { state.map.remove(); } catch (e) {} }
      box.innerHTML = "";
      state.map = L.map("map", { zoomControl: true, attributionControl: true, preferCanvas: true })
        .setView([state.trip.center[1], state.trip.center[0]], 12);
      state.map.__amap = false;
      applyTileLayer();
    }
    state.layers.forEach(function (l) { state.map.removeLayer(l); });
    state.layers = [];
    state.markers = {};

    var bounds = L.latLngBounds([]);
    state.trip.days.forEach(function (day) {
      var color = DAY_COLORS[(day.index - 1) % DAY_COLORS.length];
      var pts = [], n = 0;
      day.items.forEach(function (it) {
        if (it.kind === "spot") n += 1;
        if (it.kind === "hotel") return;
        if (it.kind === "meal" && !state.showMeals) return;
        pts.push([it.lat, it.lon]);
      });
      if (pts.length > 1) {
        var line = L.polyline(pts, { color: color, weight: 3.5, opacity: 0.82, dashArray: "9 6" }).addTo(state.map);
        state.layers.push(line);
      }
      var spotNo = 0;
      day.items.forEach(function (it) {
        if (it.kind === "hotel") return;
        if (it.kind === "meal" && !state.showMeals) return;
        var label = it.kind === "spot" ? String(++spotNo) : (it.meal === "breakfast" ? "早" : it.meal === "lunch" ? "午" : "晚");
        var bg = it.kind === "spot" ? color : C.warn;
        var icon = L.divIcon({
          className: "pin",
          html: '<div style="width:24px;height:24px;border-radius:50% 50% 50% 4px;transform:rotate(-45deg);background:' + bg +
            ';box-shadow:0 2px 6px rgba(0,0,0,.3)"></div>' +
            '<div style="position:absolute;left:0;top:0;width:24px;height:24px;display:grid;place-items:center;color:' + C.white + ';font:700 11px sans-serif">' +
            label + "</div>",
          iconSize: [24, 24], iconAnchor: [12, 24]
        });
        var m = L.marker([it.lat, it.lon], { icon: icon }).addTo(state.map);
        m.bindPopup(
          '<div style="font:12px/1.6 sans-serif;min-width:150px"><b>' + esc(it.name) + "</b><br>" +
          esc((it.meal ? MEAL_LABEL[it.meal] : KIND_LABEL[it.kind]) + "　" + it.time) +
          (it.note ? "<br><span style='color:" + C.muted + "'>" + esc(it.note) + "</span>" : "") +
          "</div>");
        state.layers.push(m);
        bounds.extend([it.lat, it.lon]);
      });
    });
    var seenH = {};
    state.trip.days.forEach(function (day) {
      day.items.forEach(function (it) {
        if (it.kind !== "hotel") return;
        var k = it.lat + "," + it.lon;
        if (seenH[k]) return;
        seenH[k] = 1;
        var icon = L.divIcon({
          className: "pin",
          html: '<div style="width:22px;height:22px;border-radius:7px;background:' + C.ink + ";color:" + C.white + ";font:700 12px/22px sans-serif;text-align:center;border:2px solid " + C.white + ';box-shadow:0 2px 6px rgba(0,0,0,.28)">H</div>',
          iconSize: [22, 22], iconAnchor: [11, 11]
        });
        var m = L.marker([it.lat, it.lon], { icon: icon }).addTo(state.map)
          .bindPopup('<b>' + esc(it.name) + "</b><br>住宿，参考 " + money(it.price) + " 每晚");
        state.layers.push(m);
        state.markers[k] = m;
        bounds.extend([it.lat, it.lon]);
      });
    });

    $("legend").innerHTML = state.trip.days.map(function (d) {
      var c = DAY_COLORS[(d.index - 1) % DAY_COLORS.length];
      return '<span><i style="background:' + c + '"></i>第 ' + d.index + " 天　" + esc(d.theme || "") + "</span>";
    }).join("") + "<span><i style='background:" + C.ink + ";border-radius:2px'></i>酒店</span>";

    if (bounds.isValid()) state.map.fitBounds(bounds, { padding: [36, 36] });
    setTimeout(function () { state.map.invalidateSize(); }, 60);
    $("mapNote").textContent = state.tileOk ? "OpenStreetMap，路线按经纬度绘制" : "底图加载失败，仅显示坐标与路线";

    if (!state.map.__offline) {
      state.map.__offline = L.layerGroup().addTo(state.map);
      state.map.on("moveend zoomend", drawOfflineFallback);
    }
    drawOfflineFallback();
  }

  function drawOfflineFallback() {
    var map = state.map;
    if (!map || !state.trip || !map.__offline || state.mapProvider === "amap") return;
    var group = map.__offline;
    group.clearLayers();
    if (state.tileOk) return;
    var bounds = map.getBounds();
    var nw = map.latLngToLayerPoint(bounds.getNorthWest());
    var se = map.latLngToLayerPoint(bounds.getSouthEast());
    var cw = Math.max(1, Math.round(se.x - nw.x)), chh = Math.max(1, Math.round(se.y - nw.y));
    var cv = document.createElement("canvas");
    var dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = cw * dpr; cv.height = chh * dpr;
    cv.style.width = cw + "px"; cv.style.height = chh + "px";
    var ctx = cv.getContext("2d");
    ctx.scale(dpr, dpr);

    function px(lon, lat) {
      var p = map.latLngToLayerPoint([lat, lon]);
      return [p.x - nw.x, p.y - nw.y];
    }
    ctx.fillStyle = C.paperSunk; ctx.fillRect(0, 0, cw, chh);
    ctx.strokeStyle = C.rule; ctx.lineWidth = 1;
    var step = map.getZoom() >= 12 ? 0.05 : map.getZoom() >= 10 ? 0.2 : 1;
    for (var lon = Math.floor(bounds.getWest() / step) * step; lon <= bounds.getEast(); lon += step) {
      var a = px(lon, bounds.getSouth()), b2 = px(lon, bounds.getNorth());
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b2[0], b2[1]); ctx.stroke();
    }
    for (var lat = Math.floor(bounds.getSouth() / step) * step; lat <= bounds.getNorth(); lat += step) {
      var c = px(bounds.getWest(), lat), d2 = px(bounds.getEast(), lat);
      ctx.beginPath(); ctx.moveTo(c[0], c[1]); ctx.lineTo(d2[0], d2[1]); ctx.stroke();
    }
    state.trip.days.forEach(function (day) {
      var color = DAY_COLORS[(day.index - 1) % DAY_COLORS.length];
      var seq = day.items.filter(function (i) { return i.kind !== "hotel"; });
      if (seq.length < 2) return;
      ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.globalAlpha = 0.55; ctx.setLineDash([8, 6]);
      ctx.beginPath();
      seq.forEach(function (it, i) {
        var p = px(it.lon, it.lat);
        if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      });
      ctx.stroke(); ctx.globalAlpha = 1; ctx.setLineDash([]);
    });
    group.addLayer(L.imageOverlay(cv.toDataURL("image/png"), map.getBounds(), { opacity: 0.96, interactive: false, pane: "tilePane" }));
    $("mapNote").textContent = "在线底图不可用，已切换离线矢量底图（坐标与路线准确）";
  }

  function applyTileLayer() {
    if (!state.map || state.mapProvider === "amap") return;
    if (state.tileLayer) { state.map.removeLayer(state.tileLayer); state.tileLayer = null; }
    var conf = state.tileMode === "satellite"
      ? {
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr: "Imagery &copy; Esri", max: 18
      }
      : {
        url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr: "&copy; OpenStreetMap contributors", max: 19
      };
    var layer = L.tileLayer(conf.url, { maxZoom: conf.max, attribution: conf.attr, crossOrigin: true });
    var failTimer = setTimeout(function () {
      if (state.tileOk && state.tileLayer && state.tileLayer._tiles &&
        Object.keys(state.tileLayer._tiles).length > 0) return;
      if (state.tileOk) {
        state.tileOk = false;
        drawOfflineFallback();
      }
    }, 4500);
    layer.on("tileerror", function () {
      if (state.tileOk) {
        state.tileOk = false;
        $("mapNote").textContent = "底图加载失败（网络受限），坐标与路线仍然准确";
      }
    });
    layer.on("tileload", function () {
      clearTimeout(failTimer);
      if (!state.tileOk) {
        state.tileOk = true;
        $("mapNote").textContent = "OpenStreetMap，路线按经纬度绘制";
        drawOfflineFallback();
      }
    });
    layer.addTo(state.map);
    state.tileLayer = layer;
  }
  // ---------------------------------------------------------------- 编辑动作
  function refreshFrom(trip) {
    state.trip = trip;
    renderAll();
  }
  function move(key, dir, day) {
    api("/api/trips/" + encodeURIComponent(state.trip.id) + "/items/" + encodeURIComponent(key) + "/move",
      { method: "POST", body: { direction: dir, day: day } })
      .then(function (d) { refreshFrom(d.trip); })
      .catch(function (e) { toast(e.message, true); });
  }
  function patchItem(key, patch) {
    api("/api/trips/" + encodeURIComponent(state.trip.id) + "/items/" + encodeURIComponent(key),
      { method: "PATCH", body: patch })
      .then(function (d) { refreshFrom(d.trip); })
      .catch(function (e) { toast(e.message, true); });
  }
  function removeItem(key, name) {
    if (!confirm("确定从行程里删除「" + name + "」？")) return;
    api("/api/trips/" + encodeURIComponent(state.trip.id) + "/items/" + encodeURIComponent(key),
      { method: "DELETE" })
      .then(function (d) { refreshFrom(d.trip); toast("已删除：" + name); })
      .catch(function (e) { toast(e.message, true); });
  }
  function addDay() {
    if (state.trip.days.length >= 7) { toast("最多 7 天", true); return; }
    api("/api/trips/" + encodeURIComponent(state.trip.id) + "/days", { method: "POST" })
      .then(function (d) { refreshFrom(d.trip); toast("已添加第 " + d.trip.days.length + " 天"); })
      .catch(function (e) { toast(e.message, true); });
  }
  function deleteDay(no) {
    if (state.trip.days.length <= 1) { toast("至少保留一天", true); return; }
    if (!confirm("删除第 " + no + " 天？")) return;
    api("/api/trips/" + encodeURIComponent(state.trip.id) + "/days/" + no, { method: "DELETE" })
      .then(function (d) { refreshFrom(d.trip); toast("已删除第 " + no + " 天"); })
      .catch(function (e) { toast(e.message, true); });
  }
  function replan() {
    if (state.busy) return;
    var req = readForm();
    var keep = state.trip.days.some(function (d) {
      return d.items.some(function (i) { return i.fixed; });
    });
    busy(true, "正在按新条件重排…", ["读取新条件", "重新选点", "重排时间轴", "更新预算"]);
    api("/api/trips/" + encodeURIComponent(state.trip.id) + "/replan",
      { method: "POST", body: Object.assign({}, req, { keep_locked: keep }) })
      .then(function (d) {
        stopBusy(); setTrip(d.trip);
        toast(keep ? "已重排，锁定项已保留" : "已按新条件重排");
        loadHistory();
      }).catch(function (e) { stopBusy(); toast("重排失败：" + e.message, true); });
  }

  // ---------------------------------------------------------------- 添加 POI
  function openPoi(day, kind) {
    $("poiModal").classList.add("on");
    $("poiDay").innerHTML = state.trip.days.map(function (d) {
      return '<option value="' + d.index + '"' + (d.index === day ? " selected" : "") + ">第 " + d.index + " 天　" + esc(d.date) + "</option>";
    }).join("");
    $("poiKind").value = kind || "spot";
    $("poiSearch").value = "";
    loadPois();
  }
  function loadPois() {
    var kind = $("poiKind").value;
    var q = $("poiSearch").value.trim();
    if (kind === "hotel") { $("poiList").innerHTML = '<div class="empty">酒店会在添加后自动套用当前住宿档次</div>'; return; }
    $("poiList").innerHTML = '<div class="skel">加载中…</div>';
    api("/api/pois?city=" + encodeURIComponent(state.trip.city) + "&kind=" + kind + "&q=" + encodeURIComponent(q))
      .then(function (d) {
        var used = {};
        state.trip.days.forEach(function (day) {
          day.items.forEach(function (it) { if (it.ref) used[it.ref] = true; });
        });
        if (!d.pois.length) { $("poiList").innerHTML = '<div class="empty">没有匹配的候选</div>'; return; }
        $("poiList").innerHTML = "";
        d.pois.forEach(function (p) {
          var right = kind === "meal" ? "人均 " + money(p.price) : (Number(p.ticket) > 0 ? money(p.ticket) : "免费");
          var desc = kind === "meal" ? (p.cuisine || "") + "，" + (p.dish || "") : (p.tags || []).slice(0, 3).join(" / ");
          var node = el("div", "poi" + (used[p.id] ? " in" : ""),
            '<div style="min-width:0"><div class="nm">' + esc(p.name) + '</div><div class="ds">' + esc(desc) + "</div></div>" +
            '<div class="rt">' + esc(right) + "</div>");
          if (used[p.id]) { node.title = "已在行程中"; }
          else {
            node.onclick = function () {
              var day = Number($("poiDay").value);
              api("/api/trips/" + encodeURIComponent(state.trip.id) + "/items",
                { method: "POST", body: { kind: kind, ref: p.id, day: day } })
                .then(function (r) {
                  closeModal("poiModal");
                  refreshFrom(r.trip);
                  toast("已加入第 " + day + " 天：" + p.name);
                }).catch(function (e) { toast(e.message, true); });
            };
          }
          $("poiList").appendChild(node);
        });
      }).catch(function (e) { $("poiList").innerHTML = '<div class="empty">' + esc(e.message) + "</div>"; });
  }
  function closeModal(id) { $(id).classList.remove("on"); }

  // ---------------------------------------------------------------- 导出
  function download(url, filename) {
    var a = document.createElement("a");
    a.href = url;
    a.download = filename || "";
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { a.remove(); }, 500);
  }
  function exportPdf() {
    var url = API + "/api/trips/" + encodeURIComponent(state.trip.id) + "/export.pdf";
    download(url);
    toast("PDF 已开始下载");
  }
  function openPrint() {
    var url = API + "/api/trips/" + encodeURIComponent(state.trip.id) + "/export.html";
    var w = window.open(url, "_blank");
    if (!w) { toast("弹窗被拦截，请允许后重试", true); return; }
    toast("已打开打印版，按 Ctrl+P 可存为 PDF");
  }

  // 纯 Canvas 长图（不依赖 html2canvas，离线也能用）
  function exportPng(mode) {
    if (mode === "map") return exportMapPng();
    var t = state.trip;
    var W = 1080, pad = 48;
    var heads = (t.party || {}).heads || 2;
    var lines = [];
    function line(text, opt) {
      opt = opt || {};
      lines.push({ text: String(text), size: opt.size || 15, bold: !!opt.bold, color: opt.color || C.ink, gap: opt.gap == null ? 8 : opt.gap, indent: opt.indent || 0 });
    }
    line(t.title || "我的行程", { size: 30, bold: true, gap: 6 });
    var first = t.days[0] || {};
    line(t.city + "　" + (first.date || "") + " 起　" + t.days.length + " 天　" + heads + " 人", { size: 14, color: C.muted, gap: 14 });
    if (t.summary) line(t.summary, { size: 15, color: C.ink2, gap: 18 });

    var b = t.budget || {};
    line("预算 " + money(b.total) + "　人均 " + money(b.per_person) + "　景点 " + (t.stats || {}).spots + " 个　里程 " + Math.round((t.stats || {}).km || 0) + " km",
      { size: 15, bold: true, color: C.accent, gap: 20 });

    t.days.forEach(function (day) {
      line("第 " + day.index + " 天　" + (day.theme || "") + "　" + (day.date || "") + " " + (day.weekday || ""), { size: 19, bold: true, gap: 8 });
      day.items.forEach(function (it) {
        var tag = it.meal ? MEAL_LABEL[it.meal] : KIND_LABEL[it.kind];
        var price = it.kind === "spot" ? (Number(it.ticket) ? money(it.ticket) + "/人" : "免费")
          : it.kind === "meal" ? "人均 " + money(it.price) : money(it.price) + "/晚";
        line(it.time + "　[" + tag + "] " + it.name + "　" + price, { size: 15, bold: true, gap: 4 });
        if (it.note) line(it.note, { size: 13, color: C.muted, gap: 3, indent: 26 });
        if (it.transfer) line("↳ " + it.transfer.from + " → " + it.transfer.mode + " " + it.transfer.minutes + " 分钟，" + it.transfer.km + " km",
          { size: 12, color: C.faint, gap: 3, indent: 26 });
      });
      line("", { size: 8, gap: 10 });
    });

    if ((t.tips || []).length) {
      line("实用贴士", { size: 19, bold: true, gap: 8 });
      t.tips.forEach(function (x) { line("— " + x, { size: 14, color: C.ink2, gap: 5 }); });
    }
    line("由「智能旅行助手」生成，" + new Date().toLocaleString("zh-CN"), { size: 11, color: C.faint, gap: 4 });

    var measure = document.createElement("canvas").getContext("2d");
    function font(o) { return (o.bold ? "700 " : "400 ") + o.size + "px " + "\"Microsoft YaHei\",sans-serif"; }
    var wrapped = [];
    lines.forEach(function (l) {
      measure.font = font(l);
      var maxW = W - pad * 2 - l.indent;
      var text = l.text || "";
      var cur = "";
      if (!text) { wrapped.push({ l: l, text: "" }); return; }
      for (var i = 0; i < text.length; i++) {
        var test = cur + text[i];
        if (measure.measureText(test).width > maxW && cur) {
          wrapped.push({ l: l, text: cur });
          cur = text[i];
        } else { cur = test; }
      }
      if (cur) wrapped.push({ l: l, text: cur });
    });
    var H = pad * 2 + wrapped.reduce(function (s, w) { return s + w.l.size * 1.55 + w.l.gap; }, 0);
    var cv = document.createElement("canvas");
    var scale = 2;
    cv.width = W * scale; cv.height = Math.max(300, H) * scale;
    var ctx = cv.getContext("2d");
    ctx.scale(scale, scale);
    ctx.fillStyle = C.white; ctx.fillRect(0, 0, W, H);
    // 顶部色带
    var grad = ctx.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0, C.ink); grad.addColorStop(1, C.accent);
    ctx.fillStyle = grad; ctx.fillRect(0, 0, W, 6);

    var y = pad + 6;
    wrapped.forEach(function (w) {
      var l = w.l;
      ctx.font = font(l);
      ctx.fillStyle = l.color;
      ctx.textBaseline = "top";
      ctx.fillText(w.text, pad + l.indent, y);
      y += l.size * 1.55 + l.gap;
    });
    cv.toBlob(function (blob) {
      var url = URL.createObjectURL(blob);
      download(url, (t.title || "行程") + "-长图.png");
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      toast("行程长图已导出");
    }, "image/png");
  }

  // 地图 PNG：按 Web Mercator 自己算瓦片范围，瓦片和坐标点用同一套投影，
  // 因此路线一定画在正确位置上。瓦片跨域失败时退化为纯矢量图，功能不受影响。
  function exportMapPng(opts) {
    opts = opts || {};
    var staticMap = opts.staticMap || null;
    var t = state.trip;
    var seq = [];
    t.days.forEach(function (day) {
      day.items.forEach(function (it) {
        if (it.kind !== "hotel") seq.push({ it: it, day: day.index });
      });
    });
    if (!seq.length) { toast("行程里还没有景点", true); return; }

    var W = 1200, H = 760;
    var cv = document.createElement("canvas");
    cv.width = W * 2; cv.height = H * 2;
    var ctx = cv.getContext("2d");
    ctx.scale(2, 2);
    ctx.fillStyle = C.paperSunk; ctx.fillRect(0, 0, W, H);

    function mercX(lon, z) { return (lon + 180) / 360 * Math.pow(2, z); }
    function mercY(lat, z) {
      var rad = lat * Math.PI / 180;
      return (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * Math.pow(2, z);
    }

    if (staticMap) {
      return drawStaticMapExport(staticMap, W, H, cv, ctx);
    }

    // 自动选缩放级别：让整条路线落在画布里
    var lons = seq.map(function (p) { return p.it.lon; });
    var lats = seq.map(function (p) { return p.it.lat; });
    var lon0 = Math.min.apply(null, lons), lon1 = Math.max.apply(null, lons);
    var lat0 = Math.min.apply(null, lats), lat1 = Math.max.apply(null, lats);
    var zoom = 16;
    for (; zoom > 9; zoom--) {
      var sx = Math.abs(mercX(lon1, zoom) - mercX(lon0, zoom)) * 256;
      var sy = Math.abs(mercY(lat1, zoom) - mercY(lat0, zoom)) * 256;
      if (sx <= W * 0.72 && sy <= H * 0.66) break;
    }

    // 以路线中心为画布中心，反推需要哪些瓦片
    var cx = (mercX(lon0, zoom) + mercX(lon1, zoom)) / 2;
    var cy = (mercY(lat0, zoom) + mercY(lat1, zoom)) / 2;
    var originX = cx - (W / 2) / 256;
    var originY = cy - (H / 2) / 256;
    function toPx(lon, lat) {
      return [(mercX(lon, zoom) - originX) * 256, (mercY(lat, zoom) - originY) * 256];
    }
    var x0 = Math.floor(originX), y0 = Math.floor(originY);
    var x1 = Math.ceil(originX + W / 256), y1 = Math.ceil(originY + H / 256);
    var max = Math.pow(2, zoom);
    var tiles = [];
    for (var x = x0; x <= x1; x++) {
      for (var y = y0; y <= y1; y++) {
        if (y < 0 || y >= max) continue;
        tiles.push({ x: ((x % max) + max) % max, y: y, z: zoom,
          px: (x - originX) * 256, py: (y - originY) * 256 });
      }
    }

    function drawAll() {
      // 底图网格（瓦片缺失时的保底视觉）
      ctx.strokeStyle = "rgba(180,196,214,.45)"; ctx.lineWidth = 1;
      for (var gx = 0; gx < W; gx += 64) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke(); }
      for (var gy = 0; gy < H; gy += 64) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke(); }

      // 路线
      t.days.forEach(function (day) {
        var color = DAY_COLORS[(day.index - 1) % DAY_COLORS.length];
        var items = day.items.filter(function (i) { return i.kind !== "hotel"; });
        if (items.length < 2) return;
        ctx.strokeStyle = color; ctx.lineWidth = 3.5; ctx.globalAlpha = 0.85; ctx.lineJoin = "round";
        ctx.beginPath();
        items.forEach(function (it, i) {
          var p = toPx(it.lon, it.lat);
          if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
        });
        ctx.stroke(); ctx.globalAlpha = 1;
      });

      // 站点
      t.days.forEach(function (day) {
        var color = DAY_COLORS[(day.index - 1) % DAY_COLORS.length], n2 = 0;
        day.items.forEach(function (it) {
          if (it.kind === "hotel") return;
          var p = toPx(it.lon, it.lat);
          var label = it.kind === "spot" ? String(++n2)
            : (it.meal === "breakfast" ? "早" : it.meal === "lunch" ? "午" : "晚");
          var bg = it.kind === "spot" ? color : C.warn;
          ctx.beginPath(); ctx.arc(p[0], p[1], 13, 0, Math.PI * 2);
          ctx.fillStyle = C.white; ctx.fill();
          ctx.beginPath(); ctx.arc(p[0], p[1], 10.5, 0, Math.PI * 2);
          ctx.fillStyle = bg; ctx.fill();
          ctx.fillStyle = C.white; ctx.font = "700 10px sans-serif";
          ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText(label, p[0], p[1] + 0.5);
          if (it.kind === "spot") {
            ctx.font = "600 11px 'Microsoft YaHei',sans-serif";
            ctx.textAlign = "left"; ctx.textBaseline = "top";
            var tw = ctx.measureText(it.name).width;
            var tx = p[0] + 15, ty = p[1] - 9;
            ctx.fillStyle = "rgba(255,255,255,.92)";
            ctx.fillRect(tx - 3, ty - 2, tw + 8, 17);
            ctx.fillStyle = C.ink; ctx.fillText(it.name, tx + 1, ty);
          }
        });
      });

      // 酒店
      var seenHotel = {};
      t.days.forEach(function (day) {
        day.items.forEach(function (it) {
          if (it.kind !== "hotel") return;
          var k = it.lon + "," + it.lat;
          if (seenHotel[k]) return;
          seenHotel[k] = 1;
          var p = toPx(it.lon, it.lat);
          ctx.beginPath(); ctx.arc(p[0], p[1], 12, 0, Math.PI * 2);
          ctx.fillStyle = C.ink; ctx.fill();
          ctx.strokeStyle = C.white; ctx.lineWidth = 2; ctx.stroke();
          ctx.fillStyle = C.white; ctx.font = "700 11px sans-serif";
          ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText("H", p[0], p[1] + 0.5);
        });
      });

      // 标题栏
      ctx.fillStyle = "rgba(255,255,255,.95)"; ctx.fillRect(0, 0, W, 58);
      ctx.strokeStyle = C.rule; ctx.beginPath(); ctx.moveTo(0, 58); ctx.lineTo(W, 58); ctx.stroke();
      ctx.fillStyle = C.ink; ctx.font = "700 20px 'Microsoft YaHei',sans-serif";
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillText(t.title || "行程路线", 24, 26);
      ctx.fillStyle = C.muted; ctx.font = "400 12px 'Microsoft YaHei',sans-serif";
      ctx.fillText(t.city + "　" + t.days.length + " 天　" + seq.length + " 站（含餐饮）　按经纬度绘制", 24, 45);

      // 图例
      var lx = 24, ly = H - 26;
      t.days.forEach(function (day) {
        var color = DAY_COLORS[(day.index - 1) % DAY_COLORS.length];
        ctx.beginPath(); ctx.arc(lx, ly, 5, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
        ctx.fillStyle = C.ink2; ctx.font = "400 11px 'Microsoft YaHei',sans-serif";
        ctx.textAlign = "left"; ctx.textBaseline = "middle";
        ctx.fillText("第 " + day.index + " 天", lx + 9, ly);
        lx += 62;
      });

      cv.toBlob(function (blob) {
        var url = URL.createObjectURL(blob);
        download(url, (t.title || "行程") + "-地图.png");
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
        toast(failedTiles ? "地图已导出（部分底图瓦片不可用，路线已矢量绘制）" : "地图已导出");
      }, "image/png");
    }

    var failedTiles = 0, done = 0, total = tiles.length;
    if (!total) { drawAll(); return; }
    var guard = setTimeout(function () { if (done < total) { done = total; drawAll(); } }, 8000);
    tiles.forEach(function (tile) {
      var img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = function () {
        try { ctx.drawImage(img, tile.px, tile.py, 256, 256); } catch (e) { failedTiles++; }
        if (++done >= total) { clearTimeout(guard); drawAll(); }
      };
      img.onerror = function () {
        failedTiles++;
        if (++done >= total) { clearTimeout(guard); drawAll(); }
      };
      img.src = "https://a.tile.openstreetmap.org/" + tile.z + "/" + tile.x + "/" + tile.y + ".png";
    });
  }


  // ---------------------------------------------------------------- 高德静态图导出
  // 高德 JS API 2.0 没有 StaticMap 插件了，改为后端调 Web 服务 API 渲染底图，
  // 前端拿到 dataURL 后按相同的墨卡托投影叠上虚线路线。Key 始终留在后端。
  function exportAmapStatic() {
    var t = state.trip;
    if (!t) return;
    toast("正在生成高德底图…");
    api("/api/trips/" + encodeURIComponent(t.id) + "/staticmap.json")
      .then(function (d) {
        var img = new Image();
        img.onload = function () { drawStaticExport(d, img); };
        img.onerror = function () {
          toast("底图加载失败，改用矢量图导出", true);
          exportMapPng();
        };
        img.src = d.dataUrl;
      })
      .catch(function (e) {
        toast("高德底图生成失败（" + e.message + "），改用矢量图导出", true);
        exportMapPng();
      });
  }

  function mercPx(lon, lat, z) {
    var n = 256 * Math.pow(2, z);
    var x = (lon + 180) / 360 * n;
    var rad = lat * Math.PI / 180;
    var y = (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2 * n;
    return [x, y];
  }

  // Canvas 画水滴标记（与页面上的 HTML 标记同款）
  function drawPin(ctx, x, y, color, label, k) {
    var r = 13 * k;          // 头部半径
    var cy = y - 26 * k;     // 圆心
    // 水滴轮廓：上半圆 + 两侧收拢到底部尖点
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.bezierCurveTo(x - r * 0.55, y - r * 0.55, x - r, cy + r * 0.72, x - r, cy);
    ctx.arc(x, cy, r, Math.PI, 0, false);
    ctx.bezierCurveTo(x + r, cy + r * 0.72, x + r * 0.55, y - r * 0.55, x, y);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,.9)";
    ctx.lineWidth = 1.6 * k;
    ctx.stroke();
    // 白色内圆
    ctx.beginPath();
    ctx.arc(x, cy, r * 0.52, 0, Math.PI * 2);
    ctx.fillStyle = C.white;
    ctx.fill();
    if (!label) return;
    // 右上角编号小牌子
    var bw = 19 * k, bh = 17 * k, bx = x + r * 0.35, by = cy - r * 1.5;
    ctx.beginPath();
    var rr = 5 * k;
    ctx.moveTo(bx + rr, by);
    ctx.lineTo(bx + bw - rr, by);
    ctx.quadraticCurveTo(bx + bw, by, bx + bw, by + rr);
    ctx.lineTo(bx + bw, by + bh - rr);
    ctx.quadraticCurveTo(bx + bw, by + bh, bx + bw - rr, by + bh);
    ctx.lineTo(bx + rr, by + bh);
    ctx.quadraticCurveTo(bx, by + bh, bx, by + bh - rr);
    ctx.lineTo(bx, by + rr);
    ctx.quadraticCurveTo(bx, by, bx + rr, by);
    ctx.closePath();
    ctx.fillStyle = C.white;
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6 * k;
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = "700 " + (11 * k) + "px 'Segoe UI',sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, bx + bw / 2, by + bh / 2 + 0.5 * k);
  }

  function drawStaticExport(d, img) {
    var t = state.trip;
    var W = d.width, H = d.height;
    var scale = W / (d.logicalWidth || 1024);   // 后端请求 scale=2
    var k = scale;                              // 标记尺寸随图放大
    var cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    var ctx = cv.getContext("2d");
    ctx.drawImage(img, 0, 0, W, H);

    var c = mercPx(d.center[0], d.center[1], d.zoom);
    function toPx(lon, lat) {
      var p = mercPx(lon, lat, d.zoom);
      return [(p[0] - c[0]) * scale + W / 2, (p[1] - c[1]) * scale + H / 2];
    }

    // 虚线路线
    t.days.forEach(function (day) {
      var items = day.items.filter(function (i) { return i.kind !== "hotel"; });
      if (items.length < 2) return;
      ctx.strokeStyle = "rgba(22,119,255,.9)";
      ctx.lineWidth = 4 * k;
      ctx.setLineDash([12 * k, 8 * k]);
      ctx.lineJoin = "round";
      ctx.beginPath();
      items.forEach(function (it, i) {
        var q = ptOf(it), p = toPx(q[0], q[1]);
        if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      });
      ctx.stroke();
      ctx.setLineDash([]);
    });

    // 景点水滴 + 全局编号；餐饮（可选）与酒店
    var seq = 0;
    t.days.forEach(function (day) {
      day.items.forEach(function (it) {
        if (it.kind === "hotel") return;
        if (it.kind === "meal" && !state.showMeals) return;
        var q = ptOf(it), p = toPx(q[0], q[1]);
        if (it.kind === "spot") {
          seq += 1;
          drawPin(ctx, p[0], p[1], C.accent, String(seq), k);
        } else {
          // 餐饮：小圆点 + 早/午/晚
          var r = 10 * k;
          ctx.beginPath(); ctx.arc(p[0], p[1] - r * 0.6, r, 0, Math.PI * 2);
          ctx.fillStyle = C.warn; ctx.fill();
          ctx.strokeStyle = C.white; ctx.lineWidth = 2 * k; ctx.stroke();
          ctx.fillStyle = C.white; ctx.font = "700 " + (9.5 * k) + "px 'Microsoft YaHei',sans-serif";
          ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText(it.meal === "breakfast" ? "早" : it.meal === "lunch" ? "午" : "晚", p[0], p[1] - r * 0.6);
        }
      });
    });
    var seenH = {};
    t.days.forEach(function (day) {
      day.items.forEach(function (it) {
        if (it.kind !== "hotel") return;
        var q = ptOf(it), p = toPx(q[0], q[1]);
        var key = q[0] + "," + q[1];
        if (seenH[key]) return;
        seenH[key] = 1;
        var s2 = 11 * k;
        ctx.beginPath();
        ctx.rect(p[0] - s2, p[1] - s2, s2 * 2, s2 * 2);
        ctx.fillStyle = C.ink; ctx.fill();
        ctx.strokeStyle = C.white; ctx.lineWidth = 2 * k; ctx.stroke();
        ctx.fillStyle = C.white; ctx.font = "700 " + (11 * k) + "px 'Segoe UI',sans-serif";
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText("H", p[0], p[1]);
      });
    });

    // 标题栏
    var topH = 62 * scale;
    ctx.fillStyle = "rgba(255,255,255,.95)";
    ctx.fillRect(0, 0, W, topH);
    ctx.strokeStyle = C.rule; ctx.lineWidth = scale;
    ctx.beginPath(); ctx.moveTo(0, topH); ctx.lineTo(W, topH); ctx.stroke();
    ctx.fillStyle = C.ink;
    ctx.font = "700 " + (21 * scale) + "px 'Microsoft YaHei',sans-serif";
    ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillText(t.title || "行程路线", 24 * scale, 26 * scale);
    ctx.fillStyle = C.muted;
    ctx.font = "400 " + (12.5 * scale) + "px 'Microsoft YaHei',sans-serif";
    ctx.fillText(t.city + "　" + t.days.length + " 天　" + (t.stats ? t.stats.spots : 0) + " 个景点　虚线为游览顺序",
      24 * scale, 47 * scale);

    cv.toBlob(function (blob) {
      var u = URL.createObjectURL(blob);
      download(u, (t.title || "行程") + "-地图.png");
      setTimeout(function () { URL.revokeObjectURL(u); }, 4000);
      toast("地图已导出（高德底图）");
    }, "image/png");
  }

  // ---------------------------------------------------------------- 事件绑定
  function bind() {
    $("btnPlan").onclick = generate;
    $("btnRefresh").onclick = function () { showView("home"); };
    if ($("btnBack")) $("btnBack").onclick = function () { showView("home"); };
    $("btnReplan").onclick = replan;
    $("btnAdd").onclick = function () {
      if (!state.trip) return;
      openPoi(state.trip.days[0].index, "spot");
    };
    $("btnAddDay").onclick = addDay;
    $("btnAddDay2").onclick = addDay;
    $("btnFit").onclick = function () {
      if (!state.map) return;
      if (state.mapProvider === "amap") {
        var pts = [];
        state.trip.days.forEach(function (d) { d.items.forEach(function (it) { if (it.kind !== "hotel") pts.push(ptOf(it)); }); });
        fitAmapView(state.map, pts);
        return;
      }
      if (!state.layers.length) return;
      var b = L.latLngBounds([]);
      state.layers.forEach(function (l) { if (l.getLatLng) b.extend(l.getLatLng()); });
      if (b.isValid()) state.map.fitBounds(b, { padding: [36, 36] });
    };
    $("btnMeals").onclick = function () {
      state.showMeals = !state.showMeals;
      $("btnMeals").classList.toggle("primary", state.showMeals);
      $("btnMeals").textContent = state.showMeals ? "餐饮：显示" : "餐饮";
      renderMap();
    };
    $("btnLayer").onclick = function () {
      if (state.mapProvider === "amap") {
        state.tileMode = state.tileMode === "street" ? "satellite" : "street";
        setAmapStyle();
        return;
      }
      state.tileMode = state.tileMode === "street" ? "satellite" : "street";
      $("btnLayer").textContent = state.tileMode === "street" ? "底图：街道" : "底图：卫星";
      applyTileLayer();
    };
    $("btnExport").onclick = function (e) {
      e.stopPropagation();
      $("exportMenu").classList.toggle("hidden");
    };
    document.addEventListener("click", function () {
      $("exportMenu").classList.add("hidden");
    });
    $("exportMenu").querySelectorAll("[data-exp]").forEach(function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        $("exportMenu").classList.add("hidden");
        var m = b.dataset.exp;
        if (!state.trip) return;
        if (m === "pdf") exportPdf();
        else if (m === "print") openPrint();
        else if (m === "map" && state.mapProvider === "amap" && window.AMap) exportAmapStatic();
        else exportPng(m);
      };
    });
    document.querySelectorAll("[data-close]").forEach(function (b) {
      b.onclick = function () { closeModal(b.dataset.close); };
    });
    $("poiKind").onchange = loadPois;
    var tmr = null;
    $("poiSearch").oninput = function () { clearTimeout(tmr); tmr = setTimeout(loadPois, 220); };
    $("poiModal").addEventListener("click", function (e) {
      if (e.target === $("poiModal")) closeModal("poiModal");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { closeModal("poiModal"); closeLightbox(); }
    });
    $("lightbox").onclick = function (e) {
      if (e.target.id === "lightbox" || e.target.id === "lightboxClose") closeLightbox();
    };
  }


  // ---------------------------------------------------------------- 侧栏导航
  function initWorkspaceNav() {
    var nav = $("workspaceNav");
    if (!nav) return;
    var links = Array.prototype.slice.call(nav.querySelectorAll(".nav-item"));
    links.forEach(function (a) {
      a.onclick = function (e) {
        e.preventDefault();
        var target = document.querySelector(a.getAttribute("href"));
        if (!target) return;
        var top = target.getBoundingClientRect().top + window.scrollY - 76;
        window.scrollTo({ top: top, behavior: "smooth" });
        links.forEach(function (x) { x.classList.remove("on"); });
        a.classList.add("on");
      };
    });
    // 滚动时高亮当前分区
    var onScroll = function () {
      var best = links[0], bestTop = -Infinity;
      links.forEach(function (a) {
        var t = document.querySelector(a.getAttribute("href"));
        if (!t) return;
        var top = t.getBoundingClientRect().top - 90;
        if (top <= 0 && top > bestTop) { bestTop = top; best = a; }
      });
      links.forEach(function (x) { x.classList.toggle("on", x === best); });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // ---------------------------------------------------------------- 启动
  function boot() {
    api("/api/health").then(function (h) {
      var pill = $("modelPill");
      var txt = $("modelText");
      if (h.llm.mode === "rule") {
        pill.className = "pill warn";
        txt.textContent = "本地规则模式";
        $("genHint").textContent = h.llm.configured
          ? "已开启强制规则模式：不调用大模型，秒出结果。"
          : "未检测到 DEEPSEEK_API_KEY，将使用本地规则引擎。在 travel-assistant/.env 填入 Key 后可启用 AI。";
      } else {
        pill.className = "pill";
        txt.textContent = "AI 在线，" + h.llm.model;
        $("genHint").textContent = "使用 " + h.llm.model + " 生成，约 30~60 秒；失败会自动降级到本地规则。";
      }
    }).catch(function () {
      $("modelPill").className = "pill bad";
      $("modelText").textContent = "后端未连接";
    });

    api("/api/options").then(function (o) {
      state.options = o;
      initForm();
      loadHistory();
      // 1) 先把行程渲染出来（不依赖地图库）
      var wanted = new URLSearchParams(location.search).get("trip");
      if (wanted) {
        api("/api/trips/" + encodeURIComponent(wanted)).then(function (r) {
          setTrip(r.trip);
        }).catch(function (e) {
          console.error("[ds] load trip failed:", e && e.message);
          toast("打开行程失败：" + (e && e.message), true);
        });
      }
      // 2) 再初始化地图（高德优先，失败回退 Leaflet），就绪后补渲染地图
      api("/api/config").then(function (c) { state.amapConfig = c.map; })
        .catch(function () { state.amapConfig = { provider: "leaflet" }; })
        .then(function () { return initMapProvider(); })
        .catch(function (e) {
          state.mapError = e.message;
          state.mapProvider = "leaflet";
        })
        .then(function () {
          updateMapProviderUI();
          if (state.trip) renderMap();
        });
    }).catch(function (e) {
      toast("无法连接后端：" + e.message + "（请先运行 run.bat）", true);
    });
    bind();
    initWorkspaceNav();
  }

  function updateMapProviderUI() {
    var amap = state.mapProvider === "amap";
    $("btnLayer").textContent = amap ? "底图：纸" : "底图：街道";
    $("mapNote").textContent = amap ? "高德地图，路线按经纬度绘制" : "OpenStreetMap，路线按经纬度绘制";
    if (state.mapError) {
      $("mapNote").textContent = state.mapError;
      toast(state.mapError, true);
    }
    var pill = $("mapProviderPill");
    if (pill) {
      pill.textContent = amap ? "高德地图" : "OSM 底图";
      pill.title = amap ? "高德 JS API 2.0（GCJ-02）" : "OpenStreetMap（WGS-84）";
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
