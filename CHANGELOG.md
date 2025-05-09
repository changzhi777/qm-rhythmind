# Changelog

All notable changes to **RHYTHMIND 律动** are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- WebSocket streaming endpoint for real-time agent output
- Dashboard UI (React) connected to MCP
- Wearable device ingest (Apple Health / Garmin Connect)
- Multi-user isolation with JWT-based session management

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

[Unreleased]: https://github.com/iotchange/qm-rhythmind/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/iotchange/qm-rhythmind/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/iotchange/qm-rhythmind/releases/tag/v0.1.0
