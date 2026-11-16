# -*- coding: utf-8 -*-
"""坐标体系转换：WGS-84 → GCJ-02（火星坐标）。

为什么需要它：
- 我们 POI 库里存的是 WGS-84（GPS / OpenStreetMap 的坐标系）；
- 高德、腾讯、百度这些国内地图用的是加密后的 GCJ-02；
- 如果直接把 WGS-84 丢给高德，位置会整体偏移 300~500 米——地图上看起来
  "故宫在东城区边缘"，用户一眼就会发现不对。

算法是公开的（GCJ-02 偏移算法），在中国大陆范围内有效，
境外坐标直接原样返回（GCJ-02 只对中国区域加密）。
"""

from __future__ import annotations

import math
from typing import Tuple

# 克拉索夫斯基椭球（GCJ-02 算法固定使用这组参数）
_A = 6378245.0
_EE = 0.00669342162296594323


def out_of_china(lon: float, lat: float) -> bool:
    """粗略判断是否在中国境外（境外不做偏移）。"""
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lon: float, lat: float) -> Tuple[float, float]:
    """WGS-84 → GCJ-02，返回 (lon, lat)。"""
    if out_of_china(lon, lat):
        return lon, lat
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return round(lon + dlon, 6), round(lat + dlat, 6)


def gcj02_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    """GCJ-02 → WGS-84（逆变换用迭代逼近，误差 < 1m）。"""
    if out_of_china(lon, lat):
        return lon, lat
    wlon, wlat = lon, lat
    for _ in range(8):
        glon, glat = wgs84_to_gcj02(wlon, wlat)
        dlon, dlat = glon - lon, glat - lat
        if abs(dlon) < 1e-7 and abs(dlat) < 1e-7:
            break
        wlon -= dlon
        wlat -= dlat
    return round(wlon, 6), round(wlat, 6)
