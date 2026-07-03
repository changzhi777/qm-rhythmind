#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Authentik OIDC 一键部署 (NetBird 身份认证)
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
#
# 部署 Authentik + Postgres,与 NetBird 同主机
# NetBird .env 需配置:
#   NETBIRD_USE_AUTH0=false
#   NETBIRD_AUTH_OIDC_CONFIGURATION_ENDPOINT=https://qingmulife.cn/application/o/netbird/.well-known/openid-configuration
#   NETBIRD_AUTH_CLIENT_ID=<从 Authentik 拿>
#   NETBIRD_AUTH_AUDIENCE=netbird
#
# 用法 (在 106.53.168.73 上):
#   bash deploy_authentik.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

INSTALL_DIR="/opt/netbird"
NETBIRD_DOMAIN="${NETBIRD_DOMAIN:-qingmulife.cn}"
AUTHENTIK_VERSION="${AUTHENTIK_VERSION:-2024.6}"
POSTGRES_VERSION="${POSTGRES_VERSION:-16-alpine}"
AUTHENTIK_SECRET_KEY="${AUTHENTIK_SECRET_KEY:-$(openssl rand -base64 32 | head -c 32)}"
PG_PASS="${PG_PASS:-$(openssl rand -base64 24 | head -c 24)}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}ℹ${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

[[ $EUID -eq 0 ]] || err "请以 root 身份运行"

sep
echo "  Authentik OIDC 部署"
sep
echo "  域名: $NETBIRD_DOMAIN"
echo "  Authentik Version: $AUTHENTIK_VERSION"
echo ""

# ── 1. 创建 Authentik 目录 ──
info "[1/5] 创建目录"

mkdir -p "$INSTALL_DIR/authentik/media"
cd "$INSTALL_DIR/artifacts"

ok "目录就绪"
echo ""

# ── 2. 生成 Authentik .env ──
info "[2/5] 生成 Authentik 环境配置"

cat > "$INSTALL_DIR/artifacts/authentik.env" << ENV_EOF
# Authentik 配置 (由 deploy_authentik.sh 生成)
AUTHENTIK_SECRET_KEY=$AUTHENTIK_SECRET_KEY
AUTHENTIK_POSTGRESQL__HOST=postgres
AUTHENTIK_POSTGRESQL__PORT=5432
AUTHENTIK_POSTGRESQL__NAME=authentik
AUTHENTIK_POSTGRESQL__USER=authentik
AUTHENTIK_POSTGRESQL__PASSWORD=$PG_PASS
AUTHENTIK_REDIS__HOST=redis
AUTHENTIK_REDIS__PORT=6379
AUTHENTIK_LISTEN__HTTP=0.0.0.0:9000
AUTHENTIK_LISTEN__HTTPS=0.0.0.0:9443
ENV_EOF

# 追加到 .env(给 NetBird 读)
cat "$INSTALL_DIR/artifacts/authentik.env" > "$INSTALL_DIR/artifacts/authentik.env.tmp"
mv "$INSTALL_DIR/artifacts/authentik.env.tmp" "$INSTALL_DIR/artifacts/authentik.env"

ok "已生成 authentik.env"
warn "AUTHENTIK_SECRET_KEY 已生成(请妥善保存)"
echo ""

# ── 3. 追加 Authentik + Postgres 到 docker-compose ──
info "[3/5] 扩展 docker-compose.yml"

# 检查是否已包含
if grep -q "authentik-server" "$INSTALL_DIR/artifacts/docker-compose.yml"; then
  ok "已包含 authentik,跳过"
else
cat >> "$INSTALL_DIR/artifacts/docker-compose.yml" << APPEND_EOF

  # ── Authentik OIDC + Postgres + Redis (2026-07-03 追加) ──
  authentik-server:
    image: ghcr.io/goauthentik/server:${AUTHENTIK_VERSION}
    container_name: authentik-server
    restart: unless-stopped
    command: server
    env_file:
      - authentik.env
    volumes:
      - $INSTALL_DIR/authentik/media:/media
      - $INSTALL_DIR/authentik/custom-templates:/templates
    networks:
      - netbird
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  authentik-worker:
    image: ghcr.io/goauthentik/server:${AUTHENTIK_VERSION}
    container_name: authentik-worker
    restart: unless-stopped
    command: worker
    env_file:
      - authentik.env
    volumes:
      - $INSTALL_DIR/authentik/media:/media
      - $INSTALL_DIR/authentik/custom-templates:/templates
    networks:
      - netbird
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  postgres:
    image: postgres:${POSTGRES_VERSION}
    container_name: authentik-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_DB=authentik
      - POSTGRES_USER=authentik
      - POSTGRES_PASSWORD=$PG_PASS
    volumes:
      - $INSTALL_DIR/authentik/pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U authentik"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - netbird

  redis:
    image: redis:7-alpine
    container_name: authentik-redis
    restart: unless-stopped
    command: --save 60 1 --loglevel warning
    volumes:
      - $INSTALL_DIR/authentik/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - netbird
APPEND_EOF
  ok "已追加 Authentik 服务"
fi

echo ""

# ── 4. 启动 ──
info "[4/5] 启动 Authentik"

cd "$INSTALL_DIR/artifacts"

docker compose pull authentik-server authentik-worker postgres redis 2>&1 | tail -3

docker compose up -d postgres redis 2>&1
info "等待 Postgres 健康..."
for i in {1..30}; do
  if docker compose ps postgres | grep -q "(healthy)"; then
    ok "Postgres 健康"
    break
  fi
  sleep 2
done

docker compose up -d authentik-server authentik-worker 2>&1 | tail -5

echo ""
info "等待 Authentik 启动 (60s)..."
sleep 30

echo ""

# ── 5. 创建 admin 账号 ──
info "[5/5] 配置管理员账号"

docker compose ps authentik-server | head -3

# 通过 ak-cli 设置 admin
info "提示: 首次访问 https://authentik.$NETBIRD_DOMAIN/if/admin/"
info "     默认用户 akadmin,首次登录会提示设置密码"

echo ""
echo "  创建 OIDC Provider for NetBird:"
echo "  1. 访问 https://authentik.$NETBIRD_DOMAIN/if/admin/"
echo "  2. 登录后: Applications → Providers → Create"
echo "     - Type: OAuth2/OpenID Connect"
echo "     - Name: netbird"
echo "     - Authorization flow: default-provider-authorization-explicit-consent"
echo "     - Client type: Confidential"
echo "     - Redirect URI: https://$NETBIRD_DOMAIN/oauth2/callback"
echo "     - Scopes: openid, email, profile"
echo "  3. 创建 Application: Applications → Applications → Create"
echo "     - Name: netbird"
echo "     - Provider: 上面创建的 netbird"
echo "  4. 复制 Client ID 和 Client Secret"

# 写入 NetBird .env 模板
cat > "$INSTALL_DIR/artifacts/netbird-oidc.env" << OIDC_EOF
# 复制到主 docker-compose 的 environment (或 docker compose --env-file)
NETBIRD_USE_AUTH0=false
NETBIRD_AUTH_OIDC_CONFIGURATION_ENDPOINT=https://authentik.$NETBIRD_DOMAIN/application/o/netbird/.well-known/openid-configuration
NETBIRD_AUTH_CLIENT_ID=<从 Authentik 复制的 Client ID>
NETBIRD_AUTH_AUDIENCE=netbird
OIDC_EOF

ok "已生成 netbird-oidc.env 模板"

sep
echo -e "${GREEN}  ✓ Authentik OIDC 部署完成${NC}"
echo ""
echo "  配置文件:"
echo "    $INSTALL_DIR/artifacts/authentik.env       (Authentik 配置)"
echo "    $INSTALL_DIR/artifacts/netbird-oidc.env    (OIDC 模板,需填 Client ID)"
echo ""
echo "  下一步:"
echo "    1. 访问 https://authentik.$NETBIRD_DOMAIN/if/admin/ 创建 OIDC"
echo "    2. 把 Client ID 填入 netbird-oidc.env"
echo "    3. docker compose restart management  # 重启加载 OIDC 配置"
echo "    4. 测试 OIDC 登录 https://$NETBIRD_DOMAIN/"
sep