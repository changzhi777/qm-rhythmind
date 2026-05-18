[根目录](../../../CLAUDE.md) > **tests**

# tests 模块 — E2E 自动化测试

> **最后更新:** 2026-05-18T12:22:25+08:00

---

## 模块职责

全链路 E2E 自动化测试，对生产环境 `https://aisport.tech/qm` 执行 10 轮测试，覆盖页面加载、API 端点、数据完整性，生成 MD + HTML(内联 SVG) + A4 PDF 三件套报告。

---

## 文件清单

| 文件 | 职责 |
|------|------|
| `e2e_test.py` | 主测试脚本（含测试引擎 + 报告生成器） |

---

## 运行

```bash
# 前置：预热服务器（避免冷启动超时）
curl -sS https://aisport.tech/qm/dashboard > /dev/null

# 执行 10 轮测试
python3 tests/e2e_test.py
```

**输出目录:** `/tmp/qm-e2e-reports/`

---

## 测试用例

### 页面测试（5 项）

| 用例 | 路径 | 验证 |
|------|------|------|
| 首页重定向 | `/qm/` | HTTP 200 |
| 仪表盘页面 | `/qm/dashboard` | HTTP 200, ~18KB |
| 数据大屏页面 | `/qm/bigscreen` | HTTP 200, ~16KB |
| 报告页面 | `/qm/report` | HTTP 200, ~10KB |
| 静态资源 JS | `/qm/_next/static/chunks/*.js` | HTTP 200 |

### API 测试（2 项）

| 用例 | 端点 | 验证 |
|------|------|------|
| Dashboard API | `GET /qm/api/dashboard` | `status == "ok"`, 含 `data` |
| Reports API | `GET /qm/api/reports` | `status == "ok"`, 含 `reports` |

### 数据完整性测试（7 项）

| 断言键 | 期望值 |
|--------|--------|
| `profile.vo2_max` | `52` |
| `profile.bmi` | `24.9` |
| `profile.weight_kg` | `78` |
| `profile.age` | `34` |
| `training.metrics` | dict 含 `readiness_score` |
| `running.summary` | dict 含 `total_km` |
| `sleep.summary` | dict 含 `avg_total_hours` |

---

## 报告生成规范

三件套产出：

| 文件 | 格式 | 说明 |
|------|------|------|
| `e2e-report.md` | Markdown | 文本报告，SVG 图表相对路径引用 |
| `e2e-report.html` | HTML | 深色主题，SVG 内联嵌入，A4 `@page` 规则，自包含 |
| `e2e-report.pdf` | PDF | Chrome headless `--print-to-pdf`，A4 规格 |

**SVG 图表内容：**
- 响应时间趋势折线图（页面 vs API，面积渐变填充）
- 各轮次通过率条形图
- 通过率甜甜圈图

---

## 关键依赖

| 依赖 | 用途 |
|------|------|
| Python 3.9+ | 测试脚本运行时 |
| `curl` | HTTP 请求（subprocess 调用） |
| Google Chrome headless | HTML → PDF 转换 |
| `statistics` (stdlib) | P95 等统计计算 |

---

## 常见问题

**Q: Round 1 全部超时怎么办？**
A: 服务器冷启动导致，先 `curl` 预热再跑测试。

**Q: 如何修改测试轮次？**
A: 修改脚本顶部 `ROUNDS = 10` 常量。

**Q: 如何部署测试报告？**
A: 报告生成后复制到 `docs/e2e/`，可通过 nginx 服务。
