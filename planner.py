# -*- coding: utf-8 -*-
"""行程规划：大模型负责"选与排"，本地库负责"准与算"。

流程：
  用户输入 ──► 提示词（带候选景点/餐厅清单） ──► DeepSeek 返回 JSON
       ──► 校验 + 用 POI 库补全真实经纬度/门票/时长
       ──► 排时间轴（早中晚） ──► 计算预算 ──► 返回 itinerary

如果模型调用失败（没网/没 Key/返回不合法），自动降级成本地规则引擎，
保证"永远有结果"。降级时返回 source="rule"，前端会明确标注。
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import bootstrap  # noqa: F401  （把 vendor/ 加入 sys.path）
import coords
import poi_data as db

PACE_SPOTS = {"relaxed": (2, 2), "moderate": (2, 3), "intense": (3, 4)}  # (每日最少, 最多) 景点数

TIER_PRICE = {
    "economy": {"label": "经济型", "food": 0.75},
    "comfort": {"label": "舒适型", "food": 1.0},
    "premium": {"label": "高端型", "food": 1.6},
}

STYLE_LABEL = {
    "history": "历史人文", "nature": "自然风光", "food": "美食探店",
    "art": "艺术文艺", "family": "亲子休闲", "night": "夜景城市",
    "shopping": "购物打卡",
}

MEAL_TIMES = {"breakfast": ("08:00", 1.0), "lunch": ("12:00", 1.5), "dinner": ("18:00", 1.5)}


# --------------------------------------------------------------------------- #
# 几何 & 交通估算
# --------------------------------------------------------------------------- #
def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def transfer_estimate(km: float) -> Dict:
    """一段位移的时间与打车费用估算。"""
    if km <= 1.2:
        return {"mode": "步行", "minutes": max(5, int(km * 13)), "cost": 0.0}
    if km > 20:
        # 远郊（长城、青城山、兵马俑这类）：按包车/长途往返计
        minutes = int(km / 55.0 * 60) + 20
        cost = round(60.0 + km * 2.4, 1)
        return {"mode": "远郊包车", "minutes": max(40, minutes), "cost": cost}
    if km <= 4.0:
        mode, kmh = "公交/地铁", 16
        cost = db.TRANSIT_PER_MOVE
    else:
        mode, kmh = "打车", 26
        cost = round(db.TAXI_START + max(0.0, km - 3.0) * db.TAXI_PER_KM, 1)
    minutes = int(km / kmh * 60) + 8
    return {"mode": mode, "minutes": max(8, minutes), "cost": cost}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(total: int) -> str:
    total = max(0, min(total, 23 * 60 + 59))
    return "%02d:%02d" % (total // 60, total % 60)


# --------------------------------------------------------------------------- #
# 提示词
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """你是资深的中国旅行规划师。根据用户条件，从给定候选清单中挑选景点与餐厅，
排出每天的时间轴。只输出 JSON，不要任何解释、不要 markdown 代码块。

输出 JSON 结构：
{
  "title": "行程标题，12字以内，有画面感",
  "summary": "两句话概括这趟行程的调性",
  "tips": ["3~5条实用提醒，如预约、穿着、避坑"],
  "days": [
    {
      "theme": "当天主题，8字以内",
      "items": [
        {"kind": "spot", "ref": "候选id", "time": "09:00", "duration": 2.5, "note": "一句话为什么来"},
        {"kind": "meal", "ref": "候选id", "time": "12:00", "meal": "lunch", "note": "点什么"},
        {"kind": "hotel", "time": "21:00", "note": "回到酒店休息"}
      ]
    }
  ]
}

硬性规则：
1. spot 和 meal 的 ref 必须来自候选清单的 id，不得编造 id；同名景点只能出现一次。
2. 每天景点数量按用户节奏控制：relaxed 2个、moderate 2~3个、intense 3~4个。
3. 每天固定三段餐食：早餐(08:00)、午餐(12:00)、晚餐(18:00)，ref 从餐饮候选里选，
   同一天三餐不要选同一家。
4. 时间轴必须递增，相邻两站之间留出交通时间（同城 20~40 分钟，跨区/远郊 60~90 分钟）。
5. 每天最后一个 item 是 hotel，time 取 21:00~22:00。
6. 第 1 天的第一个景点不要早于 09:00（考虑抵达）。
7. note 用中文，口语化，不超过 30 字，要有具体信息（门票、排队、拍照点、必点菜），不要空话。"""


def build_user_prompt(req: dict) -> str:
    city = req["city"]
    days = int(req["days"])
    start = req.get("start_date") or date.today().isoformat()
    styles = [STYLE_LABEL.get(s, s) for s in (req.get("styles") or [])] or ["综合"]
    pace = req.get("pace", "moderate")
    tier = req.get("tier", "comfort")
    party = req.get("party") or {}
    adults = int(party.get("adults", 2) or 2)
    children = int(party.get("children", 0) or 0)
    budget = req.get("budget")
    preference = (req.get("preference") or "").strip()

    lines = [
        "城市：%s" % city,
        "日期：%s 出发，共 %d 天" % (start, days),
        "人数：%d 位成人%s" % (adults, ("，%d 个孩子" % children) if children else ""),
        "节奏：%s（每日景点 %d~%d 个）" % (
            {"relaxed": "轻松", "moderate": "适中", "intense": "紧凑"}.get(pace, "适中"),
            PACE_SPOTS.get(pace, PACE_SPOTS["moderate"])[0],
            PACE_SPOTS.get(pace, PACE_SPOTS["moderate"])[1],
        ),
        "偏好：%s" % "、".join(styles),
        "住宿档次：%s" % TIER_PRICE.get(tier, TIER_PRICE["comfort"])["label"],
    ]
    if budget:
        lines.append("总预算上限：%s 元（需在 tips 里提醒是否超支）" % budget)
    if children:
        lines.append("有孩子：避免高强度徒步和夜生活，优先亲子友好景点")
    if preference:
        lines.append("额外要求：%s" % preference)
    lines.append("")
    lines.append(db.candidates_text(city))
    lines.append("")
    lines.append("请输出 JSON。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 模型调用（OpenAI 兼容协议 / DeepSeek）
# --------------------------------------------------------------------------- #
class LLMError(RuntimeError):
    pass


def load_env_file(path: Optional[str] = None) -> None:
    """读 .env，补进 os.environ（不覆盖已有真实环境变量）。"""
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and val:
                    os.environ.setdefault(key, val)
    except OSError:
        pass


def llm_config() -> dict:
    key = (os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise LLMError("没有配置 DEEPSEEK_API_KEY，请在 travel-assistant/.env 里填入 Key，或使用本地规则模式")
    base = (os.getenv("LLM_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return {
        "key": key,
        "base": base,
        # 实测：deepseek-flash 会把大量 token 花在 reasoning 上，JSON 容易被截断；
        # v4-pro 在 reasoning_effort=low 时约 40s 出完整 JSON，质量也更好。
        "model": os.getenv("LLM_MODEL") or "deepseek-v4-pro",
        "temperature": float(os.getenv("LLM_TEMPERATURE") or "0.6"),
        "effort": os.getenv("LLM_EFFORT") or "low",
    }


def _extract_json(text: str) -> dict:
    """从模型输出里取 JSON。

    实测 deepseek-flash 偶尔会输出两个对象（先给一份草稿再给一份正式的），
    所以不能只做 json.loads，而是用 raw_decode 取出第一个完整对象。
    """
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    if not text:
        raise LLMError("模型返回了空内容")
    try:
        return json.loads(text)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start >= 0:
        try:
            obj, _end = decoder.raw_decode(text[start:])
            if isinstance(obj, dict) and "days" in obj:
                return obj
        except ValueError:
            pass
        start = text.find("{", start + 1)
    raise LLMError("模型没有返回合法 JSON（前 120 字：%s）" % text[:120])


def call_llm(prompt: str, timeout: int = 150) -> dict:
    cfg = llm_config()
    import requests

    # 注意：deepseek-flash / v4-pro 是推理模型，reasoning_tokens 也算在 max_tokens 里。
    # max_tokens 给小了会被截断成半截 JSON，所以这里留足 8192，并在截断时自动重试一次。
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": cfg["temperature"],
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS") or "16384"),
        "response_format": {"type": "json_object"},
        "reasoning_effort": cfg.get("effort") or "low",
    }
    last_err = None
    dropped_format = False
    for attempt in range(3):
        try:
            r = requests.post(
                cfg["base"] + "/chat/completions",
                headers={"Authorization": "Bearer " + cfg["key"], "Content-Type": "application/json"},
                json=body,
                timeout=timeout,
            )
            if r.status_code >= 400:
                if r.status_code == 400 and not dropped_format and "response_format" in r.text:
                    body.pop("response_format", None)
                    dropped_format = True
                    continue
                raise LLMError("模型接口返回 %s：%s" % (r.status_code, r.text[:200]))
            data = r.json()
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
            # 截断：加大预算重试
            if choice.get("finish_reason") == "length":
                body["max_tokens"] = min(body["max_tokens"] * 2, 32768)
                last_err = LLMError("模型输出被截断（finish_reason=length）")
                continue
            return _extract_json(text)
        except LLMError as exc:
            if "被截断" in str(exc) and attempt < 2:
                last_err = exc
                continue
            raise
        except Exception as exc:  # 网络类错误重试
            last_err = exc
            if attempt < 2:
                time.sleep(1.2)
    raise LLMError("模型调用失败：%s: %s" % (type(last_err).__name__, last_err))


# --------------------------------------------------------------------------- #
# 本地规则引擎（降级 & 离线演示）
# --------------------------------------------------------------------------- #
def rule_plan(req: dict) -> dict:
    city = req["city"]
    days = int(req["days"])
    styles = set(req.get("styles") or [])
    pace = req.get("pace", "moderate")
    lo, hi = PACE_SPOTS.get(pace, PACE_SPOTS["moderate"])
    per_day = min(hi, max(lo, 2 if pace != "intense" else 3))
    spots = list(db.SPOTS.get(city) or db.SPOTS["北京"])
    rng = random.Random(hash((city, days, tuple(sorted(styles)))) & 0xFFFF)

    def relevance(s):
        hit = len(styles & set(s["tags"]))
        star = 2 if "必去" in s["tags"] else 0
        return hit * 3 + star + rng.random()

    need = days * per_day
    clon, clat = db.CITY_CENTER[city]

    def is_remote(s: dict) -> bool:
        # 32km 之外视为“远郊一日游”（八达岭、慕田峪、青城山、兵马俑、西溪这类）
        return haversine_km(clon, clat, s["lon"], s["lat"]) > 32.0

    # 选点策略：每天先定一个"锚点"，再在锚点附近补点。
    # 远郊景点（离市中心 >32km）单独占一天，且当天只放它一个——
    # 否则就会出现"上午长城、下午国贸"这种一天 200km 的排法。
    used: set = set()
    # 同一趟别排两个"同类唯一体验"：长城只去一处、主题乐园不重复
    EXCLUSIVE_TAGS = {"长城", "主题乐园", "湿地", "古镇", "温泉"}
    used_tags: set = set()

    def pickable(only_local=False):
        out = []
        for s in spots:
            if s["id"] in used:
                continue
            if (set(s["tags"]) & EXCLUSIVE_TAGS) & used_tags:
                continue
            if only_local and is_remote(s):
                continue
            out.append(s)
        return out

    def take(s):
        used.add(s["id"])
        used_tags.update(set(s["tags"]) & EXCLUSIVE_TAGS)

    buckets: List[List[dict]] = [[] for _ in range(days)]

    def best(cands):
        return max(cands, key=relevance)

    # 1) 远郊：强相关的优先单独成日（最多占一半天数，保证市区也有内容）
    remotes = [s for s in spots if is_remote(s)]
    remotes.sort(key=relevance, reverse=True)
    remote_buckets: List[List[dict]] = []
    for s in remotes:
        if len(remote_buckets) >= max(1, (days + 1) // 2):
            break
        if s["id"] in used or (set(s["tags"]) & EXCLUSIVE_TAGS) & used_tags:
            continue
        if styles and not (styles & set(s["tags"])) and "必去" not in s["tags"]:
            continue
        take(s)
        remote_buckets.append([s])

    # 2) 市区：每天一个锚点（相关度最高），再就近补到 per_day
    local_days: List[List[dict]] = []
    for _ in range(days - len(remote_buckets)):
        cands = pickable(only_local=True)
        if not cands:
            break
        anchor = best(cands)
        take(anchor)
        bucket = [anchor]
        while len(bucket) < per_day:
            cands = pickable(only_local=True)
            if not cands:
                break
            near = [s for s in cands
                    if haversine_km(anchor["lon"], anchor["lat"], s["lon"], s["lat"]) <= 18.0]
            pool = near or cands
            nxt = min(pool, key=lambda s: haversine_km(bucket[-1]["lon"], bucket[-1]["lat"],
                                                       s["lon"], s["lat"]))
            take(nxt)
            bucket.append(nxt)
        local_days.append(bucket)

    # 3) 远郊日也可能有"顺路景点"（比如兵马俑 + 华清宫，相距 8km）
    for rb in remote_buckets:
        anchor = rb[0]
        while len(rb) < per_day:
            cands = [s for s in pickable()
                     if haversine_km(anchor["lon"], anchor["lat"], s["lon"], s["lat"]) <= 15.0]
            if not cands:
                break
            nxt = min(cands, key=lambda s: haversine_km(rb[-1]["lon"], rb[-1]["lat"], s["lon"], s["lat"]))
            take(nxt)
            rb.append(nxt)

    # 4) 交错排列：第 1 天市区，之后远郊/市区轮着来
    buckets = []
    di = ri = 0
    while len(buckets) < days:
        d = len(buckets)
        if local_days and (d == 0 or d == days - 1 or d % 2 == 0 or ri >= len(remote_buckets)):
            buckets.append(local_days.pop(0) if local_days else [])
        elif ri < len(remote_buckets):
            buckets.append(remote_buckets[ri])
            ri += 1
        elif local_days:
            buckets.append(local_days.pop(0))
        else:
            buckets.append([])

    # 5) 还有空天（景点太少）就把剩下最相关的塞进去
    for d in range(days):
        if not buckets[d]:
            continue
        while len(buckets[d]) < per_day and not is_remote(buckets[d][0]):
            cands = pickable()
            if not cands:
                break
            s = best(cands)
            take(s)
            buckets[d].append(s)
    day_buckets = buckets

    eateries = db.EATERIES.get(city) or []
    by_meal = {m: [e for e in eateries if m in e.get("meal", [])] or eateries for m in MEAL_TIMES}
    hotel = db.hotel_for(city, req.get("tier", "comfort"))

    out_days = []
    used_eats: set = set()
    for d in range(days):
        day_spots = day_buckets[d] if d < len(day_buckets) else []
        items: List[dict] = []
        for s in day_spots:
            items.append({"kind": "spot", "ref": s["id"], "time": "09:00", "duration": s["hours"],
                          "note": s.get("note") or ""})
        # 三餐：从当天景点的地理重心出发选最近的餐厅；
        # 整个行程尽量不重复同一家（早/午/晚各自轮换），实在没有才复用。
        if day_spots:
            lon = sum(s["lon"] for s in day_spots) / len(day_spots)
            lat = sum(s["lat"] for s in day_spots) / len(day_spots)
        else:
            lon, lat = db.CITY_CENTER.get(city, (116.4, 39.9))
        chosen: List[dict] = []
        for meal in ("breakfast", "lunch", "dinner"):
            # 早餐在酒店/第一站附近吃：以酒店坐标为圆心；
            # 午晚餐跟着当天景点走，以景点重心为圆心。
            if meal == "breakfast" and hotel:
                blon, blat = hotel["lon"], hotel["lat"]
            else:
                blon, blat = lon, lat
            same_day = {m["ref"] for m in chosen}
            # 分档挑选（宁缺毋滥地按档降级）：
            #   1) 未用过 + 明确适配该时段（早餐放宽到早/午市店）
            #   2) 已用过 + 适配该时段
            #   3) 未用过 + 任意时段
            #   4) 已用过 + 任意时段
            # 每档内部取离当天景点重心最近的一家；同一天不能重复同一家。
            if meal == "breakfast":
                timed = [e for e in eateries if set(e.get("meal", [])) & {"breakfast", "lunch"}]
            else:
                timed = [e for e in eateries if meal in e.get("meal", [])]
            usable = [e for e in eateries if e["id"] not in same_day]
            timed = [e for e in timed if e["id"] not in same_day]
            tiers = [
                [e for e in timed if e["id"] not in used_eats],
                [e for e in timed if e["id"] in used_eats],
                [e for e in usable if e["id"] not in used_eats],
                usable,
            ]
            pool = next((t for t in tiers if t), eateries)
            e = min(pool, key=lambda x: haversine_km(blon, blat, x["lon"], x["lat"]))
            used_eats.add(e["id"])
            dist = haversine_km(blon, blat, e["lon"], e["lat"])
            note = "试试" + (e.get("dish") or e.get("cuisine") or "")
            if dist > 12:
                note = "周边选择有限，建议就近解决或返程再吃；备选：" + e["name"]
            chosen.append({"kind": "meal", "ref": e["id"], "time": MEAL_TIMES[meal][0],
                           "duration": MEAL_TIMES[meal][1], "meal": meal,
                           "note": note, "far": dist > 12})
        items += chosen
        items.append({"kind": "hotel", "time": "21:00", "duration": 0,
                      "note": "回酒店休息" if hotel else "返回住处"})
        label = STYLE_LABEL.get(next(iter(styles), ""), "经典")
        if any(is_remote(s) for s in day_spots):
            label = "近郊远足 · " + (day_spots[0]["name"] if len(day_spots) == 1 else label)
        out_days.append({"theme": label, "items": items})
    return {
        "title": "%s %d 日" % (city, days),
        "summary": "按你的%s偏好与%s节奏生成的 %s %d 日行程。" % (
            "、".join(STYLE_LABEL.get(s, s) for s in styles) or "综合",
            {"relaxed": "轻松", "moderate": "适中", "intense": "紧凑"}.get(pace, "适中"), city, days),
        "tips": ["热门景点请提前 1~7 天在官方渠道预约", "行程为示意排布，可随时拖动调整顺序",
                 "餐饮与交通价格为人均估算，以现场为准"],
        "days": out_days,
    }


# --------------------------------------------------------------------------- #
# 组装：模型 JSON → 可用的行程对象（补坐标、排时间轴、算预算）
# --------------------------------------------------------------------------- #
def _find_spot(city: str, ref: str, name: str = "") -> Optional[dict]:
    idx = db.spot_index(city)
    if ref in idx:
        return idx[ref]
    if name:
        for s in idx.values():
            if s["name"] == name or name in s["name"]:
                return s
    # 别的城市可能有同名（比如都叫"博物馆"），兜底全局找
    for c, spots in db.SPOTS.items():
        for s in spots:
            if s["id"] == ref or (name and s["name"] == name):
                return s
    return None


def _find_eatery(city: str, ref: str) -> Optional[dict]:
    return db.eatery_index(city).get(ref)


def assemble(req: dict, raw: dict, source: str) -> dict:
    city = req["city"]
    pace = req.get("pace", "moderate")
    tier = req.get("tier", "comfort")
    party = req.get("party") or {}
    adults = max(1, int(party.get("adults", 2) or 2))
    children = int(party.get("children", 0) or 0)
    heads = adults + children
    start = req.get("start_date") or date.today().isoformat()
    try:
        start_d = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        start_d = date.today()

    days_in = raw.get("days") or []
    days: List[dict] = []
    seen: set = set()
    unknown: List[str] = []

    for di in range(int(req["days"])):
        raw_day = days_in[di] if di < len(days_in) else {}
        items: List[dict] = []
        used_eateries: set = set()
        raw_items = raw_day.get("items") or []
        for it in raw_items:
            kind = it.get("kind")
            if kind == "spot":
                s = _find_spot(city, str(it.get("ref") or ""), str(it.get("name") or ""))
                if not s:
                    unknown.append(str(it.get("ref")))
                    continue
                if s["id"] in seen:
                    continue
                seen.add(s["id"])
                items.append({
                    "kind": "spot", "ref": s["id"], "name": s["name"],
                    "lon": s["lon"], "lat": s["lat"], "ticket": s["ticket"],
                    "duration": float(it.get("duration") or s["hours"]), "tags": s["tags"],
                    "open": s.get("open"), "note": it.get("note") or s.get("note") or "",
                    "fixed": False,
                })
            elif kind == "meal":
                e = _find_eatery(city, str(it.get("ref") or ""))
                if not e or e["id"] in used_eateries:
                    continue
                used_eateries.add(e["id"])
                items.append({
                    "kind": "meal", "ref": e["id"], "name": e["name"], "lon": e["lon"], "lat": e["lat"],
                    "price": e["price"], "meal": it.get("meal") or "lunch", "cuisine": e.get("cuisine"),
                    "duration": float(it.get("duration") or 1.5), "note": it.get("note") or e.get("note") or "",
                    "fixed": False,
                })
            elif kind == "hotel":
                h = db.hotel_for(city, tier)
                items.append({
                    "kind": "hotel", "ref": (h or {}).get("id", "hotel"), "name": (h or {}).get("name", "酒店"),
                    "lon": (h or {}).get("lon", db.CITY_CENTER[city][0]),
                    "lat": (h or {}).get("lat", db.CITY_CENTER[city][1]),
                    "price": (h or {}).get("price", 500), "duration": 0,
                    "note": it.get("note") or "返回酒店休息", "fixed": False,
                })
        if not any(i["kind"] == "spot" for i in items):
            # 模型给的这天没解析出景点 → 用规则引擎补一天
            fill = rule_plan(req)["days"][di % len(rule_plan(req)["days"])]
            for it in fill["items"]:
                if it["kind"] == "spot":
                    s = _find_spot(city, it["ref"])
                    if s and s["id"] not in seen:
                        seen.add(s["id"])
                        items.append({"kind": "spot", "ref": s["id"], "name": s["name"], "lon": s["lon"],
                                      "lat": s["lat"], "ticket": s["ticket"], "duration": s["hours"],
                                      "tags": s["tags"], "open": s.get("open"), "note": s.get("note", ""),
                                      "fixed": False})
                elif it["kind"] == "meal":
                    e = _find_eatery(city, it["ref"])
                    if e and e["id"] not in used_eateries:
                        used_eateries.add(e["id"])
                        items.append({"kind": "meal", "ref": e["id"], "name": e["name"], "lon": e["lon"],
                                      "lat": e["lat"], "price": e["price"], "meal": it["meal"],
                                      "cuisine": e.get("cuisine"), "duration": 1.5, "note": e.get("note", ""),
                                      "fixed": False})
                elif it["kind"] == "hotel" and not any(i["kind"] == "hotel" for i in items):
                    h = db.hotel_for(city, tier)
                    items.append({"kind": "hotel", "ref": h["id"], "name": h["name"], "lon": h["lon"],
                                  "lat": h["lat"], "price": h["price"], "duration": 0,
                                  "note": "返回酒店休息", "fixed": False})
        if not any(i["kind"] == "hotel" for i in items):
            h = db.hotel_for(city, tier)
            items.append({"kind": "hotel", "ref": h["id"], "name": h["name"], "lon": h["lon"], "lat": h["lat"],
                          "price": h["price"], "duration": 0, "note": "返回酒店休息", "fixed": False})

        d = start_d + timedelta(days=di)
        day = {
            "index": di + 1,
            "date": d.isoformat(),
            "weekday": "周" + "一二三四五六日"[d.weekday()],
            "theme": raw_day.get("theme") or "第 %d 天" % (di + 1),
            "items": items,
        }
        day = schedule_day(day)
        days.append(day)

    plan = {
        "id": "trip_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + str(random.randint(100, 999)),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "req": req,
        "title": raw.get("title") or "%s %d 日游" % (city, int(req["days"])),
        "summary": raw.get("summary") or "",
        "tips": [str(t) for t in (raw.get("tips") or [])][:6],
        "city": city,
        "days": days,
        "unknown_refs": unknown[:8],
        "center": db.CITY_CENTER[city],
        "party": {"adults": adults, "children": children, "heads": heads},
        "tier": tier,
        "pace": pace,
    }
    plan["budget"] = compute_budget(plan)
    plan["stats"] = compute_stats(plan)
    return plan


SLOTS = {
    "breakfast": (8 * 60, 10 * 60 + 30),
    "morning": (9 * 60 + 30, 12 * 60 + 30),
    "lunch": (11 * 60 + 30, 14 * 60 + 30),
    "afternoon": (13 * 60 + 30, 17 * 60 + 30),
    "dinner": (17 * 60, 20 * 60),
    "hotel": (20 * 60, 22 * 60 + 30),
}


def schedule_day(day: dict) -> dict:
    """重排一天的时间轴（按“时段”分配，而不是一路往后顺延）。

    一天被切成 5 个时段：早餐 / 上午 / 午餐 / 下午 / 晚餐，每个时段有固定窗口。
    交通时间从“上一项结束”起算；挤不下时优先压缩项目时长并给当天加提醒，
    但绝不打乱“早餐→上午→午餐→下午→晚餐→酒店”的顺序，
    因此不会出现午餐排在 14:29、晚餐排在 13:20 这种时间倒挂。
    """
    items = day["items"]
    spots = [i for i in items if i["kind"] == "spot"]
    meals = [i for i in items if i["kind"] == "meal"]
    hotels = [i for i in items if i["kind"] == "hotel"]

    order = {"breakfast": 0, "lunch": 1, "dinner": 2}
    meals.sort(key=lambda i: order.get(i.get("meal"), 9))
    # 按早/午/晚取餐；同一时段多余的那家归到 "others" 里保留，避免被静默丢弃
    def first_of(meal):
        return [m for m in meals if m.get("meal") == meal][:1]

    breakfasts = first_of("breakfast")
    lunches = first_of("lunch")
    dinners = first_of("dinner")
    others = [m for m in meals if m not in breakfasts + lunches + dinners]

    n = len(spots)
    morning = spots[:(n + 1) // 2]
    afternoon = spots[(n + 1) // 2:]

    seq = []
    seq += breakfasts
    seq += morning
    seq += lunches
    seq += afternoon
    seq += dinners
    seq += others
    seq += hotels[:1]

    cur = 8 * 60
    prev = None
    for it in seq:
        kind, meal = it["kind"], it.get("meal")
        if it.get("fixed") and it.get("time"):
            start = _minutes(it["time"])
        elif kind == "meal":
            start = 7 * 60 + 50 if meal == "breakfast" else SLOTS.get(meal, (12 * 60, 14 * 60))[0]
        elif kind == "spot":
            start = SLOTS["morning"][0] if it in morning else SLOTS["afternoon"][0]
        else:
            start = SLOTS["hotel"][0]

        if prev is not None:
            km = haversine_km(prev["lon"], prev["lat"], it["lon"], it["lat"])
            tr = transfer_estimate(km)
            it["transfer"] = {"from": prev["name"], "km": round(km, 1), "mode": tr["mode"],
                              "minutes": tr["minutes"], "cost": tr["cost"]}
            start = max(start, prev["end_min"] + tr["minutes"])
        else:
            it.pop("transfer", None)

        start = max(start, cur)
        dur = max(20, int(round(float(it.get("duration") or 0) * 60)))
        it["start_min"] = start
        it["end_min"] = start + dur
        it["time"] = _hhmm(it["start_min"])
        it["shortened"] = False
        cur = it["end_min"] + 10
        prev = it

    # 结束太晚 → 从后往前压缩景点时长（保持顺序不变）
    guard = 0
    while seq and seq[-1]["end_min"] > 22 * 60 and guard < 8:
        guard += 1
        target = None
        for it in reversed(seq):
            if it["kind"] == "spot" and it["end_min"] - it["start_min"] > 50 and not it.get("fixed"):
                target = it
                break
        if target is None:
            break
        overflow = seq[-1]["end_min"] - 22 * 60
        cut = min(overflow, target["end_min"] - target["start_min"] - 45)
        if cut <= 0:
            break
        target["end_min"] -= cut
        target["shortened"] = True
        # 压缩后把后续项目的开始时间一并前移（转移时间保持原样）
        cursor = target["end_min"] + 10
        after = False
        for it in seq:
            if it is target:
                after = True
                continue
            if not after or it.get("fixed"):
                continue
            tr = it.get("transfer") or {}
            it["start_min"] = max(cursor + int(tr.get("minutes") or 0), it["start_min"] - cut)
            it["end_min"] -= cut
            it["time"] = _hhmm(it["start_min"])
            cursor = it["end_min"] + 10
        for it in seq:
            it["time"] = _hhmm(it["start_min"])

    # 当日提示：远郊日 / 时间被压缩
    day.pop("warning", None)
    day_km = sum(float(i.get("transfer", {}).get("km") or 0) for i in seq)
    for i in seq:
        if i["kind"] == "spot" and i["end_min"] - i["start_min"] < int(float(i.get("duration") or 0) * 60) - 10:
            day["warning"] = "当天时间偏紧，部分景点游览时长被压缩，建议删减或挪到别的一天"
            break
    if day_km > 80:
        day["warning"] = day.get("warning") or "当天有远郊景点，单日往返约 %.0fkm，建议早出发" % day_km

    day["items"] = seq
    if seq:
        day["start_time"] = _hhmm(min(i["start_min"] for i in seq))
        day["end_time"] = _hhmm(max(i["end_min"] for i in seq))
    day["route"] = [[i["lon"], i["lat"]] for i in seq if i["kind"] in ("spot", "meal")]
    return day


def attach_gcj(plan: dict) -> dict:
    """给每个站点补上高德/腾讯需要的 GCJ-02 坐标（lon_g/lat_g）。

    WGS-84 给 Leaflet/OSM 用，GCJ-02 给高德用；两套都带上，前端按底图服务商选一套，
    这样"换地图"不会导致站点整体偏移 300~500 米。
    """
    for day in plan.get("days", []):
        for it in day.get("items", []):
            if "lon_g" not in it and it.get("lon") is not None and it.get("lat") is not None:
                glon, glat = coords.wgs84_to_gcj02(float(it["lon"]), float(it["lat"]))
                it["lon_g"], it["lat_g"] = glon, glat
        day["route_g"] = [[i["lon_g"], i["lat_g"]] for i in day.get("items", [])
                          if i.get("kind") in ("spot", "meal") and "lon_g" in i]
    return plan


def compute_budget(plan: dict) -> dict:
    req = plan["req"]
    tier = plan.get("tier", "comfort")
    food_mul = TIER_PRICE.get(tier, TIER_PRICE["comfort"])["food"]
    heads = plan["party"]["heads"]
    adults = plan["party"]["adults"]
    children = plan["party"]["children"]
    days = plan["days"]

    ticket = hotel = meal = transit = 0.0
    detail_ticket, detail_meal, detail_transit, detail_hotel = [], [], [], []

    for day in days:
        d_ticket = d_meal = d_transit = 0.0
        for it in day["items"]:
            if it["kind"] == "spot":
                amt = float(it.get("ticket") or 0) * heads
                d_ticket += amt
                if amt > 0:
                    detail_ticket.append({"name": it["name"], "unit": it["ticket"], "qty": heads, "amount": amt})
            elif it["kind"] == "meal":
                amt = float(it.get("price") or 0) * food_mul * heads
                d_meal += amt
                detail_meal.append({"name": it["name"] + "（%s）" % {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}.get(it.get("meal"), "用餐"),
                                    "unit": round(it["price"] * food_mul),
                                    "qty": heads, "amount": amt})
            if it.get("transfer"):
                # 打车/包车按车计价（4 人一车），公共交通按人
                if it["transfer"]["mode"] in ("打车", "远郊包车"):
                    d_transit += it["transfer"]["cost"] * max(1, math.ceil(heads / 4.0))
                else:
                    d_transit += it["transfer"]["cost"] * heads
        nights = 1 if day is days[-1] and len(days) == 1 else 1
        h = db.hotel_for(plan["city"], tier) or {}
        room_price = float(h.get("price") or 500)
        rooms = max(1, math.ceil(heads / 2.0))
        amt = room_price * rooms
        hotel += amt
        detail_hotel.append({"name": "第 %d 晚 · %s" % (day["index"], h.get("name", "酒店")),
                             "unit": room_price, "qty": rooms, "amount": amt})
        ticket += d_ticket
        meal += d_meal
        transit += d_transit

    # 去返程大交通：按城市距离给一个粗估（人均往返）
    intercity = _intercity_estimate(plan["city"], plan["req"].get("origin") or "", heads)
    items = [
        {"key": "ticket", "label": "门票", "amount": round(ticket)},
        {"key": "hotel", "label": "住宿", "amount": round(hotel)},
        {"key": "meal", "label": "餐饮", "amount": round(meal)},
        {"key": "transit", "label": "市内交通", "amount": round(transit)},
    ]
    if intercity["amount"]:
        items.append({"key": "intercity", "label": "往返大交通", "amount": round(intercity["amount"])})
    total = sum(i["amount"] for i in items)
    budget = {
        "currency": "CNY",
        "total": total,
        "per_person": round(total / heads),
        "per_day": round(total / max(1, len(days))),
        "items": items,
        "detail": {
            "ticket": detail_ticket,
            "meal": detail_meal,
            "hotel": detail_hotel,
            "intercity": intercity.get("note", ""),
        },
        "limit": req.get("budget"),
    }
    if req.get("budget"):
        try:
            budget["over"] = total > float(req["budget"])
            budget["diff"] = round(total - float(req["budget"]))
        except (TypeError, ValueError):
            pass
    return budget


def _intercity_estimate(city: str, origin: str, heads: int) -> dict:
    """按出发地到目的地的大致距离给出往返预算（高铁二等座/经济舱均价）。"""
    if not origin:
        return {"amount": 0}
    km_table = {
        ("上海", "北京"): 1318, ("北京", "上海"): 1318, ("杭州", "北京"): 1279, ("北京", "杭州"): 1279,
        ("上海", "杭州"): 175, ("杭州", "上海"): 175, ("成都", "西安"): 700, ("西安", "成都"): 700,
        ("北京", "西安"): 1200, ("西安", "北京"): 1200, ("广州", "上海"): 1800, ("上海", "广州"): 1800,
    }
    km = km_table.get((origin, city))
    if not km:
        return {"amount": 0, "note": "未提供出发地或距离未知，往返大交通未计入"}
    if km < 800:
        per = round(km * 0.45 / 10) * 10 * 2      # 高铁二等座，往返
        way = "高铁"
    else:
        per = round(max(450, km * 0.32) / 10) * 10 * 2  # 淡季经济舱，往返
        way = "飞机"
    return {"amount": per * heads, "note": "%s往返 %s → %s（约 %dkm）人均 %d 元估算" % (way, origin, city, km, per)}


def compute_stats(plan: dict) -> dict:
    spots, meals, km_total = 0, 0, 0.0
    for day in plan["days"]:
        for it in day["items"]:
            if it["kind"] == "spot":
                spots += 1
            elif it["kind"] == "meal":
                meals += 1
            if it.get("transfer"):
                km_total += it["transfer"]["km"]
    return {"days": len(plan["days"]), "spots": spots, "meals": meals, "km": round(km_total, 1)}


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def normalize_req(req: dict) -> dict:
    city = str(req.get("city") or "北京").strip()
    if city not in db.SPOTS:
        city = "北京"
    try:
        days = max(1, min(int(req.get("days") or 3), 7))
    except (TypeError, ValueError):
        days = 3
    styles = [s for s in (req.get("styles") or []) if s in STYLE_LABEL][:4]
    pace = req.get("pace") if req.get("pace") in PACE_SPOTS else "moderate"
    tier = req.get("tier") if req.get("tier") in TIER_PRICE else "comfort"
    party = req.get("party") or {}
    try:
        adults = max(1, min(int(party.get("adults", 2)), 12))
    except (TypeError, ValueError):
        adults = 2
    try:
        children = max(0, min(int(party.get("children", 0)), 8))
    except (TypeError, ValueError):
        children = 0
    return {
        "city": city,
        "days": days,
        "start_date": req.get("start_date") or date.today().isoformat(),
        "styles": styles,
        "pace": pace,
        "tier": tier,
        "party": {"adults": adults, "children": children},
        "budget": req.get("budget") or None,
        "preference": str(req.get("preference") or "")[:200],
        "origin": str(req.get("origin") or "")[:20],
    }


def build_plan(req: dict, mode: str = "auto") -> dict:
    """mode: auto（先模型后规则）/ llm（只用模型）/ rule（只用规则）。"""
    req = normalize_req(req)
    if mode != "rule":
        try:
            raw = call_llm(build_user_prompt(req))
            plan = assemble(req, raw, source="llm")
            plan["model"] = llm_config()["model"]
            return attach_gcj(plan)
        except Exception as exc:
            if mode == "llm":
                raise
            plan = assemble(req, rule_plan(req), source="rule")
            plan["fallback_reason"] = "%s: %s" % (type(exc).__name__, str(exc)[:180])
            return attach_gcj(plan)
    plan = assemble(req, rule_plan(req), source="rule")
    plan["fallback_reason"] = "已选择本地规则模式（不消耗模型额度）"
    return attach_gcj(plan)


def replan(req: dict, plan: dict) -> dict:
    """按新条件重排（保留已锁定项）。简单起见：整单重生成后，把锁定项放回对应天。"""
    locked = collect_locked(plan)
    new_plan = build_plan(req, mode=plan.get("source") == "rule" and "rule" or "auto")
    if not locked:
        return new_plan
    by_key = {i.get("ref"): i for d in new_plan["days"] for i in d["items"]}
    for day in new_plan["days"]:
        for it in day["items"]:
            if it.get("ref") in locked:
                it["fixed"] = True
        schedule_day(day)
    new_plan["budget"] = compute_budget(new_plan)
    new_plan["stats"] = compute_stats(new_plan)
    return attach_gcj(new_plan)


def collect_locked(plan: dict) -> set:
    return {i.get("ref") for d in plan.get("days", []) for i in d.get("items", []) if i.get("fixed")}
