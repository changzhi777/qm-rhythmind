[根目录](../../../CLAUDE.md) > **tests**

# tests 模块 — E2E 自动化测试

> **最后更新:** 2026-06-11T10:00:00+08:00

---

## 模块职责

全链路 E2E 自动化测试，对生产环境 `https://aisport.tech/qm` 执行 10 轮测试，覆盖页面加载、API 端点、数据完整性，生成 MD + HTML(内联 SVG) + A4 PDF 三件套报告。支持 `--upload` 上传报告到生产服务器。

---

## 文件清单

| 文件 | 职责 | 行数 |
|------|------|------|
| `e2e_test.py` | 主测试脚本（测试引擎 + 报告生成器 + 上传） | 512 |

---

## 运行

```bash
# 前置：预热服务器（避免冷启动超时）
curl -sS https://aisport.tech/qm/dashboard > /dev/null

# 执行 10 轮测试
python3 tests/e2e_test.py

# 执行并上传报告到服务器
python3 tests/e2e_test.py --upload
```

**输出目录:** `/tmp/qm-e2e-reports/`

---

## 测试引擎架构

```
main()
  ├── for i in 1..ROUNDS:
  │     └── run_round(i)
  │           ├── PAGE_TESTS (5 项)  → http_get() → curl subprocess
  │           ├── API_TESTS (3 项)   → http_api() → curl + JSON parse
  │           └── DATA_ASSERTIONS (7 项) → 从 dashboard API 提取数据断言
  │
  ├── generate_svg()    → 响应时间趋势折线图 + 通过率条形图 + 甜甜圈图
  ├── generate_md()     → Markdown 报告 (含统计表 + 明细)
  ├── generate_html()   → 深色主题 HTML (内联 SVG + 统计卡片 + 各轮折叠详情)
  │
  ├── Chrome headless   → HTML → A4 PDF (通过临时 HTTP 服务器避免 file:// 限制)
  │
  └── [--upload] upload_reports()
        └── sshpass + scp → /var/www/aisport.tech/qm/test_reports/{id}/
```

### http_get / http_api

```python
def http_get(path: str, timeout: int = 10) -> dict:
    # subprocess.run(["curl", "-sS", "-o", "/dev/null", "-w",
    #   "%{http_code} %{time_total} %{size_download}", ...])
    # 返回: {status, time, size, ok, error?}

def http_api(path: str, timeout: int = 10) -> dict:
    # curl -H "Authorization: Bearer garmin_user_001" ...
    # 解析 JSON → {time, ok, data, body_len, error?}
```

---

## 测试用例

### 页面测试（5 项）

| 用例 | 路径 | 验证 |
|------|------|------|
| 首页重定向 | `/` | HTTP 200 |
| 仪表盘页面 | `/dashboard` | HTTP 200, ~18KB |
| 数据大屏页面 | `/bigscreen` | HTTP 200, ~16KB |
| 报告页面 | `/report` | HTTP 200, ~10KB |
| 测试报告页面 | `/test-report` | HTTP 200 |

### API 测试（3 项）

| 用例 | 端点 | 验证 |
|------|------|------|
| Dashboard API | `GET /qm/api/dashboard` | `status == "ok"`, 含 `data` |
| Reports API | `GET /qm/api/reports` | `status == "ok"`, 含 `reports` |
| Test Reports API | `GET /qm/api/test-reports` | `status == "ok"` |

### 数据完整性测试（7 项）

| 断言键 | 断言函数 | 期望值 |
|--------|---------|--------|
| `profile.vo2_max` | `lambda v: v == 52` | 52 |
| `profile.bmi` | `lambda v: v == 24.9` | 24.9 |
| `profile.weight_kg` | `lambda v: v == 78` | 78 |
| `profile.age` | `lambda v: v == 34` | 34 |
| `training.metrics` | `isinstance(v, dict) and "readiness_score" in v` | dict |
| `running.summary` | `isinstance(v, dict) and "total_km" in v` | dict |
| `sleep.summary` | `isinstance(v, dict) and "avg_total_hours" in v` | dict |

---

## 报告生成规范

三件套产出：

| 文件 | 格式 | 说明 |
|------|------|------|
| `e2e-report.md` | Markdown | 文本报告，SVG 图表相对路径引用 |
| `e2e-report.html` | HTML | 深色主题，SVG 内联嵌入，A4 `@page` 规则，自包含 |
| `e2e-report.pdf` | PDF | Chrome headless `--print-to-pdf`，A4 规格 |

### SVG 图表规格（800×440 画布）

| 元素 | 坐标/参数 | 说明 |
|------|---------|------|
| 背景 | 0,0 800×440, `#0d1117` | 深色主题 |
| 标题 | 400,28 `font-size=16` | "RHYTHMIND E2E 响应时间趋势" |
| 网格线 | cl=80, cr=760, ct=60, cb=340 | 5 条水平虚线 |
| 页面折线 | `#00C9A7` 2.5px stroke, 0.15 opacity area | 各轮页面平均响应时间 |
| API 折线 | `#00D4FF` 2.5px stroke, 0.15 opacity area | 各轮 API 平均响应时间 |
| 数据点 | 3.5px radius circle | 每轮一个圆点 |
| 通过率条 | 下部条形图, 370-386 | 每轮通过数/总数，<100% 红色 |
| 甜甜圈 | 720,410 r=25 | 总通过率百分比 |
| 图例 | 左下 10,400 | 页面(绿) + API(蓝) |
| 统计 | 左下 350,398-412 | avg/p95 数值 |

### HTML 报告结构

```html
<body style="background:#0d1117; max-width:210mm; padding:32px">
  <h1>RHYTHMIND E2E 测试报告</h1>
  <p class="meta">测试时间 / 轮次 / 环境</p>
  
  <!-- 统计卡片网格 (grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))) -->
  <div class="summary-grid">
    8 stat-card: 总测试数/通过数/失败数/通过率/页面avg/API avg/页面p95/API p95
  </div>
  
  <!-- SVG 图表内联 -->
  <div class="chart">{svg_content}</div>
  
  <!-- 测试用例明细表 -->
  <table>15 行 × (类别/用例/通过率/平均响应/失败轮次)</table>
  
  <!-- 各轮次折叠详情 -->
  <details>× 10 (每轮 15 测试行，折叠)</details>
  
  <div class="footer">湖南青沐生命科技有限公司 | RHYTHMIND 律动</div>
</body>
```

### PDF 生成流程

```
HTML 文件
  │
  ├── 启动临时 HTTP 服务器 (Python http.server, 随机端口)
  │     └── Chrome 不支持 file:// 协议打印，必须通过 HTTP 加载
  │
  ├── Chrome headless --print-to-pdf={pdf_path}
  │     └── --print-to-pdf-no-header (去除页眉页脚)
  │
  └── 关闭临时 HTTP 服务器
```

### upload_reports 流程

```python
def upload_reports(results, stats):
    # 1. 生成 meta.json (rounds/total/passed/failed/pass_rate/page_avg/api_avg)
    # 2. sshpass -p <pwd> ssh root@43.129.201.118 mkdir -p /var/www/aisport.tech/qm/test_reports/{id}
    # 3. sshpass scp 上传 5 个文件 (meta.json, e2e-report.md, .html, .pdf, e2e-charts.svg)
    # 报告访问: https://aisport.tech/qm/test-report
    # API 访问: https://aisport.tech/qm/api/test-reports/{report_id}
```

### 统计计算

```python
stats = {
    "page_times": [],   # 所有页面请求的 time_ms 列表
    "api_times": [],    # 所有 API 请求的 time_ms 列表
    "total_passed": 0,  # 累计通过数
    "total_failed": 0,  # 累计失败数
}
# avg = statistics.mean(list)
# p95 = sorted(list)[int(len(list) * 0.95)]
```

---

## 关键依赖

| 依赖 | 用途 |
|------|------|
| Python 3.9+ | 测试脚本运行时 |
| `curl` | HTTP 请求（subprocess 调用） |
| `sshpass` | SSH 密码认证上传 |
| Google Chrome headless | HTML → PDF 转换 |
| `statistics` (stdlib) | P95 等统计计算 |
| `http.server` (stdlib) | 临时 HTTP 服务（PDF 生成用） |

---

## 常见问题

**Q: Round 1 全部超时怎么办？**
A: 服务器冷启动导致，先 `curl` 预热再跑测试。

**Q: 如何修改测试轮次？**
A: 修改脚本顶部 `ROUNDS = 10` 常量。

**Q: Chrome 找不到怎么办？**
A: 脚本自动搜索 `google-chrome` 或 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`。

**Q: PDF 生成失败？**
A: 检查 Chrome 版本 ≥110（支持 headless print-to-pdf）。

**Q: 如何部署测试报告？**
A: `--upload` 参数自动通过 sshpass+scp 上传到生产服务器 `/var/www/aisport.tech/qm/test_reports/`。

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：补充测试引擎架构图、http_get/http_api 签名、SVG 图表坐标规格、HTML 报告结构、PDF 生成流程、upload_reports 上传流程、统计计算方法
- **2026-05-18** 首次 AI 上下文初始化
