# docs/stress-reports — 压力测试报告归档

## 目录结构

```
docs/stress-reports/
├── README.md                # 本说明
├── stress-report.md         # Markdown 摘要
└── stress-report.html       # HTML 报告（带内联 SVG）
```

## 最新一次压测（2026-06-14）

**测试时间**: 2026-06-14 02:55:59 +08:00  
**目标**: http://localhost:8000 (本地 dev)  
**修复后真实基线**（10 阶段脚本仅跑 Layer 1 6 阶段，~2 min）：

| 阶段 | 通过率 | RPS | P50 | P95 | P99 | 评估 |
|------|--------|-----|-----|-----|-----|------|
| L1-5users | **100%** (36899/0) | 371.4 | 2ms | 5ms | 6ms | 🟢 |
| L1-10users | **100%** (38363/0) | 192.5 | 4ms | 10ms | 13ms | 🟢 |
| L1-25users | **100%** (37167/0) | 74.4 | 12ms | 21ms | 56ms | 🟢 |
| L1-50users | **100%** (38212/0) | 38.2 | 24ms | 39ms | 72ms | 🟢 |
| L1-100users | **100%** (35979/0) | 18.0 | 52ms | 91ms | 117ms | 🟡 |
| L1-200users | **99.9%** (37966/43) | 9.4 | 71ms | 157ms | 406ms | 🟡 |

**结论**：
- ✅ Layer 1 全部 100% 通过（修复后真实数据）
- 🟡 200 并发下偶发 43 个失败（0.11%）— 真实瓶颈信号
- 🚀 峰值 RPS = 371.4（远超生产需求）

## ⚠️ 历史报告（2026-06-13 旧数据）

**已知问题**：`stress_test.py` `_l1_worker` 函数曾有 Bug — 计算了 `headers` 但**未传入 `fetch_get`**，导致 Authorization 头不发送，**所有需 auth 端点返 403**。

**修复时间**: 2026-06-14  
**修复内容**：
- `fetch_get` 新增 `headers` 参数
- `_l1_worker` 调用时传 `headers=headers`

**修复前报告 Layer 1 数据失真**（约 50% 通过率虚高 RPS），仅作历史参考。

## 🔧 复现命令

```bash
# 启动本地 dev 服务
nohup .venv/bin/uvicorn rhythmind.api.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn-dev.log 2>&1 &
cd frontend && nohup npm run dev > /tmp/nextjs-dev.log 2>&1 &

# 跑压测（Layer 1 6 阶段 ~2 min）
python3 -c "
import asyncio, sys
sys.path.insert(0, 'scripts')
import stress_test
stress_test.STAGES = [
    {'name': 'L1-5users', 'layer': 'Layer1', 'concurrency': 5, 'duration': 20},
    {'name': 'L1-10users', 'layer': 'Layer1', 'concurrency': 10, 'duration': 20},
    {'name': 'L1-25users', 'layer': 'Layer1', 'concurrency': 25, 'duration': 20},
    {'name': 'L1-50users', 'layer': 'Layer1', 'concurrency': 50, 'duration': 20},
    {'name': 'L1-100users', 'layer': 'Layer1', 'concurrency': 100, 'duration': 20},
    {'name': 'L1-200users', 'layer': 'Layer1', 'concurrency': 200, 'duration': 20},
]
asyncio.run(stress_test.main())
"
```

## 📊 SLO 建议

基于修复后基线：
- **P95 < 100ms @ 50 并发**（生产日常负载）
- **P99 < 500ms @ 200 并发**（极限峰值）
- **失败率 < 0.1%**（除 200 并发外）

如需更高吞吐，建议升级到 gunicorn -w 4 或多实例 + 负载均衡。
