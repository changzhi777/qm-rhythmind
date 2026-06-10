# rhythmind/integrations — 外部平台集成

> `[根目录](../../../../CLAUDE.md) > **rhythmind** > **integrations**`

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 变更记录

- **2026-06-10** 深化：补充完整函数签名/参数/返回值/飞书 API 映射、认证缓存时序、错误处理策略
- **2026-05-27** 首次 AI 上下文初始化

---

## 模块职责

外部第三方平台 API 集成层。当前包含飞书（Lark）API 客户端，支持双模式认证（直连 OAuth + lark-cli 子进程），Token 自动缓存并提前 5 分钟刷新。

---

## 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `__init__.py` | — | 模块导出 |
| `feishu_client.py` | 195 | 飞书 API 客户端（认证/消息/群聊/机器人） |

---

## 飞书客户端 (feishu_client.py)

### 认证架构

```
send_text_message / reply_text / get_bot_info ...
    │
    ├── (直连 OAuth) _get_tenant_token_direct()
    │       └─ httpx POST /auth/v3/tenant_access_token/internal
    │          { app_id, app_secret } → token (2h, 提前5min刷新)
    │
    └── (lark-cli 回退) _get_tenant_token_via_cli()
            └─ asyncio subprocess lark-cli
               POST /open-apis/auth/v3/tenant_access_token/internal --as bot
```

**认证选择逻辑**: `_has_direct_credentials()` 检查 `FEISHU_APP_ID` + `FEISHU_APP_SECRET` 是否已配置

**Token 缓存**:
```python
_token_cache = {"token": "", "expires_at": 0.0}
# expire = min(expire - 300s, 即提前5分钟刷新)
```

### 内部函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `_has_direct_credentials()` | `() -> bool` | 判断是否配置了飞书应用凭证 |
| `_get_tenant_token()` | `async () -> str` | 获取 tenant_access_token（自动选通道） |
| `_get_tenant_token_direct()` | `async () -> str` | httpx 直连飞书 API 获取 token |
| `_get_tenant_token_via_cli()` | `async () -> str` | lark-cli 子进程获取 token |
| `_api_headers()` | `async () -> dict[str, str]` | 构造 Bearer + Content-Type 请求头 |
| `_cli_api(method, path, data, params)` | `async (...) -> dict` | lark-cli 子进程通用调用 |

### 对外接口（完整签名）

#### 消息发送

```python
async def send_text_message(
    receive_id: str,               # 接收者 ID（open_id / chat_id / user_id）
    text: str,                     # 消息文本
    receive_id_type: str = "open_id",  # open_id / chat_id / user_id
) -> dict[str, Any]:               # { code, msg, data: { message_id } }
```

**实现**: `_cli_api("POST", "/im/v1/messages", data={...})`

#### 消息回复

```python
async def reply_text(
    message_id: str,               # 被回复消息 ID
    text: str,                     # 回复文本
) -> dict[str, Any]:               # 飞书 API 响应
```

**实现**: httpx 直连 `POST /im/v1/messages/{message_id}/reply`

```python
async def reply_markdown(
    message_id: str,               # 被回复消息 ID
    content: str,                  # Markdown 内容
) -> dict[str, Any]:
```

**实现**: httpx 直连，`msg_type: "interactive"`，带 RHYTHMIND 品牌卡片（turquoise 模板）

#### 群聊管理

```python
async def list_bot_chats(
    page_size: int = 20,
) -> list[dict[str, Any]]:
```

**实现**: `_cli_api("GET", "/im/v1/chats")`，如 `has_more` 且 items 为空则重试 page_size=50

```python
async def get_chat_messages(
    chat_id: str,
    page_size: int = 20,
    start_time: str | None = None,  # ISO 时间戳字符串
) -> list[dict[str, Any]]:
```

**实现**: `_cli_api("GET", "/im/v1/messages", params={...})`

#### 机器人

```python
async def get_bot_info() -> dict[str, Any]:
```

**实现**: `_cli_api("GET", "/open-apis/bot/v3/info")`

### 飞书 API 对照表

| 函数 | HTTP 方法 | 飞书 API 路径 | 调用方式 | 超时 |
|------|---------|--------------|---------|------|
| `send_text_message` | POST | `/im/v1/messages` | lark-cli | 15s |
| `reply_text` | POST | `/im/v1/messages/{id}/reply` | httpx 直连 | 10s |
| `reply_markdown` | POST | `/im/v1/messages/{id}/reply` | httpx 直连 | 10s |
| `list_bot_chats` | GET | `/im/v1/chats` | lark-cli | 15s |
| `get_chat_messages` | GET | `/im/v1/messages` | lark-cli | 15s |
| `get_bot_info` | GET | `/bot/v3/info` | lark-cli | 15s |

### 错误处理策略

| 场景 | 行为 |
|------|------|
| `_cli_api` 返回 `code != 0` | `log.error` → 返回空列表 `[]`（静默降级） |
| `_cli_api` 非零退出码 | `log.error` → 返回 `{code: -1, msg: "CLI call failed"}` |
| Token 获取失败 | `raise RuntimeError`（阻断后续调用） |
| httpx 超时 | 抛异常，由调用方处理 |

---

## 关键依赖

- `httpx` — HTTP 客户端（直连模式）
- `structlog` — 结构化日志
- `asyncio` — lark-cli 子进程调用
- `shutil.which("lark-cli")` — CLI 路径探测（回退默认路径）
- `rhythmind.config.settings` — `feishu_app_id`, `feishu_app_secret`

---

## 配置项

| 配置 | 说明 | 必填 |
|------|------|------|
| `FEISHU_APP_ID` | 飞书应用 ID | 直连模式必填 |
| `FEISHU_APP_SECRET` | 飞书应用密钥 | 直连模式必填 |
| `FEISHU_VERIFICATION_TOKEN` | 事件订阅验证 Token | Webhook 路由用 |

---

## 相关模块

- [[api/routers/feishu]] — 飞书事件 Webhook + 消息轮询路由（调用 feishu_client）
- [[config]] — `Settings` 飞书凭证配置
