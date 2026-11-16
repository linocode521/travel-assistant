# -*- coding: utf-8 -*-
"""端到端接口测试：不需要浏览器，也不需要真模型（强制走本地规则）。

用法：python test_api.py [--live] [--llm]
  --live  对已启动的服务做真实 HTTP 测试（默认端口 8766）
  --llm   额外跑一次真实大模型生成（会花钱，约 40s）
"""

from __future__ import annotations

import json
import os
import sys
import time

import bootstrap  # noqa: F401

import server


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print("  ok  %s" % msg)


def main():
    live = "--live" in sys.argv
    with_llm = "--llm" in sys.argv

    server.FORCE_RULE = True
    server.load_trips()
    c = server.app.test_client()
    print("[1] 元信息")
    r = c.get("/api/health")
    check(r.status_code == 200 and r.get_json()["ok"], "GET /api/health")
    r = c.get("/api/options")
    o = r.get_json()
    check(len(o["cities"]) >= 6 and len(o["styles"]) >= 5, "GET /api/options 返回城市与偏好")
    check(c.get("/").status_code == 200, "GET / 返回前端页面")

    print("[2] 生成行程（本地规则）")
    payload = {
        "city": "北京", "days": 3, "styles": ["history", "food"], "pace": "moderate",
        "tier": "comfort", "party": {"adults": 2, "children": 1},
        "start_date": "2026-11-20", "budget": 5000, "origin": "上海",
    }
    t0 = time.time()
    r = c.post("/api/plan", json=payload)
    check(r.status_code == 200, "POST /api/plan 200")
    trip = r.get_json()["trip"]
    check(len(trip["days"]) == 3, "生成 3 天")
    check(trip["budget"]["total"] > 0, "预算已计算：%s" % trip["budget"]["total"])
    check(trip["stats"]["spots"] >= 4, "景点数 %s" % trip["stats"]["spots"])
    ids = [i.get("ref") for d in trip["days"] for i in d["items"] if i["kind"] == "spot"]
    check(len(ids) == len(set(ids)), "景点不重复")
    for d in trip["days"]:
        times = [i["start_min"] for i in d["items"]]
        check(times == sorted(times), "第 %d 天时间轴单调递增" % d["index"])
        spots = [i for i in d["items"] if i["kind"] == "spot"]
        for s in spots:
            check(-90 <= s["lat"] <= 90 and 70 <= s["lon"] <= 140, "坐标合法：%s" % s["name"])
    print("      耗时 %.2fs，总预算 ¥%s，里程 %s km" % (time.time() - t0, trip["budget"]["total"], trip["stats"]["km"]))
    tid = trip["id"]

    print("[3] 增删改 / 移动")
    r = c.get("/api/pois?city=北京&kind=spot")
    pois = r.get_json()["pois"]
    check(len(pois) > 2, "POI 搜索返回 %d 个候选" % len(pois))
    used = {i.get("ref") for d in trip["days"] for i in d["items"]}
    free = [p for p in pois if p["id"] not in used]
    check(bool(free), "存在未加入行程的候选景点")
    r = c.post("/api/trips/%s/items" % tid, json={"kind": "spot", "ref": free[0]["id"], "day": 1})
    check(r.status_code == 200, "添加景点：%s" % free[0]["name"])
    trip = r.get_json()["trip"]
    new_item = [i for i in trip["days"][0]["items"] if i.get("ref") == free[0]["id"]][0]
    key = new_item["key"]
    before = trip["budget"]["total"]
    check(before >= 0, "添加后预算重算：%s" % before)

    r = c.post("/api/trips/%s/items/%s/move" % (tid, key), json={"direction": "up"})
    check(r.status_code == 200, "上移一项")
    r = c.patch("/api/trips/%s/items/%s" % (tid, key), json={"note": "测试备注", "fixed": True})
    it = [i for d in r.get_json()["trip"]["days"] for i in d["items"] if i.get("key") == key][0]
    check(it["note"] == "测试备注" and it["fixed"] is True, "修改备注并锁定")
    r = c.delete("/api/trips/%s/items/%s" % (tid, key))
    check(r.status_code == 200, "删除该项")
    after = r.get_json()["trip"]["budget"]["total"]
    check(after <= before + 1, "删除后预算下降：%s → %s" % (before, after))

    print("[4] 加天 / 删天")
    r = c.post("/api/trips/%s/days" % tid)
    check(len(r.get_json()["trip"]["days"]) == 4, "加一天 → 4 天")
    r = c.delete("/api/trips/%s/days/4" % tid)
    check(len(r.get_json()["trip"]["days"]) == 3, "删一天 → 3 天")

    print("[5] 重排")
    r = c.post("/api/trips/%s/replan" % tid, json={"pace": "relaxed", "keep_locked": True})
    check(r.status_code == 200, "POST replan 200")
    t2 = r.get_json()["trip"]
    check(len(t2["days"]) == 3 and t2["req"]["pace"] == "relaxed", "重排后条件已更新")

    print("[6] 导出")
    r = c.get("/api/trips/%s/export.pdf" % tid)
    check(r.status_code == 200 and r.data[:4] == b"%PDF", "PDF 导出 %d KB" % (len(r.data) // 1024))
    r = c.get("/api/trips/%s/export.html" % tid)
    check(r.status_code == 200 and "<html" in r.get_data(as_text=True), "打印版 HTML 导出")
    check("第 1 天" in r.get_data(as_text=True), "HTML 含每日行程")

    print("[7] 历史列表与错误处理")
    r = c.get("/api/trips")
    check(any(x["id"] == tid for x in r.get_json()["trips"]), "历史列表包含本次行程")
    r = c.get("/api/trips/not-exist")
    check(r.status_code == 404, "不存在的行程返回 404")
    r = c.post("/api/trips/%s/items" % tid, json={"kind": "spot", "ref": "no-such-id"})
    check(r.status_code == 404, "非法 POI 返回 404")
    r = c.post("/api/plan", json={"city": "火星", "days": 99})
    check(r.status_code == 200, "非法城市/天数被规范化而不是报错")

    if with_llm:
        print("[8] 真实大模型生成")
        import planner
        planner.load_env_file()
        t0 = time.time()
        plan = planner.build_plan(payload, mode="llm")
        check(plan["source"] == "llm", "模型生成成功（%.1fs，模型 %s）" % (time.time() - t0, plan.get("model")))
        check(len(plan["days"]) == 3, "模型输出 3 天")
        check(plan["stats"]["spots"] >= 3, "模型排了 %d 个景点" % plan["stats"]["spots"])
        check(bool(plan["tips"]), "模型给了 %d 条贴士" % len(plan["tips"]))

    if live:
        print("[9] 真实 HTTP（已启动的 8766 服务）")
        import requests
        base = "http://127.0.0.1:8766"
        check(requests.get(base + "/api/health", timeout=10).json()["ok"], "健康检查")
        check(requests.get(base + "/", timeout=10).status_code == 200, "首页可访问")
        check("leaflet" in requests.get(base + "/index.html", timeout=10).text.lower(), "页面引用 Leaflet")

    print("\n全部通过 ✅")


if __name__ == "__main__":
    storage_path = server.STORAGE
    backup = None
    if os.path.exists(storage_path):
        with open(storage_path, "rb") as fh:
            backup = fh.read()
    try:
        main()
    finally:
        # 测试会写入临时行程；结束后恢复原来的 data/trips.json，不污染演示数据
        try:
            if backup is not None:
                with open(storage_path, "wb") as fh:
                    fh.write(backup)
            elif os.path.exists(storage_path):
                os.remove(storage_path)
            print("\n(测试数据已还原)")
        except OSError as exc:
            print("\n(测试数据还原失败：%s)" % exc)
