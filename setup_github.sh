#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — GitHub 仓库一键配置脚本
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
#
# 前置条件：
#   1. 安装 GitHub CLI：brew install gh
#   2. 登录：gh auth login
#   3. 在项目根目录运行：bash setup_github.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")"

# ──────────────────────────────────────────────────────────────────────────────
# 颜色输出
# ──────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${BLUE}ℹ${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

sep
echo -e "${CYAN}🎵 RHYTHMIND 律动 — GitHub 仓库配置${NC}"
sep

# ──────────────────────────────────────────────────────────────────────────────
# Step 0: 检查依赖
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 0: 检查依赖..."

command -v git >/dev/null || err "git 未安装，请先安装 git"
command -v gh  >/dev/null || err "GitHub CLI 未安装。运行：brew install gh  然后重试"

GH_AUTH=$(gh auth status 2>&1 || true)
if echo "$GH_AUTH" | grep -q "not logged"; then
    err "未登录 GitHub CLI，请先运行：gh auth login"
fi
ok "git $(git --version | awk '{print $3}')"
ok "gh $(gh --version | head -1 | awk '{print $3}')"

GH_USER=$(gh api user --jq '.login')
ok "GitHub 用户：${GH_USER}"

# ──────────────────────────────────────────────────────────────────────────────
# Step 1: 配置 git 本地用户
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 1: 配置 git 用户..."
git config user.name  "外星动物（常智）/ IoTchange"
git config user.email "14455975@qq.com"
git branch -M main 2>/dev/null || true
ok "git 用户已配置"

# ──────────────────────────────────────────────────────────────────────────────
# Step 2: 初始 git commit
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 2: 初始 git commit..."

# 清理 sandbox 遗留 lock
rm -f .git/index.lock && ok "清理 index.lock" || true

# 激活 git hooks（如果还未激活）
if [ -f setup_hooks.sh ]; then
    bash setup_hooks.sh 2>/dev/null || true
fi

# 重新 add 确保所有文件在暂存区
git add .

COMMIT_COUNT=$(git rev-list --count HEAD 2>/dev/null || echo "0")
if [ "$COMMIT_COUNT" -gt "0" ]; then
    warn "仓库已有提交，跳过初始 commit"
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

# ──────────────────────────────────────────────────────────────────────────────
# Step 3: 创建 GitHub 仓库
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 3: 创建 GitHub 仓库..."

REPO_NAME="qm-rhythmind"
REPO_EXISTS=$(gh repo view "${GH_USER}/${REPO_NAME}" --json name --jq '.name' 2>/dev/null || echo "")

if [ -n "$REPO_EXISTS" ]; then
    warn "仓库 ${GH_USER}/${REPO_NAME} 已存在，跳过创建"
else
    gh repo create "${REPO_NAME}" \
        --private \
        --description "🎵 RHYTHMIND 律动 — Multi-agent AI Health Platform | 多智能体 AI 健康平台" \
        --source=. \
        --remote=origin \
        --push
    ok "GitHub 仓库已创建：https://github.com/${GH_USER}/${REPO_NAME}"
fi

# 确保 remote origin 已配置
if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "https://github.com/${GH_USER}/${REPO_NAME}.git"
    ok "remote origin 已添加"
fi

# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Push + 版本 Tag
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 4: Push 代码 + 创建 v0.1.1 tag..."

git push -u origin main 2>/dev/null || warn "push 已是最新，无需推送"

# 创建 v0.1.1 tag（如果不存在）
if git rev-parse "v0.1.1" >/dev/null 2>&1; then
    warn "tag v0.1.1 已存在，跳过"
else
    git tag -a "v0.1.1" -m "RHYTHMIND 律动 v0.1.1 — 首个完整发布版本"
    git push origin "v0.1.1"
    ok "tag v0.1.1 已推送"
fi

# ──────────────────────────────────────────────────────────────────────────────
# Step 5: 仓库元数据（Topics）
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 5: 配置仓库 Topics..."

gh repo edit "${GH_USER}/${REPO_NAME}" \
    --add-topic "multi-agent" \
    --add-topic "health-ai" \
    --add-topic "mlx" \
    --add-topic "ag2" \
    --add-topic "hermes-pattern" \
    --add-topic "mcp" \
    --add-topic "python" \
    --add-topic "apple-silicon" \
    2>/dev/null && ok "Topics 已配置" || warn "Topics 配置失败（可忽略）"

# ──────────────────────────────────────────────────────────────────────────────
# Step 6: 分支保护规则（main）
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 6: 配置 main 分支保护..."

gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/${GH_USER}/${REPO_NAME}/branches/main/protection" \
    -f required_status_checks='{"strict":true,"contexts":["test (3.12)"]}' \
    -f enforce_admins=false \
    -f required_pull_request_reviews='{"required_approving_review_count":1,"dismiss_stale_reviews":true}' \
    -f restrictions=null \
    2>/dev/null && ok "main 分支保护已启用" || warn "分支保护配置需要 Pro/Team 账户，已跳过"

# ──────────────────────────────────────────────────────────────────────────────
# Step 7: 配置 GitHub Actions Secrets 提示
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 7: GitHub Actions Secrets..."
echo ""
echo -e "  ${YELLOW}以下 Secret 需要手动配置（在仓库 Settings → Secrets → Actions）：${NC}"
echo ""
echo -e "  ${CYAN}必须：${NC}"
echo "    CLAUDE_API_KEY   — Anthropic API Key（用于 auto-fix-issue AI 辅助分析）"
echo ""
echo -e "  ${CYAN}可选（发布 Docker 镜像时需要）：${NC}"
echo "    DOCKERHUB_USERNAME"
echo "    DOCKERHUB_TOKEN"
echo "    CODECOV_TOKEN    — 覆盖率上报到 codecov.io"
echo ""
echo -e "  ${CYAN}快速配置命令：${NC}"
echo "    gh secret set CLAUDE_API_KEY --body 'sk-ant-...'"
echo "    gh secret set CODECOV_TOKEN  --body 'your-token'"
echo ""

# ──────────────────────────────────────────────────────────────────────────────
# Step 7b: 导入 Issue Labels
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 7b: 导入 Issue Labels..."

if [ -f ".github/labels.yml" ] && command -v python3 >/dev/null; then
    python3 - <<PYEOF
import subprocess, sys
try:
    import yaml
except ImportError:
    subprocess.run(["pip3", "install", "pyyaml", "-q"])
    import yaml

import os
with open(".github/labels.yml") as f:
    labels = yaml.safe_load(f)

repo = os.popen("gh api user --jq '.login'").read().strip() + "/qm-rhythmind"
for lbl in labels:
    name  = lbl["name"]
    color = lbl.get("color", "ededed")
    desc  = lbl.get("description", "")
    r = subprocess.run(
        ["gh", "label", "create", name,
         "--color", color, "--description", desc,
         "--repo", repo, "--force"],
        capture_output=True, text=True
    )
    mark = "✓" if r.returncode == 0 else "~"
    print(f"  {mark} {name}")
PYEOF
    ok "Labels 导入完成"
else
    warn "跳过 Labels 导入（缺少 .github/labels.yml 或 python3）"
fi

# ──────────────────────────────────────────────────────────────────────────────
# Step 8: 创建 develop 分支
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 8: 创建 develop 分支..."

if git ls-remote --heads origin develop | grep -q develop; then
    warn "develop 分支已存在，跳过"
else
    git checkout -b develop
    git push -u origin develop
    git checkout main
    ok "develop 分支已创建并推送"
fi

# ──────────────────────────────────────────────────────────────────────────────
# Step 9: 触发首次 CI
# ──────────────────────────────────────────────────────────────────────────────
echo ""
info "Step 9: 检查 CI 状态..."
sleep 3
gh run list --repo "${GH_USER}/${REPO_NAME}" --limit 3 2>/dev/null || true

# ──────────────────────────────────────────────────────────────────────────────
# 完成
# ──────────────────────────────────────────────────────────────────────────────
echo ""
sep
echo -e "${GREEN}🎉 GitHub 仓库配置完成！${NC}"
sep
echo ""
echo -e "  ${CYAN}仓库地址：${NC}  https://github.com/${GH_USER}/${REPO_NAME}"
echo -e "  ${CYAN}Actions：${NC}   https://github.com/${GH_USER}/${REPO_NAME}/actions"
echo -e "  ${CYAN}Issues：${NC}    https://github.com/${GH_USER}/${REPO_NAME}/issues"
echo -e "  ${CYAN}Releases：${NC}  https://github.com/${GH_USER}/${REPO_NAME}/releases"
echo ""
echo -e "  ${YELLOW}后续操作：${NC}"
echo "    1. 设置 Secrets（见 Step 7 提示）"
echo "    2. 在 Issue 中打 'bug' 标签测试自动修复流程"
echo "    3. 发布新版本：git tag v0.1.2 && git push origin v0.1.2"
echo ""
echo -e "${CYAN}🎵 RHYTHMIND 律动 · 作者：外星动物（常智）/ IoTchange${NC}"
sep
