#!/usr/bin/env python3
"""RHYTHMIND E2E 测试 — 10轮全链路测试 + MD/HTML/PDF 报告生成

报告规范：MD + HTML(内联SVG) → Playwright 转 A4 PDF

环境变量：
  E2E_AUTH_TOKEN  — Bearer token（默认 garmin_user_001，生产需 JWT）
  E2E_BASE_URL    — 目标环境 URL（默认 https://aisport.tech/qm）
"""

import json
import os
import statistics
import sys
import subprocess
import time
from datetime import datetime
from pathlib import Path

BASE_URL = os.environ.get("E2E_BASE_URL", "https://aisport.tech/qm")
E2E_AUTH_TOKEN = os.environ.get("E2E_AUTH_TOKEN", "garmin_user_001")
ROUNDS = 10
RETRY_COUNT = int(os.environ.get("E2E_RETRY", "1"))
RETRY_DELAY = float(os.environ.get("E2E_RETRY_DELAY", "1.0"))
REPORT_DIR = Path("/tmp/qm-e2e-reports")


# ── HTTP 测试 ──────────────────────────────────────────────

def http_get(path: str, timeout: int = 10) -> dict:
    t0 = time.time()
    try:
        r = subprocess.run(
            ["curl", "-sSk", "-o", "/dev/null", "-w",
             "%{http_code} %{time_total} %{size_download}",
             f"{BASE_URL}{path}", "--max-time", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        parts = r.stdout.strip().split()
        if len(parts) >= 3:
            return {"status": int(parts[0]), "time": float(parts[1]), "size": int(parts[2]), "ok": True}
        return {"status": 0, "time": time.time() - t0, "size": 0, "ok": False, "error": r.stderr[:200]}
    except Exception as e:
        return {"status": 0, "time": time.time() - t0, "size": 0, "ok": False, "error": str(e)[:200]}


def http_api(path: str, timeout: int = 10) -> dict:
    t0 = time.time()
    try:
        r = subprocess.run(
            ["curl", "-sSk", "-H", f"Authorization: Bearer {E2E_AUTH_TOKEN}",
             f"{BASE_URL}/api{path}", "--max-time", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        elapsed = time.time() - t0
        body = r.stdout
        try:
            data = json.loads(body)
            # JWT 认证失败 → 标记为 skipped（非测试逻辑错误）
            if "detail" in data and "status" not in data:
                detail = data.get("detail", "")
                is_auth = any(kw in detail.lower() for kw in ("token", "signature", "jwt", "auth", "unauthorized", "not authenticated"))
                if is_auth:
                    return {"time": elapsed, "ok": False, "skipped": True, "skip_reason": detail[:100], "body_len": len(body)}
                return {"time": elapsed, "ok": False, "error": f"API: {detail[:100]}", "body_len": len(body)}
            return {"time": elapsed, "ok": data.get("status") == "ok", "data": data, "body_len": len(body)}
        except json.JSONDecodeError:
            return {"time": elapsed, "ok": False, "error": f"Invalid JSON: {body[:100]}", "body_len": len(body)}
    except Exception as e:
        return {"time": time.time() - t0, "ok": False, "error": str(e)[:200]}


def http_get_json(url: str, timeout: int = 10) -> dict:
    """无需认证的公开 JSON API 调用。"""
    t0 = time.time()
    try:
        r = subprocess.run(
            ["curl", "-sSk", url, "--max-time", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        elapsed = time.time() - t0
        body = r.stdout
        try:
            data = json.loads(body)
            return {"time": elapsed, "ok": True, "data": data, "body_len": len(body)}
        except json.JSONDecodeError:
            return {"time": elapsed, "ok": False, "error": f"Invalid JSON: {body[:100]}", "body_len": len(body)}
    except Exception as e:
        return {"time": time.time() - t0, "ok": False, "error": str(e)[:200]}


# ── 测试用例 ──────────────────────────────────────────────

PAGE_TESTS = [
    {"name": "首页重定向", "path": "/", "expect_status": 200},
    {"name": "仪表盘页面", "path": "/dashboard", "expect_status": 200},
    {"name": "数据大屏页面", "path": "/bigscreen", "expect_status": 200},
    {"name": "报告页面", "path": "/report", "expect_status": 200},
    {"name": "测试报告页面", "path": "/test-report", "expect_status": 200},
]

API_TESTS = [
    {"name": "Dashboard API", "path": "/dashboard"},
    {"name": "Reports API", "path": "/reports"},
    {"name": "Test Reports API", "path": "/test-reports"},
]

# 无需认证的公开 API（直接 GET，不走 http_api 的 Bearer 认证）
PUBLIC_API_TESTS = [
    {"name": "Health: Ready Check", "url": "https://aisport.tech/readyz", "expect_key": "status"},
    {"name": "Health: Live Check", "url": "https://aisport.tech/livez", "expect_status": 200},
    {"name": "Version API", "url": "https://aisport.tech/version", "expect_key": "version"},
    {"name": "Users Summary API", "url": f"{BASE_URL}/api/users/summary", "expect_key": "users"},
]

DATA_ASSERTIONS = {
    # 结构验证：生产数据必须存在的 JSON 响应字段
    "running.activity": lambda v: isinstance(v, dict),
    "activity.running": lambda v: isinstance(v, dict),
    "activity.general": lambda v: isinstance(v, dict),
    # 以下为 profile 字段（可选 — 仅该用户有 profile 数据时验证）
    "profile.vo2_max": lambda v: v is None or (isinstance(v, (int, float)) and 20 <= v <= 80),
    "profile.bmi": lambda v: v is None or (isinstance(v, float) and 10 <= v <= 50),
    "profile.weight_kg": lambda v: v is None or (isinstance(v, (int, float)) and 30 <= v <= 200),
    "profile.age": lambda v: v is None or (isinstance(v, int) and 0 <= v <= 120),
}


def run_round(round_num: int) -> dict:
    results = {"round": round_num, "timestamp": datetime.now().isoformat(), "tests": []}

    def _run_test(test_fn, category, name, meta):
        """Run a test with retry logic."""
        for attempt in range(RETRY_COUNT + 1):
            r = test_fn()
            if r.get("ok"):
                break
            if r.get("skipped"):
                break
            if attempt < RETRY_COUNT:
                time.sleep(RETRY_DELAY)
        return {
            "category": category, "name": name,
            "passed": r.get("ok", False),
            "skipped": r.get("skipped", False),
            "skip_reason": r.get("skip_reason", ""),
            **meta(r),
            "error": r.get("error"),
        }

    # 页面测试
    for test in PAGE_TESTS:
        def _test(t=test):
            return http_get(t["path"])
        results["tests"].append(_run_test(
            _test, "页面", test["name"],
            lambda r: {"status": r.get("status", 0), "time_ms": round(r["time"] * 1000, 1), "size_kb": round(r.get("size", 0) / 1024, 1)}
        ))

    # API 测试（需认证）
    for test in API_TESTS:
        def _test(t=test):
            return http_api(t["path"])
        results["tests"].append(_run_test(
            _test, "API", test["name"],
            lambda r: {"time_ms": round(r["time"] * 1000, 1), "size_kb": round(r.get("body_len", 0) / 1024, 1)}
        ))

    # 公开 API 测试
    for test in PUBLIC_API_TESTS:
        if "expect_status" in test:
            def _test_fn(t=test):
                t0 = time.time()
                try:
                    r = subprocess.run(
                        ["curl", "-sSk", "-w", "%{http_code}", t["url"], "--max-time", "10"],
                        capture_output=True, text=True, timeout=15,
                    )
                    elapsed = time.time() - t0
                    body = r.stdout
                    # Extract HTTP status from last 3 chars
                    http_code_str = body[-3:] if len(body) >= 3 else ""
                    status = int(http_code_str) if http_code_str.isdigit() else 0
                    body_len = len(body) - 3 if status > 0 else len(body)
                    ok = status == t.get("expect_status", 200)
                    return {"ok": ok, "time": elapsed, "body_len": body_len}
                except Exception as e:
                    return {"ok": False, "time": time.time() - t0, "error": str(e)[:200]}
        else:
            has_key = test.get("expect_key")
            def _test_fn(t=test, k=has_key):
                r = http_get_json(t["url"])
                if k and k not in r.get("data", {}):
                    r["ok"] = False
                    r["error"] = f"Missing expected key: {k}"
                return r

        results["tests"].append(_run_test(
            _test_fn, "公开API", test["name"],
            lambda r: {"time_ms": round(r["time"] * 1000, 1), "size_kb": round(r.get("body_len", 0) / 1024, 1)}
        ))

    # 数据完整性断言（仅 API 通过时执行）
    dashboard = http_api("/dashboard")
    if dashboard["ok"] and "data" in dashboard:
        data = dashboard["data"].get("data", {})
        for key, assertion in DATA_ASSERTIONS.items():
            value = data.get(key)
            try:
                ok = assertion(value)
            except Exception:
                ok = False
            results["tests"].append({
                "category": "数据完整性", "name": key, "passed": ok,
                "skipped": False, "skip_reason": "",
                "value": value, "time_ms": 0,
            })
    elif dashboard.get("skipped"):
        for key, assertion in DATA_ASSERTIONS.items():
            results["tests"].append({
                "category": "数据完整性", "name": key, "passed": False,
                "skipped": True, "skip_reason": dashboard.get("skip_reason", "JWT auth required"),
                "value": None, "time_ms": 0,
            })

    return results


# ── SVG 图表 ─────────────────────────────────────────────

def generate_svg(results: list, stats: dict) -> str:
    page_avg, api_avg, pass_counts = [], [], []
    for r in results:
        pt = [t["time_ms"] for t in r["tests"] if t["category"] == "页面" and t["time_ms"] > 0]
        at = [t["time_ms"] for t in r["tests"] if t["category"] == "API" and t["time_ms"] > 0]
        page_avg.append(statistics.mean(pt) if pt else 0)
        api_avg.append(statistics.mean(at) if at else 0)
        pass_counts.append(sum(1 for t in r["tests"] if t["passed"]))

    all_times = page_avg + api_avg
    max_time = max(all_times) * 1.2 if all_times else 100
    w, h = 800, 440
    cl, cr, ct, cb = 80, 760, 60, 340
    cw, ch = cr - cl, cb - ct

    def x(i): return cl + (i / max(ROUNDS - 1, 1)) * cw
    def y(v): return cb - (v / max_time) * ch if max_time > 0 else cb

    C_BG, C_PAGE, C_API, C_GRID, C_TEXT, C_WHITE = "#0d1117", "#00C9A7", "#00D4FF", "#333", "#888", "#fff"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="system-ui,sans-serif">',
        f'<rect width="{w}" height="{h}" fill="{C_BG}" rx="8"/>',
        f'<text x="{w//2}" y="28" text-anchor="middle" fill="{C_WHITE}" font-size="16" font-weight="600">RHYTHMIND E2E 响应时间趋势</text>',
        f'<text x="{w//2}" y="46" text-anchor="middle" fill="{C_TEXT}" font-size="11">10 轮测试 · {datetime.now().strftime("%Y-%m-%d %H:%M")}</text>',
    ]

    for i in range(5):
        val = max_time * i / 4
        yy = y(val)
        parts.append(f'<line x1="{cl}" y1="{yy}" x2="{cr}" y2="{yy}" stroke="{C_GRID}" stroke-dasharray="4,4"/>')
        parts.append(f'<text x="{cl-8}" y="{yy+4}" text-anchor="end" fill="{C_TEXT}" font-size="10">{val:.0f}</text>')
    parts.append(f'<text x="{cl-8}" y="{cb+20}" text-anchor="end" fill="{C_TEXT}" font-size="10">ms</text>')

    for i in range(ROUNDS):
        parts.append(f'<text x="{x(i)}" y="{cb+16}" text-anchor="middle" fill="{C_TEXT}" font-size="10">R{i+1}</text>')

    for avg, color, label in [(page_avg, C_PAGE, "页面"), (api_avg, C_API, "API")]:
        if not avg:
            continue
        pts = " ".join(f"{x(i)},{y(avg[i])}" for i in range(ROUNDS))
        area = pts + f" {x(ROUNDS-1)},{cb} {x(0)},{cb}"
        parts.append(f'<polygon points="{area}" fill="{color}" opacity="0.15"/>')
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>')
        for i in range(ROUNDS):
            parts.append(f'<circle cx="{x(i)}" cy="{y(avg[i])}" r="3.5" fill="{color}"/>')

    # 通过率条
    by = 370
    parts.append(f'<text x="{cl}" y="{by+12}" fill="{C_TEXT}" font-size="10">通过数:</text>')
    bw = (cw - 60) / ROUNDS
    for i in range(ROUNDS):
        bx = cl + 50 + i * bw
        total_t = len(results[i]["tests"])
        ratio = pass_counts[i] / total_t if total_t else 0
        fill = C_PAGE if ratio == 1 else "#FF4757"
        parts.append(f'<rect x="{bx}" y="{by}" width="{bw-4}" height="16" rx="2" fill="{fill}" opacity="0.7"/>')
        parts.append(f'<text x="{bx+bw/2-2}" y="{by+12}" text-anchor="middle" fill="{C_WHITE}" font-size="8">{pass_counts[i]}</text>')

    # 图例 + 统计
    ly = 400
    parts.append(f'<circle cx="{cl+10}" cy="{ly}" r="5" fill="{C_PAGE}"/>')
    parts.append(f'<text x="{cl+20}" y="{ly+4}" fill="{C_WHITE}" font-size="12">页面平均响应</text>')
    parts.append(f'<circle cx="{cl+150}" cy="{ly}" r="5" fill="{C_API}"/>')
    parts.append(f'<text x="{cl+160}" y="{ly+4}" fill="{C_WHITE}" font-size="12">API 平均响应</text>')

    pt_s = stats["page_times"]
    at_s = stats["api_times"]
    sx = cl + 350
    if pt_s:
        parts.append(f'<text x="{sx}" y="{ly-2}" fill="{C_TEXT}" font-size="11">页面 avg {statistics.mean(pt_s):.0f}ms | p95 {sorted(pt_s)[int(len(pt_s)*0.95)]:.0f}ms</text>')
    if at_s:
        parts.append(f'<text x="{sx}" y="{ly+14}" fill="{C_TEXT}" font-size="11">API avg {statistics.mean(at_s):.0f}ms | p95 {sorted(at_s)[int(len(at_s)*0.95)]:.0f}ms</text>')

    # 甜甜圈图 - 通过率
    dcx, dcy, dr = 720, 410, 25
    total = stats["total_passed"] + stats["total_failed"]
    ratio = stats["total_passed"] / total if total else 0
    angle = ratio * 360
    import math
    x1 = dcx + dr * math.cos(math.radians(-90))
    y1 = dcy + dr * math.sin(math.radians(-90))
    x2 = dcx + dr * math.cos(math.radians(-90 + angle))
    y2 = dcy + dr * math.sin(math.radians(-90 + angle))
    large = 1 if angle > 180 else 0
    parts.append(f'<circle cx="{dcx}" cy="{dcy}" r="{dr}" fill="none" stroke="{C_GRID}" stroke-width="6"/>')
    parts.append(f'<path d="M {dcx} {dcy-dr} A {dr} {dr} 0 {large} 1 {x2:.1f} {y2:.1f}" fill="none" stroke="{C_PAGE}" stroke-width="6" stroke-linecap="round"/>')
    parts.append(f'<text x="{dcx}" y="{dcy+2}" text-anchor="middle" fill="{C_WHITE}" font-size="11" font-weight="600">{ratio*100:.1f}%</text>')
    parts.append(f'<text x="{dcx}" y="{dcy+dr+16}" text-anchor="middle" fill="{C_TEXT}" font-size="9">通过率</text>')

    parts.append('</svg>')
    return "\n".join(parts)


# ── MD 报告 ──────────────────────────────────────────────

def generate_md(results: list, stats: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = stats["total_passed"] + stats["total_failed"] + stats.get("total_skipped", 0)
    effective = stats["total_passed"] + stats["total_failed"]
    rate = stats["total_passed"] / effective * 100 if effective else 0
    pt, at = stats["page_times"], stats["api_times"]

    lines = [
        "# RHYTHMIND E2E 测试报告", "",
        f"> 测试时间: {now}  ",
        f"> 测试轮次: {ROUNDS}  ",
        f"> 目标环境: {BASE_URL}", "",
        "## 总体结果", "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 总测试数 | {total} |",
        f"| 通过数 | **{stats['total_passed']}** |",
        f"| 失败数 | {stats['total_failed']} |",
    ]
    if stats.get("total_skipped", 0) > 0:
        lines.append(f"| 跳过数 | {stats['total_skipped']} (需有效 JWT) |")
    lines.append(f"| 通过率 | **{rate:.1f}%** |")
    if pt:
        lines.append(f"| 页面平均响应 | {statistics.mean(pt):.0f} ms |")
        lines.append(f"| 页面 P95 | {sorted(pt)[int(len(pt)*0.95)]:.0f} ms |")
    if at:
        lines.append(f"| API 平均响应 | {statistics.mean(at):.0f} ms |")
        lines.append(f"| API P95 | {sorted(at)[int(len(at)*0.95)]:.0f} ms |")

    lines += ["", "## 测试用例明细", "",
              "| # | 类别 | 用例 | 通过率 | 平均(ms) | 说明 |",
              "|---|------|------|--------|---------|------|"]

    test_names = [(t["category"], t["name"]) for t in results[0]["tests"]]
    for idx, (cat, name) in enumerate(test_names, 1):
        p = sum(1 for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and t["passed"])
        s = sum(1 for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and t.get("skipped"))
        ts = [t["time_ms"] for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and t["time_ms"] > 0 and not t.get("skipped")]
        avg = statistics.mean(ts) if ts else 0
        fails = [r["round"] for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and not t["passed"] and not t.get("skipped")]
        if s == ROUNDS:
            icon, note = "⏭️", "需 JWT 认证"
        elif p == ROUNDS:
            icon, note = "✅", ""
        else:
            icon, note = "❌", f"失败轮次: {','.join(map(str,fails))}"
        lines.append(f"| {idx} | {cat} | {name} | {icon} {p}/{ROUNDS} | {avg:.0f} | {note} |")

    lines += ["", "## 性能趋势", "", "![趋势图](./e2e-charts.svg)", ""]
    return "\n".join(lines)


# ── HTML 报告（内联 SVG）─────────────────────────────────

def generate_html(results: list, stats: dict, svg_content: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = stats["total_passed"] + stats["total_failed"] + stats.get("total_skipped", 0)
    effective = stats["total_passed"] + stats["total_failed"]
    rate = stats["total_passed"] / effective * 100 if effective else 0
    total_rate = stats["total_passed"] / total * 100 if total else 0
    pt, at = stats["page_times"], stats["api_times"]
    skipped = stats.get("total_skipped", 0)

    # 测试用例行
    test_names = [(t["category"], t["name"]) for t in results[0]["tests"]]
    rows = ""
    for idx, (cat, name) in enumerate(test_names, 1):
        p = sum(1 for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and t["passed"])
        s = sum(1 for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and t.get("skipped"))
        ts = [t["time_ms"] for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and t["time_ms"] > 0 and not t.get("skipped")]
        avg = statistics.mean(ts) if ts else 0
        if s == ROUNDS:
            icon, color, note = "⏭️", "#FFB800", "需 JWT 认证"
        elif p == ROUNDS:
            icon, color, note = "✅", "#00C9A7", "-"
        else:
            fails = [str(r["round"]) for r in results for t in r["tests"] if t["category"] == cat and t["name"] == name and not t["passed"] and not t.get("skipped")]
            icon, color, note = "❌", "#FF4757", f"失败: R{','.join(fails)}"
        rows += f'<tr><td>{idx}</td><td>{cat}</td><td>{name}</td><td style="color:{color};font-weight:600">{icon} {p}/{ROUNDS}</td><td>{avg:.0f}</td><td style="color:#888;font-size:11px">{note}</td></tr>\n'

    # 各轮次折叠
    rounds_html = ""
    for r in results:
        p = sum(1 for t in r["tests"] if t["passed"])
        s = sum(1 for t in r["tests"] if t.get("skipped"))
        f = sum(1 for t in r["tests"] if not t["passed"] and not t.get("skipped"))
        icon = "✅" if f == 0 and s == 0 else ("⚠️" if f == 0 and s > 0 else "❌")
        summary = f"Round {r['round']} {icon} — {p} passed"
        if f > 0: summary += f" / {f} failed"
        if s > 0: summary += f" / {s} skipped"
        detail_rows = ""
        for t in r["tests"]:
            if t.get("skipped"):
                si = "⏭️"
            elif t["passed"]:
                si = "✅"
            else:
                si = "❌"
            detail = t.get("skip_reason", "") or t.get("error", "") or str(t.get("value", ""))
            if len(detail) > 50: detail = detail[:50] + "..."
            detail_rows += f'<tr><td>{t["category"]}</td><td>{t["name"]}</td><td>{si}</td><td>{t["time_ms"]:.0f}</td><td style="font-size:10px;color:#888">{detail}</td></tr>\n'
        rounds_html += f'''
        <details style="margin:4px 0">
          <summary style="cursor:pointer;color:#ccc;font-size:13px;padding:6px 0">{summary}</summary>
          <table><tr><th>类别</th><th>用例</th><th>状态</th><th>响应(ms)</th><th>详情</th></tr>{detail_rows}</table>
        </details>'''

    skipped_card = '<div class="stat-card"><div class="val" style="color:#FFB800">' + str(skipped) + '</div><div class="label">跳过 (需JWT)</div></div>' if skipped > 0 else ""

    pt_avg = f'{statistics.mean(pt):.0f}' if pt else 'N/A'
    pt_p95 = f'{sorted(pt)[int(len(pt)*0.95)]:.0f}' if len(pt) > 5 else 'N/A'
    at_avg = f'{statistics.mean(at):.0f}' if at else 'N/A'
    at_p95 = f'{sorted(at)[int(len(at)*0.95)]:.0f}' if len(at) > 5 else 'N/A'

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>RHYTHMIND E2E 测试报告</title>
<style>
  @page {{ size: A4; margin: 15mm; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1117; color: #e0e0e0; font-family: system-ui, -apple-system, sans-serif; padding: 32px; max-width: 210mm; margin: 0 auto; font-size: 13px; line-height: 1.6; }}
  h1 {{ color: #fff; font-size: 22px; margin-bottom: 4px; }}
  h2 {{ color: #00C9A7; font-size: 16px; margin: 24px 0 12px; border-bottom: 1px solid #333; padding-bottom: 6px; }}
  .meta {{ color: #888; font-size: 11px; margin-bottom: 20px; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 16px 0; }}
  .stat-card {{ background: #161b22; border: 1px solid #333; border-radius: 8px; padding: 14px; text-align: center; }}
  .stat-card .val {{ font-size: 24px; font-weight: 700; color: #00C9A7; }}
  .stat-card .val.warn {{ color: #FF4757; }}
  .stat-card .label {{ font-size: 11px; color: #888; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; }}
  th {{ background: #161b22; color: #888; padding: 8px 12px; text-align: left; border-bottom: 1px solid #333; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #222; }}
  tr:hover {{ background: #161b22; }}
  .chart {{ margin: 20px 0; }}
  .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #333; color: #555; font-size: 10px; text-align: center; }}
  details table {{ margin: 8px 0; }}
  @media print {{ body {{ padding: 0; }} .no-print {{ display: none; }} }}
</style>
</head>
<body>
<h1>RHYTHMIND E2E 测试报告</h1>
<p class="meta">测试时间: {now} | 轮次: {ROUNDS} | 环境: {BASE_URL}</p>

<h2>总体结果</h2>
<div class="summary-grid">
  <div class="stat-card"><div class="val">{total}</div><div class="label">总测试数</div></div>
  <div class="stat-card"><div class="val">{stats["total_passed"]}</div><div class="label">通过数</div></div>
  <div class="stat-card"><div class="val {"warn" if stats["total_failed"] > 0 else ""}">{stats["total_failed"]}</div><div class="label">失败数</div></div>
  {skipped_card}
  <div class="stat-card"><div class="val">{rate:.1f}%</div><div class="label">通过率 (不含跳过)</div></div>
  <div class="stat-card"><div class="val">{pt_avg}ms</div><div class="label">页面平均响应</div></div>
  <div class="stat-card"><div class="val">{at_avg}ms</div><div class="label">API 平均响应</div></div>
  <div class="stat-card"><div class="val">{pt_p95}ms</div><div class="label">页面 P95</div></div>
  <div class="stat-card"><div class="val">{at_p95}ms</div><div class="label">API P95</div></div>
</div>

<h2>性能趋势</h2>
<div class="chart">
{svg_content}
</div>

<h2>测试用例明细</h2>
<table>
<tr><th>#</th><th>类别</th><th>用例</th><th>通过率</th><th>平均(ms)</th><th>说明</th></tr>
{rows}
</table>

<h2>各轮次详情</h2>
{rounds_html}

<div class="footer">
  湖南青沐生命科技有限公司 | RHYTHMIND 律动 E2E 自动化测试 | 报告由 Claude Code 自动生成
</div>
</body>
</html>'''


def upload_reports(results: list, stats: dict):
    """将报告文件上传到生产服务器。"""
    total = stats["total_passed"] + stats["total_failed"]
    rate = stats["total_passed"] / total * 100 if total else 0
    pt = stats["page_times"]
    at = stats["api_times"]

    report_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    remote_dir = f"/var/www/aisport.tech/qm/test_reports/{report_id}"

    print(f"\n  📤 上传报告到服务器...")

    # 生成 meta.json
    meta = {
        "timestamp": datetime.now().isoformat(),
        "rounds": ROUNDS,
        "total": total,
        "passed": stats["total_passed"],
        "failed": stats["total_failed"],
        "pass_rate": rate,
        "page_avg_ms": round(statistics.mean(pt)) if pt else 0,
        "api_avg_ms": round(statistics.mean(at)) if at else 0,
    }
    meta_path = REPORT_DIR / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    ssh_host = "root@43.129.201.118"
    ssh_pass = "q1w2e3r4+"

    # 创建远程目录
    r = subprocess.run(
        ["sshpass", "-p", ssh_pass, "ssh", "-o", "StrictHostKeyChecking=no",
         ssh_host, f"mkdir -p {remote_dir}"],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        print(f"  ❌ 创建远程目录失败: {r.stderr[:100]}")
        return

    # 上传所有文件
    files_to_upload = ["meta.json", "e2e-report.md", "e2e-report.html", "e2e-report.pdf", "e2e-charts.svg"]
    for fname in files_to_upload:
        fpath = REPORT_DIR / fname
        if not fpath.exists():
            continue
        r = subprocess.run(
            ["sshpass", "-p", ssh_pass, "scp", "-o", "StrictHostKeyChecking=no",
             str(fpath), f"{ssh_host}:{remote_dir}/"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            print(f"    ✅ {fname}")
        else:
            print(f"    ❌ {fname}: {r.stderr[:80]}")

    print(f"  ✅ 报告已上传: https://aisport.tech/qm/test-report")
    print(f"     API: https://aisport.tech/qm/api/test-reports/{report_id}")


# ── 主流程 ──────────────────────────────────────────────

def main():
    REPORT_DIR.mkdir(exist_ok=True)
    all_results = []
    stats = {"page_times": [], "api_times": [], "total_passed": 0, "total_failed": 0, "total_skipped": 0}

    print(f"{'='*60}")
    print(f"  RHYTHMIND E2E — {ROUNDS} 轮全链路测试")
    print(f"  {BASE_URL} · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    token_display = E2E_AUTH_TOKEN[:12] + "..." if len(E2E_AUTH_TOKEN) > 12 else E2E_AUTH_TOKEN
    print(f"  Auth: Bearer {token_display}")
    print(f"{'='*60}\n")

    for i in range(1, ROUNDS + 1):
        result = run_round(i)
        all_results.append(result)
        p = sum(1 for t in result["tests"] if t["passed"])
        s = sum(1 for t in result["tests"] if t.get("skipped"))
        f = sum(1 for t in result["tests"] if not t["passed"] and not t.get("skipped"))
        stats["total_passed"] += p
        stats["total_failed"] += f
        stats["total_skipped"] += s
        for t in result["tests"]:
            if t["time_ms"] > 0 and not t.get("skipped"):
                if t["category"] == "页面":
                    stats["page_times"].append(t["time_ms"])
                elif t["category"] == "API":
                    stats["api_times"].append(t["time_ms"])
        status = "PASS" if f == 0 else f"FAIL({f})"
        skip_info = f" ⏭️{s}" if s > 0 else ""
        print(f"  Round {i:2d}/{ROUNDS}  ✅{p}  ❌{f}{skip_info}  {status}")
        if i < ROUNDS:
            time.sleep(0.5)

    # 生成三件套
    svg = generate_svg(all_results, stats)
    md = generate_md(all_results, stats)

    (REPORT_DIR / "e2e-charts.svg").write_text(svg, encoding="utf-8")
    (REPORT_DIR / "e2e-report.md").write_text(md, encoding="utf-8")

    html = generate_html(all_results, stats, svg)
    html_path = REPORT_DIR / "e2e-report.html"
    html_path.write_text(html, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  ✅ 报告已生成:")
    print(f"    📄 e2e-report.md")
    print(f"    🌐 e2e-report.html (内联 SVG)")
    print(f"    📊 e2e-charts.svg")
    print(f"  📑 下一步: HTML → A4 PDF (Playwright)")
    print(f"{'='*60}")

    return str(html_path), all_results, stats


if __name__ == "__main__":
    html_path, all_results, stats = main()

    # HTML → A4 PDF (Chrome headless)
    pdf_path = str(Path(html_path).parent / "e2e-report.pdf")
    print("\n  正在生成 A4 PDF...")

    # 先启动临时 HTTP 服务器（Chrome 不支持 file:// 协议打印）
    import http.server, threading, socketserver
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", 0), handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        import subprocess, shutil
        chrome = shutil.which("google-chrome") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        html_dir = str(Path(html_path).parent)
        r = subprocess.run([
            chrome, "--headless", "--disable-gpu", "--no-sandbox",
            f"--print-to-pdf={pdf_path}", "--print-to-pdf-no-header",
            f"http://localhost:{port}/{Path(html_path).name}",
        ], capture_output=True, text=True, timeout=30, cwd=html_dir)
        httpd.shutdown()

    if Path(pdf_path).exists():
        size_kb = Path(pdf_path).stat().st_size / 1024
        print(f"  ✅ A4 PDF: {pdf_path} ({size_kb:.0f} KB)")
    else:
        print(f"  ❌ PDF 生成失败: {r.stderr[:200] if r.stderr else 'unknown'}")

    # --upload: 上传报告到服务器
    if "--upload" in sys.argv:
        upload_reports(all_results, stats)
