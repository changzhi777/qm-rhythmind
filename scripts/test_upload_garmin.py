"""
scripts/test_upload_garmin.py — 真实上传链路 E2E 测试(2026-06-24)

目的:把佳明 20260526 目录的 JSON 通过 /upload/file 上传,验证后端入库链路
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

# 配置
CT109_API = "http://localhost:8000"  # 在 CT109 内
EXTERNAL_API = "https://aisport.tech/qm/api"  # 公网入口(走 nginx)
DATA_ROOT = Path("/opt/garmin-data/DI_CONNECT")

# 测试文件清单(覆盖各种类型)
TEST_FILES = [
    ("DI-Connect-Metrics/MetricsMaxMetData_20260216_20260527_11032831.json", "VO2Max 31 数据点"),
    ("DI-Connect-Metrics/EnduranceScore_20260216_20260527_11032831.json", "耐力评分"),
    ("DI-Connect-Metrics/HillScore_20260216_20260527_11032831.json", "爬坡评分"),
    ("DI-Connect-Metrics/TrainingReadinessDTO_20260216_20260527_11032831.json", "训练准备度 257 数据点"),
    ("DI-Connect-Wellness/11032831_bioMetrics_latest.json", "生理数据"),
    ("DI-Connect-Wellness/11032831_fitnessAgeData.json", "体能年龄"),
    ("DI-Connect-Fitness/8616680518888_personalRecord.json", "个人纪录"),
]


def upload_file(api_base: str, token: str, file_path: Path) -> dict:
    """单文件上传测试"""
    if not file_path.exists():
        return {"status": "skip", "error": f"file not found: {file_path}"}

    try:
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f, "application/json")}
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.post(
                f"{api_base}/qm/api/upload/file",
                files=files,
                headers=headers,
                timeout=60,
            )
        return {
            "status": "ok" if r.status_code == 200 else "fail",
            "http_code": r.status_code,
            "response": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:200],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def main() -> int:
    """主函数"""
    # 在 CT109 内执行时使用 localhost;本地测试时使用公网
    if "--internal" in sys.argv:
        api_base = CT109_API
    else:
        api_base = EXTERNAL_API

    token = os.environ.get("E2E_AUTH_TOKEN", "athlete_demo_001")

    print(f"API: {api_base}")
    print(f"Token: {token}")
    print(f"Data root: {DATA_ROOT}")
    print(f"Test files: {len(TEST_FILES)}")
    print()

    results = []
    total_start = time.time()

    for rel_path, desc in TEST_FILES:
        file_path = DATA_ROOT / rel_path
        print(f"📤 [{desc}] {rel_path}")
        if not file_path.exists():
            print(f"   ❌ SKIP: file not found")
            results.append({"file": rel_path, "status": "skip"})
            continue

        size_kb = file_path.stat().st_size / 1024
        print(f"   Size: {size_kb:.1f} KB")

        start = time.time()
        result = upload_file(api_base, token, file_path)
        elapsed = time.time() - start

        if result["status"] == "ok":
            print(f"   ✅ OK ({elapsed:.1f}s) http={result.get('http_code')}")
            resp = result.get("response", {})
            if isinstance(resp, dict):
                facts = resp.get("facts_imported", 0)
                msg = resp.get("message", "")
                print(f"      facts_imported: {facts}")
                if msg:
                    print(f"      message: {msg[:100]}")
        elif result["status"] == "skip":
            print(f"   ⚠ SKIP: {result.get('error')}")
        elif result["status"] == "fail":
            print(f"   ❌ FAIL ({elapsed:.1f}s) http={result.get('http_code')}")
            print(f"      response: {str(result.get('response'))[:200]}")
        else:
            print(f"   💥 ERROR: {result.get('error')}")

        results.append({
            "file": rel_path,
            "status": result["status"],
            "elapsed_s": elapsed,
            "http": result.get("http_code"),
            "facts": result.get("response", {}).get("facts_imported") if isinstance(result.get("response"), dict) else None,
        })
        print()

    total_elapsed = time.time() - total_start

    # 汇总
    print("=" * 60)
    print("📊 汇总")
    print("=" * 60)
    ok = sum(1 for r in results if r["status"] == "ok")
    fail = sum(1 for r in results if r["status"] == "fail")
    skip = sum(1 for r in results if r["status"] == "skip")
    err = sum(1 for r in results if r["status"] == "error")
    total_facts = sum((r.get("facts") or 0) for r in results)

    print(f"  ✅ OK:   {ok}/{len(results)}")
    print(f"  ❌ FAIL: {fail}/{len(results)}")
    print(f"  ⚠ SKIP:  {skip}/{len(results)}")
    print(f"  💥 ERR:  {err}/{len(results)}")
    print(f"  📦 Total facts imported: {total_facts}")
    print(f"  ⏱  Total time: {total_elapsed:.1f}s")

    # 退出码
    return 0 if (fail == 0 and err == 0) else 1


if __name__ == "__main__":
    sys.exit(main())