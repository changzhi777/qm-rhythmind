#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# NetBird Management 一键部署 (腾讯云 106.53.168.73)
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
#
# 部署: management + signal + relay + coturn + caddy
# 前提: 域名 qingmulife.cn 已解析到 106.53.168.73
# 端口: TCP 80/443, UDP 3478 + 49152-65535
#
# 用法 (在 106.53.168.73 上以 root 身份):
#   bash deploy_management.sh
#
# 验证:
#   curl -I https://qingmulife.cn/
#   docker compose -p netbird ps
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── 路径与配置 ──
INSTALL_DIR="/opt/netbird"
DATA_DIR="/var/lib/netbird"
NETBIRD_DOMAIN="${NETBIRD_DOMAIN:-qingmulife.cn}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-admin@qingmulife.cn}"
NETBIRD_VERSION="${NETBIRD_VERSION:-0.29.1}"
NETBIRD_IMAGE="${NETBIRD_IMAGE:-netbirdio/netbird:${NETBIRD_VERSION}}"
COTURN_IMAGE="${COTURN_IMAGE:-coturn/coturn:4.6}"
CADDY_IMAGE="${COTURN_IMAGE:-caddy:2.7}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}ℹ${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# ── 0. 权限检查 ──
[[ $EUID -eq 0 ]] || err "请以 root 身份运行: sudo bash $0"

sep
echo "  NetBird Management 部署"
sep
echo "  域名: $NETBIRD_DOMAIN"
echo "  数据: $DATA_DIR"
echo "  镜像: $NETBIRD_IMAGE"
echo ""

# ── 1. 安装 Docker ──
info "[1/6] 安装 Docker + Compose"

if command -v docker &> /dev/null; then
  ok "Docker 已安装: $(docker --version)"
else
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
  ok "Docker 已安装: $(docker --version)"
fi

# Docker Compose (plugin 或独立 binary)
if docker compose version &> /dev/null; then
  ok "Compose Plugin 已安装: $(docker compose version --short)"
elif command -v docker-compose &> /dev/null; then
  ok "Compose v1 已安装: $(docker-compose --version)"
else
  err "未找到 Docker Compose,请安装 docker-compose-plugin"
fi

echo ""

# ── 2. 创建目录结构 ──
info "[2/6] 创建项目目录"

mkdir -p "$INSTALL_DIR/artifacts" "$DATA_DIR/management" "$DATA_DIR/coturn" "$DATA_DIR/caddy"
cd "$INSTALL_DIR"

ok "目录创建: $INSTALL_DIR"
echo ""

# ── 3. 生成 docker-compose.yml ──
info "[3/6] 生成 docker-compose.yml"

cat > "$INSTALL_DIR/artifacts/docker-compose.yml" << COMPOSE_EOF
# NetBird Management + Signal + Relay + Coturn + Caddy
# 由 deploy_management.sh 自动生成 (2026-07-03)

services:
  # NetBird Management (主服务)
  management:
    image: $NETBIRD_IMAGE
    container_name: netbird-management
    restart: unless-stopped
    volumes:
      - $DATA_DIR/management:/var/lib/netbird
    healthcheck:
      test: ["CMD", "/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5
    environment:
      - NETBIRD_MGMT_DOMAIN=$NETBIRD_DOMAIN
      - NETBIRD_MGMT_HTTP_PORT=80
      - NETBIRD_MGMT_TLS=true
      - NETBIRD_MGMT_SINGLE_ACCOUNT_MODE_DOMAIN=netbird.qingmulife.cn
      - NETBIRD_MGMT_DISABLE_LETSENCRYPT=true  # 由 Caddy 统一管证书
      - NETBIRD_LOG_LEVEL=info
    networks:
      - netbird

  # NetBird Signal (ICE 候选交换)
  signal:
    image: $NETBIRD_IMAGE
    container_name: netbird-signal
    restart: unless-stopped
    command: ["signal", "--port=80", "--log-level=info"]
    healthcheck:
      test: ["CMD", "/healthz"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - netbird

  # NetBird Relay (中继回落)
  relay:
    image: $NETBIRD_IMAGE
    container_name: netbird-relay
    restart: unless-stopped
    command: ["relay", "--port=80", "--log-level=info", "--tls-domain=$NETBIRD_DOMAIN"]
    networks:
      - netbird

  # Coturn (STUN/TURN)
  coturn:
    image: $COTURN_IMAGE
    container_name: netbird-coturn
    restart: unless-stopped
    network_mode: host
    command: >
      -n
      --log-file=stdout
      --realm=netbird
      --fingerprint
      --no-tls
      --no-dtls
      --listening-port=3478
      --min-port=49152
      --max-port=65535
      --external-ip=106.53.168.73
      --user=netbird:netbird
    healthcheck:
      test: ["CMD-SHELL", "nc -z 127.0.0.1 3478 || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3

  # Caddy (反代 + Let's Encrypt)
  caddy:
    image: caddy:2.7
    container_name: netbird-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - netbird

networks:
  netbird:
    driver: bridge

volumes:
  caddy_data:
  caddy_config:
COMPOSE_EOF

ok "已生成 docker-compose.yml"
echo ""

# ── 4. 生成 Caddyfile ──
info "[4/6] 生成 Caddyfile"

cat > "$INSTALL_DIR/artifacts/Caddyfile" << CADDY_EOF
# NetBird Caddy 反代 + 自动 Let's Encrypt
# 由 deploy_management.sh 自动生成

# ── Dashboard + Management (单端口 443 合并) ──
$NETBIRD_DOMAIN {
    reverse_proxy management:80
}

# Authentik (子域)
authentik.$NETBIRD_DOMAIN {
    reverse_proxy authentik-server:9000
}

# 保留 NetBird Dashboard API 路径
api.$NETBIRD_DOMAIN {
    reverse_proxy management:80
}
CADDY_EOF

ok "已生成 Caddyfile"
echo ""

# ── 5. 启动服务 ──
info "[5/6] 启动 NetBird 服务"

cd "$INSTALL_DIR/artifacts"

docker compose pull 2>&1 | tail -3 || warn "拉镜像失败,使用现有镜像"

docker compose up -d 2>&1 | tail -10

# 等待 management 健康
info "等待 management 健康 (30s)..."
for i in {1..30}; do
  if docker compose exec -T management /healthz 2>/dev/null; then
    ok "Management 已健康"
    break
  fi
  sleep 2
  echo -n "."
done
echo ""

# ── 6. 验证 ──
info "[6/6] 验证服务"

sleep 5

echo "  容器状态:"
docker compose ps 2>&1 | head -20

echo ""
echo "  端口监听:"
ss -tlnp 2>/dev/null | grep -E ':80|:443|:3478' | head -10 | sed 's/^/    /'

echo ""
echo "  HTTPS 测试:"
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 https://$NETBIRD_DOMAIN/ 2>&1 || echo "FAIL")
echo "    https://$NETBIRD_DOMAIN/ → HTTP $HTTP_CODE"

sep
echo -e "${GREEN}  ✓ NetBird Management 部署完成${NC}"
echo ""
echo "下一步:"
echo "  1. 等待 1-2 分钟让 Let's Encrypt 签发证书"
echo "  2. 访问 https://$NETBIRD_DOMAIN/ 验证 dashboard"
echo "  3. 部署 Authentik OIDC: bash deploy_authentik.sh"
echo "  4. 创建 setup key: docker compose exec management netbird-cli setup-key create"
echo "  5. 客户端安装: bash install_client.sh --setup-key <KEY>"
sep