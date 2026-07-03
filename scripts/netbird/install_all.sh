#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# NetBird 一体化部署入口 (腾讯云 106.53.168.73)
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
#
# 顺序执行: deploy_management.sh + deploy_authentik.sh
# 输出 setup key 给客户端用
#
# 用法 (在 106.53.168.73 上):
#   bash install_all.sh
#
# 完成后:
#   1. 浏览器访问 https://qingmulife.cn/ (NetBird Dashboard)
#   2. 用 Authentik 账号登录
#   3. 创建 setup key (Setup Keys → Create)
#   4. 在 CT109 上: bash install_client.sh --setup-key <KEY>
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NETBIRD_DOMAIN="${NETBIRD_DOMAIN:-qingmulife.cn}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}ℹ${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }

[[ $EUID -eq 0 ]] || err "请以 root 身份运行: sudo bash $0"

sep
echo "  NetBird 一体化部署 (CT109 ↔ 腾讯云)"
sep
echo "  域名: $NETBIRD_DOMAIN"
echo ""

# ── 步骤 1: Management 部署 ──
info "[1/3] 部署 NetBird Management + Coturn + Caddy"
bash "$SCRIPT_DIR/deploy_management.sh" || err "Management 部署失败"

echo ""

# ── 步骤 2: Authentik OIDC ──
info "[2/3] 部署 Authentik OIDC + Postgres"
bash "$SCRIPT_DIR/deploy_authentik.sh" || err "Authentik 部署失败"

echo ""

# ── 步骤 3: 等待服务完全启动 ──
info "[3/3] 等待所有服务健康..."

sleep 30

echo ""
sep
echo -e "${GREEN}  ✓ NetBird 一体化部署完成${NC}"
sep
echo ""
echo "  服务状态:"
docker -p netbird compose -f /opt/netbird/artifacts/docker-compose.yml ps 2>/dev/null | head -15

echo ""
echo "  端口监听:"
ss -tlnp 2>/dev/null | grep -E ':80|:443|:3478|:9000' | head -10

echo ""
echo "  关键 URL:"
echo "    NetBird Dashboard: https://$NETBIRD_DOMAIN/"
echo "    Authentik Admin:    https://authentik.$NETBIRD_DOMAIN/if/admin/"
echo ""
echo "  ⚠ 下一步操作(浏览器):"
echo "  1. 访问 https://authentik.$NETBIRD_DOMAIN/if/admin/"
echo "     - 默认用户: akadmin"
echo "     - 首次登录会提示设置密码"
echo ""
echo "  2. 创建 OIDC Provider for NetBird:"
echo "     - Applications → Providers → Create"
echo "       Type: OAuth2/OpenID Connect"
echo "       Name: netbird"
echo "       Client type: Confidential"
echo "       Redirect URI: https://$NETBIRD_DOMAIN/oauth2/callback"
echo "       Scopes: openid, email, profile"
echo "     - Applications → Applications → Create"
echo "       Name: netbird"
echo "       Provider: 上面创建的"
echo ""
echo "  3. 把 Client ID/Secret 写入 /opt/netbird/artifacts/netbird-oidc.env"
echo "     然后: docker compose -f /opt/netbird/artifacts/docker-compose.yml restart management"
echo ""
echo "  4. 创建 Setup Key:"
echo "     docker exec netbird-management netbird-cli setup-key create \\"
echo "         --name 'CT109 Client' --expires 720h --usage-count 5"
echo ""
echo "  5. 在 CT109 上:"
echo "     scp scripts/netbird/install_client.sh root@10.10.10.19:/tmp/"
echo "     ssh root@10.10.10.19 bash /tmp/install_client.sh --setup-key <KEY>"
echo ""
echo "  6. 验证 mesh:"
echo "     bash scripts/netbird/verify_vpn.sh"
sep