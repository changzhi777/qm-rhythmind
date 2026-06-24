"""
scripts/test_api_smoke.py — 25 API 烟测(2026-06-24)

目的:验证 25 API 端点全部可用,数据一致性
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

import requests

API_BASE = "http://localhost:8000"  # CT109 内
TOKEN = "athlete_demo_001"

# 25 API 测试矩阵
ENDPOINTS: list[tuple[str, str, str, dict[str, Any] | None]] = [
    # (method, path, name, body or None)
    # 健康检查
    ("GET", "/livez", "健康检查 liveness", None),
    ("GET", "/readyz", "健康检查 readiness", None),
    ("GET", "/version", "版本信息", None),
    # Dashboard
    ("GET", "/qm/api/dashboard", "仪表盘数据", None),
    ("GET", "/qm/api/users/summary", "用户摘要", None),
    ("GET", "/qm/api/influxdb/timeseries?metric=steps&range=-7d", "InfluxDB 时序", None),
    # Persona
    ("GET", "/api/v1/users/athlete_demo_001/persona", "用户 persona", None),
    # P1 端点
    ("GET", "/api/v1/goals", "P1: 目标", None),
    ("PUT", "/api/v1/goals", "P1: 目标更新", {"goals": []}),
    ("GET", "/api/v1/dashboard/comparison?metric=vo2_max&range=-7d", "P1: 同比/环比", None),
    ("GET", "/api/v1/thresholds", "P1: 阈值", None),
    ("PUT", "/api/v1/thresholds", "P1: 阈值更新", {"overrides": []}),
    ("POST", "/api/v1/users/switch/test-user", "P1: 用户切换", None),
    # P2 端点
    ("GET", "/api/v1/events", "P2: SSE 实时", None),  # 需要短超时
    ("GET", "/api/v1/chat/sessions", "P2: 聊天会话", None),
    ("GET", "/api/v1/upload/chunk", "P2: 分片状态", None),
    ("GET", "/api/v1/reports/search?q=test", "P2: 报告搜索", None),
    ("GET", "/api/v1/reports/compare?ids=1,2", "P2: 报告对比", None),
    ("GET", "/api/v1/test-reports/1/cases", "P2: 测试用例详情", None),
    ("GET", "/api/v1/llm-observe/alerts", "P2: LLM 告警", None),
    ("GET", "/api/v1/llm-observe/budgets", "P2: LLM 预算", None),
    ("GET", "/api/v1/medical/labs/trend?test=glucose", "P2: 化验趋势", None),
    ("GET", "/api/v1/bigscreen/users", "P2: 大屏用户", None),
    ("GET", "/api/v1/test-reports?limit=5", "P2: 测试报告列表", None),
    ("GET", "/api/v1/health/upload/stream", "P2: SSE 上传流", None),  # SSE
]


def call_endpoint(method: str, path: str, name: str, body: dict | None) -> dict:
    """调用单个端点"""
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    is_sse = "events" in path or "stream" in path

    try:
        if method == "GET":
            timeout = 3 if is_sse else 10
            r = requests.get(url, headers=headers, timeout=timeout, stream=is_sse)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=body, timeout=10)
        elif method == "PUT":
            r = requests.put(url, headers=headers, json=body, timeout=10)
        else:
            return {"status": "error", "error": f"unknown method: {method}"}

        if is_sse:
            # SSE: 读第一行
            try:
                first_line = next(r.iter_lines(), None)
                return {
                    "status": "ok" if first_line else "fail",
                    "http": r.status_code,
                    "first_event": first_line.decode()[:200] if first_line else None,
                }
            except StopIteration:
                return {"status": "fail", "http": r.status_code, "error": "no events"}

        if r.headers.get("content-type", "").startswith("application/json"):
            data = r.json()
        else:
            data = r.text[:200]

        return {
            "status": "ok" if r.status_code in (200, 201, 204) else "fail",
            "http": r.status_code,
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


def main() -> int:
    print(f"API: {API_BASE}")
    print(f"Token: {TOKEN}")
    print(f"端点: {len(ENDPOINTS)}")
    print()

    results = []
    start_total = time.time()

    for method, path, name, body in ENDPOINTS:
        result = call_endpoint(method, path, name, body)
        status = result["status"]
        http = result.get("http", "-")
        if status == "ok":
            mark = "✅"
        elif status == "fail":
            mark = "❌"
        else:
            mark = "💥"
        print(f"  {mark} {method:4s} {path:60s} {status:8s} http={http}")

        if status != "ok" and "data" in result:
            data_str = str(result["data"])[:150]
            print(f"      → {data_str}")
        elif "first_event" in result and result["first_event"]:
            print(f"      → {result['first_event'][:100]}")

        results.append({"name": name, "method": method, "path": path, **result})

    elapsed = time.time() - start_total
    print()
    print("=" * 70)
    print("📊 汇总")
    print("=" * 70)
    ok = sum(1 for r in results if r["status"] == "ok")
    fail = sum(1 for r in results if r["status"] == "fail")
    err = sum(1 for r in results if r["status"] == "error")
    total = len(results)

    print(f"  ✅ OK:   {ok}/{total}")
    print(f"  ❌ FAIL: {fail}/{total}")
    print(f"  💥 ERR:  {err}/{total}")
    print(f"  ⏱  Time:  {elapsed:.1f}s")

    # 重点验证:dashboard 数据
    print()
    print("=" * 70)
    print("🔍 数据一致性验证")
    print("=" * 70)
    try:
        r = requests.get(f"{API_BASE}/qm/api/users/summary", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)
        data = r.json()
        for u in data.get("users", []):
            print(f"  用户: {u['display_name']} (id={u['user_id']})")
            print(f"    facts_count: {u['facts_count']}")
            print(f"    profile: vo2_max={u['profile'].get('vo2_max')}, bmi={u['profile'].get('bmi')}, age={u['profile'].get('age')}")
            print(f"    running: {u['running'].get('total_runs')} runs, {u['running'].get('total_km')} km, pace={u['running'].get('avg_pace_min_per_km')}")
    except Exception as e:
        print(f"  ⚠ 验证失败: {e}")

    return 0 if (fail == 0 and err == 0) else 1


if __name__ == "__main__":
    sys.exit(main())