# 压力测试 & 最大用户承载基准

> 创建时间: 2026-05-26 19:12:15
> 方案: 渐进式全链路压力测试
> 环境: 本地 (macOS ARM64, M4, 16GB)

## 目标

1. 确定各层最大并发用户数（P95 < 3s 拐点）
2. 输出架构优化建议清单

## 测试分层

### Layer 1: 轻量层（纯 IO，不涉及 LLM）
- GET /qm/dashboard, /qm/api/dashboard, /qm/api/reports, /qm/api/test-reports
- GET /ping, /health, /version
- 预期：CPU/IO 密集，DB 连接池瓶颈

### Layer 2: 中量层（Agent 流水线 + LLM）
- POST /qm/api/chat（三阶段 Agent: Metrics → Data → Coach）
- 每轮 ~16s（27B 推理瓶颈）
- 预期：LLM 推理串行是最大瓶颈

### Layer 3: 重量层（上传 + 分析 + Agent）
- POST /api/v1/health/upload + 触发 Agent
- 预期：最重路径，综合所有瓶颈

## 加压阶梯

| 阶段 | 并发用户 | 持续时间 | 层级 |
|------|---------|---------|------|
| 1 | 5 | 30s | Layer 1 |
| 2 | 10 | 30s | Layer 1 |
| 3 | 25 | 30s | Layer 1 |
| 4 | 50 | 30s | Layer 1 |
| 5 | 100 | 30s | Layer 1 |
| 6 | 200 | 30s | Layer 1 |
| 7 | 5 | 60s | Layer 2 |
| 8 | 10 | 60s | Layer 2 |
| 9 | 20 | 60s | Layer 2 |
| 10 | 5 | 60s | Layer 3 |

## 执行步骤

1. 编写压力测试脚本（基于 Locust 思路，纯 Python + asyncio/aiohttp）
2. 运行 Layer 1 渐进加压
3. 运行 Layer 2 Agent 压测
4. 运行 Layer 3 综合压测
5. 汇总数据，计算各层拐点
6. 输出优化建议清单
7. 生成 HTML 报告

## 产出文件

- `scripts/stress_test.py` — 压测脚本
- `/tmp/qm-stress-reports/stress-report.html` — HTML 报告
- `/tmp/qm-stress-reports/stress-report.md` — MD 报告
