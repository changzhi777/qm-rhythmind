# rhythmind/core/cache — Redis 缓存层

> `[根目录(../../../CLAUDE.md) > **rhythmind** > **core** > **cache**`

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 模块职责

基于 Redis 的异步缓存层，单文件模块 (`__init__.py`)，提供四层缓存策略。全部操作失败时静默降级，不阻断业务。

---

## 架构

```
                    ┌─────────────────────┐
                    │   业务调用方          │
                    │ Agent / API / MCP   │
                    └──────┬──────┬───────┘
                           │      │
              ┌────────────┘      └────────────┐
              ▼                                 ▼
    ┌─────────────────┐              ┌─────────────────┐
    │ @cache_async    │              │ SessionCache    │
    │ (装饰器缓存)     │              │ FactCache       │
    │                 │              │ IntentCache     │
    └────────┬────────┘              └────────┬────────┘
             │                                │
             └────────────┬───────────────────┘
                          ▼
              ┌─────────────────────┐
              │  Redis (asyncio)    │
              │  pool_size 默认 10  │
              └─────────────────────┘
                          │
                   故障时静默降级 → None / skip
```

---

## TTL 设计

| 缓存类型 | TTL | 对齐目标 | 失效条件 |
|---------|-----|---------|---------|
| Session | 30 min | JWT 过期时间 | 用户登出 |
| Fact | 5 min | 可穿戴数据更新频率 | 新数据写入 |
| LLM Response | 10 min | 相同 prompt 返回相同结果 | — |
| Intent | 10 min | 重复问题免重新分类 | — |

---

## 对外接口

### 装饰器缓存 (`cache_async`)

```python
from rhythmind.core.cache import cache_async

@cache_async("llm_response", ttl_seconds=600)
async def call_llm(prompt: str, model: str) -> str:
    # 首次调用执行函数，结果写入 Redis
    # 600s 内相同参数直接返回缓存值
    ...

@cache_async(
    "dashboard_data",
    ttl_seconds=120,
    key_builder=lambda *a, **kw: f"dash:{kw.get('user_id', 'anon')}",
)
async def get_dashboard_data(user_id: str) -> dict: ...
```

**参数**:

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `cache_key_prefix` | str | 必填 | Redis key 前缀 |
| `ttl_seconds` | int | 必填 | 过期时间 |
| `key_builder` | callable | auto | 自定义 key 构建函数（默认用 `hash(args+kwargs)`） |

### SessionCache

```python
from rhythmind.core.cache import SessionCache

# 读取会话
session = await SessionCache.get(user_id, session_id)  # -> dict | None

# 写入会话
await SessionCache.set(user_id, session_id, data)

# 删除单个会话
await SessionCache.delete(user_id, session_id)

# 清除用户所有会话（登出）
await SessionCache.clear_user(user_id)
```

**数据结构**: `session:{user_id}:{session_id}` → JSON dict，TTL 30min

### FactCache

```python
from rhythmind.core.cache import FactCache

# 查询
fact = await FactCache.get(user_id, subject, predicate)  # -> dict | None

# 写入
await FactCache.set(user_id, subject, predicate, data)

# 单个事实失效
await FactCache.invalidate(user_id, subject, predicate)

# 用户所有事实缓存失效（新数据入库时调用）
await FactCache.invalidate_user(user_id)
```

**数据结构**: `fact:{user_id}:{subject}:{predicate}` → JSON dict，TTL 5min

### IntentCache

```python
from rhythmind.core.cache import IntentCache

intent = await IntentCache.get(user_id, text_hash)  # -> str | None
await IntentCache.set(user_id, text_hash, intent)
```

**数据结构**: `intent:{user_id}:{hash(text)}` → intent 字符串，TTL 10min

---

## 底层连接

### Redis 客户端单例

```python
from rhythmind.core.cache import (
    get_redis,      # 获取/创建异步 Redis 连接
    close_redis,    # 关闭连接（应用 shutdown 时调用）
)
```

**连接参数**:

| 配置 | 来源 | 默认值 |
|------|------|--------|
| URL | `settings.redis_url` | `redis://localhost:6379/15` |
| 连接池大小 | `settings.redis_pool_size` | 10 |
| 编码 | `decode_responses=True` | — |

### 故障策略矩阵

| 操作 | Redis 不可达 | key 不存在 |
|------|------------|-----------|
| `get()` | 返回 `None`（穿透到数据源） | 返回 `None` |
| `set()` | 跳过（不缓存，下次直接查） | 写入 |
| `delete()` / `clear_user()` | 跳过 | 跳过 |
| `invalidate()` | 跳过 | 跳过 |

**核心原则**: 不抛异常，不阻断业务，Redis 完全透明。

---

## 使用场景

| 场景 | 缓存层 | 示例 |
|------|--------|------|
| LLM 调用去重 | `@cache_async` | 相同 prompt 10min 内不重复调用 |
| Dashboard 数据 | `@cache_async` | 2min 内重复请求直接返回 |
| 用户会话状态 | `SessionCache` | JWT token 有效期内免查 DB |
| 健康知识图谱查询 | `FactCache` | `query_current(subject, predicate)` 缓存 5min |
| Chat 意图分类 | `IntentCache` | 相同问题不重复分类 |
| 数据更新后的级联失效 | `FactCache.invalidate_user()` | 新 Garmin 数据入库后清除 |

---

## 相关模块

| 模块 | 使用方式 |
|------|---------|
| [[core/hermes_base]] | `@cache_async` 装饰 LLM 调用 |
| [[core/memory/fact_manager]] | `FactCache` 缓存 `query_current` 结果 |
| [[api/main]] | `close_redis()` 在 shutdown 事件中调用 |

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：补充架构图、完整参数表、故障策略矩阵、底层连接配置、5 个使用场景表、数据 key 结构
- **2026-05-18** 首次 AI 上下文初始化
