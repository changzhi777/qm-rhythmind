# Changelog

All notable changes to **RHYTHMIND 律动** are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 待外部资源

### ⚠️ S3 审计日志桶配置（TBD — 需要 AWS 账号）
- `S3JsonlSink` 防篡改审计日志，需要创建 S3 bucket + Object Lock
- 详见 `docs/RUNBOOK.md` §2.1

### ⚠️ HIPAA/PIPL 法律审查（TBD — 需要法务团队）
- 健康数据保留期限、数据处理协议、用户同意书、通报流程
- 详见 `docs/RUNBOOK.md` §7.3

---

## [0.1.9] — 2026-05-12

### Added — Phase 1/2/3/4 Implementation Sprint

**Phase 1: Production Hardening (continued)**
- InfluxDB `delete_user_data()` for GDPR/PIPL (R-3 closure via `privacy_delete`)
- QMD `purge_user()` for user data deletion
- `docs/RUNBOOK.md` §2.1 PITR 恢复演练 + §10 密钥轮换流程

**Phase 2: Test Coverage**
- `tests/unit/test_loop_guard.py` — 8 scenarios (cooling/reset/redis-fail-open/ttl)
- `tests/unit/test_rate_limit.py` — 6 scenarios (under/over/fail-open/first-call)
- `tests/unit/test_influx_client.py` — 9 scenarios (write/query/delete/trend)
- `tests/unit/test_agent_pool.py` — 9 scenarios (acquire/lru/evict/invalidate/stats)
- `tests/unit/test_audit_sinks.py` — 12 scenarios (record/sink/buffer/rollback)
- `tests/integration/test_admin_skill_approval.py` — 5 new tests (idempotent/pagination/reject-no-qmd)
- `tests/integration/test_privacy_endpoints.py` — 4 new tests (report-structure/stores-clean)

**Phase 3: Streaming + Wearable**
- `WS /api/v1/health/upload/stream/ws` — WebSocket streaming endpoint (JWT query param, SSE-to-WS protocol translation)
- `POST /api/v1/health/ingest` — CSV wearable data ingestion endpoint (Apple Health / Google Health / Fitbit export)
- `docs/DASHBOARD_UI_ARCHITECTURE.md` — React/Vite + Zustand + Recharts design doc
- `docs/WEARABLE_DEVICE_RESEARCH.md` — HealthKit/Health Connect/Fitbit analysis + P0 CSV recommendation

**Phase 4: Observability + Security**
- `rhythmind_loop_guard_calls_total` Prometheus Counter (labels: intent, result=allowed/throttled/error)
- `tests/unit/test_observability.py` — 12 test scenarios for metrics/middleware/noop降级
- `.pre-commit-config.yaml` — detect-secrets + forbid-unsafe-test-files + forbid-debug-print hooks

**Config**
- `settings.agent_pool_max_users` / `agent_pool_ttl` now explicit in config.py

---

## [Unreleased]

### Added — Skill approval workflow (2026-05-10, R-4 closure)
- New `SkillRecord.status` column (`pending` / `approved` / `rejected`); migration `003_skill_status.py`
- `settings.skill_require_approval` (default `False` for backward compat)
- `settings.admin_user_ids` (CSV) + `admin_user_ids_set` property
- New `/api/v1/admin/skills/pending`, `/approve`, `/reject` endpoints with admin role gate
- `SkillEngine.persist_to_qmd` now writes `pending` skills to DB but does NOT push them to QMD until approved
- `AuditEvent.SKILL_APPROVED` / `SKILL_REJECTED` events on every admin action
- 7 new integration tests (`tests/integration/test_admin_skill_approval.py`)
- Closes THREAT_MODEL.md R-4

### Added — Production hardening sweep (2026-05-09)
- **Security**
  - `assert_production_safe()` startup gate rejects default secrets, weak `JWT_SECRET`, and `mlx://` spec on non-Apple platforms
  - `dev_auth_bypass` flag explicitly required (default `false`); ENV=prod forbids it
  - CORS wildcards removed; origins driven by `CORS_ALLOW_ORIGINS` env var
  - Container entrypoint validates secrets before starting uvicorn
  - `docs/SECURITY.md` — coordinated disclosure, threat model, residual risk register
- **Reliability**
  - `/livez` and `/readyz` probes (split from old `/health`); `/readyz` actually pings DB + Redis
  - Optional `RUN_MIGRATIONS_ON_STARTUP=true` runs `alembic upgrade head` from entrypoint
  - Helm chart `migrationJob` runs migrations as a pre-install/pre-upgrade hook
- **Rate limiting**
  - Redis fixed-window limiter, per-user + per-IP, applied to `/health/upload` and `/health/chat`
  - Fail-open if Redis unreachable (matches LoopGuard behavior)
- **Observability**
  - `/metrics` Prometheus endpoint with HTTP / LLM / compliance / pool counters and histograms
  - OpenTelemetry FastAPI instrumentation; OTLP exporter via `OTEL_EXPORTER_OTLP_ENDPOINT`
  - Sentry SDK actually initialized in lifespan (was previously a dangling dependency); `send_default_pii=False`
- **Deployment**
  - Multi-stage non-root Dockerfile (uid 1001) + `HEALTHCHECK` + `.dockerignore`
  - `scripts/docker-entrypoint.sh` runs Alembic + secret guard
  - Helm chart `charts/rhythmind/` — Deployment / Service / HPA / PDB / Ingress / NetworkPolicy / ServiceMonitor / PrometheusRule / dashboard ConfigMap / migration Job
  - Grafana dashboard `rhythmind-overview.json` with HTTP, LLM, compliance, pool panels
  - Prometheus alerting rules covering RUNBOOK §8 thresholds
- **Tests**
  - New `tests/integration/` with full FastAPI ASGI tests (Bearer auth, validation, probes, metrics, rate-limit 429)
  - LLM-path e2e using `pytest-httpx` to mock Ollama (`AdapterRouter` → `OllamaAdapter` → openai SDK)
  - **203 tests passing** (195 unit + 8 integration)
- **Docs**
  - `docs/DEPLOYMENT.md` (local / docker / K8s / Helm)
  - `docs/RUNBOOK.md` (oncall procedures, alert thresholds)
  - `docs/SECURITY.md`
- **CI**
  - New `poetry-lock-check` job validates `poetry.lock` is in sync with `pyproject.toml`

### Changed
- `__version__` is now sourced from `_version.py` only (no more inconsistent literals across `__init__.py` / `main.py` / README)
- `docker-compose.yml` no longer ships hardcoded `JWT_SECRET` / `LITELLM_MASTER_KEY` defaults; uses `${VAR:?...}` to force `.env` provisioning

### Planned
- WebSocket streaming endpoint for real-time agent output
- Dashboard UI (React) connected to MCP
- Wearable device ingest (Apple Health / Garmin Connect)
- HIPAA / PIPL compliance audit + user data export/delete endpoints
- PG backup + PITR drill documented in RUNBOOK §2.1

---

## [0.1.1] — 2025-05-09

### Added
- **Model Adapter Layer** (`src/rhythmind/adapters/`)
  - `ModelAdapter` abstract base class — unified `chat()` / `stream()` / `health_check()` interface
  - `MLXAdapter` — Apple Silicon MLX-LM direct inference; `asyncio.Semaphore(1)` for OOM guard; Qwen3 thinking-mode control (`enable_thinking` + `/no_think` fallback + `<think>` tag stripping); `_MODEL_CACHE` for warm-start
  - `OllamaAdapter` — OpenAI-compat HTTP client to local Ollama; health check via `/api/tags`
  - `LiteLLMAdapter` — wraps existing LiteLLM proxy path
  - `AdapterRouter` — prefix-based dispatch (`mlx://` → MLX, `ollama://` → Ollama, else → LiteLLM); module-level singleton `adapter_router`
- **MCP Server** (`src/rhythmind/mcp/`)
  - `build_mcp_server()` factory with 5 tools: `rhythmind_status`, `rhythmind_search`, `rhythmind_fact_query`, `rhythmind_fact_update`, `rhythmind_session_log`
  - FastAPI SSE router (`GET /mcp/sse` + `POST /mcp/messages/`) integrated into `main.py`
- **Version management**
  - `VERSION` file (`0.1.1`)
  - `src/rhythmind/_version.py` — authoritative version + metadata constants
  - `scripts/bump_version.py` — `major` / `minor` / `patch` bump with regex sync across all three files
  - `.githooks/pre-commit` — auto-bumps patch on every commit; `setup_hooks.sh` for one-command hook activation
- **GitHub Actions CI/CD**
  - `.github/workflows/ci.yml` — pytest + ruff on push/PR to `main` / `develop`; Codecov upload; artifact upload on failure
  - `.github/workflows/release.yml` — test → GitHub Release (notes from CHANGELOG) → optional Docker GHCR push
  - `.github/workflows/auto-fix-issue.yml` — on `bug` label: run tests, create `fix/issue-N-slug` branch, draft PR with diagnostics, post progress comment on Issue
- **GitHub project templates**
  - `.github/ISSUE_TEMPLATE/bug_report.yml` — structured bug report form
  - `.github/ISSUE_TEMPLATE/feature_request.yml` — feature request form
  - `.github/pull_request_template.md` — PR checklist
- **Docs**
  - `LICENSE` — CC BY-NC 4.0; commercial use by written permission
  - `CHANGELOG.md` (this file)
  - `README.md` — quickstart, architecture Mermaid diagrams, API reference
  - `docs/ARCHITECTURE.md` — detailed component breakdown and data-flow diagrams
- **Config additions** (`src/rhythmind/config.py`)
  - `model_primary_spec = "mlx://mlx-community/Qwen3-30B-A3B-4bit"`
  - `model_compliance_spec = "ollama://gemma3:4b"`
  - `mlx_thinking_mode`, `mlx_max_tokens`, `mlx_temperature`, `mlx_semaphore_limit`
  - `ollama_base_url`
- **Tests** — 28 new unit tests (`tests/unit/test_model_adapters.py`); total 156 passing

### Changed
- `HermesBase.call_llm()` — routes through `AdapterRouter` instead of direct `AsyncOpenAI`; `model` param now accepts full `model_spec` (e.g. `"mlx://..."`)
- `PromptAuditor` — refactored to use `_get_adapter()` → `OllamaAdapter`; removed direct `AsyncOpenAI` dependency
- `pyproject.toml` — added `mcp` dependency; author metadata updated

### Fixed
- Module-level imports in `mcp/server.py` — fixed `patch()` target failures in tests caused by lazy in-function imports

---

## [0.1.0] — 2025-04-15

### Added
- **HermesBase** — 6-step Hermes Pattern v2 loop:
  `recall_memory` → `retrieve_skills` → `execute` (call_llm) → `compliance_check` → `extract_skills` → `update_memory`
- **AG2/AutoGen 0.4 Swarm** three-stage pipeline:
  `MetricsAgent` → `DataAgent` → `CoachAgent` via `SwarmDataCoach` orchestrator
- **FactManager** — health knowledge graph backed by SQLite (Alembic migrations)
- **MemoryManager** — session memory with recency decay
- **SkillEngine + SkillExtractor** — LLM-driven skill discovery and reuse
- **PromptAuditor** — LLM-based compliance review with keyword blocklist gate
- **QMDClient** — Quantum-Mechanics-Dynamics stub client
- **InfluxDB client** — time-series metric ingest (`MetricPoint`)
- **FastAPI application** — health endpoint + lifespan management
- **LoopGuard** — infinite-loop detection for agent orchestration
- **Database** — SQLAlchemy async engine; Alembic migrations (initial schema + health_fact table)
- **ARQ** task queue integration for multi-instance concurrency
- **Full test suite** — 128 unit tests across all core modules

---

[Unreleased]: https://github.com/changzhi777/qm-rhythmind/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/changzhi777/qm-rhythmind/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/changzhi777/qm-rhythmind/releases/tag/v0.1.0
