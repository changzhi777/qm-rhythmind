#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — 本地发布助手
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
#
# 用法：
#   bash scripts/release.sh patch   # 0.1.1 → 0.1.2
#   bash scripts/release.sh minor   # 0.1.1 → 0.2.0
#   bash scripts/release.sh major   # 0.1.1 → 1.0.0
#
# 流程：
#   1. 运行测试（全绿才继续）
#   2. Bump 版本号（VERSION + _version.py + pyproject.toml）
#   3. 更新 CHANGELOG.md（提示手动填写）
#   4. git commit + tag + push → 触发 release.yml
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}ℹ${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

BUMP_TYPE="${1:-patch}"
[[ "$BUMP_TYPE" =~ ^(major|minor|patch)$ ]] || \
    err "参数必须是 major / minor / patch，当前：$BUMP_TYPE"

OLD_VERSION=$(cat VERSION)
sep
echo -e "${CYAN}🎵 RHYTHMIND 律动 — 发布流程 (${BUMP_TYPE})${NC}"
echo "   当前版本：${OLD_VERSION}"
sep

# ── Step 1: 运行测试 ──────────────────────────────────────────────────────────
echo ""
info "Step 1: 运行单元测试..."
if ! pytest tests/unit/ -q --tb=short 2>&1; then
    err "测试未全绿，中止发布。请修复后重试。"
fi
ok "测试全绿"

# ── Step 2: Bump 版本号 ───────────────────────────────────────────────────────
echo ""
info "Step 2: Bump 版本号 (${BUMP_TYPE})..."
python scripts/bump_version.py "$BUMP_TYPE"
NEW_VERSION=$(cat VERSION)
ok "版本号：${OLD_VERSION} → ${NEW_VERSION}"

# ── Step 3: CHANGELOG 提示 ────────────────────────────────────────────────────
echo ""
warn "Step 3: 请在 CHANGELOG.md 中为 [${NEW_VERSION}] 填写变更记录"
echo "  格式参考："
echo ""
echo "  ## [${NEW_VERSION}] — $(date +%Y-%m-%d)"
echo "  ### Added"
echo "  - ..."
echo "  ### Fixed"
echo "  - ..."
echo ""
read -r -p "  已更新 CHANGELOG.md？按 Enter 继续，Ctrl+C 中止... " _

# ── Step 4: git commit + tag + push ──────────────────────────────────────────
echo ""
info "Step 4: git commit + tag v${NEW_VERSION} + push..."

# 确保 hooks 不再 double-bump（已经 bump 过了）
git add VERSION src/rhythmind/_version.py pyproject.toml CHANGELOG.md
git commit --no-verify -m "chore: release v${NEW_VERSION}

$(grep -A 20 "## \[${NEW_VERSION}\]" CHANGELOG.md | head -20 || echo '版本升级')"

git tag -a "v${NEW_VERSION}" -m "RHYTHMIND 律动 v${NEW_VERSION}"
git push origin main
git push origin "v${NEW_VERSION}"

ok "v${NEW_VERSION} tag 已推送 → 触发 release.yml"

# ── 完成 ──────────────────────────────────────────────────────────────────────
echo ""
sep
echo -e "${GREEN}🎉 发布流程完成！${NC}"
sep
GH_USER=$(gh api user --jq '.login' 2>/dev/null || echo "your-user")
echo ""
echo -e "  ${CYAN}Release：${NC} https://github.com/${GH_USER}/qm-rhythmind/releases/tag/v${NEW_VERSION}"
echo -e "  ${CYAN}Actions：${NC} https://github.com/${GH_USER}/qm-rhythmind/actions"
echo ""
echo -e "${CYAN}🎵 RHYTHMIND 律动 · 外星动物（常智）/ IoTchange${NC}"
sep
