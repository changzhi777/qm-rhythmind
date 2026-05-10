# RHYTHMIND 律动

> **Multi-agent AI Health Platform**  
> 作者：外星动物（常智）/ IoTchange · 邮箱：14455975@qq.com  
> 许可：[CC BY-NC 4.0](LICENSE) · 版本：`0.1.5`

[![CI](https://github.com/changzhi777/qm-rhythmind/actions/workflows/ci.yml/badge.svg)](https://github.com/changzhi777/qm-rhythmind/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)

---

## 项目简介

RHYTHMIND 律动 是一个基于多智能体协作的 AI 健康管理平台，本地优先推理（Apple Silicon），生产部署亦支持 K8s + Ollama / LiteLLM。核心特性：

- **三阶段 Swarm 流水线**：指标采集 → 数据分析 → 健康教练，全程多智能体协作
- **Hermes Pattern v2**：标准化 6 步智能体执行循环，内置记忆、技能、合规
- **多形态推理**：MLX（本地 Apple Silicon）+ Ollama（HTTP）+ LiteLLM（云端网关）三路自动路由
- **MCP 接口**：Model Context Protocol SSE 服务，对外暴露健康工具
- **生产就绪运维**：限流（Redis 双层）、Prometheus `/metrics`、OpenTelemetry、`/livez`+`/readyz`、Helm chart、PrometheusRule + Grafana dashboard
- **测试**：195 单元 + 8 集成 = **203 个测试**，GitHub Actions 持续集成

> 完整运维文档见 [DEPLOYMENT.md](docs/DEPLOYMENT.md) · [RUNBOOK.md](docs/RUNBOOK.md) · [SECURITY.md](docs/SECURITY.md) · [THREAT_MODEL.md](docs/THREAT_MODEL.md)
> 生产就绪度评估 + 灰度路径见 [PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md)；非技术摘要见 [EXECUTIVE_SUMMARY.md](docs/EXECUTIVE_SUMMARY.md)
> 贡献者请读 [CONTRIBUTING.md](CONTRIBUTING.md) · Helm chart 见 [charts/rhythmind/](charts/rhythmind/)

---

## 系统架构

### 整体架构

```mermaid
graph TB
    subgraph 外部接入层
        A[REST API<br/>FastAPI] -->|HTTP| B[Agent 路由器]
        C[MCP Client<br/>Claude / IDE] -->|SSE| D[MCP Server<br/>/mcp/sse]
    end

    subgraph 多智能体 Swarm 层
        B --> E[MetricsAgent<br/>指标采集]
        E -->|handoff| F[DataAgent<br/>数据分析]
        F -->|handoff| G[CoachAgent<br/>健康教练]
        D --> E
    end

    subgraph Hermes 核心层
        E & F & G --> H[HermesBase<br/>6 步执行循环]
        H --> I[AdapterRouter<br/>模型路由]
        H --> J[MemoryManager<br/>会话记忆]
        H --> K[SkillEngine<br/>技能复用]
        H --> L[PromptAuditor<br/>合规审查]
        H --> M[FactManager<br/>健康知识图谱]
    end

    subgraph 模型适配层
        I -->|mlx://| N[MLXAdapter<br/>Qwen3-30B-A3B-4bit]
        I -->|ollama://| O[OllamaAdapter<br/>gemma3:4b]
        I -->|其他| P[LiteLLMAdapter<br/>云端备用]
    end

    subgraph 数据层
        J & M --> Q[(SQLite<br/>Alembic)]
        G --> R[(InfluxDB<br/>时序指标)]
    end
```

### Hermes Pattern v2 — 智能体执行循环

```mermaid
sequenceDiagram
    participant U as 用户 / 上游 Agent
    participant H as HermesBase
    participant Mem as MemoryManager
    participant Skill as SkillEngine
    participant LLM as AdapterRouter
    participant Audit as PromptAuditor
    participant Fact as FactManager

    U->>H: run(task)
    H->>Mem: 1. recall_memory(task)
    Mem-->>H: 历史上下文
    H->>Skill: 2. retrieve_skills(task)
    Skill-->>H: 可复用技能
    H->>LLM: 3. call_llm(messages)
    LLM-->>H: 原始回复
    H->>Audit: 4. compliance_check(reply)
    Audit-->>H: 审查结果
    H->>Skill: 5. extract_skills(reply)
    Skill-->>H: 新技能已存储
    H->>Mem: 6. update_memory(result)
    H->>Fact: update_facts(result)
    H-->>U: 最终结果
```

### 模型适配路由

```mermaid
flowchart LR
    spec["model_spec 字符串"]
    spec -->|"mlx://..."| mlx["MLXAdapter<br/>asyncio.to_thread(generate)<br/>Semaphore(1) OOM 防护"]
    spec -->|"ollama://..."| ollama["OllamaAdapter<br/>OpenAI-compat HTTP<br/>health: /api/tags"]
    spec -->|其他| litellm["LiteLLMAdapter<br/>LiteLLM Proxy"]
    mlx & ollama & litellm --> out["统一 chat() 返回 str"]
```

### 自动化 Bug 修复流程

```mermaid
flowchart TD
    A[Issue 提交] -->|打上 bug 标签| B[auto-fix-issue.yml 触发]
    B --> C[检出代码 + 安装依赖]
    C --> D[pytest tests/unit/ 定位失败点]
    D --> E[创建修复分支<br/>fix/issue-N-slug]
    E --> F[草稿 PR + 诊断报告]
    F --> G[Issue 回复进度]
    G --> H[开发者在分支上修复]
    H --> I[PR 改为 Ready for Review]
    I --> J[CI 验证 + 合并]
```

---

## 快速开始

### 环境要求

| 组件 | 版本 |
|------|------|
| Python | 3.12+ |
| macOS | 15+ (Apple Silicon M 系列) |
| Ollama | 最新版 |
| InfluxDB | 2.x（可选）|

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/changzhi777/qm-rhythmind.git
cd qm-rhythmind

# 2. 安装依赖
pip install -e ".[dev]"

# 3. 启用 Git 钩子（自动版本升级）
bash setup_hooks.sh

# 4. 拉取本地模型
ollama pull gemma3:4b

# 5. 下载 MLX 模型（约 6GB，需 Apple Silicon）
python -c "from mlx_lm import load; load('mlx-community/Qwen3-30B-A3B-4bit')"
```

### 配置

复制 `.env.example` 并按需修改：

```bash
cp .env.example .env
```

关键配置项：

```env
# 主推理模型（Apple Silicon MLX）
MODEL_PRIMARY_SPEC=mlx://mlx-community/Qwen3-30B-A3B-4bit

# 合规审查模型（Ollama 本地）
MODEL_COMPLIANCE_SPEC=ollama://gemma3:4b

# 数据库
DATABASE_URL=sqlite+aiosqlite:///./rhythmind.db

# InfluxDB（可选）
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=your-token
INFLUXDB_ORG=rhythmind
INFLUXDB_BUCKET=health
```

### 启动服务

```bash
# 开发模式（热重载）
uvicorn rhythmind.api.main:app --reload --port 8000

# 生产模式
uvicorn rhythmind.api.main:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## 生产部署

完整步骤见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。最简 K8s 流程：

```bash
# 1. 准备 Secret（JWT_SECRET ≥32 字符，且不在默认黑名单）
kubectl create namespace rhythmind
kubectl -n rhythmind create secret generic rhythmind-secrets \
    --from-literal=JWT_SECRET=$(openssl rand -hex 32) \
    --from-literal=LITELLM_MASTER_KEY=$(openssl rand -hex 16) \
    --from-literal=DATABASE_URL=postgresql+asyncpg://USER:PWD@HOST:5432/rhythmind \
    --from-literal=INFLUXDB_TOKEN=$(openssl rand -hex 24)

# 2. 部署 Helm chart
helm upgrade --install rhythmind ./charts/rhythmind -n rhythmind \
    --set image.tag=0.1.5 \
    --set env=prod \
    --set corsAllowOrigins=https://app.rhythmind.ai \
    --set serviceMonitor.enabled=true \
    --set prometheusRule.enabled=true \
    --set grafanaDashboard.enabled=true

# 3. 验证
kubectl -n rhythmind port-forward svc/rhythmind 8000:80
curl http://localhost:8000/readyz   # 应返回 {"status":"ready", "checks": {"db":"ok","redis":"ok"}}
curl http://localhost:8000/metrics  # Prometheus 指标
```

---

## API 接口

### 健康检查

| 端点 | 用途 |
|---|---|
| `GET /livez` | K8s livenessProbe（仅检查进程存活） |
| `GET /readyz` | K8s readinessProbe（含 DB/Redis 检查） |
| `GET /metrics` | Prometheus 暴露端点 |
| `GET /health` | 兼容旧 LB（=`/livez`） |

```http
GET /readyz
```

### MCP 接口（Model Context Protocol）

```http
GET  /mcp/sse          # SSE 连接
POST /mcp/messages/    # 消息处理
```

MCP 工具列表：

| 工具名 | 描述 |
|--------|------|
| `rhythmind_status` | 平台状态查询 |
| `rhythmind_search` | 健康知识搜索 |
| `rhythmind_fact_query` | 健康事实查询 |
| `rhythmind_fact_update` | 健康事实更新 |
| `rhythmind_session_log` | 会话日志查询 |

在 Claude Desktop 中使用 MCP：

```json
{
  "mcpServers": {
    "rhythmind": {
      "url": "http://localhost:8000/mcp/sse"
    }
  }
}
```

---

## 项目结构

```
qm-rhythmind/
├── src/rhythmind/
│   ├── adapters/           # 模型适配层
│   │   ├── model_adapter.py    # ABC 基类
│   │   ├── mlx_adapter.py      # Apple MLX 推理
│   │   ├── ollama_adapter.py   # Ollama HTTP 客户端
│   │   ├── litellm_adapter.py  # LiteLLM 代理
│   │   └── adapter_router.py   # 前缀路由 + 单例
│   ├── agents/             # AG2 Swarm 智能体
│   │   ├── metrics_agent.py    # 指标采集
│   │   ├── data_agent.py       # 数据分析
│   │   └── coach_agent.py      # 健康教练
│   ├── core/               # Hermes 核心
│   │   ├── hermes_base.py      # 6 步执行循环
│   │   ├── memory/             # 记忆管理
│   │   ├── skill/              # 技能引擎
│   │   ├── compliance/         # 合规审查
│   │   └── qmd/                # QMD 客户端
│   ├── mcp/                # MCP 服务
│   │   ├── server.py           # 工具注册
│   │   └── router.py           # SSE 路由
│   ├── orchestrator/       # 流水线编排
│   │   ├── router.py           # 任务路由
│   │   ├── loop_guard.py       # 循环防护
│   │   └── workflows/          # Swarm 工作流
│   ├── api/                # FastAPI 层
│   ├── db/                 # 数据库 + 迁移
│   └── config.py           # 全局配置
├── tests/unit/             # 156 个单元测试
├── scripts/                # 工具脚本
│   └── bump_version.py         # 版本管理
├── .github/
│   ├── workflows/          # CI/CD
│   └── ISSUE_TEMPLATE/     # Issue 模板
├── docs/
│   └── ARCHITECTURE.md     # 详细架构文档
├── VERSION                 # 版本号（单一来源）
├── CHANGELOG.md
└── pyproject.toml
```

---

## 开发指南

### 运行测试

```bash
# 全量单元测试
pytest tests/unit/ -q

# 覆盖率报告
pytest tests/unit/ --cov=rhythmind --cov-report=html

# 代码风格检查
ruff check src/ tests/
```

### 版本管理

```bash
# 手动升级版本
python scripts/bump_version.py patch   # 0.1.1 → 0.1.2
python scripts/bump_version.py minor   # 0.1.1 → 0.2.0
python scripts/bump_version.py major   # 0.1.1 → 1.0.0

# Git 提交时自动升级 patch（通过 pre-commit 钩子）
git commit -m "feat: ..."
```

### 发布新版本

```bash
# 推送 tag 触发 release.yml
git tag v0.1.2
git push origin v0.1.2
```

---

## 许可协议

本项目采用 [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](LICENSE) 许可。

- ✅ 允许：学习、研究、非商业项目使用与修改
- ❌ 禁止：商业用途（需获得书面授权）

商业合作请联系：14455975@qq.com

---

## 作者

**外星动物（常智）/ IoTchange**  
湖南青沐生命科技有限公司 · CTO  
邮箱：14455975@qq.com | changzhi777@gmail.com

---

_RHYTHMIND 律动 · Copyright 2024-2025 外星动物（常智）/ IoTchange_
