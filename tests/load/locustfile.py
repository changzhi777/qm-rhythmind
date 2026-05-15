# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Locust load test
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
"""
压测目标 (staging only)：
  - 验证 P95 延迟在 SLO 内
  - 触发 HPA 行为，观察扩容曲线
  - 验证 LoopGuard 与 rate limiter 的实际拦截阈值
  - 暴露任何只在并发下出现的 bug（连接池、Redis 抖动、AgentPool LRU）

使用：
  pip install locust
  # 假设 staging 在 https://staging.rhythmind.ai
  RHYTHMIND_BASE=https://staging.rhythmind.ai \\
  RHYTHMIND_TOKEN=eyJ... \\
  locust -f tests/load/locustfile.py --host $RHYTHMIND_BASE \\
         --users 50 --spawn-rate 5 --run-time 5m

UI 模式去掉最后三行参数即可。

⚠ 严禁打生产域名。压测会消耗真实 LLM 配额。
"""
from __future__ import annotations

import os
import random

from locust import HttpUser, between, events, tag, task

# ── 全局配置 ────────────────────────────────────────────────────────────────

BASE = os.getenv("RHYTHMIND_BASE", "http://localhost:8000")
TOKEN = os.getenv("RHYTHMIND_TOKEN", "")  # 必须在 staging 颁发的 JWT
USER_POOL_SIZE = int(os.getenv("RHYTHMIND_USER_POOL", "200"))


@events.test_start.add_listener
def _check_token(environment, **_kwargs):
    if not TOKEN:
        environment.runner.quit()
        raise RuntimeError("RHYTHMIND_TOKEN must be set (a real JWT for staging).")


# ── 用户行为 ───────────────────────────────────────────────────────────────

class HealthUser(HttpUser):
    """
    模拟单个 user_id 的典型行为：探针 + 上传 + 偶发对话。

    比例（@task 数字）：
      - upload   : 6
      - chat     : 3
      - readyz   : 1   （监控用，确保探针自身也算到容量里）
    """
    wait_time = between(1, 4)

    def on_start(self) -> None:
        # 用 user_pool_id 让每个虚拟用户固定一个 user_id 跑完，
        # 避免每次随机导致 LoopGuard 计数失真。
        self.user_id = f"loadtest_{random.randint(1, USER_POOL_SIZE):04d}"
        self.client.headers.update({
            "Authorization": f"Bearer {TOKEN}",
            "X-Loadtest-User": self.user_id,
        })

    # ── 上传健康数据（最重的路径，命中三 Agent + LLM）───────────────────
    @tag("upload")
    @task(6)
    def upload(self) -> None:
        body = {
            "source": "garmin",
            "sport_type": "running",
            "user_goal": "维持有氧",
            "heart_rate_avg": random.randint(120, 165),
            "heart_rate_max": random.randint(170, 195),
            "steps": random.randint(2000, 15000),
            "distance_km": round(random.uniform(2, 12), 2),
        }
        with self.client.post(
            "/api/v1/health/upload",
            json=body,
            name="POST /upload",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 429:
                # 限流期望路径，不算失败
                resp.success()
            else:
                resp.failure(f"unexpected {resp.status_code}: {resp.text[:200]}")

    @tag("chat")
    @task(3)
    def chat(self) -> None:
        prompt = random.choice([
            "今天我的训练强度合适吗？",
            "下周该如何安排？",
            "膝盖有点不舒服怎么办？",
        ])
        with self.client.post(
            "/api/v1/health/chat",
            json={"text": prompt, "context": {}},
            name="POST /chat",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 429):
                resp.success()
            else:
                resp.failure(f"unexpected {resp.status_code}")

    @tag("probe")
    @task(1)
    def readyz(self) -> None:
        # /readyz 不需要鉴权
        self.client.get("/readyz", name="GET /readyz")


# ── 自定义阈值（脱离 SLO 即标红）──────────────────────────────────────────
# 通过 events.request 收集，简化版本：locust 自带 --html 报告即可。

@events.quitting.add_listener
def _check_slo(environment, **_kwargs) -> None:
    stats = environment.stats
    # 全局失败率
    fail_ratio = stats.total.fail_ratio
    p95_ms = stats.total.get_response_time_percentile(0.95)
    summary = (
        f"\n=== SLO check ===\n"
        f"  total requests : {stats.total.num_requests}\n"
        f"  failures       : {stats.total.num_failures} ({fail_ratio:.2%})\n"
        f"  p95 latency    : {p95_ms:.0f} ms\n"
    )
    print(summary, flush=True)

    # 失败率 > 1% 即视为压测失败（429 已被 catch_response 标 success）
    if fail_ratio > 0.01 or p95_ms > 30_000:
        environment.process_exit_code = 1
