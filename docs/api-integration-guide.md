# RHYTHMIND 律动 — API & MCP 集成指南

> **版本:** 0.2.0
> **更新日期:** 2026-05-23
> **Base URL:** `https://aisport.tech/qm` (生产) | `http://localhost:8000` (本地)

---

## 目录

1. [认证](#1-认证)
2. [REST API 端点](#2-rest-api-端点)
   - [健康数据上传](#21-健康数据)
   - [仪表盘与报告](#22-仪表盘与报告)
   - [医疗分析](#23-医疗分析)
   - [LLM 观测](#24-llm-观测)
   - [隐私与合规](#25-隐私与合规)
   - [管理接口](#26-管理接口)
   - [基础设施](#27-基础设施探针)
3. [MCP 工具接口](#3-mcp-工具接口)
4. [错误处理](#4-错误处理)
5. [限流策略](#5-限流策略)
6. [SDK 集成示例](#6-sdk-集成示例)

---

## 1. 认证

### JWT Bearer Token

所有 API 端点（除基础设施探针外）均需 `Authorization: Bearer <token>` 头。

**生产环境**：标准 JWT（HS256 签名），`sub` 字段为 `user_id`。

```http
GET /qm/api/dashboard HTTP/1.1
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**开发模式**（`ENV=dev` + `DEV_AUTH_BYPASS=true`）：可直接传 `user_id` 明文作为 token。

```http
GET /api/dashboard HTTP/1.1
Authorization: Bearer garmin_user_001
```

### MCP 认证

MCP SSE 连接通过 `headers` 传递 JWT：

```json
{
  "mcpServers": {
    "rhythmind": {
      "url": "http://localhost:8000/mcp/sse",
      "headers": { "Authorization": "Bearer eyJ..." }
    }
  }
}
```

生产环境 `MCP_REQUIRE_AUTH=true` 强制验证；本地开发可关闭。

---

## 2. REST API 端点

### 2.1 健康数据

#### POST /api/v1/health/upload

上传结构化健康指标，触发三阶段 Agent 流水线（Metrics → Data → Coach），同步返回完整分析结果。

```http
POST /api/v1/health/upload
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体：**

```json
{
  "source": "garmin",
  "sport_type": "running",
  "user_goal": "半马完赛",
  "heart_rate_avg": 145,
  "heart_rate_max": 178,
  "heart_rate_zones": { "z1": 30, "z2": 25, "z3": 20, "z4": 15, "z5": 10 },
  "steps": 12000,
  "distance_km": 8.5,
  "calories": 520,
  "sleep_hours": 7.5,
  "hrv": 62,
  "body_fat_pct": 18.5,
  "muscle_mass_kg": 35.2,
  "water_pct": 55.0,
  "visceral_fat": 8
}
```

| 字段 | 类型 | 必填 | 范围 | 说明 |
|------|------|------|------|------|
| `source` | string | 是 | garmin/apple/huawei/xiaomi/manual | 数据来源 |
| `sport_type` | string | 否 | - | 运动类型，默认 `general` |
| `user_goal` | string | 否 | - | 用户目标，默认 `健康维护` |
| `heart_rate_avg` | float | 否 | 20-250 | 平均心率 |
| `heart_rate_max` | float | 否 | 20-250 | 最大心率（须 ≥ avg） |
| `heart_rate_zones` | HRZones | 否 | - | 心率区间分布（百分比） |
| `steps` | int | 否 | ≥0 | 步数 |
| `distance_km` | float | 否 | ≥0 | 距离（公里） |
| `calories` | int | 否 | ≥0 | 卡路里消耗 |
| `sleep_hours` | float | 否 | 0-24 | 睡眠时长 |
| `hrv` | float | 否 | ≥0 | 心率变异性 |
| `body_fat_pct` | float | 否 | 0-100 | 体脂率 |
| `muscle_mass_kg` | float | 否 | ≥0 | 肌肉量 |
| `water_pct` | float | 否 | 0-100 | 水分率 |
| `visceral_fat` | int | 否 | ≥0 | 内脏脂肪等级 |
| `source_raw` | object | 否 | - | 原始数据透传 |

**响应（200）：**

```json
{
  "status": "success",
  "session_id": "uuid-xxx",
  "data": {
    "load_level": "moderate",
    "summary": "...",
    "plan_name": "周期化训练计划",
    "motivation": "..."
  }
}
```

---

#### POST /api/v1/health/upload/stream

SSE 流式版本，逐步推送每个 Agent 的进度。

```http
POST /api/v1/health/upload/stream
Authorization: Bearer <token>
Content-Type: application/json
Accept: text/event-stream
```

请求体同上。响应为 SSE 事件流：

```
event: start
data: {"session_id": "uuid-xxx", "message": "开始分析"}

event: metrics_done
data: {"load_level": "moderate", "anomaly_count": 2}

event: data_done
data: {"summary": "..."}

event: coach_done
data: {"plan_name": "周期化训练计划", "motivation": "..."}

event: done
data: {完整分析结果}
```

---

#### WS /api/v1/health/upload/stream/ws

WebSocket 流式版本。

**连接：** `ws://host/api/v1/health/upload/stream/ws?token=<jwt>`

**协议：**

1. 连接成功 → 服务器发送 `{"type": "connected", "data": {"session_id": "..."}}`
2. 客户端发送 `{"input_data": {...}}`（同 upload 请求体）
3. 服务器流式推送 `{"type": "metrics_done", "data": {...}}` 等
4. 完成 → `{"type": "done", "data": {...}}`
5. 关闭 → `{"type": "close"}`

---

#### POST /api/v1/health/ingest

接收可穿戴设备导出的 CSV 文件。

```http
POST /api/v1/health/ingest?source=apple_health
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | File | CSV 文件（必须 .csv 后缀） |
| `source` | Query | apple_health / google_health / fitbit / manual |

CSV 必需列：`timestamp`（ISO 8601）。可选列：`heart_rate`, `steps`, `sleep_minutes`, `spo2`, `blood_pressure_systolic`, `blood_pressure_diastolic`。

```csv
timestamp,heart_rate,steps,sleep_minutes,spo2
2026-05-12T08:00:00Z,65,1200,0,98
2026-05-12T09:00:00Z,72,300,480,97
```

**响应（200）：**

```json
{
  "status": "success",
  "user_id": "garmin_user_001",
  "source": "apple_health",
  "rows_parsed": 2,
  "errors": [],
  "write_ok": true
}
```

---

#### POST /api/v1/health/chat

自然语言对话，自动意图分类后路由到对应工作流。

```http
POST /api/v1/health/chat
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体：**

```json
{
  "text": "我最近心率偏高，训练时容易喘，该怎么办？",
  "context": { "recent_activity": "半马训练" }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 1-2000 字符 |
| `context` | object | 否 | 附加上下文 |

**响应（200）：**

```json
{
  "status": "success",
  "session_id": "uuid-xxx",
  "data": { "coach_response": "..." },
  "message": ""
}
```

---

#### GET /api/v1/health/memory

查看用户 Agent 记忆摘要（仅 `debug=True` 模式可用）。

**响应（200）：**

```json
{
  "user_id": "garmin_user_001",
  "memory": {
    "metrics_agent": { ... },
    "data_agent": { ... },
    "coach_agent": { ... }
  }
}
```

---

#### GET /api/v1/health/pool/stats

Agent 池状态诊断（仅 `debug=True` 模式可用）。

---

### 2.2 仪表盘与报告

#### GET /qm/api/dashboard

获取仪表盘汇总数据（所有当前有效健康事实）。

```http
GET /qm/api/dashboard
Authorization: Bearer <token>
```

**响应（200）：**

```json
{
  "status": "ok",
  "data": {
    "profile.gender": "MALE",
    "profile.age": 34,
    "running.total_runs": 539,
    "running.total_km": 4648,
    "sleep.avg_hours": 6.2,
    "training.acwr": 0.8
  }
}
```

数据键格式：`{subject}.{predicate}`，值类型为 JSON。

---

#### GET /qm/api/reports

AI 分析报告列表。

```http
GET /qm/api/reports?limit=20
Authorization: Bearer <token>
```

**响应（200）：**

```json
{
  "status": "ok",
  "reports": [
    {
      "id": 123,
      "timestamp": "2026-05-23T10:00:00+08:00",
      "model": "omlX://gemma-4-e4b-it-4bit",
      "is_current": true,
      "preview": "总体评价：该用户是一位 34 岁的..."
    }
  ]
}
```

---

#### GET /qm/api/reports/{report_id}

单篇报告详情。

**响应（200）：**

```json
{
  "status": "ok",
  "report": {
    "id": 123,
    "content": "# RHYTHMIND 健康分析报告\n\n...",
    "model": "omlX://gemma-4-e4b-it-4bit",
    "timestamp": "2026-05-23T10:00:00+08:00",
    "is_current": true
  }
}
```

---

#### GET /qm/api/reports/{report_id}/download

下载 AI 报告 PDF（含二维码水印）。

**响应（200）：** `application/pdf`，文件名格式 `{user_id}_{YYYYMMDDHHmmss}.pdf`。

---

#### POST /qm/api/analyze

触发本地模型重新分析，生成新的 AI 健康报告。

```http
POST /qm/api/analyze
Authorization: Bearer <token>
```

**响应（200）：**

```json
{
  "status": "ok",
  "message": "分析完成",
  "chars": 1250
}
```

---

#### POST /qm/api/import-facts

批量导入健康事实数据（管理端点，供数据迁移使用）。

```http
POST /qm/api/import-facts
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体：**

```json
[
  {"subject": "profile", "predicate": "gender", "object_json": "MALE", "source": "garmin"},
  {"subject": "profile", "predicate": "vo2_max", "object_json": 52.0, "source": "garmin"}
]
```

**响应（200）：**

```json
{
  "status": "ok",
  "imported": 2,
  "errors": []
}
```

---

#### POST /qm/api/upload/file

通用文件上传端点 — 支持 CSV、JSON、TXT、PDF（多模态 AI 提取）、图像（多模态 AI 分析）。

```http
POST /qm/api/upload/file
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `file` | File | 支持 .csv/.json/.txt/.pdf/.png/.jpg/.jpeg |

- **CSV/JSON/TXT**：直接解析入库
- **PDF**：每页转图片 → 多模态模型提取健康数据 → 结构化入库
- **图像**：多模态模型识别化验单/体检报告 → 结构化入库

**响应（200）：**

```json
{
  "status": "ok",
  "message": "report.pdf 上传成功",
  "filename": "report.pdf",
  "facts_imported": 15,
  "summary": "PDF 多模态分析完成，提取 15 条数据"
}
```

---

#### POST /qm/api/chat

Chat 代理端点（前端专用，转发到 HealthRouter）。

```http
POST /qm/api/chat
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体：**

```json
{
  "text": "帮我分析一下最近的训练数据",
  "context": {}
}
```

**响应（200）：**

```json
{
  "status": "success",
  "session_id": "uuid-xxx",
  "message": "",
  "data": { "coach_response": "..." }
}
```

---

### 2.3 医疗分析

#### POST /api/v1/medical/analyze

综合健康分析（AI 解读患者全部医疗数据）。

```http
POST /api/v1/medical/analyze
Authorization: Bearer <token>
```

**响应（200）：**

```json
{
  "status": "success",
  "session_id": "uuid-xxx",
  "summary": "综合评估摘要...",
  "insights": ["洞察1", "洞察2"],
  "concerns": ["关注点1"],
  "recommendations": ["建议1", "建议2"],
  "risk_flags": [],
  "confidence": 0.92
}
```

---

#### GET /api/v1/medical/timeline

临床事件时间线。

```http
GET /api/v1/medical/timeline?event_type=住院&limit=50
Authorization: Bearer <token>
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `event_type` | Query | 可选，筛选事件类型 |
| `limit` | Query | 1-200，默认 50 |

---

#### GET /api/v1/medical/medications

用药列表 + AI 审查（药物交互检测）。

```http
GET /api/v1/medical/medications?status_filter=active
Authorization: Bearer <token>
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `status_filter` | Query | active / all / discontinued，默认 active |

---

#### GET /api/v1/medical/labs/{test}

化验结果趋势（AI 趋势解读）。

```http
GET /api/v1/medical/labs/血常规?limit=20
Authorization: Bearer <token>
```

---

### 2.4 LLM 观测

#### GET /api/v1/llm-observe/metrics

LLM 调用汇总指标（直查 Langfuse PG）。

```http
GET /api/v1/llm-observe/metrics?days=7
Authorization: Bearer <token>
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `days` | Query | 1-90，默认 7 |

**响应（200）：**

```json
{
  "total_calls": 1234,
  "success_rate": 0.9856,
  "avg_latency_ms": 856.3,
  "p95_latency_ms": 2100.5,
  "total_tokens": 500000,
  "total_cost": 12.34,
  "by_model": [
    {
      "model": "gpt-4o",
      "calls": 800,
      "avg_latency_ms": 1200,
      "tokens": 300000,
      "cost": 10.0
    }
  ],
  "by_day": [
    {
      "date": "2026-05-23",
      "calls": 200,
      "avg_latency_ms": 800,
      "tokens": 50000,
      "cost": 2.0
    }
  ]
}
```

---

#### GET /api/v1/llm-observe/traces

Trace 列表（分页）。

```http
GET /api/v1/llm-observe/traces?limit=50&offset=0&model=gpt-4o
Authorization: Bearer <token>
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `limit` | Query | 1-200，默认 50 |
| `offset` | Query | ≥0，默认 0 |
| `model` | Query | 可选，按模型筛选 |

**响应（200）：**

```json
[
  {
    "id": "obs-uuid-xxx",
    "name": "coach_agent",
    "user_id": "garmin_user_001",
    "model": "gpt-4o",
    "status": "success",
    "latency_ms": 1234.5,
    "tokens": 1500,
    "cost": 0.05,
    "created_at": "2026-05-23T10:00:00"
  }
]
```

---

#### GET /api/v1/llm-observe/traces/{trace_id}

Trace 详情。

**响应（200）：**

```json
{
  "id": "obs-uuid-xxx",
  "name": "coach_agent",
  "input": { ... },
  "output": { ... },
  "model": "gpt-4o",
  "model_params": { "temperature": 0.3 },
  "tokens": { "prompt": 500, "completion": 1000, "total": 1500 },
  "cost": { "input": 0.01, "output": 0.04, "total": 0.05 },
  "latency_ms": 1234.5,
  "metadata": { ... },
  "created_at": "2026-05-23T10:00:00"
}
```

---

#### GET /api/v1/llm-observe/suggestions

规则引擎优化建议（5 条规则自动检测）。

```http
GET /api/v1/llm-observe/suggestions?days=7
Authorization: Bearer <token>
```

**响应（200）：**

```json
{
  "suggestions": [
    {
      "title": "模型延迟偏高",
      "severity": "warn",
      "detail": "模型 X 平均延迟 5000ms，超过全局均值 2 倍",
      "metric_key": "avg_latency_ms",
      "current_value": 5000.0,
      "threshold": 2000.0
    }
  ]
}
```

| 规则 | 条件 | 严重级 |
|------|------|--------|
| 模型延迟偏高 | avg_latency > 2x 全局均值 | warn |
| Token 利用率低 | output/input < 5% | info |
| 错误率异常 | error_rate > 5% | critical |
| 成本周环比增长 | week_delta > 30% | warn |
| 重复 Prompt | repeated > 10/小时 | info |

---

#### POST /api/v1/llm-observe/analyze

LLM 深度分析（AI 生成优化报告）。

```http
POST /api/v1/llm-observe/analyze
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体：**

```json
{ "days": 7 }
```

**响应（200）：**

```json
{
  "status": "success",
  "report": "# LLM 调用优化报告\n\n## 1. 调用概况\n...\n## 2. 性能瓶颈\n...\n## 3. 成本优化\n..."
}
```

---

### 2.5 隐私与合规

#### GET /api/v1/privacy/export

导出当前用户全部个人数据（JSON 附件）。

```http
GET /api/v1/privacy/export
Authorization: Bearer <token>
```

**响应（200）：** `application/json`，`Content-Disposition: attachment`。

---

#### POST /api/v1/privacy/delete

永久删除当前用户全部个人数据（不可逆）。

```http
POST /api/v1/privacy/delete
Authorization: Bearer <token>
Content-Type: application/json
```

**请求体：**

```json
{ "confirm_token": "<your_user_id>" }
```

`confirm_token` 必须等于当前 `user_id` 作为二次确认。

---

#### GET /api/v1/privacy/policy

获取隐私政策信息。

**响应（200）：**

```json
{
  "policy_url": "https://rhythmind.ai/privacy",
  "contact_email": "14455975@qq.com",
  "last_updated": "2026-05-09"
}
```

---

### 2.6 管理接口

以下接口要求 `user_id` 在 `ADMIN_USER_IDS` 白名单中。

#### GET /api/v1/admin/skills/pending

列出待审核的 Skill 记录。

```http
GET /api/v1/admin/skills/pending?limit=50&offset=0
Authorization: Bearer <admin_token>
```

**响应（200）：**

```json
{
  "total": 5,
  "items": [
    {
      "id": 1,
      "agent": "coach_agent",
      "skill_hash": "abc123",
      "content": "用户偏好长距离慢跑...",
      "source_task": "health_analysis",
      "confidence": 0.85,
      "created_at": "2026-05-20T10:00:00"
    }
  ]
}
```

---

#### POST /api/v1/admin/skills/{skill_hash}/approve

批准 Skill 并推送到 QMD 知识库。

**响应（204）：** 无内容（幂等）。

---

#### POST /api/v1/admin/skills/{skill_hash}/reject

拒绝 Skill（不推 QMD，不再使用）。

**响应（204）：** 无内容。

---

### 2.7 基础设施探针

无需认证。

| 端点 | 用途 | 响应 |
|------|------|------|
| `GET /ping` | 存活检测 | `{"status": "ok", "env": "dev"}` |
| `GET /livez` | K8s livenessProbe | `{"status": "alive", "version": "0.2.0"}` |
| `GET /readyz` | K8s readinessProbe（含 DB/Redis 检查） | `{"status": "ready", "checks": {"db": "ok", "redis": "ok"}}` |
| `GET /health` | 兼容旧 LB | `{"status": "healthy", "version": "0.2.0"}` |
| `GET /version` | 版本信息 | `{"version": "0.2.0", "git_sha": "...", "build_time": "...", "env": "prod"}` |
| `GET /metrics` | Prometheus 指标 | Prometheus text format |

---

## 3. MCP 工具接口

RHYTHMIND 通过 MCP (Model Context Protocol) 暴露 5 个健康工具，支持任何 MCP 兼容客户端直接调用。

### 连接配置

**Claude Desktop / Claude Code：**

```json
{
  "mcpServers": {
    "rhythmind": {
      "url": "http://localhost:8000/mcp/sse",
      "headers": { "Authorization": "Bearer <jwt>" }
    }
  }
}
```

**SSE 端点：** `GET /mcp/sse`
**消息端点：** `POST /mcp/messages/`

---

### 工具清单

#### rhythmind_status

获取用户健康概览（当前有效事实 + 近期记忆摘要）。

```json
{
  "name": "rhythmind_status",
  "arguments": {
    "user_id": "garmin_user_001"
  }
}
```

**响应：**

```json
{
  "user_id": "garmin_user_001",
  "current_facts": [
    {
      "subject": "profile",
      "predicate": "gender",
      "object": "MALE",
      "source": "garmin",
      "since": "2026-01-15T00:00:00"
    }
  ],
  "fact_count": 25,
  "recent_memory_keys": ["health_status"],
  "status": "ok"
}
```

---

#### rhythmind_search

语义检索健康知识库（BM25 + 向量 + LLM 重排序）。

```json
{
  "name": "rhythmind_search",
  "arguments": {
    "user_id": "garmin_user_001",
    "query": "半马训练配速策略",
    "collection": "health_knowledge",
    "top_k": 5
  }
}
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `user_id` | string | 是 | - | 用户 ID（个性化排序） |
| `query` | string | 是 | - | 检索查询（中英文均可） |
| `collection` | string | 否 | health_knowledge | 检索集合 |
| `top_k` | int | 否 | 5 | 返回数量 |

---

#### rhythmind_fact_query

查询时序健康知识图谱。

```json
{
  "name": "rhythmind_fact_query",
  "arguments": {
    "user_id": "garmin_user_001",
    "subject": "user_goal",
    "predicate": "targets",
    "mode": "current",
    "limit": 20
  }
}
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `user_id` | string | 是 | - | 用户 ID |
| `subject` | string | 是 | - | 查询主体（user_goal/injury/baseline 等） |
| `predicate` | string | 否 | - | 关系谓词 |
| `mode` | string | 否 | current | `current`=仅有效 / `history`=含历史 |
| `limit` | int | 否 | 20 | 历史模式最大返回数 |

**响应：**

```json
{
  "user_id": "garmin_user_001",
  "subject": "user_goal",
  "predicate": "targets",
  "mode": "current",
  "facts": [
    {
      "id": 42,
      "predicate": "targets",
      "object": "半马 1 小时 45 分完赛",
      "source": "garmin",
      "confidence": 1.0,
      "valid_from": "2026-03-01T00:00:00",
      "valid_until": null,
      "is_current": true
    }
  ],
  "count": 1
}
```

---

#### rhythmind_fact_update

写入或过期健康事实。

```json
{
  "name": "rhythmind_fact_update",
  "arguments": {
    "user_id": "garmin_user_001",
    "action": "write",
    "subject": "user_goal",
    "predicate": "targets",
    "object": { "goal": "全马完赛", "deadline": "2026-10-01" },
    "source": "mcp_client",
    "confidence": 0.9
  }
}
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `user_id` | string | 是 | - | 用户 ID |
| `action` | string | 是 | - | `write`=写入并过期旧值 / `invalidate`=批量过期 |
| `subject` | string | 是 | - | 主体 |
| `predicate` | string | 是 | - | 谓词 |
| `object` | object | write 时必填 | - | 事实值（任意 JSON） |
| `source` | string | 否 | mcp_client | 来源 Agent 名称 |
| `confidence` | float | 否 | 1.0 | 置信度 0-1 |

**写入响应：**

```json
{
  "action": "write",
  "fact_id": 99,
  "subject": "user_goal",
  "predicate": "targets",
  "object": { "goal": "全马完赛", "deadline": "2026-10-01" },
  "status": "ok"
}
```

**过期响应：**

```json
{
  "action": "invalidate",
  "subject": "user_goal",
  "predicate": "targets",
  "invalidated_count": 1,
  "status": "ok"
}
```

---

#### rhythmind_session_log

将训练会话数据写入 InfluxDB 时序库。

```json
{
  "name": "rhythmind_session_log",
  "arguments": {
    "user_id": "garmin_user_001",
    "source": "garmin",
    "sport_type": "running",
    "metrics": {
      "heart_rate_avg": 145,
      "heart_rate_max": 178,
      "steps": 12000,
      "distance_km": 8.5,
      "calories": 520,
      "hrv": 62
    }
  }
}
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `user_id` | string | 是 | - | 用户 ID |
| `source` | string | 是 | - | 设备来源（garmin/apple/huawei/manual） |
| `sport_type` | string | 否 | general | 运动类型 |
| `metrics` | object | 是 | - | 训练指标（见下表） |

**metrics 支持的字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `heart_rate_avg` | float | 平均心率 |
| `heart_rate_max` | float | 最大心率 |
| `steps` | float | 步数 |
| `distance_km` | float | 距离（公里） |
| `calories` | float | 卡路里 |
| `sleep_hours` | float | 睡眠时长 |
| `hrv` | float | 心率变异性 |
| `body_fat_pct` | float | 体脂率 |
| `muscle_mass_kg` | float | 肌肉量 |
| `water_pct` | float | 水分率 |
| `visceral_fat` | float | 内脏脂肪 |

---

## 4. 错误处理

### HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 200 | 成功 |
| 204 | 成功（无内容，管理操作） |
| 400 | 请求参数错误 |
| 401 | 未认证（JWT 缺失/过期/无效） |
| 403 | 无权限（非 admin） |
| 404 | 资源不存在 |
| 422 | 数据校验失败 / 合规检查未通过 |
| 429 | 限流（请求过于频繁） |
| 503 | 服务不可用（依赖组件异常） |

### 错误响应格式

```json
{
  "detail": "具体错误信息"
}
```

### MCP 错误

MCP 工具错误通过返回 JSON 中的 `error` 字段表示：

```json
{
  "error": "missing_argument",
  "field": "query"
}
```

常见错误码：`missing_argument`、`invalid_action`、`unknown_tool`。

---

## 5. 限流策略

| 端点 | 用户级 | IP 级 |
|------|--------|-------|
| 健康数据上传 | 10 次/5 分钟 | 30 次/5 分钟 |
| 文本对话 | 20 次/5 分钟 | 60 次/5 分钟 |
| 医疗分析 | 20 次/5 分钟 | 30 次/5 分钟 |
| 隐私导出 | 5 次/小时 | - |
| 隐私删除 | 3 次/小时 | - |

限流基于 Redis 固定窗口算法，超出返回 `429 Too Many Requests`。

---

## 6. SDK 集成示例

### Python（httpx）

```python
import httpx

BASE = "https://aisport.tech/qm"
TOKEN = "your-jwt-token"

headers = {"Authorization": f"Bearer {TOKEN}"}

# 获取仪表盘数据
resp = httpx.get(f"{BASE}/api/dashboard", headers=headers)
print(resp.json())

# 上传健康数据
resp = httpx.post(f"{BASE}/api/v1/health/upload", headers=headers, json={
    "source": "manual",
    "heart_rate_avg": 72,
    "steps": 8500,
    "sleep_hours": 7.0,
})
print(resp.json())

# 触发 AI 分析
resp = httpx.post(f"{BASE}/api/analyze", headers=headers)
print(resp.json())

# 获取报告列表
resp = httpx.get(f"{BASE}/api/reports", headers=headers)
for report in resp.json()["reports"]:
    print(f"Report #{report['id']}: {report['preview'][:50]}...")
```

### cURL

```bash
# 仪表盘
curl -H "Authorization: Bearer $TOKEN" \
  https://aisport.tech/qm/api/dashboard

# 上传健康数据
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source":"manual","heart_rate_avg":72,"steps":8500}' \
  https://aisport.tech/qm/api/v1/health/upload

# 文件上传（PDF 报告分析）
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@report.pdf" \
  https://aisport.tech/qm/api/upload/file

# SSE 流式上传
curl -N -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"source":"garmin","heart_rate_avg":145}' \
  https://aisport.tech/qm/api/v1/health/upload/stream

# LLM 观测指标
curl -H "Authorization: Bearer $TOKEN" \
  "https://aisport.tech/qm/api/v1/llm-observe/metrics?days=7"
```

### JavaScript / TypeScript

```typescript
const BASE = "https://aisport.tech/qm";
const TOKEN = "your-jwt-token";

const headers = {
  Authorization: `Bearer ${TOKEN}`,
  "Content-Type": "application/json",
};

// 获取仪表盘
const dash = await fetch(`${BASE}/api/dashboard`, { headers });
const { data } = await dash.json();
console.log(data);

// 上传健康数据
const upload = await fetch(`${BASE}/api/v1/health/upload`, {
  method: "POST",
  headers,
  body: JSON.stringify({
    source: "manual",
    heart_rate_avg: 72,
    steps: 8500,
    sleep_hours: 7.0,
  }),
});
console.log(await upload.json());

// SSE 流式上传
const evtSource = new EventSource(
  `${BASE}/api/v1/health/upload/stream`,
  { headers }
);
// 注意：EventSource 不支持自定义 headers，需使用 fetch + ReadableStream
const streamResp = await fetch(`${BASE}/api/v1/health/upload/stream`, {
  method: "POST",
  headers: { ...headers, Accept: "text/event-stream" },
  body: JSON.stringify({ source: "manual", heart_rate_avg: 145 }),
});
const reader = streamResp.body!.getReader();
const decoder = new TextDecoder();
while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const chunk = decoder.decode(value);
  // 解析 SSE 事件...
  console.log(chunk);
}
```

### MCP 客户端（Python SDK）

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async def use_rhythmind_mcp():
    async with sse_client(
        "http://localhost:8000/mcp/sse",
        headers={"Authorization": "Bearer your-jwt-token"},
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 获取用户健康状态
            result = await session.call_tool("rhythmind_status", {
                "user_id": "garmin_user_001",
            })
            print(result)

            # 查询健康事实
            result = await session.call_tool("rhythmind_fact_query", {
                "user_id": "garmin_user_001",
                "subject": "running",
                "mode": "current",
            })
            print(result)

            # 记录训练数据
            result = await session.call_tool("rhythmind_session_log", {
                "user_id": "garmin_user_001",
                "source": "garmin",
                "sport_type": "running",
                "metrics": {
                    "heart_rate_avg": 145,
                    "distance_km": 8.5,
                    "calories": 520,
                },
            })
            print(result)
```

---

## 附录：事实数据 Subject 体系

以下是系统中常见的 `subject` 分类，供查询和写入参考：

| Subject | 说明 | 典型 Predicate |
|---------|------|----------------|
| `profile` | 用户基本资料 | gender, age, height_cm, weight_kg, bmi |
| `running` | 跑步数据 | total_runs, total_km, avg_pace, best_5k |
| `sleep` | 睡眠数据 | avg_hours, deep_pct, rem_pct, record_days |
| `training` | 训练负荷 | acwr, readiness_score, endurance_score |
| `body` | 身体指标 | hrv_avg, vo2_max, vo2_max_best, resting_hr |
| `health_events` | 健康事件 | abnormal_hr_count, threshold |
| `user_goal` | 训练目标 | targets, deadline |
| `injury` | 伤病记录 | restricts, recovery_status |
| `baseline` | 体能基线 | vo2_max, lthr, max_hr |
| `ai_report` | AI 分析报告 | analysis |
| `upload_csv` | CSV 上传数据 | 列名 |
| `upload_json` | JSON 上传数据 | 键名 |
| `pdf_report` | PDF 提取数据 | 医学指标名 |
| `image_report` | 图像提取数据 | 健康指标名 |
