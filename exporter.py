# -*- coding: utf-8 -*-
"""导出模块：PDF（reportlab）与打印版 HTML。

中文字体：优先用 Windows 自带字体（msyh/simhei），没有则退回 reportlab 内置 CID 字体
（STSong-Light），保证在任何机器上都能出中文。
"""

from __future__ import annotations

import math
import os
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

import bootstrap  # noqa: F401  （把 vendor/ 加入 sys.path）

FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\msyh.ttc", 0),
    (r"C:\Windows\Fonts\simhei.ttf", 0),
    (r"C:\Windows\Fonts\simsun.ttc", 0),
    (r"C:\Windows\Fonts\msyhbd.ttc", 0),
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
]

CN = "CN"
CN_BOLD = "CN-Bold"

_REGISTERED = {"done": False, "ok": False}


def _ensure_font() -> None:
    if _REGISTERED["done"]:
        return
    _REGISTERED["done"] = True
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    for path, idx in FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(CN, path, subfontIndex=idx))
            pdfmetrics.registerFont(TTFont(CN_BOLD, path, subfontIndex=idx))
            _REGISTERED["ok"] = True
            return
        except Exception:
            continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        globals()["CN"] = "STSong-Light"
        globals()["CN_BOLD"] = "STSong-Light"
        _REGISTERED["ok"] = True
    except Exception:
        _REGISTERED["ok"] = False


LAYER_COLORS = ["#2f6fed", "#e8590c", "#0b7285", "#6741d9", "#2b8a3e", "#c2255c", "#5c7cfa"]


def _money(v) -> str:
    try:
        return "¥%s" % format(int(round(float(v))), ",")
    except (TypeError, ValueError):
        return "¥0"


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def build_pdf(trip: dict) -> bytes:
    _ensure_font()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageBreak,
                                    PageTemplate, Paragraph, Spacer, Table, TableStyle)

    font = globals()["CN"]
    font_b = globals()["CN_BOLD"]

    ink = colors.HexColor("#1b2430")
    muted = colors.HexColor("#6b7684")
    line = colors.HexColor("#dfe4ea")
    accent = colors.HexColor("#2f6fed")
    soft = colors.HexColor("#f4f6fa")

    st_title = ParagraphStyle("t", fontName=font_b, fontSize=22, leading=28, textColor=ink)
    st_sub = ParagraphStyle("s", fontName=font, fontSize=10.5, leading=16, textColor=muted)
    st_h1 = ParagraphStyle("h1", fontName=font_b, fontSize=13, leading=19, textColor=ink, spaceBefore=6, spaceAfter=4)
    st_body = ParagraphStyle("b", fontName=font, fontSize=9.5, leading=15, textColor=ink)
    st_note = ParagraphStyle("n", fontName=font, fontSize=8.6, leading=13, textColor=muted)
    st_tiny = ParagraphStyle("ty", fontName=font, fontSize=7.8, leading=11, textColor=muted)
    st_kpi = ParagraphStyle("k", fontName=font_b, fontSize=15, leading=18, textColor=ink, alignment=1)
    st_kpi_l = ParagraphStyle("kl", fontName=font, fontSize=7.6, leading=10, textColor=muted, alignment=1)

    story = []
    days = trip.get("days") or []
    budget = trip.get("budget") or {}
    stats = trip.get("stats") or {}

    # ---- 封面信息 ----
    story.append(Paragraph(escape(trip.get("title") or "我的行程"), st_title))
    span = "%s · %s 起 · %d 天 · %d 人" % (
        trip.get("city"), (days[0].get("date") if days else ""),
        len(days), (trip.get("party") or {}).get("heads", 2))
    story.append(Paragraph(escape(span), st_sub))
    if trip.get("summary"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(escape(trip["summary"]), st_body))

    # ---- KPI 条 ----
    tiles = [
        (_money(budget.get("total", 0)), "总预算"),
        (_money(budget.get("per_person", 0)), "人均"),
        (str(stats.get("spots", 0)), "景点"),
        ("%.0f km" % float(stats.get("km", 0)), "行程里程"),
    ]
    kpi = Table([[Paragraph(escape(a), st_kpi) for a, _ in tiles],
                 [Paragraph(escape(b), st_kpi_l) for _, b in tiles]],
                colWidths=[(170 * mm) / 4.0] * 4)
    kpi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), soft),
        ("BOX", (0, 0), (-1, -1), 0.5, line),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))
    story.append(Spacer(1, 8))
    story.append(kpi)
    story.append(Spacer(1, 10))

    # ---- 地图示意 ----
    route_flow = _map_flowable(trip, mm)
    if route_flow is not None:
        story.append(Paragraph("路线示意", st_h1))
        story.append(route_flow)
        story.append(Spacer(1, 8))

    # ---- 每日行程 ----
    for day in days:
        block = [Paragraph("第 %d 天 · %s　%s %s" % (
            day.get("index", 0), escape(day.get("theme") or ""), day.get("date", ""), day.get("weekday", "")), st_h1)]
        rows = [[Paragraph("<b>时间</b>", st_tiny), Paragraph("<b>安排</b>", st_tiny),
                 Paragraph("<b>花费</b>", st_tiny)]]
        for it in day.get("items") or []:
            kind = it.get("kind")
            icon = {"spot": "●", "meal": "◆", "hotel": "▲"}.get(kind, "·")
            color = {"spot": accent, "meal": colors.HexColor("#e8590c"), "hotel": colors.HexColor("#6741d9")}[kind] \
                if kind in ("spot", "meal", "hotel") else muted
            time_txt = "%s" % it.get("time", "")
            if it.get("transfer"):
                tr = it["transfer"]
                time_txt += "<br/><font size=6.6 color='#8b95a1'>%s %dmin %.1fkm</font>" % (
                    escape(tr.get("mode", "")), int(tr.get("minutes", 0)), float(tr.get("km", 0)))
            if kind == "spot":
                amount = _money(float(it.get("ticket") or 0) * (trip.get("party") or {}).get("heads", 2))
            elif kind == "meal":
                amount = _money(float(it.get("price") or 0) * (trip.get("party") or {}).get("heads", 2))
            else:
                amount = "—"
            detail = "<font color='%s'>%s</font> <b>%s</b>" % (color.hexval().replace("0x", "#"), icon, escape(it.get("name") or ""))
            if it.get("note"):
                detail += "<br/><font size=7.6 color='#6b7684'>%s</font>" % escape(it["note"])
            if it.get("fixed"):
                detail += " <font size=6.6 color='#2f6fed'>[已锁定]</font>"
            rows.append([Paragraph(time_txt, st_note), Paragraph(detail, st_body), Paragraph(amount, st_note)])

        tbl = Table(rows, colWidths=[24 * mm, 108 * mm, 38 * mm])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, ink),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, line),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ]))
        block.append(tbl)
        block.append(Spacer(1, 8))
        story.append(KeepTogether(block) if len(rows) <= 8 else block[0])
        if len(rows) > 8:
            story.append(tbl)

    # ---- 预算明细 ----
    story.append(PageBreak())
    story.append(Paragraph("预算明细", st_h1))
    items = budget.get("items") or []
    total = max(1, int(budget.get("total") or 0))
    brow = [[Paragraph("<b>项目</b>", st_tiny), Paragraph("<b>金额</b>", st_tiny),
             Paragraph("<b>占比</b>", st_tiny), Paragraph("<b>说明</b>", st_tiny)]]
    desc = {
        "ticket": "行程内所有门票 × 人数",
        "hotel": "按档次与房间数估算（每晚）",
        "meal": "人均餐费 × 人数，含档次系数",
        "transit": "站点间打车/公交估算",
        "intercity": budget.get("detail", {}).get("intercity", "") or "往返大交通",
    }
    for it in items:
        pct = it["amount"] / total
        bar = "█" * max(1, int(pct * 18))
        brow.append([Paragraph(escape(it["label"]), st_body), Paragraph(_money(it["amount"]), st_body),
                     Paragraph("<font color='#2f6fed'>%s</font> %.0f%%" % (bar, pct * 100), st_tiny),
                     Paragraph(escape(desc.get(it["key"], "")), st_tiny)])
    brow.append([Paragraph("<b>合计</b>", st_body), Paragraph("<b>%s</b>" % _money(total), st_body),
                 Paragraph("人均 %s" % _money(budget.get("per_person", 0)), st_tiny), Paragraph("", st_tiny)])
    bt = Table(brow, colWidths=[26 * mm, 26 * mm, 54 * mm, 64 * mm])
    bt.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, line),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ink),
        ("LINEBELOW", (0, -2), (-1, -2), 0.3, line),
        ("BACKGROUND", (0, -1), (-1, -1), soft),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(bt)
    if budget.get("over") is not None:
        story.append(Spacer(1, 4))
        msg = "超出预算 %s" % _money(budget["diff"]) if budget.get("over") else "在预算内，余 %s" % _money(-budget["diff"])
        story.append(Paragraph("预算上限 %s —— %s" % (_money(budget.get("limit")), msg),
                               ParagraphStyle("w", parent=st_note, textColor=colors.HexColor("#c92a2a") if budget.get("over") else colors.HexColor("#2b8a3e"))))

    # ---- 住宿清单 ----
    hotels = (budget.get("detail") or {}).get("hotel") or []
    if hotels:
        story.append(Spacer(1, 12))
        story.append(Paragraph("住宿安排", st_h1))
        hrows = [[Paragraph("<b>晚次 / 酒店</b>", st_tiny), Paragraph("<b>单价</b>", st_tiny),
                  Paragraph("<b>房间</b>", st_tiny), Paragraph("<b>小计</b>", st_tiny)]]
        for h in hotels:
            hrows.append([Paragraph(escape(h["name"]), st_body), Paragraph(_money(h["unit"]), st_note),
                          Paragraph(str(h["qty"]), st_note), Paragraph(_money(h["amount"]), st_note)])
        ht = Table(hrows, colWidths=[100 * mm, 26 * mm, 18 * mm, 26 * mm])
        ht.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, ink),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, line),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(ht)

    # ---- 贴士 ----
    tips = trip.get("tips") or []
    if tips:
        story.append(Spacer(1, 12))
        story.append(Paragraph("实用贴士", st_h1))
        for t in tips:
            story.append(Paragraph("· " + escape(str(t)), st_body))

    # ---- 页脚 ----
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    source = "大模型生成 + 本地数据校准" if trip.get("source") == "llm" else "本地规则引擎"
    footer_note = "本行程由「智能旅行助手」于 %s 生成（%s）。门票/餐饮/房价为估算值，请以官方渠道为准。" % (generated, source)

    def _decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 7.4)
        canvas.setFillColor(muted)
        canvas.drawString(20 * mm, 12 * mm, footer_note[:90])
        canvas.drawRightString(190 * mm, 12 * mm, "%d / %s" % (canvas.getPageNumber(), escape(trip.get("city") or "")))
        canvas.setStrokeColor(line)
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 16 * mm, 190 * mm, 16 * mm)
        canvas.restoreState()

    buf = BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                          topMargin=18 * mm, bottomMargin=22 * mm,
                          title=trip.get("title") or "行程", author="智能旅行助手")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="n")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=_decorate)])
    doc.build(story)
    return buf.getvalue()


def _map_flowable(trip: dict, mm):
    """把行程里的点投影到一张示意图上（无底图，纯几何，指向真实相对位置）。"""
    pts = []
    for di, day in enumerate(trip.get("days") or []):
        n = 0
        for it in day.get("items") or []:
            if it.get("kind") == "spot":
                n += 1
                pts.append((it["lon"], it["lat"], "%d-%d" % (day.get("index", di + 1), n), di))
    if len(pts) < 2:
        return None
    from reportlab.graphics.shapes import Drawing, Circle, Line, String, Polygon, Rect
    from reportlab.lib import colors

    lon0 = min(p[0] for p in pts)
    lon1 = max(p[0] for p in pts)
    lat0 = min(p[1] for p in pts)
    lat1 = max(p[1] for p in pts)
    span_lon = max(1e-4, lon1 - lon0)
    span_lat = max(1e-4, lat1 - lat0)
    W, H = 170 * mm, 62 * mm
    pad = 10 * mm

    def xy(lon, lat):
        # 纬度越大越靠上；保持经纬比例（按 cos(lat) 修正经向）
        x = pad + (lon - lon0) / span_lon * (W - 2 * pad)
        y = pad + (lat - lat0) / span_lat * (H - 2 * pad)
        return x, y

    d = Drawing(W, H)
    d.add(Rect(0, 0, W, H, fillColor=colors.HexColor("#f7f9fc"), strokeColor=colors.HexColor("#dfe4ea")))
    prev = None
    for i, (lon, lat, label, di) in enumerate(pts):
        x, y = xy(lon, lat)
        if prev:
            d.add(Line(prev[0], prev[1], x, y, strokeColor=colors.HexColor("#c9d3e3"), strokeWidth=1.1))
        prev = (x, y)
    for i, (lon, lat, label, di) in enumerate(pts):
        x, y = xy(lon, lat)
        c = colors.HexColor(LAYER_COLORS[di % len(LAYER_COLORS)])
        d.add(Circle(x, y, 6.2, fillColor=c, strokeColor=colors.white, strokeWidth=1.2))
        d.add(String(x, y - 2.4, label, fontName="Helvetica-Bold", fontSize=6.2,
                     fillColor=colors.white, textAnchor="middle"))
    return d


# --------------------------------------------------------------------------- #
# 打印版 HTML（浏览器可直接“打印为 PDF”或整页截图）
# --------------------------------------------------------------------------- #
def build_print_html(trip: dict) -> str:
    days = trip.get("days") or []
    budget = trip.get("budget") or {}
    stats = trip.get("stats") or {}
    items = budget.get("items") or []
    total = max(1, int(budget.get("total") or 0))

    day_html = []
    for day in days:
        rows = []
        for it in day.get("items") or []:
            kind = it.get("kind")
            cls = {"spot": "spot", "meal": "meal", "hotel": "hotel"}.get(kind, "")
            if kind == "spot":
                amount = "¥%d" % int(float(it.get("ticket") or 0) * (trip.get("party") or {}).get("heads", 2))
            elif kind == "meal":
                amount = "¥%d" % int(float(it.get("price") or 0) * (trip.get("party") or {}).get("heads", 2))
            else:
                amount = "—"
            tr = ""
            if it.get("transfer"):
                t = it["transfer"]
                tr = '<div class="tr">↓ %s %d 分钟 · %.1f km</div>' % (
                    escape(t.get("mode", "")), int(t.get("minutes", 0)), float(t.get("km", 0)))
            rows.append(
                '%s<li class="%s"><div class="time">%s</div><div class="body"><b>%s</b>'
                '<div class="note">%s</div></div><div class="amt">%s</div></li>'
                % (tr, cls, escape(it.get("time", "")), escape(it.get("name") or "酒店"), escape(it.get("note") or ""), amount))
        day_html.append(
            '<section class="day"><h2>第 %d 天 · %s<span>%s %s</span></h2><ul>%s</ul></section>'
            % (day.get("index", 0), escape(day.get("theme") or ""), day.get("date", ""), day.get("weekday", ""),
               "".join(rows)))

    budget_html = "".join(
        '<tr><td>%s</td><td class="r">¥%s</td><td class="r">%.0f%%</td></tr>'
        % (escape(i["label"]), format(int(i["amount"]), ","), i["amount"] / total * 100) for i in items)
    tips_html = "".join("<li>%s</li>" % escape(str(t)) for t in (trip.get("tips") or []))

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>%s · %s</title>
<style>
  @page { size: A4; margin: 14mm; }
  * { box-sizing: border-box; }
  body { font-family: "Microsoft YaHei","PingFang SC","Hiragino Sans GB",sans-serif; color:#1b2430; margin:0; background:#eef1f6; }
  .sheet { width:210mm; min-height:297mm; margin:16px auto; background:#fff; padding:16mm; box-shadow:0 6px 28px rgba(20,30,50,.12); }
  h1 { font-size:26px; margin:0 0 6px; }
  .sub { color:#6b7684; font-size:12px; }
  .lead { margin:10px 0 14px; font-size:12.5px; line-height:1.7; }
  .kpis { display:flex; gap:10px; margin:14px 0 18px; }
  .kpi { flex:1; background:#f4f6fa; border:1px solid #e3e8f0; border-radius:10px; padding:10px; text-align:center; }
  .kpi b { display:block; font-size:19px; }
  .kpi span { color:#6b7684; font-size:10px; }
  .day { margin:16px 0; page-break-inside:avoid; }
  .day h2 { font-size:15px; margin:0 0 8px; padding-bottom:6px; border-bottom:2px solid #1b2430; display:flex; justify-content:space-between; }
  .day h2 span { font-weight:400; font-size:10.5px; color:#6b7684; }
  ul { list-style:none; margin:0; padding:0; }
  li { display:flex; gap:10px; padding:7px 0; border-bottom:1px dashed #e3e8f0; font-size:12px; align-items:flex-start; }
  li .time { width:44px; color:#6b7684; font-size:11px; padding-top:2px; font-variant-numeric:tabular-nums; }
  li .body { flex:1; }
  li .body b { font-weight:600; }
  li.spot .body b { color:#2f6fed; }
  li.meal .body b { color:#e8590c; }
  li.hotel .body b { color:#6741d9; }
  li .note { color:#6b7684; font-size:10.5px; margin-top:2px; line-height:1.5; }
  li .amt { width:64px; text-align:right; color:#3c4552; font-size:11px; padding-top:2px; }
  .tr { font-size:9.5px; color:#9aa4b2; padding-left:54px; }
  .grid { display:flex; gap:16px; page-break-inside:avoid; }
  .grid > div { flex:1; }
  table { width:100%%; border-collapse:collapse; font-size:11.5px; }
  th,td { text-align:left; padding:6px 4px; border-bottom:1px solid #e3e8f0; }
  th { font-size:10px; color:#6b7684; font-weight:600; border-bottom:1.5px solid #1b2430; }
  td.r, th.r { text-align:right; }
  .tips li { font-size:11.5px; color:#3c4552; }
  footer { margin-top:18px; border-top:1px solid #e3e8f0; padding-top:8px; color:#9aa4b2; font-size:9.5px; }
  @media print { body{background:#fff;} .sheet{box-shadow:none;margin:0;width:auto;min-height:0;padding:0;} }
</style></head><body><div class="sheet">
<h1>%s</h1>
<div class="sub">%s · %s 起 · %d 天 · %d 人</div>
<p class="lead">%s</p>
<div class="kpis">
  <div class="kpi"><b>¥%s</b><span>总预算</span></div>
  <div class="kpi"><b>¥%s</b><span>人均</span></div>
  <div class="kpi"><b>%d</b><span>景点</span></div>
  <div class="kpi"><b>%.0f km</b><span>行程里程</span></div>
</div>
%s
<div class="grid">
  <div><h2>预算明细</h2><table><thead><tr><th>项目</th><th class="r">金额</th><th class="r">占比</th></tr></thead>
  <tbody>%s<tr><td><b>合计</b></td><td class="r"><b>¥%s</b></td><td class="r">100%%</td></tr></tbody></table></div>
  <div><h2>实用贴士</h2><ul class="tips">%s</ul></div>
</div>
<footer>本行程由「智能旅行助手」于 %s 生成（%s）。门票/餐饮/房价为估算值，请以官方渠道为准。</footer>
</div></body></html>""" % (
        escape(trip.get("title") or "行程"), escape(trip.get("city") or ""),
        escape(trip.get("title") or "我的行程"),
        escape(trip.get("city") or ""), (days[0].get("date") if days else ""), len(days),
        (trip.get("party") or {}).get("heads", 2),
        escape(trip.get("summary") or ""),
        format(int(budget.get("total") or 0), ","), format(int(budget.get("per_person") or 0), ","),
        stats.get("spots", 0), float(stats.get("km", 0)),
        "".join(day_html), budget_html, format(int(budget.get("total") or 0), ","), tips_html,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "大模型生成 + 本地数据校准" if trip.get("source") == "llm" else "本地规则引擎",
    )
