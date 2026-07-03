#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# NetBird VPN 隧道验证
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
#
# 验证 NetBird mesh VPN 是否建立成功:
#   - 本机 netbird 状态
#   - WireGuard 接口
#   - 列出 peers
#   - 测试 mesh IP 互通
#
# 用法:
#   bash verify_vpn.sh
#   bash verify_vpn.sh --peer-ip 100.64.0.2
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PEER_IP="${PEER_IP:-}"
NETBIRD_DOMAIN="${NETBIRD_DOMAIN:-qingmulife.cn}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS=0
FAIL=0
WARN=0
ok()   { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; ((WARN++)); }
info() { echo -e "${CYAN}ℹ${NC} $1"; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --peer-ip)
      PEER_IP="$2"
      shift 2
      ;;
    --management)
      NETBIRD_DOMAIN="$2"
      shift 2
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

sep
echo "  NetBird VPN 隧道验证"
sep
echo ""

# ── 1. netbird 客户端状态 ──
info "[1/6] NetBird 客户端状态"

if ! command -v netbird &> /dev/null; then
  fail "netbird 命令不存在"
  echo ""
  echo "请先安装客户端: bash install_client.sh"
  exit 1
fi

# 检查状态
NB_STATUS=$(netbird status 2>&1)
NB_EXIT=$?

if [[ $NB_EXIT -ne 0 ]]; then
  fail "netbird status 命令失败 (exit $NB_EXIT)"
  echo "$NB_STATUS" | head -5 | sed 's/^/    /'
  exit 1
fi

# 提取关键状态
if echo "$NB_STATUS" | grep -qE "Connected|connected|Management.*Connected"; then
  ok "NetBird 客户端状态: Connected"
else
  fail "NetBird 客户端未连接"
  echo "$NB_STATUS" | head -5 | sed 's/^/    /'
fi

# 检查 Management URL
if echo "$NB_STATUS" | grep -q "$NETBIRD_DOMAIN"; then
  ok "Management: $NETBIRD_DOMAIN"
else
  warn "Management URL 不匹配 (期望 $NETBIRD_DOMAIN)"
fi

# 提取 Mesh IP
MY_MESH_IP=$(echo "$NB_STATUS" | grep -oE "100\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?" | head -1 | cut -d/ -f1)
if [[ -n "$MY_MESH_IP" ]]; then
  ok "本机 Mesh IP: $MY_MESH_IP"
else
  fail "未发现 Mesh IP"
fi

echo ""

# ── 2. WireGuard 接口 ──
info "[2/6] WireGuard 接口"

WG_SHOW=$(wg show 2>&1)
WG_EXIT=$?

if [[ $WG_EXIT -ne 0 ]]; then
  fail "wg show 失败 (exit $WG_EXIT)"
else
  # 查找 wt0 或 netbird 接口
  WG_IFACE=$(echo "$WG_SHOW" | awk '/interface/ {print $2}' | head -1)
  if [[ -z "$WG_IFACE" ]]; then
    WG_IFACE=$(echo "$WG_SHOW" | grep "interface" | awk '{print $2}' | head -1)
  fi
  if [[ -n "$WG_IFACE" ]]; then
    ok "WireGuard 接口: $WG_IFACE"
  else
    warn "未找到 WireGuard 接口 (netbird 可能未启动)"
  fi

  # 检查 peer 数
  PEER_COUNT=$(echo "$WG_SHOW" | grep -c "^peer" || echo "0")
  if [[ "$PEER_COUNT" -gt 0 ]]; then
    ok "WireGuard peers: $PEER_COUNT"
  else
    warn "无 WireGuard peers"
  fi
fi

echo ""

# ── 3. Peers 列表 ──
info "[3/6] Mesh Peers 列表"

NB_PEERS=$(netbird peer list 2>&1)
echo "$NB_PEERS" | head -10 | sed 's/^/    /'

PEER_NUM=$(echo "$NB_PEERS" | grep -v "^$" | tail -n +2 | wc -l | tr -d ' ')
if [[ "$PEER_NUM" -gt 0 ]]; then
  ok "Mesh 中有 $PEER_NUM 个 peer"
else
  warn "Mesh 中无 peer"
fi

echo ""

# ── 4. ICE/P2P 模式 ──
info "[4/6] 连接模式 (Direct vs Relaying)"

# 检查 relaying
if echo "$NB_STATUS" | grep -qiE "relay|relayin"; then
  warn "当前使用 Relay 模式 (非 P2P)"
  warn "  排查 UDP 3478 是否可达,或路由器阻挡了 UDP 打洞"
elif echo "$NB_STATUS" | grep -qiE "direct|p2p|hole punching"; then
  ok "P2P 直连 (UDP 打洞成功)"
else
  warn "无法判断连接模式"
fi

echo ""

# ── 5. Mesh IP 互通测试 ──
info "[5/6] Mesh IP 互通测试"

if [[ -z "$PEER_IP" ]]; then
  # 自动取一个 peer IP
  PEER_IP=$(netbird peer list 2>&1 | grep -oE "100\.[0-9]+\.[0-9]+\.[0-9]+" | grep -v "$MY_MESH_IP" | head -1)
fi

if [[ -z "$PEER_IP" ]]; then
  warn "未指定 peer IP 且 mesh 无其他 peer"
  warn "  (单节点 mesh 是正常的;需多客户端加入后才互通)"
else
  echo "  测试 ping $PEER_IP:"
  if ping -c 3 -W 2 "$PEER_IP" 2>&1 | grep -q "1 received\|2 received\|3 received"; then
    ok "ping $PEER_IP 通"
  else
    fail "ping $PEER_IP 不通"
  fi

  echo ""
  echo "  测试 SSH $PEER_IP:22:"
  if nc -z -G 3 "$PEER_IP" 22 2>/dev/null; then
    ok "SSH $PEER_IP:22 可达"
  else
    warn "SSH $PEER_IP:22 不可达(可能防火墙阻挡)"
  fi
fi

echo ""

# ── 6. Management 连通性 ──
info "[6/6] Management 连通性"

MGMT_IP=$(dig +short A "$NETBIRD_DOMAIN" 2>&1 | head -1)
if [[ -n "$MGMT_IP" ]]; then
  echo "  Management DNS: $NETBIRD_DOMAIN → $MGMT_IP"
  if nc -z -G 3 "$MGMT_IP" 443 2>/dev/null; then
    ok "Management HTTPS 可达 ($MGMT_IP:443)"
  else
    fail "Management HTTPS 不可达 ($MGMT_IP:443)"
  fi
else
  warn "无法解析 $NETBIRD_DOMAIN"
fi

# DNS over HTTPS
HTTPS_CODE=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 10 "https://$NETBIRD_DOMAIN/" 2>&1 || echo "FAIL")
if [[ "$HTTPS_CODE" == "200" || "$HTTPS_CODE" == "302" ]]; then
  ok "Dashboard HTTP $HTTPS_CODE"
else
  fail "Dashboard HTTP $HTTPS_CODE"
fi

echo ""

# ── 汇总 ──
sep
echo "  验证结果汇总"
sep
echo -e "  ${GREEN}✓ PASS: $PASS${NC}"
[[ $WARN -gt 0 ]] && echo -e "  ${YELLOW}⚠ WARN: $WARN${NC}"
[[ $FAIL -gt 0 ]] && echo -e "  ${RED}✗ FAIL: $FAIL${NC}"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo -e "${RED}  有连通性问题,排查方向:${NC}"
  echo "  1. 检查 netbird 服务: systemctl status netbird"
  echo "  2. 查看日志: journalctl -u netbird -f"
  echo "  3. 确认 Management 可达: https://$NETBIRD_DOMAIN/"
  echo "  4. 确认 UDP 3478 (Coturn) 可达"
  echo "  5. 确认客户端有 setup key 加入 mesh"
  exit 1
fi

if [[ $WARN -gt 0 ]]; then
  echo -e "${YELLOW}  有警告(基本可用,可能需优化 P2P 模式)${NC}"
fi

echo -e "${GREEN}  NetBird VPN 隧道验证通过!${NC}"
echo ""
echo "  本机 Mesh IP: $MY_MESH_IP"
[[ -n "$PEER_IP" ]] && echo "  测试 Peer IP: $PEER_IP"
sep