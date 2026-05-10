# Load tests

Locust scaffold for staging / pre-prod capacity validation.

## 何时运行

- 每次 minor release 前对 staging 跑一次 30 分钟基准
- 任何会影响 LLM 调用次数 / 数据库读写模式的改动后
- 容量预估前（HPA 调参、PG/Redis 实例规格选型）

## 不应该做的事

- ❌ **不要打生产域名**。压测产生真实 LLM 调用 → 烧钱 + 污染指标
- ❌ 不要在没有 staging JWT 的情况下运行（`RHYTHMIND_TOKEN` 为空时脚本会主动退出）
- ❌ 不要把压测 Pod 跑在和被测应用同一节点

## 运行

```bash
pip install locust

export RHYTHMIND_BASE=https://staging.rhythmind.ai
export RHYTHMIND_TOKEN=eyJ...                  # staging 颁发的真 JWT
export RHYTHMIND_USER_POOL=200                 # 虚拟用户池大小

# 命令行模式（CI 友好）
locust -f tests/load/locustfile.py \
    --host $RHYTHMIND_BASE \
    --users 50 \
    --spawn-rate 5 \
    --run-time 10m \
    --headless \
    --html /tmp/rhythmind-load.html

# UI 模式（互动调参）
locust -f tests/load/locustfile.py --host $RHYTHMIND_BASE
# 浏览器打开 http://localhost:8089
```

## 产出

退出码 0 = 通过 SLO；1 = 失败率 > 1% 或 P95 > 30s。

`--html` 报告含每个 endpoint 的 RPS / 失败率 / 分位延迟，建议归档到 release 文档。

## 与 Grafana 配合

跑完后到 [rhythmind-overview](../../charts/rhythmind/dashboards/rhythmind-overview.json)
看：

- HTTP P95 是否随 RPS 上升而陡涨（连接池/数据库瓶颈）
- LLM P95 是否被 MLX/Ollama 单进程串行化
- AgentPool 命中率是否随用户池大小变化
- 合规拦截突增（说明 prompt 误打了关键词）

## 调参建议

- `--users`：先按 (期望 QPS × 平均延迟) 估算，例如 5 RPS × 6s = 30 用户
- `--spawn-rate`：≤ 用户数的 1/10，避免初始 burst 触发 HPA 抖动
- `RHYTHMIND_USER_POOL`：调到比 `agent_pool_max_users` 略大，能观察到 LRU 淘汰行为
