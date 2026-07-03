#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# NetBird 客户端安装与注册
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
#
# 在 CT109 (10.10.10.19) 或 腾讯云本机 执行
# 把本机加入 NetBird mesh VPN
#
# 用法:
#   bash install_client.sh --setup-key <KEY>
#   bash install_client.sh --setup-key AAAA-BBBB-CCCC
#   bash install_client.sh --management qingmulife.cn --setup-key AAAA-BBBB-CCCC
#
# 验证:
#   netbird status
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

NETBIRD_DOMAIN="${NETBIRD_DOMAIN:-qingmulife.cn}"
SETUP_KEY=""
OS_TYPE=""
INSTALL_FLAG=true

# ── 参数解析 ──
while [[ $# -gt 0 ]]; do
  case "$1" in
    --setup-key)
      SETUP_KEY="$2"
      shift 2
      ;;
    --management)
      NETBIRD_DOMAIN="$2"
      shift 2
      ;;
    --no-install)
      INSTALL_FLAG=false
      shift
      ;;
    --help|-h)
      echo "用法: $0 --setup-key <KEY> [--management domain] [--no-install]"
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

[[ -z "$SETUP_KEY" ]] && { echo "错误: 必须提供 --setup-key" >&2; exit 1; }

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${CYAN}ℹ${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

sep
echo "  NetBird 客户端安装"
sep
echo "  Management: $NETBIRD_DOMAIN"
echo "  Setup Key:  ${SETUP_KEY:0:8}***"
echo ""

# ── 0. OS 检测 ──
info "[0/5] 检测操作系统"

if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  OS_TYPE="$ID"
  ok "检测到: $PRETTY_NAME"
elif [[ "$(uname)" == "Darwin" ]]; then
  OS_TYPE="macos"
  ok "检测到: macOS"
elif [[ "$(uname)" =~ BSD ]]; then
  OS_TYPE="freebsd"
  ok "检测到: BSD"
else
  err "无法识别的操作系统"
fi

echo ""

# ── 1. 安装 NetBird ──
if $INSTALL_FLAG; then
  info "[1/5] 安装 NetBird 客户端"

  case "$OS_TYPE" in
    ubuntu|debian)
      curl -sSL https://pkgs.netbird.io/install.sh | sh
      ;;
    centos|rhel|fedora|rocky|almalinux)
      curl -sSL https://pkgs.netbird.io/install.sh | sh
      ;;
    alpine)
      apk add --no-cache netbird
      ;;
    macos)
      brew install netbirdio/tap/netbird
      ;;
    freebsd)
      pkg install netbird
      ;;
    *)
      warn "未识别的 OS,尝试通用 Linux 安装"
      curl -sSL https://pkgs.netbird.io/install.sh | sh
      ;;
  esac

  ok "NetBird 已安装: $(netbird version 2>&1 | head -1)"
else
  ok "跳过安装 (--no-install)"
fi

echo ""

# ── 2. 启用并启动服务 ──
info "[2/5] 启动 netbird 服务"

case "$OS_TYPE" in
  ubuntu|debian|centos|rhel|fedora|rocky|almalinux|alpine)
    systemctl enable netbird
    systemctl start netbird
    ok "systemd 服务已启动"
    ;;
  macos)
    brew services start netbird
    ok "brew services 已启动"
    ;;
  freebsd)
    service netbird onestart
    ;;
  *)
    netbird service install 2>/dev/null || true
    netbird service start 2>/dev/null || true
    ;;
esac

sleep 2
echo ""

# ── 3. 配置 Management ──
info "[3/5] 配置 Management URL"

netbird stop 2>/dev/null || true
netbird start 2>/dev/null || true

netbird status 2>&1 | head -5 || true

echo ""

# ── 4. 加入网络 ──
info "[4/5] 加入 NetBird mesh (setup-key)"

netbird up --management-url "https://$NETBIRD_DOMAIN" --setup-key "$SETUP_KEY" 2>&1 | tail -10

ok "已加入 mesh"
echo ""

# ── 5. 验证 ──
info "[5/5] 验证连接"

sleep 3

echo ""
echo "  NetBird 状态:"
netbird status 2>&1 | head -15 | sed 's/^/    /'

echo ""
echo "  WireGuard 接口:"
wg show 2>&1 | head -10 | sed 's/^/    /'

echo ""
echo "  Mesh IP:"
MESH_IP=$(netbird status 2>&1 | grep -oE "100\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+" | head -1)
if [[ -n "$MESH_IP" ]]; then
  ok "Mesh IP: $MESH_IP"
else
  warn "未发现 Mesh IP,可能未完全连接"
fi

sep
echo -e "${GREEN}  ✓ NetBird 客户端部署完成${NC}"
echo ""
echo "  主机名: $(hostname)"
echo "  Management: https://$NETBIRD_DOMAIN"
echo "  Mesh IP: ${MESH_IP:-<等待分配>}"
echo ""
echo "  测试 mesh 互通:"
echo "    netbird peer list        # 列出其他 peer"
echo "    ping <peer-100.x.x.x>   # 测试 mesh 互通"
echo "    ssh root@<peer-ip>      # 经 mesh SSH"
sep