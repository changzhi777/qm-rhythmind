# rhythmind/mcp — MCP Server 与路由

> `[根目录(../../CLAUDE.md) > **rhythmind** > **mcp**`

---

## 模块职责

Model Context Protocol (MCP) SSE 服务，对外暴露健康工具，供 MCP 兼容客户端（Claude Desktop、Claude Code、企业微信 Bot 等）调用。

---

## 入口与启动

- **入口**: `from rhythmind.mcp import build_mcp_server`
- **路由挂载**: `app.include_router(mcp_router)` 在 `api/main.py` 中
- **SSE 端点**: `/mcp/sse` (GET), `/mcp/messages/` (POST)

---

## 对外接口

### MCP 工具清单

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `rhythmind_status` | 平台状态查询 | `user_id` |
| `rhythmind_search` | 健康知识语义搜索 | `user_id`, `query`, `collection?`, `top_k?` |
| `rhythmind_fact_query` | 时序知识图谱查询 | `user_id`, `subject`, `predicate?`, `mode?`, `limit?` |
| `rhythmind_fact_update` | 健康事实写入/过期 | `user_id`, `action`, `subject`, `predicate`, `object?`, `source?`, `confidence?` |
| `rhythmind_session_log` | 训练会话日志写入 | `user_id`, `source`, `sport_type?`, `metrics` |

### build_mcp_server

```python
def build_mcp_server() -> Server: ...
```

### SSE 路由

```python
@router.get("/sse")
async def sse_endpoint(request: Request, user_id: MCPUserId) -> StreamingResponse: ...

@router.post("/messages/")
async def messages_endpoint(request: Request, user_id: MCPUserId) -> Response: ...
```

---

## 关键依赖与配置

- **MCP**: `mcp >= 1.0`
- **认证**: JWT 验证（在 SSE 握手阶段），生产环境 `mcp_require_auth=True`
- **配置**: `settings.mcp_require_auth`

---

## 数据模型

无持久化数据模型，通过 `MemoryManager` / `FactManager` 读写。

---

## 测试与质量

- 测试目录：`tests/` 下有 MCP 相关测试
- 代码风格：`ruff check src/rhythmind/mcp/`

---

## 常见问题 (FAQ)

**Q: MCP 端点如何配置认证？**  
A: 生产环境需开启 `mcp_require_auth=True`，通过 JWT Bearer token 验证。

**Q: MCP 服务不可用时是否影响 REST API？**  
A: 独立运行，不影响 REST API 主流程。

**Q: 如何在 Claude Code 中使用 MCP？**  
A: 在 `claude_desktop_config.json` 中配置 `"url": "http://localhost:8000/mcp/sse"`。

---

## 相关文件清单

```
src/rhythmind/mcp/
├── __init__.py     # 公开 API: build_mcp_server
├── server.py       # MCP 工具注册（5 个健康工具）
└── router.py      # SSE 路由 + JWT 鉴权
```

---

## 变更记录 (Changelog)

- **2026-05-12** 完整扫描完成，新增工具清单和 SSE 路由详情
- **2026-05-12** 首次 AI 上下文初始化
