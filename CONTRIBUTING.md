# Contributing to RHYTHMIND 律动

> 本项目为 CC BY-NC 4.0 许可的非商业开源项目。商业用途请联系 14455975@qq.com。
> 任何 PR 视为同意以相同许可贡献。

谢谢愿意为 RHYTHMIND 出力。本指南覆盖：开发环境、代码规范、PR 流程、
安全 / 合规要求。先读一遍 [SECURITY.md](docs/SECURITY.md) 与
[THREAT_MODEL.md](docs/THREAT_MODEL.md)，再开始动手。

---

## 1. 开发环境

```bash
# 1) Python 3.12（项目硬要求；3.10/3.11 跑不起来）
python3.12 --version

# 2) Poetry
pipx install poetry==1.8.3

# 3) 装依赖（含 dev 组）
poetry install --without cv

# 4) 装 git hooks（pre-commit + 自动版本 bump）
bash setup_hooks.sh

# 5) 跑测试确认环境 OK
poetry run pytest tests/ -q
# 应看到 208 passed
```

**poetry.lock 是必须文件**——任何修改 `pyproject.toml` 依赖的 PR 都要同步重跑：

```bash
bash scripts/bootstrap_lock.sh
git add poetry.lock
```

CI 的 `poetry-lock-check` job 会强制校验。

---

## 2. 代码规范

### 2.1 工具

| 工具 | 用途 | 触发 |
|---|---|---|
| `ruff check` | lint（含 import 排序、未用导入、bug-bear） | pre-commit + CI |
| `ruff format` | 格式化（black 兼容） | pre-commit |
| `mypy --strict` | 类型检查 | 鼓励但 CI 暂不强制（计划中） |
| `pytest` | 单元 + 集成测试 | CI 必过 |

### 2.2 风格约定

- **类型注解**：所有公开函数、Pydantic model、dataclass 必须带；测试函数可选
- **async/await**：核心路径全 async；不要在 async 函数内 sync I/O
- **错误处理**：业务错误用 `HTTPException`；适配器/外部 IO 异常向上抛，由 endpoint 边界统一处理
- **日志**：用 `structlog`；事件名小写下划线（`hermes.run start`），永远不要把请求体或健康指标原始值写日志
- **导入顺序**：标准库 → 三方 → `rhythmind.*`；`from __future__ import annotations` 永远在第一行
- **命名**：类 `CamelCase`，函数 `snake_case`，常量 `UPPER_SNAKE`，私有以 `_` 起；中文注释完全 OK，但函数名 / 变量名一律英文

### 2.3 不做的事

- 不要直接拼 SQL；走 SQLAlchemy ORM
- 不要在生产路径上调用 `print` / `logging.info` 时打 user 原始数据；改用 structlog 的结构字段（自动脱敏更容易加）
- 不要在 dependency injector 之外 new `MetricsAgent` / `DataAgent` / `CoachAgent`，请通过 `AgentPool.acquire(user_id)`
- 不要把 secret 默认值写进代码（`assert_production_safe()` 会拒启）

---

## 3. PR 流程

1. **从 `develop` 分支拉分支**：`feature/<topic>` 或 `fix/<issue-id>-<slug>`
2. **commit message** 用 [Conventional Commits](https://www.conventionalcommits.org/)：
   ```
   feat(api): add /privacy/export endpoint
   fix(adapters): handle ollama 5xx retries correctly
   docs(runbook): document PG PITR drill steps
   ```
   pre-commit hook 会基于 `feat/fix/perf` 自动 bump version；纯 `docs/chore` 不 bump。
3. **PR 标题**与 commit 主行一致；描述包含：
   - 变更动机（issue 链接 / 用户故事）
   - 关键设计决策
   - 测试覆盖（哪些用例新加 / 修改）
   - 是否影响安全模型（如是，附 STRIDE 简评）
4. **CI 必须全绿**：unit tests / integration tests / `helm lint` / `poetry-lock-check`
5. **代码评审**至少 1 人 LGTM；触碰下列敏感区域必须额外 +1 安全评审：
   - `src/rhythmind/api/deps.py`（鉴权）
   - `src/rhythmind/config.py` 的 `assert_production_safe()`
   - `src/rhythmind/privacy/`
   - `src/rhythmind/api/rate_limit.py`
   - 任何新加的 `/api/v1/*` 路由
6. **Squash & Merge** 进 `develop`；release 由维护者按节奏 cut 到 `main`

---

## 4. 安全 / 合规要求

发新功能前问自己（也写到 PR 描述里）：

- [ ] 新接口走 `CurrentUserId` 强制鉴权了吗？
- [ ] 新存储字段含个人信息吗？如果是：是否被 `PrivacyService.export_user_data` / `delete_user_data` 覆盖？
- [ ] 新增了向第三方的出站调用吗？（数据出境 → 在 SECURITY.md / 用户协议同步）
- [ ] 新依赖是否经过 `pip-audit`？
- [ ] 新 LLM prompt 模板：是否加了 system 与 user 输入的隔离？是否被 `ComplianceGate` 覆盖？
- [ ] 改密钥 / Secret 处理：是否同步更新了 `_SECRET_DEFAULTS_BLOCKLIST` 与 `assert_production_safe()`？

发现安全漏洞**不要**开公开 issue —— 走 [SECURITY.md §1](docs/SECURITY.md#1-漏洞披露coordinated-disclosure) 私下渠道。

---

## 5. 测试要求

- **新功能 = 新测试**。无单测的 PR 一般不被合并
- **单元测试** 在 `tests/unit/`；外部依赖（Redis / Influx / QMD / LLM）一律 mock
- **集成测试** 在 `tests/integration/`；用真实 ASGI 栈 + fakeredis + dependency_overrides；外部 LLM HTTP 用 `pytest-httpx` 拦截
- **触碰鉴权 / 输入校验** 的 PR 必须有"否定测试"（401 / 422 / 越权拒绝）
- 不要因为"暂时跑不过"就关掉测试；改成 `pytest.mark.skip(reason="...")` 并附 issue 链接

---

## 6. 文档

- 增 / 改用户可见行为 → 同步更新 [README.md](README.md) 的"快速开始"或"API 接口"段
- 改运维行为 → 更新 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) 与 [docs/RUNBOOK.md](docs/RUNBOOK.md)
- 改架构 → 更新 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 与 [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md)
- 任何破坏性变更 → 写进 [CHANGELOG.md](CHANGELOG.md) 的 `Unreleased > Changed`

---

## 7. Issue 与 RFC

- **Bug 报告**：用 `.github/ISSUE_TEMPLATE/bug.md`，含复现步骤、预期/实际结果、版本号
- **新功能**：先开 issue 讨论；体量大的（>500 行）建议先发 RFC（一份 markdown）
- 微小修改（typo / 单测补充）可以直接 PR，不必先开 issue

---

## 8. 日常命令速查

```bash
# 测试 + 覆盖率
poetry run pytest tests/ -q
poetry run pytest tests/unit/ --cov=src/rhythmind --cov-report=term-missing

# Lint / 格式化
poetry run ruff check src/ tests/
poetry run ruff format src/ tests/

# 跑 API（开发模式）
poetry run uvicorn rhythmind.api.main:app --reload --port 8000

# Helm 渲染（需要本地装 helm）
helm lint charts/rhythmind
helm template rhythmind charts/rhythmind --debug | less

# Locust 压测（仅 staging）
locust -f tests/load/locustfile.py --host $RHYTHMIND_BASE
```

---

谢谢贡献。任何疑问联系 14455975@qq.com。
