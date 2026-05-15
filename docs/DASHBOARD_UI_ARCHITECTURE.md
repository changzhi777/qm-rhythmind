# Dashboard UI 架构设计（Phase 3.4）

> 版本：0.1.8
> 状态：规划中（待前端实现）
> 依赖：MCP Server (`/mcp/sse`) + REST API (`/api/v1/health/*`)

---

## 1. 背景与目标

当前 `qm-rhythmind` 是纯 Python 后端（FastAPI），无前端代码。CHANGELOG.md 提及"Dashboard UI (React) connected to MCP"作为规划项。本文档定义该 React Dashboard 的架构设计。

**设计目标**：
- 面向终端用户（B端/C端），展示健康报告、训练计划、趋势分析
- 通过 MCP SSE 长连接实时推送 Swarm 进度（替代方案：WebSocket）
- 最小依赖：纯 React + Vite，不引入重型框架
- 可嵌入或独立部署

---

## 2. 技术选型

| 层级 | 技术 | 理由 |
|------|------|------|
| 框架 | React 18 + Vite | 生态成熟，HMR 快 |
| 状态管理 | Zustand | 轻量，TypeScript 友好 |
| 数据获取 | SWR 或 TanStack Query | 缓存 + 乐观更新 |
| 实时通信 | MCP SSE / WebSocket | 复用现有后端协议 |
| 样式 | TailwindCSS | 快速迭代 |
| 图表 | Recharts | 轻量 React 原生 |
| 移动端 | Responsive 设计（Tailwind） | 不过早引入 React Native |

---

## 3. 核心页面

```
/                    → 重定向 /dashboard
/dashboard           → 健康概览（核心）
/dashboard/upload    → 数据上传（含流式进度）
/dashboard/chat      → 文本对话界面
/dashboard/profile   → 用户画像 + 历史趋势
/dashboard/admin     → 技能审核（admin 用户）
/login               → 登录页
```

---

## 4. 数据流设计

### 4.1 实时流（上传进度）

**方案 A：MCP SSE**（推荐，与后端协议一致）
```
前端                        后端
  │                           │
  ├─ GET /mcp/sse?token=... ─►│  (SSE 长连接)
  │                           │
  │◄─ event: metrics_done ────┤
  │◄─ event: data_done ───────┤
  │◄─ event: coach_done ──────┤
  │◄─ event: done ────────────┤
```

**方案 B：WebSocket**（`/health/upload/stream/ws`）
```
前端                        后端
  │                           │
  ├─ WS /upload/stream/ws ──►│
  │  ?token=...               │
  │                           │
  ├─ send({input_data}) ─────►│
  │◄─ recv({type:connected}) ─┤
  │◄─ recv({type:metrics_done})┤
  ...                         ...
```

### 4.2 认证流程

```
用户 → /login (表单) → POST /api/v1/auth/login
     ← {token: jwt, expires_in: 3600}

后续请求 Header: Authorization: Bearer <token>
```

> 注意：当前后端无 `/auth/login` 端点（依赖外部 Auth 服务或 JWTissuer）。Phase 1 实现中 Token 由外部 IdP 签发，前端仅存储和转发。

---

## 5. 组件架构

```
src/
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx      # 侧边栏 + 顶栏包裹
│   │   ├── Sidebar.tsx
│   │   └── TopBar.tsx
│   ├── health/
│   │   ├── MetricCard.tsx    # 单指标展示（心率/步数等）
│   │   ├── MetricsChart.tsx  # 时序折线图（Recharts）
│   │   ├── TrainingPlan.tsx   # 训练计划卡片
│   │   ├── StreamProgress.tsx # SSE/WebSocket 流进度
│   │   └── AnomalyAlert.tsx  # 异常提醒徽章
│   ├── chat/
│   │   ├── ChatWindow.tsx    # 对话气泡列表
│   │   ├── ChatInput.tsx     # 文本输入 + 发送
│   │   └── IntentTag.tsx     # 意图分类标签
│   └── ui/
│       ├── Button.tsx
│       ├── Card.tsx
│       ├── Modal.tsx
│       └── Spinner.tsx
├── hooks/
│   ├── useHealthUpload.ts    # 封装上传 + 流式回调
│   ├── useSSE.ts             # MCP SSE 连接管理
│   ├── useWebSocket.ts       # WebSocket 连接管理
│   └── useAuth.ts            # Token 存储 + 刷新
├── stores/
│   ├── authStore.ts          # Zustand: user + token
│   ├── healthStore.ts        # 当前健康数据缓存
│   └── streamStore.ts        # 流式进度状态
├── pages/
│   ├── DashboardPage.tsx
│   ├── UploadPage.tsx
│   ├── ChatPage.tsx
│   └── ProfilePage.tsx
└── api/
    ├── client.ts             # SWR fetch wrapper
    ├── sse.ts                # SSE 事件解析
    └── websocket.ts          # WS 消息发送/接收
```

---

## 6. 实时进度组件设计

### StreamProgress 组件状态机

```
IDLE → CONNECTING → CONNECTED → STREAMING → DONE
                              ↓
                          ERROR → CLOSED
```

**显示元素**：
- 进度条（3 个阶段：指标分析 / 数据解读 / 训练计划）
- 当前阶段高亮文字描述
- 每个阶段耗时
- 最终结果卡片（点击展开详情）

---

## 7. Mock 数据（开发用）

在 `.env` 中设置 `VITE_USE_MOCK_API=true` 时，Dashboard 使用 `src/mocks/handlers.ts` (MSW) 返回假数据，避免依赖后端。

---

## 8. 与后端 MCP 的集成

Dashboard 通过 MCP SSE 连接获取实时数据：

```typescript
// useSSE.ts 示例
function useMCPStream(token: string) {
  const [events, setEvents] = useState<MCPSSEEvent[]>([]);

  useEffect(() => {
    const es = new EventSource(`/mcp/sse?token=${token}`);
    es.addEventListener('metrics_done', (e) => {
      setEvents(prev => [...prev, JSON.parse(e.data)]);
    });
    es.addEventListener('done', (e) => {
      setEvents(prev => [...prev, { type: 'done', data: JSON.parse(e.data) }]);
    });
    return () => es.close();
  }, [token]);

  return events;
}
```

---

## 9. 安全边界

| 检查项 | 要求 |
|--------|------|
| Token 存储 | 仅存内存，刷新后清空；不用 localStorage 存 JWT |
| CORS | 仅允许配置的域名访问 API |
| 敏感操作 | 删除/导出需二次确认（confirm token） |
| 管理员路由 | `/dashboard/admin` 仅 `admin_user_ids` 列表用户可见 |
| HTTPS | 生产必须用 HTTPS，否则 WebSocket 被浏览器阻止 |

---

## 10. 部署架构

```
                    ┌─────────────────┐
                    │   React/Vite    │
                    │  Dashboard UI   │
                    └────────┬────────┘
                             │ HTTPS
                             ▼
                    ┌─────────────────┐
                    │  Nginx (WAF)    │
                    │  /dashboard/*   │  ← 静态文件
                    │  /api/* → API   │
                    │  /mcp/* → MCP   │
                    └────────┬────────┘
                             │
               ┌─────────────┴─────────────┐
               ▼                           ▼
    ┌──────────────────┐       ┌──────────────────┐
    │  rhythmind-api   │       │   Grafana         │
    │  (FastAPI)       │       │  (Prometheus)    │
    └──────────────────┘       └──────────────────┘
```

---

## 11. 推荐开发顺序

1. **AppShell + 路由** — 页面骨架 + 响应式布局
2. **健康概览页** — 静态数据展示（Mock）
3. **数据上传 + StreamProgress** — 接入 `/health/upload/stream` SSE
4. **文本对话页** — 接入 `/health/chat`
5. **认证流** — 登录页 + token 管理
6. **管理员页** — 技能审核（`/api/v1/admin/skills/*`）
7. **可穿戴设备配对** — Phase 3.5 输出后对接

---

## 12. 依赖后端接口清单

| 前端需求 | 后端端点 | 状态 |
|---------|---------|------|
| 健康数据上传（同步） | `POST /api/v1/health/upload` | ✅ 已实现 |
| 健康数据上传（SSE） | `POST /api/v1/health/upload/stream` | ✅ 已实现 |
| 健康数据上传（WS） | `WS /api/v1/health/upload/stream/ws` | ✅ 刚实现 |
| 文本对话 | `POST /api/v1/health/chat` | ✅ 已实现 |
| 用户记忆 | `GET /api/v1/health/memory` | ✅ 已实现（debug 模式） |
| Agent 池状态 | `GET /api/v1/health/pool/stats` | ✅ 已实现（debug 模式） |
| 数据导出 | `GET /api/v1/privacy/export` | ✅ 已实现 |
| 数据删除 | `POST /api/v1/privacy/delete` | ✅ 已实现 |
| 技能列表（admin） | `GET /api/v1/admin/skills/pending` | ✅ 已实现 |
| 技能审批（admin） | `POST /api/v1/admin/skills/:hash/approve` | ✅ 已实现 |
| MCP SSE | `GET /mcp/sse?token=` | ✅ 已实现 |
| MCP 消息 | `POST /mcp/messages/` | ✅ 已实现 |
| 登录 | 无（外部 IdP） | ⚠️ 待设计 |

---

> 本文档为规划文档，实际实现时需根据用户反馈和优先级调整。