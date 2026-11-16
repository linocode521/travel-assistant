# -*- coding: utf-8 -*-
"""智能旅行助手 · 后端服务（Flask）。

启动：  python server.py            # http://127.0.0.1:8766
       python server.py --open     # 启动并自动打开浏览器
       python server.py --demo     # 强制本地规则模式（不消耗模型额度）

接口：
  GET  /api/health                健康检查 / 模型可用性
  GET  /api/options               城市、偏好、节奏、档次等可选项
  POST /api/plan                  生成行程（LLM，失败自动降级规则引擎）
  GET  /api/trips                 历史行程列表
  GET  /api/trips/<id>            读取行程
  PATCH /api/trips/<id>           编辑行程（整体替换 days / 元信息）
  POST /api/trips/<id>/items      添加景点/餐厅/酒店
  DELETE /api/trips/<id>/items/<key>  删除某一项
  POST /api/trips/<id>/items/<key>/move   上移/下移
  PATCH /api/trips/<id>/items/<key>       修改单项（时间锁、备注）
  POST /api/trips/<id>/replan     按新条件重排（保留锁定项）
  GET  /api/pois?city=北京&q=...  搜索 POI（“添加景点”时用）
  GET  /api/trips/<id>/export.pdf 导出 PDF
  GET  /api/trips/<id>/export.html 导出打印版 HTML
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import traceback
import uuid
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional

# 本机 pip 对系统 site-packages 无写权限，依赖装在项目内的 vendor/ 目录里。
# 放在所有第三方 import 之前，保证双击 run.bat / 直接 python server.py 都能跑起来。
_BASE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_BASE, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
sys.path.insert(0, _BASE)

from flask import Flask, jsonify, request, send_from_directory, Response

import poi_data as db
import planner
import exporter
import poi_photos

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
STORAGE = os.path.join(DATA_DIR, "trips.json")

app = Flask(__name__, static_folder=None)
app.config["JSON_AS_ASCII"] = False
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

FORCE_RULE = False
_LOCK = threading.Lock()
_TRIPS: Dict[str, dict] = {}


# --------------------------------------------------------------------------- #
# 存储
# --------------------------------------------------------------------------- #
def load_trips() -> None:
    if not os.path.exists(STORAGE):
        return
    try:
        with open(STORAGE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print("[warn] 读取历史行程失败：%s" % exc)
        return
    if not isinstance(data, list):
        return
    for t in data:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        # 旧数据可能没有 GCJ-02 坐标：加载时补一次，切高德底图才不会偏
        try:
            planner.attach_gcj(t)
            index_items(t)
            # 旧行程里存的是当时的预算结构，重算一遍让文案/口径跟当前版本一致
            t["budget"] = planner.compute_budget(t)
            t["stats"] = planner.compute_stats(t)
        except Exception:
            pass
        _TRIPS[t["id"]] = t


def save_trips() -> None:
    items = sorted(_TRIPS.values(), key=lambda t: t.get("created_at") or "", reverse=True)[:50]
    try:
        tmp = STORAGE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, STORAGE)
    except OSError as exc:
        print("[warn] 保存历史行程失败：%s" % exc)


def get_trip(trip_id: str) -> Optional[dict]:
    return _TRIPS.get(trip_id)


def refresh(trip: dict) -> dict:
    """任何编辑之后：重排时间轴 → 重算预算与统计 → 补坐标 → 落盘。"""
    planner.attach_gcj(trip)
    for day in trip["days"]:
        planner.schedule_day(day)
    planner.attach_gcj(trip)
    trip["budget"] = planner.compute_budget(trip)
    trip["stats"] = planner.compute_stats(trip)
    trip["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with _LOCK:
        _TRIPS[trip["id"]] = trip
        save_trips()
    return trip


def item_key(day_index: int, item: dict) -> str:
    return "d%d:%s" % (day_index, item.get("ref") or uuid.uuid4().hex[:6])


def index_items(trip: dict) -> None:
    planner.attach_gcj(trip)
    for day in trip["days"]:
        for it in day["items"]:
            it["key"] = item_key(day["index"], it)
            it.setdefault("fixed", False)


# --------------------------------------------------------------------------- #
# HTTP 基础
# --------------------------------------------------------------------------- #
@app.after_request
def add_cors(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def cors_preflight(_any: str):
    return ("", 204)


def err(message: str, code: int = 400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), code


# --------------------------------------------------------------------------- #
# 静态页
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/favicon.ico")
def favicon():
    # 内联 SVG 当站点图标，省一个文件、也省掉一条 404 噪音
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
        "<rect width='64' height='64' rx='14' fill='#0f766e'/>"
        "<text x='32' y='45' font-size='34' text-anchor='middle' fill='#ffffff'>✈</text></svg>"
    )
    return Response(svg, mimetype="image/svg+xml")


@app.route("/<path:filename>")
def static_files(filename: str):
    safe = os.path.normpath(filename).replace("\\", "/")
    if safe.startswith("..") or safe.startswith("/"):
        return err("非法路径", 403)
    return send_from_directory(BASE_DIR, safe)


# --------------------------------------------------------------------------- #
# 元信息
# --------------------------------------------------------------------------- #
@app.route("/api/health")
def health():
    planner.load_env_file()
    key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    return jsonify({
        "ok": True,
        "service": "travel-assistant",
        "version": "1.0.0",
        "llm": {
            "configured": bool(key),
            "model": os.getenv("LLM_MODEL") or "deepseek-flash",
            "mode": "rule" if FORCE_RULE else ("auto" if key else "rule"),
        },
        "time": datetime.now().isoformat(timespec="seconds"),
    })


@app.route("/api/options")
def options():
    return jsonify({
        "ok": True,
        "cities": db.all_cities_summary(),
        "styles": [{"key": k, "label": v} for k, v in planner.STYLE_LABEL.items()],
        "paces": [
            {"key": "relaxed", "label": "轻松", "hint": "每天 2 个景点，留足休息"},
            {"key": "moderate", "label": "适中", "hint": "每天 2~3 个景点"},
            {"key": "intense", "label": "紧凑", "hint": "每天 3~4 个景点，早起晚归"},
        ],
        "tiers": [{"key": k, "label": v["label"]} for k, v in planner.TIER_PRICE.items()],
        "defaults": {"city": "北京", "days": 3, "pace": "moderate", "tier": "comfort", "styles": ["history"]},
        "limits": {"days": [1, 7], "adults": [1, 12], "children": [0, 8]},
    })


@app.route("/api/config")
def config():
    """前端地图配置。

    配了 AMAP_KEY 就用高德官方底图（需要 Web 端 JS API Key + 安全密钥），
    否则前端自动退回 Leaflet + OpenStreetMap。Key 只从 .env 读，不写死在前端。
    """
    amap_key = (os.getenv("AMAP_KEY") or os.getenv("AMAP_JS_KEY") or "").strip()
    security = (os.getenv("AMAP_SECURITY_CODE") or os.getenv("AMAP_SECURITY") or "").strip()
    return jsonify({
        "ok": True,
        "map": {
            "provider": "amap" if amap_key else "leaflet",
            "amap": {
                "key": amap_key,
                "securityCode": security,
                "version": os.getenv("AMAP_VERSION") or "2.0",
            },
            "coord": "gcj02" if amap_key else "wgs84",
        },
    })


# --------------------------------------------------------------------------- #
# 生成行程
# --------------------------------------------------------------------------- #
@app.route("/api/plan", methods=["POST"])
def plan():
    payload = request.get_json(silent=True) or {}
    try:
        req = planner.normalize_req(payload)
    except Exception as exc:
        return err("参数不合法：%s" % exc)

    mode = "rule" if (FORCE_RULE or payload.get("mode") == "rule") else "auto"
    try:
        trip = planner.build_plan(req, mode=mode)
    except planner.LLMError as exc:
        return err("模型调用失败：%s" % exc, 502, hint="可勾选“本地规则模式”继续体验")
    except Exception as exc:
        traceback.print_exc()
        return err("生成行程出错：%s" % exc, 500)

    index_items(trip)
    # 「先秒出、后台升级」：AI 版覆盖同一条规则版记录，历史里不留两条
    reuse_id = payload.get("reuse_id")
    with _LOCK:
        if reuse_id and reuse_id in _TRIPS:
            trip["id"] = reuse_id
            trip["created_at"] = _TRIPS[reuse_id].get("created_at") or trip.get("created_at")
            trip["upgraded"] = True
        _TRIPS[trip["id"]] = trip
        save_trips()
    trip["item_count"] = sum(len(d["items"]) for d in trip["days"])
    return jsonify({"ok": True, "trip": trip})


# --------------------------------------------------------------------------- #
# 行程读取 / 编辑
# --------------------------------------------------------------------------- #
@app.route("/api/trips")
def list_trips():
    items = sorted(_TRIPS.values(), key=lambda t: t.get("created_at") or "", reverse=True)
    slim = [{
        "id": t["id"], "title": t.get("title"), "city": t.get("city"),
        "created_at": t.get("created_at"), "source": t.get("source"),
        "days": len(t.get("days", [])), "total": (t.get("budget") or {}).get("total"),
        "spots": (t.get("stats") or {}).get("spots"),
    } for t in items]
    return jsonify({"ok": True, "trips": slim})


@app.route("/api/trips/<trip_id>")
def read_trip(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    return jsonify({"ok": True, "trip": trip})


@app.route("/api/trips/<trip_id>", methods=["PATCH"])
def patch_trip(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    body = request.get_json(silent=True) or {}
    for field in ("title", "summary", "tips", "req"):
        if field in body:
            trip[field] = body[field]
    if "days" in body and isinstance(body["days"], list):
        if len(body["days"]) == 0:
            return err("行程至少保留一天", 400)
        trip["days"] = body["days"]
        index_items(trip)
    refresh(trip)
    return jsonify({"ok": True, "trip": trip})


def _find_item(trip: dict, key: str):
    for day in trip["days"]:
        for it in day["items"]:
            if it.get("key") == key:
                return day, it
    return None, None


@app.route("/api/trips/<trip_id>/items", methods=["POST"])
def add_item(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    ref = body.get("ref")
    day_no = int(body.get("day") or 1)
    day = next((d for d in trip["days"] if d["index"] == day_no), trip["days"][0])
    city = trip["city"]

    if kind == "spot":
        s = db.spot_index(city).get(ref)
        if not s:
            return err("景点不存在：%s" % ref, 404)
        if any(i.get("ref") == s["id"] for d in trip["days"] for i in d["items"]):
            return err("这个景点已经在行程里了", 409)
        item = {"kind": "spot", "ref": s["id"], "name": s["name"], "lon": s["lon"], "lat": s["lat"],
                "ticket": s["ticket"], "duration": s["hours"], "tags": s["tags"], "open": s.get("open"),
                "note": body.get("note") or s.get("note") or "", "fixed": False}
    elif kind == "meal":
        e = db.eatery_index(city).get(ref)
        if not e:
            return err("餐厅不存在：%s" % ref, 404)
        item = {"kind": "meal", "ref": e["id"], "name": e["name"], "lon": e["lon"], "lat": e["lat"],
                "price": e["price"], "meal": body.get("meal") or "lunch", "cuisine": e.get("cuisine"),
                "duration": 1.5, "note": body.get("note") or e.get("note") or "", "fixed": False}
    elif kind == "hotel":
        h = db.hotel_for(city, trip.get("tier", "comfort"))
        item = {"kind": "hotel", "ref": h["id"], "name": h["name"], "lon": h["lon"], "lat": h["lat"],
                "price": h["price"], "duration": 0, "note": body.get("note") or "返回酒店休息", "fixed": False}
        day["items"] = [i for i in day["items"] if i["kind"] != "hotel"]
    else:
        return err("kind 只能是 spot / meal / hotel", 400)

    pos = body.get("position")
    if pos == "start":
        day["items"].insert(0, item)
    elif pos == "end":
        day["items"].append(item)
    else:
        # 默认插在最后一个景点之后（hotel 之前）
        idx = len(day["items"])
        for i, it in enumerate(day["items"]):
            if it["kind"] == "hotel":
                idx = i
                break
        if item["kind"] == "hotel":
            idx = len(day["items"])
        day["items"].insert(idx, item)

    index_items(trip)
    refresh(trip)
    return jsonify({"ok": True, "trip": trip})


@app.route("/api/trips/<trip_id>/items/<key>", methods=["DELETE"])
def delete_item(trip_id: str, key: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    found = False
    for day in trip["days"]:
        before = len(day["items"])
        day["items"] = [i for i in day["items"] if i.get("key") != key]
        if len(day["items"]) != before:
            found = True
    if not found:
        return err("没有这一项", 404)
    refresh(trip)
    return jsonify({"ok": True, "trip": trip})


@app.route("/api/trips/<trip_id>/items/<key>", methods=["PATCH"])
def patch_item(trip_id: str, key: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    day, item = _find_item(trip, key)
    if not item:
        return err("没有这一项", 404)
    body = request.get_json(silent=True) or {}
    if "note" in body:
        item["note"] = str(body["note"])[:120]
    if "fixed" in body:
        item["fixed"] = bool(body["fixed"])
    if "duration" in body:
        try:
            item["duration"] = max(0.25, min(float(body["duration"]), 12.0))
        except (TypeError, ValueError):
            pass
    if "time" in body and isinstance(body["time"], str):
        item["time"] = body["time"]
        item["fixed"] = True
    refresh(trip)
    return jsonify({"ok": True, "trip": trip})


@app.route("/api/trips/<trip_id>/items/<key>/move", methods=["POST"])
def move_item(trip_id: str, key: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    body = request.get_json(silent=True) or {}
    direction = body.get("direction", "up")
    target_day = body.get("day")
    for day in trip["days"]:
        idx = next((i for i, it in enumerate(day["items"]) if it.get("key") == key), None)
        if idx is None:
            continue
        if target_day and target_day != day["index"]:
            # 跨天移动
            dst = next((d for d in trip["days"] if d["index"] == int(target_day)), None)
            if not dst:
                return err("目标天不存在", 400)
            item = day["items"].pop(idx)
            dst["items"].insert(max(0, len(dst["items"]) - 1), item)
        elif direction == "up" and idx > 0:
            day["items"][idx - 1], day["items"][idx] = day["items"][idx], day["items"][idx - 1]
        elif direction == "down" and idx < len(day["items"]) - 1:
            day["items"][idx + 1], day["items"][idx] = day["items"][idx], day["items"][idx + 1]
        break
    refresh(trip)
    return jsonify({"ok": True, "trip": trip})


@app.route("/api/trips/<trip_id>/days", methods=["POST"])
def add_day(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    last = trip["days"][-1]
    h = db.hotel_for(trip["city"], trip.get("tier", "comfort"))
    try:
        from datetime import date, timedelta
        d = date.fromisoformat(last["date"]) + timedelta(days=1)
        date_iso, weekday = d.isoformat(), "周" + "一二三四五六日"[d.weekday()]
    except Exception:
        date_iso, weekday = last["date"], last["weekday"]
    day = {"index": last["index"] + 1, "date": date_iso, "weekday": weekday,
           "theme": "第 %d 天" % (last["index"] + 1),
           "items": [{"kind": "hotel", "ref": h["id"], "name": h["name"], "lon": h["lon"], "lat": h["lat"],
                      "price": h["price"], "duration": 0, "note": "返回酒店休息", "fixed": False}]}
    trip["days"].append(day)
    index_items(trip)
    refresh(trip)
    return jsonify({"ok": True, "trip": trip})


@app.route("/api/trips/<trip_id>/days/<int:day_no>", methods=["DELETE"])
def delete_day(trip_id: str, day_no: int):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    if len(trip["days"]) <= 1:
        return err("至少保留一天", 400)
    trip["days"] = [d for d in trip["days"] if d["index"] != day_no]
    for i, d in enumerate(trip["days"], 1):
        d["index"] = i
    index_items(trip)
    refresh(trip)
    return jsonify({"ok": True, "trip": trip})


@app.route("/api/trips/<trip_id>/replan", methods=["POST"])
def replan(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    body = request.get_json(silent=True) or {}
    req = dict(trip["req"])
    for k in ("city", "days", "start_date", "styles", "pace", "tier", "party", "budget", "preference", "origin"):
        if k in body:
            req[k] = body[k]
    if body.get("keep_locked", True):
        locked = planner.collect_locked(trip)
    else:
        locked = set()
    new_req = planner.normalize_req(req)
    mode = "rule" if FORCE_RULE or body.get("mode") == "rule" else "auto"
    try:
        new_trip = planner.build_plan(new_req, mode=mode)
    except planner.LLMError as exc:
        return err("模型调用失败：%s" % exc, 502)
    for day in new_trip["days"]:
        for it in day["items"]:
            if it.get("ref") in locked:
                it["fixed"] = True
        planner.schedule_day(day)
    new_trip["budget"] = planner.compute_budget(new_trip)
    new_trip["stats"] = planner.compute_stats(new_trip)
    index_items(new_trip)
    if body.get("replace", True):
        old_id = trip["id"]
        new_trip["id"] = old_id
        new_trip["created_at"] = trip.get("created_at") or new_trip["created_at"]
        with _LOCK:
            _TRIPS[old_id] = new_trip
            save_trips()
        return jsonify({"ok": True, "trip": new_trip})
    with _LOCK:
        _TRIPS[new_trip["id"]] = new_trip
        save_trips()
    return jsonify({"ok": True, "trip": new_trip})


# --------------------------------------------------------------------------- #
# POI 搜索 / 导出
# --------------------------------------------------------------------------- #
@app.route("/api/pois")
def search_pois():
    city = request.args.get("city") or "北京"
    q = (request.args.get("q") or "").strip().lower()
    kind = request.args.get("kind") or "spot"
    pool: List[dict] = []
    if kind == "spot":
        pool = db.SPOTS.get(city, [])
    elif kind == "meal":
        pool = db.EATERIES.get(city, [])
    out = []
    for p in pool:
        hay = (p["name"] + p.get("cuisine", "") + " ".join(p.get("tags", []))).lower()
        if q and q not in hay:
            continue
        out.append(p)
    return jsonify({"ok": True, "city": city, "kind": kind, "pois": out[:40]})


CITY_LANDMARK = {
    "北京": "天安门广场", "上海": "外滩", "杭州": "西湖（断桥—白堤）",
    "成都": "宽窄巷子", "西安": "西安城墙", "广州": "广州塔",
}


@app.route("/api/city-photo")
def city_photo():
    """重定向到该城市的代表地标实拍图，给首页空状态用。"""
    city = (request.args.get("city") or "北京").strip()
    name = CITY_LANDMARK.get(city)
    if not name:
        spots = db.SPOTS.get(city) or db.SPOTS["北京"]
        name = spots[0]["name"]
    info = poi_photos.lookup(city, name)
    url = info.get("photo") or ""
    if not url:
        return ("", 404)
    from flask import redirect
    return redirect(url, code=302)


@app.route("/api/poi-info")
def poi_info():
    """景点实拍图与补充信息（地址、评分、开放时间），带缓存。"""
    city = (request.args.get("city") or "").strip()
    name = (request.args.get("name") or "").strip()
    if not name:
        return err("缺少 name", 400)
    info = poi_photos.lookup(city, name)
    return jsonify({"ok": True, "photo": info.get("photo", ""),
                    "address": info.get("address", ""),
                    "rating": info.get("rating", ""),
                    "open": info.get("open", "")})


@app.route("/api/trips/<trip_id>/export.pdf")
def export_pdf(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    try:
        data = exporter.build_pdf(trip)
    except Exception as exc:
        traceback.print_exc()
        return err("PDF 生成失败：%s" % exc, 500)
    fname = "%s-%s.pdf" % (trip.get("title", "行程").replace("/", "_"), trip["city"])
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = "attachment; filename*=UTF-8''%s" % _url_quote(fname)
    return resp


@app.route("/api/trips/<trip_id>/export.html")
def export_html(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    html = exporter.build_print_html(trip)
    return Response(html, mimetype="text/html; charset=utf-8")


# --------------------------------------------------------------------------- #
# 高德静态图（导出地图 PNG 用）
# 高德 JS API 2.0 已不再提供 StaticMap 插件，改为后端调 Web 服务 API，
# 把底图渲染好再交给前端叠路线——Key 也就不用暴露给浏览器。
# --------------------------------------------------------------------------- #
def _merc(lon: float, lat: float, z: int):
    n = 256.0 * (2 ** z)
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


@app.route("/api/trips/<trip_id>/staticmap.json")
def static_map(trip_id: str):
    trip = get_trip(trip_id)
    if not trip:
        return err("行程不存在", 404)
    key = (os.getenv("AMAP_KEY") or os.getenv("AMAP_JS_KEY") or "").strip()
    if not key:
        return err("未配置 AMAP_KEY，无法生成高德底图", 400)

    W, H = 1024, 760
    pts = []          # (lon, lat, label, kind)
    spot_seq = 0
    for day in trip.get("days") or []:
        for it in day.get("items") or []:
            lon = it.get("lon_g") or it.get("lon")
            lat = it.get("lat_g") or it.get("lat")
            if lon is None or lat is None:
                continue
            if it.get("kind") == "spot":
                spot_seq += 1
                pts.append((float(lon), float(lat), str(spot_seq), "spot"))
            elif it.get("kind") == "hotel":
                pts.append((float(lon), float(lat), "H", "hotel"))
    if not pts:
        return err("行程里还没有可标注的点", 400)

    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    center = ((min(lons) + max(lons)) / 2.0, (min(lats) + max(lats)) / 2.0)
    zoom = 11
    for z in range(17, 8, -1):
        xs = [_merc(lo, la, z)[0] for lo, la in zip(lons, lats)]
        ys = [_merc(lo, la, z)[1] for lo, la in zip(lons, lats)]
        if (max(xs) - min(xs)) <= W * 0.62 and (max(ys) - min(ys)) <= H * 0.58:
            zoom = z
            break

    markers = "|".join(
        "mid,0x1677ff,%s:%.6f,%.6f" % (lab, lo, la) if kind == "spot"
        else "mid,0x7048e8,%s:%.6f,%.6f" % (lab, lo, la)
        for lo, la, lab, kind in pts
    )
    try:
        import requests
        r = requests.get(
            "https://restapi.amap.com/v3/staticmap",
            params={
                "location": "%.6f,%.6f" % center,
                "zoom": zoom,
                "size": "%d*%d" % (W, H),
                "scale": 2,
                # 只出底图；标记与路线由前端 canvas 绘制，保证和页面样式完全一致
                "key": key,
            },
            timeout=20,
        )
    except Exception as exc:
        return err("高德静态图请求失败：%s" % exc, 502)
    ctype = r.headers.get("Content-Type", "")
    if not ctype.startswith("image"):
        info = ""
        try:
            info = r.json().get("info", "")
        except Exception:
            info = r.text[:120]
        return err("高德静态图返回异常：%s（可能是 Key 不支持 Web 服务 API）" % info, 502)

    # 读出图片真实尺寸，前端按这个尺寸做投影，路线才不会错位
    import struct
    w, h = W, H
    try:
        if r.content[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", r.content[16:24])
    except Exception:
        pass
    import base64
    return jsonify({
        "ok": True,
        "dataUrl": "data:image/png;base64," + base64.b64encode(r.content).decode("ascii"),
        "center": center,
        "zoom": zoom,
        "width": w,
        "height": h,
        "logicalWidth": W,
        "logicalHeight": H,
    })


def _url_quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text)


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #
def main() -> None:
    global FORCE_RULE
    ap = argparse.ArgumentParser(description="智能旅行助手后端")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--demo", action="store_true", help="强制本地规则模式，不调用大模型")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    planner.load_env_file()
    if args.demo:
        FORCE_RULE = True
    load_trips()

    url = "http://%s:%d" % (args.host, args.port)
    print("─" * 56)
    print(" 智能旅行助手 已启动  %s" % url)
    print(" 模型模式：%s" % ("本地规则（--demo）" if FORCE_RULE else (
        "自动（LLM 优先，失败降级规则）" if (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
        else "本地规则（未检测到 API Key）")))
    print(" 历史行程：%d 条" % len(_TRIPS))
    print("─" * 56)
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
