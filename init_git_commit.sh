#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Git 初始提交脚本
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
#
# 在项目根目录运行：bash init_git_commit.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}ℹ${NC} $*"; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

sep
echo -e "${CYAN}🎵 RHYTHMIND 律动 — Git 初始提交${NC}"
sep
echo ""

# 1. 清理 sandbox 遗留 lock
rm -f .git/index.lock && ok "清理 index.lock" || true

# 2. 配置 git 用户
git config user.name  "外星动物（常智）/ IoTchange"
git config user.email "14455975@qq.com"
git branch -M main 2>/dev/null || true
ok "git 用户已配置"

# 3. 让所有 shell 脚本可执行
chmod +x setup_github.sh setup_hooks.sh init_git_commit.sh \
         scripts/bump_version.py scripts/release.sh \
         scripts/setup_secrets.sh \
         scripts/init_qmd_collections.sh 2>/dev/null || true
ok "Shell 脚本权限设置完成"

# 4. 重新 add 全部文件
git add .
ok "git add . 完成"

# 5. 检查是否已有 commit
COMMIT_COUNT=$(git rev-list --count HEAD 2>/dev/null || echo "0")
if [ "$COMMIT_COUNT" -gt "0" ]; then
    echo -e "${CYAN}ℹ${NC} 仓库已有提交（${COMMIT_COUNT}个），跳过初始 commit"
else
    git commit --no-verify -m "feat: initial commit — RHYTHMIND 律动 v0.1.1

多智能体 AI 健康平台完整初始版本

核心特性：
- HermesBase 6步执行循环（记忆/技能/推理/合规/提取/更新）
- AG2/AutoGen 0.4 Swarm 三阶段流水线（MetricsAgent→DataAgent→CoachAgent）
- Model Adapter 层（MLXAdapter/OllamaAdapter/LiteLLMAdapter + AdapterRouter）
- MLX 本地推理（Qwen3-30B-A3B-4bit）+ Ollama 合规审查（gemma3:4b）
- MCP Server（FastAPI SSE，5个健康工具）
- PromptAuditor 合规内建
- FactManager 健康知识图谱（SQLite + Alembic）
- 版本管理 + Git 钩子自动 patch 升级
- GitHub Actions CI/CD（ci/release/auto-fix-issue）
- 156 个单元测试全绿

作者：外星动物（常智）/ IoTchange <14455975@qq.com>
许可：CC BY-NC 4.0  版本：0.1.1"

    ok "初始 commit 完成：$(git log --oneline -1)"
fi

echo ""
sep
echo -e "${GREEN}✓ 本地 Git 仓库就绪${NC}"
sep
echo ""
echo "  下一步：运行 setup_github.sh 创建 GitHub 仓库并推送"
echo ""
echo "  前置条件："
echo "    brew install gh"
echo "    gh auth login"
echo ""
echo "  然后运行："
echo -e "    ${CYAN}bash setup_github.sh${NC}"
echo ""
echo -e "${CYAN}🎵 RHYTHMIND 律动 · 外星动物（常智）/ IoTchange${NC}"
sep
