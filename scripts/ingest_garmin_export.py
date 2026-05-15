#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# scripts/ingest_garmin_export.py
# 把 Garmin Connect 导出包里的 activities 数据按顺序推入本地 /api/v1/health/upload，
# 用真实数据跑通 MetricsAgent → DataAgent → CoachAgent 三阶段流水线。
# ─────────────────────────────────────────────────────────────────────────────
"""
用法（最简）:
    cp /path/to/garmin_export.zip ~/Downloads/
    unzip ~/Downloads/garmin_export.zip -d ~/Downloads/garmin_export
    python scripts/ingest_garmin_export.py \\
        --export-dir ~/Downloads/garmin_export \\
        --base-url http://localhost:8000 \\
        --token alice

输出:
    docs/eval/garmin_run_<YYYY-MM-DD-HHMM>.csv
    控制台总览（成功率 / P50/P95 时延 / 平均 anomaly 数）

注意:
    - 默认 sleep 2s/请求避免触发限流（默认 30/min/user）
    - 仅处理 CSV 内的字段；FIT 文件、HRV 详情、Body Composition 不读
    - source_raw 透传 Garmin 原始字段，方便后续 fact 关联
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import httpx
except ImportError:
    print("FATAL: missing 'httpx'. Run: pip install httpx", file=sys.stderr)
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("garmin_ingest")


# ── 佳明 → rhythmind sport_type 映射 ────────────────────────────────────────

_SPORT_MAP = {
    "running":         "running",
    "treadmill_running": "running",
    "trail_running":   "running",
    "track_running":   "running",
    "cycling":         "cycling",
    "road_biking":     "cycling",
    "indoor_cycling":  "cycling",
    "mountain_biking": "cycling",
    "gravel_cycling":  "cycling",
    "swimming":        "swimming",
    "open_water_swimming": "swimming",
    "lap_swimming":    "swimming",
    "strength_training": "strength",
    "yoga":            "yoga",
    "walking":         "walking",
    "hiking":          "hiking",
}


def _normalize_sport(raw: str) -> str:
    if not raw:
        return "general"
    s = raw.strip().lower().replace(" ", "_")
    return _SPORT_MAP.get(s, "general")


# ── CSV 字段提取（容错：佳明导出列名跨版本会变）────────────────────────────

def _f(row: dict, *names: str) -> float | None:
    """从可能的多个候选列名里取第一个能解析为 float 的值。"""
    for n in names:
        v = row.get(n)
        if v is None or v == "" or v == "--":
            continue
        try:
            # 移除千分位逗号
            return float(str(v).replace(",", "").strip())
        except ValueError:
            continue
    return None


def _i(row: dict, *names: str) -> int | None:
    v = _f(row, *names)
    return int(v) if v is not None else None


def _parse_duration_seconds(s: str | None) -> float | None:
    """支持 'HH:MM:SS' / 'MM:SS' / 数字（秒）。"""
    if not s or s == "--":
        return None
    s = str(s).strip()
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
    try:
        return float(s)
    except ValueError:
        return None


# ── 找 activities CSV ───────────────────────────────────────────────────────

def find_activities_csv(export_dir: Path) -> Path:
    """
    Garmin 不同年份导出包结构变过几次，宽松匹配:
      - Activities.csv（直接根目录或子目录）
      - UDSFile_<id>_activities.csv（DI-Connect-Aggregator 下）
      - any csv with both 'activity' and ('hr' or 'heart') in header
    """
    candidates: list[Path] = []
    for p in export_dir.rglob("*.csv"):
        name_lower = p.name.lower()
        if "activit" in name_lower or "summarizedactivities" in name_lower:
            candidates.append(p)

    if not candidates:
        raise FileNotFoundError(
            f"在 {export_dir} 下找不到 activities 类 CSV — "
            f"导出包结构可能变了，请给我看一下 `find {export_dir} -name '*.csv'` 的输出"
        )

    # 优先选行数多的（主活动文件通常最大）
    candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
    log.info("activities CSV: %s (%.1f KB)", candidates[0], candidates[0].stat().st_size / 1024)
    return candidates[0]


# ── 单行 CSV → upload payload ───────────────────────────────────────────────

def csv_row_to_payload(row: dict) -> dict | None:
    """
    把一行佳明 CSV 转成 HealthDataUploadRequest 兼容的 dict。
    Returns None 表示信息太少，跳过这一行。
    """
    sport_raw = row.get("Activity Type") or row.get("activityType") or row.get("sport")
    sport_type = _normalize_sport(sport_raw or "")

    hr_avg = _f(row, "Avg HR", "averageHR", "Average Heart Rate", "avg_hr")
    hr_max = _f(row, "Max HR", "maxHR", "Max Heart Rate", "max_hr")
    steps  = _i(row, "Steps", "steps")
    dist_km = _f(row, "Distance", "distance", "Distance (km)")
    if dist_km is not None and dist_km > 1000:
        # 部分导出是米
        dist_km = dist_km / 1000.0
    calories = _i(row, "Calories", "calories")

    # 至少要有"心率或步数或距离"其中一项，否则没意义
    if hr_avg is None and steps is None and dist_km is None:
        return None

    payload: dict = {
        "source": "garmin",
        "sport_type": sport_type,
        "user_goal": "健康维护",  # 默认；真实场景应该从用户 profile 拿
        "source_raw": {
            "garmin_date": row.get("Date") or row.get("startTime") or "",
            "title": row.get("Title") or row.get("activityName") or "",
            "duration": row.get("Time") or row.get("duration") or "",
        },
    }
    if hr_avg is not None:
        payload["heart_rate_avg"] = hr_avg
    if hr_max is not None and (hr_avg is None or hr_max >= hr_avg):
        payload["heart_rate_max"] = hr_max
    if steps is not None:
        payload["steps"] = steps
    if dist_km is not None:
        payload["distance_km"] = round(dist_km, 2)
    if calories is not None:
        payload["calories"] = calories

    return payload


# ── 主流程 ──────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    export_dir = Path(args.export_dir).expanduser().resolve()
    if not export_dir.is_dir():
        log.error("export-dir 不是目录: %s", export_dir)
        return 2

    csv_path = find_activities_csv(export_dir)
    with csv_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    log.info("读入 %d 行 activities", len(rows))

    # 输出目录
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    out_csv = out_dir / f"garmin_run_{stamp}.csv"

    results: list[dict] = []
    latencies_ms: list[float] = []

    # 同步 client（顺序请求；这一步并发不重要，避免 LLM 抢占资源）
    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        for i, row in enumerate(rows, 1):
            payload = csv_row_to_payload(row)
            if payload is None:
                log.debug("[%d/%d] 跳过：字段过少", i, len(rows))
                continue

            if args.limit and len(results) >= args.limit:
                log.info("达到 --limit %d，停止", args.limit)
                break

            t0 = time.perf_counter()
            try:
                resp = client.post(
                    "/api/v1/health/upload",
                    json=payload,
                    headers={"Authorization": f"Bearer {args.token}"},
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                latencies_ms.append(elapsed_ms)

                if resp.status_code == 200:
                    body = resp.json()
                    data = body.get("data", {})
                    metrics = data.get("metrics_analysis", {}) or {}
                    coach = data.get("training_plan", {}) or {}
                    today = coach.get("today_plan", {}) or {}
                    summary = (data.get("data_report", {}) or {}).get("summary", "")
                    plan_name = today.get("name", "")
                    anomaly_count = data.get("anomaly_count", 0)
                    load_level = metrics.get("load_level", "")
                    motivation = coach.get("motivation", "")

                    log.info(
                        "[%d/%d] %s OK %.0fms load=%s anomalies=%d plan=%s",
                        i, len(rows), payload["sport_type"], elapsed_ms,
                        load_level, anomaly_count, plan_name[:20],
                    )

                    results.append({
                        "row_index": i,
                        "date": payload["source_raw"]["garmin_date"],
                        "sport": payload["sport_type"],
                        "hr_avg": payload.get("heart_rate_avg"),
                        "distance_km": payload.get("distance_km"),
                        "status": "ok",
                        "elapsed_ms": round(elapsed_ms),
                        "load_level": load_level,
                        "anomaly_count": anomaly_count,
                        "data_summary": summary[:120].replace("\n", " "),
                        "plan_name": plan_name,
                        "motivation": motivation[:80].replace("\n", " "),
                    })
                else:
                    log.warning(
                        "[%d/%d] HTTP %d: %s",
                        i, len(rows), resp.status_code, resp.text[:200],
                    )
                    results.append({
                        "row_index": i,
                        "date": payload["source_raw"]["garmin_date"],
                        "sport": payload["sport_type"],
                        "status": f"http_{resp.status_code}",
                        "elapsed_ms": round(elapsed_ms),
                        "error": resp.text[:200],
                    })
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                log.error("[%d/%d] 异常 %s", i, len(rows), exc)
                results.append({
                    "row_index": i,
                    "date": payload["source_raw"]["garmin_date"],
                    "sport": payload["sport_type"],
                    "status": "exception",
                    "elapsed_ms": round(elapsed_ms),
                    "error": str(exc)[:200],
                })

            time.sleep(args.sleep)

    # 写结果 CSV
    if results:
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            fieldnames = sorted({k for r in results for k in r.keys()})
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(results)
        log.info("结果写入: %s", out_csv)

    # 总览
    ok = [r for r in results if r["status"] == "ok"]
    n_ok = len(ok)
    n_total = len(results)
    print("\n" + "=" * 60)
    print(f"总计: {n_total}  成功: {n_ok}  失败: {n_total - n_ok}  成功率: {n_ok/n_total*100:.1f}%" if n_total else "无样本")
    if latencies_ms:
        p50 = statistics.median(latencies_ms)
        p95 = statistics.quantiles(latencies_ms, n=20)[-1] if len(latencies_ms) >= 20 else max(latencies_ms)
        print(f"时延 平均 {statistics.mean(latencies_ms):.0f} ms / P50 {p50:.0f} ms / P95 {p95:.0f} ms / 最大 {max(latencies_ms):.0f} ms")
    if ok:
        anomalies = [r.get("anomaly_count") or 0 for r in ok]
        print(f"异常数 平均 {statistics.mean(anomalies):.2f} / 最大 {max(anomalies)}")
        loads = [r.get("load_level") for r in ok if r.get("load_level")]
        if loads:
            from collections import Counter
            print(f"负荷分布: {dict(Counter(loads))}")
    print("=" * 60)

    return 0 if n_ok > 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(description="把佳明导出数据按顺序灌入 rhythmind /health/upload")
    p.add_argument("--export-dir", required=True, help="解压后的 Garmin 导出目录")
    p.add_argument("--base-url", default="http://localhost:8000", help="API 基地址")
    p.add_argument("--token", default="alice", help="Bearer token（dev 模式下直接是 user_id）")
    p.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=全部）")
    p.add_argument("--sleep", type=float, default=2.0, help="每次请求间隔秒数（默认 2s 避免触发限流）")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
