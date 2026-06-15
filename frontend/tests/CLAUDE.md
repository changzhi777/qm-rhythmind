[根目录](../../../CLAUDE.md) > **tests**

# tests 模块 — E2E 自动化测试

> **最后更新:** 2026-06-11T13:00:00+08:00
> **基线:** E2E 全链路 190/190 通过（10 轮 × 19 用例/轮）

---

## 模块职责

全链路 E2E 自动化测试，对生产环境 `https://aisport.tech/qm` 执行 10 轮测试，覆盖页面加载、API 端点、数据完整性，生成 MD + HTML(内联 SVG) + A4 PDF 三件套报告。支持 `--upload` 上传报告到生产服务器。

**6/11 新增能力：**
- JWT 失败识别：检测 `{"detail": ...}` 无 `status` 字段的响应，自动标记为 `skipped`（非测试逻辑错误），不计入失败
- RETRY 重试机制：单用例失败可重试（默认 1 次，由 `E2E_RETRY` 控制），重试间隔由 `E2E_RETRY_DELAY`（默认 1.0s）控制
- 公开页面测试：5 项页面测试无 Authorization header（首页/仪表盘/大屏/报告/测试报告）
- 双 Token 模式：默认 `garmin_user_001`（开发态），生产可设置 `E2E_AUTH_TOKEN` 为 JWT

---

## 文件清单

| 文件 | 职责 | 行数 |
|------|------|------|
| `e2e_test.py` | 主测试脚本（测试引擎 + JWT 检测 + RETRY + 报告生成器 + 上传） | 655 |

---

## 运行

```bash
# 前置：预热服务器（避免冷启动超时）
curl -sS https://aisport.tech/qm/dashboard > /dev/null

# 执行 10 轮测试
python3 tests/e2e_test.py

# 执行并上传报告到服务器
python3 tests/e2e_test.py --upload

# 生产 JWT 模式 + 重试 3 次
E2E_AUTH_TOKEN="<JWT>" E2E_RETRY=3 E2E_RETRY_DELAY=2.0 python3 tests/e2e_test.py
```

**输出目录:** `/tmp/qm-e2e-reports/`

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `E2E_BASE_URL` | `https://aisport.tech/qm` | 目标环境 URL |
| `E2E_AUTH_TOKEN` | `garmin_user_001` | Bearer token（开发态用用户 ID，生产用 JWT） |
| `E2E_RETRY` | `1` | 单用例失败重试次数 |
| `E2E_RETRY_DELAY` | `1.0` | 重试间隔（秒） |

---

## 测试引擎架构

```
main()
  ├── for i in 1..ROUNDS:
  │     └── run_round(i)
  │           ├── PAGE_TESTS (5 项)        → http_get()  → curl subprocess（无 Auth）
  │           ├── API_TESTS (3 项)         → http_api()  → curl + Bearer + JSON parse
  │           ├── PUBLIC_API_TESTS (4 项)  → http_get(url=...) → 公开端点（无 Auth）
  │           └── DATA_ASSERTIONS (7 项)   → 从 dashboard API 提取数据断言（范围校验）
  │
  │     └── _run_test(test_fn, ...) 内部 RETRY 循环（RETRY_COUNT 次）
  │           ├── 检测 {"detail": ...} 无 status → JWT 失败 → skipped（不重试）
  │           └── 失败时 sleep(RETRY_DELAY) 后重试
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
    # subprocess.run(["curl", "-sSk", "-o", "/dev/null", "-w",
    #   "%{http_code} %{time_total} %{size_download}", ...])
    # 返回: {status, time, size, ok, error?}

def http_api(path: str, timeout: int = 10) -> dict:
    # curl -sSk -H "Authorization: Bearer {E2E_AUTH_TOKEN}" ...
    # 解析 JSON → 检测 JWT 失败（{"detail":...} 无 status）→ 标记 skipped
    # 返回: {time, ok, skipped?, data, body_len, error?}
```

### JWT 失败识别逻辑

```python
data = json.loads(body)
if "detail" in data and "status" not in data:
    # JWT 认证失败（401/403 等），非测试逻辑错误
    return {"skipped": True, "error": data["detail"][:200]}
```

---

## 测试用例

**用例总数:** 19 项/轮（5 页面 + 3 API + 4 公开 API + 7 数据完整性）× 10 轮 = **190 用例**

### 页面测试（5 项，无 Authorization）

| 用例 | 路径 | 验证 |
|------|------|------|
| 首页重定向 | `/` | HTTP 200 |
| 仪表盘页面 | `/dashboard` | HTTP 200, ~18KB |
| 数据大屏页面 | `/bigscreen` | HTTP 200, ~16KB |
| 报告页面 | `/report` | HTTP 200, ~10KB |
| 测试报告页面 | `/test-report` | HTTP 200 |

### API 测试（3 项，需 Bearer Token）

| 用例 | 端点 | 验证 |
|------|------|------|
| Dashboard API | `GET /qm/api/dashboard` | `status == "ok"`, 含 `data` |
| Reports API | `GET /qm/api/reports` | `status == "ok"`, 含 `reports` |
| Test Reports API | `GET /qm/api/test-reports` | `status == "ok"` |

### 公开 API 测试（4 项，无 Authorization）

| 用例 | URL | 验证 |
|------|-----|------|
| Health: Ready Check | `https://aisport.tech/readyz` | 含 `status` 键 |
| Health: Live Check | `https://aisport.tech/livez` | HTTP 200 |
| Version API | `https://aisport.tech/version` | 含 `version` 键 |
| Users Summary API | `https://aisport.tech/qm/api/users/summary` | 含 `users` 键 |

### 数据完整性测试（7 项，从 Dashboard API 提取）

| 断言键 | 断言函数 | 期望范围 |
|--------|---------|---------|
| `running.activity` | `isinstance(v, dict)` | dict 结构 |
| `activity.running` | `isinstance(v, dict)` | dict 结构 |
| `activity.general` | `isinstance(v, dict)` | dict 结构 |
| `profile.vo2_max` | `v is None or 20 ≤ v ≤ 80` | 范围校验（可选） |
| `profile.bmi` | `v is None or 10 ≤ v ≤ 50` | 范围校验（可选） |
| `profile.weight_kg` | `v is None or 30 ≤ v ≤ 200` | 范围校验（可选） |
| `profile.age` | `v is None or 0 ≤ v ≤ 120` | 范围校验（可选） |

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

- **2026-06-11 (本次)** 增量更新：E2E 全链路 190/190 通过基线、JWT 失败识别逻辑（`{"detail": ...}` → skipped）、RETRY 重试机制（`E2E_RETRY`/`E2E_RETRY_DELAY` 环境变量）、公开页面测试（5 项无 Auth）、双 Token 模式（dev `garmin_user_001` / prod JWT）、行数 512→655、新增环境变量表
- **2026-06-11** 深化：补充测试引擎架构图、http_get/http_api 签名、SVG 图表坐标规格、HTML 报告结构、PDF 生成流程、upload_reports 上传流程、统计计算方法
- **2026-05-18** 首次 AI 上下文初始化
