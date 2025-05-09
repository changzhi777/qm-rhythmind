#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — GitHub Secrets 配置脚本
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
#
# 用法：bash scripts/setup_secrets.sh
# 前置：gh auth login 已完成
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
ask()  { echo -e "${CYAN}?${NC} $*"; }

GH_USER=$(gh api user --jq '.login')
REPO="${GH_USER}/qm-rhythmind"

echo -e "${CYAN}━━━ RHYTHMIND GitHub Secrets 配置 ━━━${NC}"
echo ""

# ── CLAUDE_API_KEY ───────────────────────────────────────────────────────────
ask "请输入 Anthropic API Key（sk-ant-...，留空跳过）："
read -r -s CLAUDE_KEY
if [ -n "$CLAUDE_KEY" ]; then
    gh secret set CLAUDE_API_KEY --repo "$REPO" --body "$CLAUDE_KEY"
    ok "CLAUDE_API_KEY 已设置"
else
    echo "  跳过"
fi

echo ""

# ── CODECOV_TOKEN ────────────────────────────────────────────────────────────
ask "请输入 Codecov Token（留空跳过）："
read -r -s CODECOV_KEY
if [ -n "$CODECOV_KEY" ]; then
    gh secret set CODECOV_TOKEN --repo "$REPO" --body "$CODECOV_KEY"
    ok "CODECOV_TOKEN 已设置"
else
    echo "  跳过"
fi

echo ""

# ── Docker（可选）────────────────────────────────────────────────────────────
ask "是否配置 DockerHub（发布 Docker 镜像）？[y/N]："
read -r DOCKER_CONFIRM
if [[ "$DOCKER_CONFIRM" =~ ^[Yy]$ ]]; then
    ask "DockerHub 用户名："
    read -r DH_USER
    ask "DockerHub Access Token："
    read -r -s DH_TOKEN
    gh secret set DOCKERHUB_USERNAME --repo "$REPO" --body "$DH_USER"
    gh secret set DOCKERHUB_TOKEN    --repo "$REPO" --body "$DH_TOKEN"
    ok "DockerHub Secrets 已设置"
fi

echo ""
echo -e "${GREEN}✓ 所有 Secrets 配置完成${NC}"
echo ""

# 列出已设置的 Secrets（名称，不显示值）
echo "当前仓库 Secrets："
gh secret list --repo "$REPO"
