# rhythmind/integrations — 外部平台集成

> `[根目录](../../../../CLAUDE.md) > **rhythmind** > **integrations**`

> **最后更新:** 2026-05-27T10:50:56+08:00

---

## 变更记录

- **2026-05-27** 首次 AI 上下文初始化

---

## 模块职责

外部第三方平台 API 集成层。当前包含飞书（Lark）API 客户端，支持双模式认证（直连 OAuth + lark-cli 子进程）。

---

## 文件清单

| 文件 | 职责 |
|------|------|
| `__init__.py` | 模块导出 |
| `feishu_client.py` | 飞书 API 客户端（消息发送/回复/Markdown/群聊/消息历史） |

---

## 飞书客户端 (feishu_client.py)

### 认证模式

| 模式 | 条件 | 实现 |
|------|------|------|
| **直连 OAuth** | `FEISHU_APP_ID` + `FEISHU_APP_SECRET` 已配置 | `httpx` 直接调用飞书 API |
| **lark-cli 子进程** | 无直连凭证时回退 | 调用 `lark-cli` CLI 工具 |

Token 自动缓存，提前 5 分钟刷新。

### 对外接口

| 函数 | 用途 |
|------|------|
| `send_text_message(receive_id, text)` | 发送文本消息 |
| `reply_text(message_id, text)` | 回复文本消息 |
| `reply_markdown(message_id, content)` | 回复富文本卡片消息 |
| `list_bot_chats(page_size)` | 列出机器人所在群聊 |
| `get_chat_messages(chat_id, page_size, start_time)` | 获取群聊消息历史 |
| `get_bot_info()` | 获取机器人信息 |

---

## 关键依赖

- `httpx` — HTTP 客户端（直连模式）
- `rhythmind.config.settings` — 飞书凭证配置

---

## 相关模块

- [[api/routers/feishu]] — 飞书事件 Webhook + 消息轮询路由
- [[config]] — `feishu_app_id`, `feishu_app_secret`, `feishu_verification_token`
