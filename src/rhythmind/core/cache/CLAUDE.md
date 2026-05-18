# rhythmind/core/cache — Redis 缓存层

> `[根目录(../../../CLAUDE.md) > **rhythmind** > **core** > **cache**`

---

## 模块职责

基于 Redis 的异步缓存层，提供三层缓存策略：

1. **装饰器缓存** (`cache_async`) — 任意 async 函数结果缓存
2. **Session 缓存** (`SessionCache`) — 用户会话级数据
3. **Fact 缓存** (`FactCache`) — FactManager 查询结果
4. **Intent 缓存** (`IntentCache`) — 意图分类结果

---

## TTL 设计

| 缓存类型 | TTL | 对齐目标 |
|---------|-----|---------|
| Session | 30 分钟 | JWT 过期时间 |
| Fact | 5 分钟 | 可穿戴数据更新频率 |
| LLM 响应 | 10 分钟 | 相同 prompt 返回相同结果 |
| Intent | 10 分钟 | 重复问题免重新分类 |

---

## 对外接口

### 装饰器缓存

```python
@cache_async("llm_response", ttl_seconds=600)
async def call_llm(prompt: str, model: str) -> str: ...
```

### SessionCache

```python
await SessionCache.get(user_id, session_id) -> dict | None
await SessionCache.set(user_id, session_id, data) -> None
await SessionCache.delete(user_id, session_id) -> None
await SessionCache.clear_user(user_id) -> None  # 登出时调用
```

### FactCache

```python
await FactCache.get(user_id, subject, predicate) -> dict | None
await FactCache.set(user_id, subject, predicate, data) -> None
await FactCache.invalidate(user_id, subject, predicate) -> None
await FactCache.invalidate_user(user_id) -> None  # 数据更新时清除
```

### IntentCache

```python
await IntentCache.get(user_id, text_hash) -> str | None
await IntentCache.set(user_id, text_hash, intent) -> None
```

---

## 故障策略

所有 Redis 操作失败时静默降级：
- `get` → 返回 `None`（穿透到数据源）
- `set` → 跳过（不缓存，下次直接查）
- 不抛异常，不阻断业务

---

## 关键依赖

- `redis[asyncio]>=5.0` — 异步 Redis 客户端
- `settings.redis_url` — 连接地址
- `settings.redis_pool_size` — 连接池大小（默认 10）

---

## 相关文件

```
src/rhythmind/core/cache/
└── __init__.py  # 全部实现（单文件模块）
```

---

## 变更记录 (Changelog)

- **2026-05-18** 首次 AI 上下文初始化
