# -*- coding: utf-8 -*-
"""景点图片与补充信息：按名字查高德 POI，拿实拍图、地址、评分、开放时间。

为什么不用 Unsplash：Unsplash 按关键词返回氛围图，搜"北海公园"很可能给一张挪威的湖；
高德 POI 返回的是这个景点自己的实拍，还顺带给了地址和评分。

缓存分两层：进程内 dict + 磁盘 JSON，既省高德配额，也让二次渲染瞬时完成。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, Optional

import bootstrap  # noqa: F401

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "data", "poi_cache.json")
_TTL = 60 * 60 * 24 * 30          # 30 天
_LOCK = threading.Lock()
_mem: Optional[Dict[str, dict]] = None


def _load() -> Dict[str, dict]:
    global _mem
    if _mem is not None:
        return _mem
    _mem = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                _mem = data
        except (OSError, ValueError):
            _mem = {}
    return _mem


def _save() -> None:
    data = _load()
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=0)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def _key(city: str, name: str) -> str:
    return "%s|%s" % (city.strip(), name.strip())


def _fetch(city: str, name: str) -> dict:
    """向高德查一次，返回归整后的字段。"""
    key = (os.getenv("AMAP_KEY") or os.getenv("AMAP_JS_KEY") or "").strip()
    if not key:
        return {"photo": "", "address": "", "rating": "", "open": ""}
    import requests

    def query(kw: str):
        r = requests.get(
            "https://restapi.amap.com/v3/place/text",
            params={"keywords": kw, "city": city, "citylimit": "true",
                    "offset": 1, "page": 1, "extensions": "all", "key": key},
            timeout=12,
        )
        return (r.json().get("pois") or [])

    pois = []
    try:
        pois = query(name)
        if not pois:
            # 名字带括号或后缀时去掉再试一次
            short = name.split("（")[0].split("(")[0].strip()
            if short and short != name:
                pois = query(short)
    except Exception:
        return {"photo": "", "address": "", "rating": "", "open": ""}

    if not pois:
        return {"photo": "", "address": "", "rating": "", "open": ""}

    poi = pois[0]
    photos = poi.get("photos") or []
    photo = ""
    for ph in photos:
        u = (ph.get("url") or "").strip()
        if u.startswith("http"):
            photo = u.replace("http://", "https://", 1)
            break
    biz = poi.get("biz_ext") or {}
    rating = biz.get("rating") or ""
    if isinstance(rating, list):
        rating = ""
    opentime = biz.get("opentime2") or biz.get("open_time") or ""
    if isinstance(opentime, list):
        opentime = ""
    return {
        "photo": photo,
        "address": (poi.get("address") or "").strip() if isinstance(poi.get("address"), str) else "",
        "rating": str(rating).strip(),
        "open": str(opentime).strip()[:60],
    }


def lookup(city: str, name: str) -> dict:
    """带缓存地查一个景点。"""
    k = _key(city, name)
    data = _load()
    hit = data.get(k)
    if hit and (time.time() - hit.get("_ts", 0)) < _TTL:
        return hit
    info = _fetch(city, name)
    info["_ts"] = time.time()
    with _LOCK:
        data[k] = info
        _save()
    return info
