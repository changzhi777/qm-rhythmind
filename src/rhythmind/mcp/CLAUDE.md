# rhythmind/mcp — MCP Server 与路由

> `[根目录(../../CLAUDE.md) > **rhythmind** > **mcp**`

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 模块职责

Model Context Protocol (MCP) SSE 服务，对外暴露健康工具，供 MCP 兼容客户端调用。

**支持客户端**: Claude Desktop / Claude Code / 企业微信 Bot / Cursor / 自定义 MCP Client

---

## 入口与启动

- **入口**: `from rhythmind.mcp import build_mcp_server`
- **路由挂载**: `app.include_router(mcp_router)` 在 `api/main.py` 中
- **SSE 端点**: `GET /mcp/sse` (握手), `POST /mcp/messages/` (消息)

---

## 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `__init__.py` | — | 公开 API: `build_mcp_server` |
| `server.py` | ~180 | MCP 工具注册（5 个健康工具） |
| `router.py` | ~120 | SSE 路由 + JWT 鉴权 |

---

## MCP 工具清单

### 完整参数签名

#### 1. `rhythmind_status` — 平台状态查询

```
参数:
  user_id: str                     # 用户 ID（必填）

返回:
  {
    status: str,                   # "ok" | "degraded" | "error"
    user_id: str,
    facts_count: int,              # 健康事实条目数
    recent_sessions: int,          # 最近会话数
    model_platform: str,           # 当前推理平台 (mlx/ollama/litellm)
  }
```

**实现**: 检查 `FactManager` + `MemoryManager` 可达性，汇总用户数据量

#### 2. `rhythmind_search` — 健康知识语义搜索

```
参数:
  user_id: str                     # 用户 ID（必填）
  query: str                       # 搜索查询（必填）
  collection: str = "agent_skills" # 搜索集合
  top_k: int = 5                   # 返回结果数

返回:
  {
    results: list[{
      content: str,
      score: float,
      metadata: dict,
    }],
    total: int,
  }
```

**实现**: `QMDClient.query(collection, query, user_ns=user_id, top_k=top_k)`

#### 3. `rhythmind_fact_query` — 时序知识图谱查询

```
参数:
  user_id: str                     # 用户 ID（必填）
  subject: str                     # 查询主题（必填，如 "running"）
  predicate: str | None = None     # 谓词筛选（如 "summary"）
  mode: str = "current"            # "current" | "history"
  limit: int = 10                  # history 模式下的返回条数

返回 (mode="current"):
  {
    results: list[{
      id: int,
      subject: str,
      predicate: str,
      object: any,                 # JSON value
      source: str,
      confidence: float,
      valid_from: str,             # ISO datetime
      valid_until: str | null,
    }]
  }

返回 (mode="history"):
  {
    results: list[{...}],          # 按 valid_from DESC 排序
    total: int,
  }
```

**实现**: `FactManager.query_current(subject, predicate)` 或 `FactManager.query_history(subject, predicate, limit)`

#### 4. `rhythmind_fact_update` — 健康事实写入/过期

```
参数:
  user_id: str                     # 用户 ID（必填）
  action: str                      # "write" | "write_additive" | "invalidate"
  subject: str                     # 主题（必填）
  predicate: str                   # 谓词（必填）
  object: any = None               # 值（action=write 时必填）
  source: str = "mcp_client"       # 数据来源
  confidence: float = 0.8          # 置信度

返回:
  {
    success: bool,
    fact_id: int | None,           # write 成功时返回 ID
    action: str,
  }
```

**action 说明**:
- `write` — 覆盖写入（旧事实 `valid_until` 置为 now）
- `write_additive` — 叠加写入（旧事实保留，新事实追加）
- `invalidate` — 按 subject+predicate 批量失效

#### 5. `rhythmind_session_log` — 训练会话日志写入

```
参数:
  user_id: str                     # 用户 ID（必填）
  source: str                      # 数据来源（必填，如 "garmin_connect"）
  sport_type: str | None = None    # 运动类型
  metrics: dict                    # 指标键值对（必填）

返回:
  {
    session_id: str,
    facts_created: int,
  }
```

**实现**: 解析 `metrics` → 逐条写入 `FactManager.write_fact_additive()`

---

## build_mcp_server

```python
def build_mcp_server() -> Server:
    """创建并注册所有健康工具的 MCP Server 实例"""
```

**注册流程**:
```
build_mcp_server()
  └─ Server("rhythmind", version="0.2.0")
      ├─ @server.tool() → rhythmind_status
      ├─ @server.tool() → rhythmind_search
      ├─ @server.tool() → rhythmind_fact_query
      ├─ @server.tool() → rhythmind_fact_update
      └─ @server.tool() → rhythmind_session_log
```

---

## SSE 路由

### 端点

| 方法 | 路径 | 用途 | 认证 |
|------|------|------|------|
| `GET` | `/mcp/sse` | SSE 握手（建立长连接） | JWT Bearer / `?user_id=` 参数 |
| `POST` | `/mcp/messages/` | 客户端→服务端消息 | 继承 SSE 会话 |

### 认证方式

```
GET /mcp/sse
  ├─ Authorization: Bearer <jwt_token>  → 解析 user_id
  ├─ ?user_id=<id>&token=<jwt>          → 解析 user_id
  └─ settings.mcp_require_auth = False  → 开发模式跳过（默认 True）
```

### MCPUserId 依赖

```python
async def MCPUserId(
    request: Request,
    user_id: str | None = Query(None),
    authorization: str | None = Header(None),
) -> str:
    """从请求中提取并验证 user_id"""
```

---

## 数据流

```
MCP Client (Claude Desktop)
    │
    ├─ GET /mcp/sse ────────────────────── SSE 握手
    │     └─ 验证 JWT → 建立 SSE 连接
    │
    └─ POST /mcp/messages/ ─────────────── JSON-RPC 消息
          │
          ├─ "tools/list"     → 返回 5 个工具定义
          ├─ "tools/call"     → 路由到对应 handler
          │     ├─ rhythmind_status      → MemoryManager + FactManager
          │     ├─ rhythmind_search      → QMDClient.query()
          │     ├─ rhythmind_fact_query  → FactManager
          │     ├─ rhythmind_fact_update → FactManager
          │     └─ rhythmind_session_log → FactManager
          └─ "tools/response" → 返回结果给客户端
```

---

## 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `mcp_require_auth` | `True` | 生产环境强制 JWT 验证 |
| `mcp_max_sessions` | — | 最大并发 SSE 连接数 |

---

## 客户端配置示例

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "rhythmind": {
      "url": "http://localhost:8000/mcp/sse?user_id=alice&token=test-jwt"
    }
  }
}
```

### Claude Code (`.claude/settings.json`)

```json
{
  "mcpServers": {
    "rhythmind": {
      "type": "sse",
      "url": "https://aisport.tech/qm/api/mcp/sse",
      "headers": {
        "Authorization": "Bearer <jwt_token>"
      }
    }
  }
}
```

---

## 关键依赖

- **MCP SDK**: `mcp >= 1.0`（Server + SSE transport）
- **JWT**: `python-jose` / 自实现验证
- **内部依赖**: `MemoryManager`, `FactManager`, `QMDClient`

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：补充 5 个工具完整参数签名+返回值、build_mcp_server 注册流程、SSE 认证双模式、JSON-RPC 数据流图、Claude Desktop/Code 配置示例
- **2026-05-12** 首次 AI 上下文初始化
