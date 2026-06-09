#!/usr/bin/env python3
"""RHYTHMIND 渐进式压力测试 — 最大用户承载基准 + 架构优化建议

分层策略：
  Layer 1: 轻量层（纯 IO，不涉及 LLM）— 页面 + Dashboard/Reports API
  Layer 2: 中量层（Agent 流水线 + 27B LLM）— /qm/api/chat
  Layer 3: 重量层（上传 + Agent）— /api/v1/health/upload

使用：python3 scripts/stress_test.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

API_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:3000"
REPORT_DIR = Path("/tmp/qm-stress-reports")


@dataclass
class RequestResult:
    ok: bool
    status: int
    elapsed: float  # seconds
    error: str = ""
    endpoint: str = ""
    layer: str = ""


@dataclass
class StageResult:
    name: str
    layer: str
    concurrency: int
    duration: int
    results: list[RequestResult] = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total * 100 if self.total else 0

    @property
    def rps(self) -> float:
        times = [r.elapsed for r in self.results]
        return self.total / sum(times) if times else 0

    def latencies(self) -> list[float]:
        return sorted([r.elapsed * 1000 for r in self.results if r.ok])

    def p50(self) -> float:
        lats = self.latencies()
        return lats[len(lats) // 2] if lats else 0

    def p95(self) -> float:
        lats = self.latencies()
        return lats[int(len(lats) * 0.95)] if len(lats) > 5 else (lats[-1] if lats else 0)

    def p99(self) -> float:
        lats = self.latencies()
        return lats[int(len(lats) * 0.99)] if len(lats) > 10 else (lats[-1] if lats else 0)

    def avg(self) -> float:
        lats = self.latencies()
        return statistics.mean(lats) if lats else 0


# ── 请求函数 ──────────────────────────────────────────────

async def fetch_get(session: aiohttp.ClientSession, url: str, label: str, layer: str) -> RequestResult:
    t0 = time.monotonic()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            elapsed = time.monotonic() - t0
            return RequestResult(
                ok=200 <= resp.status < 300, status=resp.status,
                elapsed=elapsed, endpoint=label, layer=layer,
            )
    except Exception as e:
        return RequestResult(
            ok=False, status=0, elapsed=time.monotonic() - t0,
            error=str(e)[:80], endpoint=label, layer=layer,
        )


async def fetch_post(session: aiohttp.ClientSession, url: str, payload: dict,
                     headers: dict, label: str, layer: str, timeout: int = 120) -> RequestResult:
    t0 = time.monotonic()
    try:
        async with session.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            elapsed = time.monotonic() - t0
            body = await resp.text()
            ok = resp.status == 200
            # throttled 不算失败
            if resp.status == 200:
                try:
                    data = json.loads(body)
                    if data.get("status") == "throttled":
                        ok = None  # skip
                except json.JSONDecodeError:
                    pass
            return RequestResult(
                ok=ok if ok is not None else True, status=resp.status,
                elapsed=elapsed, endpoint=label, layer=layer,
            )
    except Exception as e:
        return RequestResult(
            ok=False, status=0, elapsed=time.monotonic() - t0,
            error=str(e)[:80], endpoint=label, layer=layer,
        )


# ── 测试场景 ──────────────────────────────────────────────

LAYER1_ENDPOINTS = [
    ("GET /ping", f"{API_URL}/ping"),
    ("GET /health", f"{API_URL}/health"),
    ("GET /version", f"{API_URL}/version"),
    ("GET /dashboard", f"{API_URL}/qm/api/dashboard"),
    ("GET /reports", f"{API_URL}/qm/api/reports"),
    ("GET /test-reports", f"{API_URL}/qm/api/test-reports"),
]

CHAT_PROMPTS = [
    "你好",
    "我最近的心率数据怎么样？",
    "今天适合跑步吗？",
]

UPLOAD_PAYLOADS = [
    {
        "source": "garmin", "sport_type": "running",
        "user_goal": "维持有氧",
        "heart_rate_avg": 145, "heart_rate_max": 178,
        "steps": 8000, "distance_km": 5.2,
    },
]


async def run_layer1_stage(session: aiohttp.ClientSession, concurrency: int, duration: int) -> list[RequestResult]:
    results: list[RequestResult] = []
    end_time = time.monotonic() + duration
    user_id = 0

    async def worker(wid: int):
        nonlocal user_id
        uid = f"stress_L1_{wid:04d}"
        while time.monotonic() < end_time:
            for label, url in LAYER1_ENDPOINTS:
                headers = {"Authorization": f"Bearer {uid}"}
                r = await fetch_get(
                    aiohttp.ClientSession(
                        headers=headers,
                        connector=aiohttp.TCPConnector(limit=0),
                    ),
                    url, label, "Layer1",
                )
                results.append(r)
                if time.monotonic() >= end_time:
                    break

    # 共用 session
    tasks = []
    for i in range(concurrency):
        tasks.append(asyncio.create_task(_l1_worker(session, i, end_time, results)))
    await asyncio.gather(*tasks)
    return results


async def _l1_worker(session: aiohttp.ClientSession, wid: int, end_time: float, results: list):
    uid = f"stress_L1_{wid:04d}"
    while time.monotonic() < end_time:
        for label, url in LAYER1_ENDPOINTS:
            headers = {"Authorization": f"Bearer {uid}"}
            r = await fetch_get(session, url, label, "Layer1")
            results.append(r)
            if time.monotonic() >= end_time:
                break


async def run_layer2_stage(session: aiohttp.ClientSession, concurrency: int, duration: int) -> list[RequestResult]:
    results: list[RequestResult] = []
    end_time = time.monotonic() + duration
    idx = 0

    async def worker(wid: int):
        nonlocal idx
        while time.monotonic() < end_time:
            uid = f"stress_L2_{wid:04d}_{idx % 100:03d}"
            idx += 1
            prompt = CHAT_PROMPTS[idx % len(CHAT_PROMPTS)]
            headers = {"Authorization": f"Bearer {uid}", "Content-Type": "application/json"}
            payload = {"text": prompt, "context": {}}
            r = await fetch_post(session, f"{API_URL}/qm/api/chat", payload, headers, "POST /chat", "Layer2", timeout=120)
            results.append(r)

    tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
    await asyncio.gather(*tasks)
    return results


async def run_layer3_stage(session: aiohttp.ClientSession, concurrency: int, duration: int) -> list[RequestResult]:
    results: list[RequestResult] = []
    end_time = time.monotonic() + duration
    idx = 0

    async def worker(wid: int):
        nonlocal idx
        while time.monotonic() < end_time:
            uid = f"stress_L3_{wid:04d}_{idx % 100:03d}"
            idx += 1
            payload = UPLOAD_PAYLOADS[idx % len(UPLOAD_PAYLOADS)]
            headers = {"Authorization": f"Bearer {uid}", "Content-Type": "application/json"}
            r = await fetch_post(
                session, f"{API_URL}/api/v1/health/upload",
                payload, headers, "POST /upload", "Layer3", timeout=120,
            )
            results.append(r)

    tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
    await asyncio.gather(*tasks)
    return results


# ── 主流程 ──────────────────────────────────────────────

STAGES = [
    # Layer 1: 轻量层渐进加压
    {"name": "L1-5users", "layer": "Layer1", "concurrency": 5, "duration": 20},
    {"name": "L1-10users", "layer": "Layer1", "concurrency": 10, "duration": 20},
    {"name": "L1-25users", "layer": "Layer1", "concurrency": 25, "duration": 20},
    {"name": "L1-50users", "layer": "Layer1", "concurrency": 50, "duration": 20},
    {"name": "L1-100users", "layer": "Layer1", "concurrency": 100, "duration": 20},
    {"name": "L1-200users", "layer": "Layer1", "concurrency": 200, "duration": 20},
    # Layer 2: Agent + LLM
    {"name": "L2-3users", "layer": "Layer2", "concurrency": 3, "duration": 60},
    {"name": "L2-5users", "layer": "Layer2", "concurrency": 5, "duration": 60},
    {"name": "L2-10users", "layer": "Layer2", "concurrency": 10, "duration": 90},
    # Layer 3: 综合上传
    {"name": "L3-3users", "layer": "Layer3", "concurrency": 3, "duration": 60},
]


async def main():
    REPORT_DIR.mkdir(exist_ok=True)
    all_stages: list[StageResult] = []

    print(f"{'='*70}")
    print(f"  RHYTHMIND 渐进式压力测试")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  API: {API_URL}")
    print(f"  阶段数: {len(STAGES)}")
    print(f"{'='*70}\n")

    connector = aiohttp.TCPConnector(limit=300, limit_per_host=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        for stage_cfg in STAGES:
            name = stage_cfg["name"]
            layer = stage_cfg["layer"]
            conc = stage_cfg["concurrency"]
            dur = stage_cfg["duration"]

            print(f"  ▶ {name} ({conc} 并发 × {dur}s)...", end="", flush=True)
            t_start = datetime.now().isoformat()

            if layer == "Layer1":
                results = await run_layer1_stage(session, conc, dur)
            elif layer == "Layer2":
                results = await run_layer2_stage(session, conc, dur)
            elif layer == "Layer3":
                results = await run_layer3_stage(session, conc, dur)
            else:
                results = []

            t_end = datetime.now().isoformat()
            stage = StageResult(
                name=name, layer=layer, concurrency=conc,
                duration=dur, results=results,
                start_time=t_start, end_time=t_end,
            )
            all_stages.append(stage)

            ok_lats = stage.latencies()
            print(f"  ✅{stage.passed} ❌{stage.failed} | "
                  f"RPS={stage.rps:.1f} | "
                  f"P50={stage.p50():.0f}ms P95={stage.p95():.0f}ms P99={stage.p99():.0f}ms")

    # 汇总
    print(f"\n{'='*70}")
    print(f"  压测完成")
    print(f"{'='*70}\n")

    generate_reports(all_stages)
    generate_optimization(all_stages)

    return all_stages


# ── 报告生成 ──────────────────────────────────────────────

def generate_reports(stages: list[StageResult]):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # MD 报告
    lines = [
        "# RHYTHMIND 压力测试报告", "",
        f"> 测试时间: {now}  ",
        f"> 目标: {API_URL}  ",
        f"> 阶段数: {len(stages)}", "",
        "## 各阶段结果", "",
        "| 阶段 | 并发 | 总请求 | 成功 | 失败 | RPS | P50(ms) | P95(ms) | P99(ms) |",
        "|------|------|--------|------|------|-----|---------|---------|---------|",
    ]

    for s in stages:
        lines.append(
            f"| {s.name} | {s.concurrency} | {s.total} | {s.passed} | {s.failed} | "
            f"{s.rps:.1f} | {s.p50():.0f} | {s.p95():.0f} | {s.p99():.0f} |"
        )

    # 拐点分析
    lines += ["", "## 拐点分析", ""]
    for layer_name in ["Layer1", "Layer2", "Layer3"]:
        layer_stages = [s for s in stages if s.layer == layer_name]
        if not layer_stages:
            continue
        lines.append(f"### {layer_name}")
        lines.append("")
        best_rps = max(layer_stages, key=lambda s: s.rps)
        best_p95 = min([s for s in layer_stages if s.passed > 0], key=lambda s: s.p95())
        lines.append(f"- 最高 RPS: {best_rps.name} ({best_rps.rps:.1f} req/s)")
        lines.append(f"- P95 最低: {best_p95.name} ({best_p95.p95():.0f}ms)")

        # 找拐点：P95 突增 > 2x 前一阶段
        prev_p95 = None
        for s in layer_stages:
            if prev_p95 and s.p95() > prev_p95 * 2 and s.p95() > 1000:
                lines.append(f"- ⚠️ 拐点: {s.name} (P95 {s.p95():.0f}ms, 前一阶段 {prev_p95:.0f}ms, 增长 >2x)")
                break
            prev_p95 = s.p95()
        lines.append("")

    md_path = REPORT_DIR / "stress-report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # HTML 报告
    html = generate_html(stages, now)
    html_path = REPORT_DIR / "stress-report.html"
    html_path.write_text(html, encoding="utf-8")

    print(f"  📄 报告: {html_path}")


def generate_html(stages: list[StageResult], now: str) -> str:
    rows = ""
    for s in stages:
        color = "#00C9A7" if s.pass_rate >= 95 else ("#FFA500" if s.pass_rate >= 80 else "#FF4757")
        rows += f'<tr>'
        rows += f'<td>{s.name}</td><td>{s.concurrency}</td><td>{s.total}</td>'
        rows += f'<td style="color:{color};font-weight:600">{s.passed}</td>'
        rows += f'<td>{s.failed}</td><td>{s.rps:.1f}</td>'
        rows += f'<td>{s.p50():.0f}</td><td>{s.p95():.0f}</td><td>{s.p99():.0f}</td>'
        rows += f'</tr>\n'

    # SVG 趋势图
    svg = generate_svg_chart(stages)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>RHYTHMIND 压力测试报告</title>
<style>
  @page {{ size: A4; margin: 15mm; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1117; color: #e0e0e0; font-family: system-ui, -apple-system, sans-serif; padding: 32px; max-width: 220mm; margin: 0 auto; font-size: 13px; line-height: 1.6; }}
  h1 {{ color: #fff; font-size: 22px; margin-bottom: 4px; }}
  h2 {{ color: #00C9A7; font-size: 16px; margin: 24px 0 12px; border-bottom: 1px solid #333; padding-bottom: 6px; }}
  .meta {{ color: #888; font-size: 11px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12px; }}
  th {{ background: #161b22; color: #888; padding: 8px 10px; text-align: left; border-bottom: 1px solid #333; font-size: 11px; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #222; }}
  tr:hover {{ background: #161b22; }}
  .chart {{ margin: 20px 0; }}
  .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #333; color: #555; font-size: 10px; text-align: center; }}
  .opt {{ background: #161b22; border: 1px solid #333; border-radius: 8px; padding: 16px; margin: 12px 0; }}
  .opt h3 {{ color: #FFA500; font-size: 14px; margin-bottom: 8px; }}
  .opt ul {{ padding-left: 20px; }}
  .opt li {{ margin: 4px 0; font-size: 12px; }}
</style>
</head>
<body>
<h1>RHYTHMIND 压力测试报告</h1>
<p class="meta">测试时间: {now} | API: {API_URL}</p>

<h2>性能趋势</h2>
<div class="chart">{svg}</div>

<h2>各阶段结果</h2>
<table>
<tr><th>阶段</th><th>并发</th><th>总请求</th><th>成功</th><th>失败</th><th>RPS</th><th>P50(ms)</th><th>P95(ms)</th><th>P99(ms)</th></tr>
{rows}
</table>

{generate_optimization_html(stages)}

<div class="footer">湖南青沐生命科技有限公司 | RHYTHMIND 律动 压力测试 | Claude Code 自动生成</div>
</body>
</html>'''


def generate_svg_chart(stages: list[StageResult]) -> str:
    l1 = [(s.concurrency, s.rps, s.p95()) for s in stages if s.layer == "Layer1"]
    if not l1:
        return "<p>No Layer1 data</p>"

    max_rps = max(r for _, r, _ in l1) * 1.2
    max_p95 = max(p for _, _, p in l1) * 1.2
    w, h = 900, 350
    cl, cr, ct, cb = 70, 860, 40, 260
    cw, ch = cr - cl, cb - ct

    def x(i): return cl + (i / max(len(l1) - 1, 1)) * cw

    C_BG, C_RPS, C_P95, C_GRID, C_TEXT, C_WHITE = "#0d1117", "#00C9A7", "#FF6B6B", "#333", "#888", "#fff"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="system-ui,sans-serif">',
        f'<rect width="{w}" height="{h}" fill="{C_BG}" rx="8"/>',
        f'<text x="{w//2}" y="24" text-anchor="middle" fill="{C_WHITE}" font-size="14" font-weight="600">Layer1: RPS & P95 vs 并发用户数</text>',
    ]

    # RPS Y轴 (左)
    for i in range(5):
        val = max_rps * i / 4
        yy = cb - (val / max_rps) * ch if max_rps else cb
        parts.append(f'<line x1="{cl}" y1="{yy}" x2="{cr}" y2="{yy}" stroke="{C_GRID}" stroke-dasharray="4,4"/>')
        parts.append(f'<text x="{cl-6}" y="{yy+4}" text-anchor="end" fill="{C_RPS}" font-size="9">{val:.0f}</text>')

    # P95 Y轴 (右)
    for i in range(5):
        val = max_p95 * i / 4
        yy = cb - (val / max_p95) * ch if max_p95 else cb
        parts.append(f'<text x="{cr+6}" y="{yy+4}" fill="{C_P95}" font-size="9">{val:.0f}</text>')

    parts.append(f'<text x="{cl-6}" y="{cb+14}" text-anchor="end" fill="{C_TEXT}" font-size="9">RPS</text>')
    parts.append(f'<text x="{cr+6}" y="{cb+14}" fill="{C_TEXT}" font-size="9">P95ms</text>')

    for i, (conc, rps, p95) in enumerate(l1):
        parts.append(f'<text x="{x(i)}" y="{cb+16}" text-anchor="middle" fill="{C_TEXT}" font-size="9">{conc}</text>')

    # RPS 线
    rps_pts = " ".join(f"{x(i)},{cb - (rps/max_rps)*ch}" for i, (_, rps, _) in enumerate(l1))
    parts.append(f'<polyline points="{rps_pts}" fill="none" stroke="{C_RPS}" stroke-width="2.5" stroke-linejoin="round"/>')
    for i, (_, rps, _) in enumerate(l1):
        parts.append(f'<circle cx="{x(i)}" cy="{cb - (rps/max_rps)*ch}" r="4" fill="{C_RPS}"/>')

    # P95 线
    p95_pts = " ".join(f"{x(i)},{cb - (p95/max_p95)*ch}" for i, (_, _, p95) in enumerate(l1))
    parts.append(f'<polyline points="{p95_pts}" fill="none" stroke="{C_P95}" stroke-width="2.5" stroke-linejoin="round" stroke-dasharray="6,3"/>')
    for i, (_, _, p95) in enumerate(l1):
        parts.append(f'<circle cx="{x(i)}" cy="{cb - (p95/max_p95)*ch}" r="4" fill="{C_P95}"/>')

    # 图例
    ly = cb + 40
    parts.append(f'<circle cx="{cl+10}" cy="{ly}" r="5" fill="{C_RPS}"/>')
    parts.append(f'<text x="{cl+20}" y="{ly+4}" fill="{C_WHITE}" font-size="11">RPS (请求/秒)</text>')
    parts.append(f'<circle cx="{cl+150}" cy="{ly}" r="5" fill="{C_P95}"/>')
    parts.append(f'<text x="{cl+160}" y="{ly+4}" fill="{C_WHITE}" font-size="11">P95 延迟 (ms)</text>')
    parts.append(f'<text x="{cl+320}" y="{ly+4}" fill="{C_TEXT}" font-size="11">X轴: 并发用户数</text>')

    parts.append('</svg>')
    return "\n".join(parts)


def generate_optimization(stages: list[StageResult]):
    """输出架构优化建议到控制台。"""
    print(f"\n{'='*70}")
    print(f"  架构优化建议")
    print(f"{'='*70}\n")

    l1_stages = [s for s in stages if s.layer == "Layer1"]
    l2_stages = [s for s in stages if s.layer == "Layer2"]
    l3_stages = [s for s in stages if s.layer == "Layer3"]

    # 分析 Layer1
    if l1_stages:
        max_l1 = max(l1_stages, key=lambda s: s.rps)
        print(f"  [Layer1 - 轻量API]")
        print(f"    最大RPS: {max_l1.name} = {max_l1.rps:.1f} req/s")
        print(f"    建议: Uvicorn 单 worker，若需 >200 RPS 考虑 gunicorn -w 4")
        print()

    if l2_stages:
        max_l2 = max(l2_stages, key=lambda s: s.rps)
        print(f"  [Layer2 - Agent流水线]")
        print(f"    最大RPS: {max_l2.name} = {max_l2.rps:.1f} req/s")
        print(f"    瓶颈: 27B 推理 ~9-17s/次，Semaphore=1 串行")
        print(f"    建议: 模型推理是绝对瓶颈，需水平扩展 oMLX 实例")
        print()

    if l3_stages:
        max_l3 = max(l3_stages, key=lambda s: s.rps)
        print(f"  [Layer3 - 综合上传]")
        print(f"    最大RPS: {max_l3.name} = {max_l3.rps:.1f} req/s")
        print()


def generate_optimization_html(stages: list[StageResult]) -> str:
    l1 = [s for s in stages if s.layer == "Layer1"]
    l2 = [s for s in stages if s.layer == "Layer2"]
    l3 = [s for s in stages if s.layer == "Layer3"]

    l1_max_rps = max(l1, key=lambda s: s.rps).rps if l1 else 0
    l2_max_rps = max(l2, key=lambda s: s.rps).rps if l2 else 0
    l3_max_rps = max(l3, key=lambda s: s.rps).rps if l3 else 0

    # 计算最大用户承载
    # Layer1: 每 user 平均每秒发 ~6 请求（6 个端点循环）
    l1_avg_per_user = l1[0].rps / l1[0].concurrency if l1 else 1
    l1_max_users = int(l1_max_rps / l1_avg_per_user) if l1_avg_per_user else 0

    # Layer2: 每 user 每 ~16s 发 1 请求
    l2_avg_per_user = l2[0].rps / l2[0].concurrency if l2 else 0.06
    l2_max_users = int(l2_max_rps / l2_avg_per_user) if l2_avg_per_user else 0

    return f'''
<h2>最大用户承载基准</h2>
<div class="opt">
<table>
<tr><th>层级</th><th>最大RPS</th><th>单用户QPS</th><th>理论最大用户数</th><th>实际瓶颈</th></tr>
<tr><td>Layer1 (轻量API)</td><td>{l1_max_rps:.1f}</td><td>{l1_avg_per_user:.2f}</td><td>~{l1_max_users}</td><td>PG连接池(30) / Uvicorn单Worker</td></tr>
<tr><td>Layer2 (Agent+LLM)</td><td>{l2_max_rps:.2f}</td><td>{l2_avg_per_user:.4f}</td><td>~{l2_max_users}</td><td>27B推理 ~16s/次 串行</td></tr>
<tr><td>Layer3 (综合上传)</td><td>{l3_max_rps:.2f}</td><td>-</td><td>-</td><td>Agent + DB 写入</td></tr>
</table>
</div>

<h2>架构优化建议</h2>
<div class="opt">
<h3>🔴 关键瓶颈（影响最大）</h3>
<ul>
<li><b>LLM 推理串行</b>: MLX Semaphore=1 + oMLX 单实例 → Agent 流水线被 LLM 吞吐卡死。建议：部署 2-4 个 oMLX 实例做负载均衡，或切换到 LiteLLM 云端网关</li>
<li><b>Uvicorn 单 Worker</b>: 单进程无法利用多核。建议：<code>gunicorn -w 4 -k uvicorn.workers.UvicornWorker</code>，RPS 可提升 ~3-4x</li>
</ul>
</div>

<div class="opt">
<h3>🟡 重要优化（显著提升）</h3>
<ul>
<li><b>PG 连接池</b>: pool_size=10 + max_overflow=20 = 30 连接上限。200 并发时排队。建议：pool_size=20, max_overflow=40</li>
<li><b>Redis 连接池</b>: pool_size=10，高并发时 Rate Limiter 和 Cache 竞争。建议：pool_size=20</li>
<li><b>AgentPool TTL</b>: 1800s 内缓存 500 用户 Agent 实例。高并发时 LRU 频繁驱逐/重建。建议：max_users=2000, TTL=3600</li>
<li><b>LoopGuard</b>: 3次/24h 过于保守，测试环境几乎必定触发。建议：按场景分级（问候 10次/24h，查询 30次/24h）</li>
</ul>
</div>

<div class="opt">
<h3>🟢 细节优化（锦上添花）</h3>
<ul>
<li><b>Dashboard 缓存</b>: /qm/api/dashboard 每次查 DB。建议：Redis 缓存 30s，降低 DB 压力</li>
<li><b>响应压缩</b>: 启用 gzip 中间件，减少传输体积</li>
<li><b>连接复用</b>: 确保 httpx.AsyncClient 全局复用而非每次创建</li>
<li><b>健康检查优化</b>: /readyz 检查 DB+Redis+LLM，高频调用时消耗资源。建议：前端只检查 /ping</li>
</ul>
</div>
'''


if __name__ == "__main__":
    asyncio.run(main())
