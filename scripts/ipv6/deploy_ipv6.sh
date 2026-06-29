#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND IPv6 部署脚本
# 作者：外星动物（常智）/ IoTchange  |  许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────
#
# 在 10.10.10.19 服务器上以 root 身份执行
# 配置 IPv6 公网地址 + 防火墙 + nginx 监听
#
# 用法：
#   IPV6_ADDR=2402:4e00:c013:7500::1 IFACE=eth0 bash deploy_ipv6.sh
#   # 或交互式:
#   bash deploy_ipv6.sh
#
# 验证：
#   bash verify_ipv6.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── 配置参数 ──
IPV6_ADDR="${IPV6_ADDR:-}"
IFACE="${IFACE:-eth0}"
API_PORT="${API_PORT:-8000}"
HTTPS_PORT="${HTTPS_PORT:-443}"
IPV6_PREFIX_LEN="${IPV6_PREFIX_LEN:-64}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}ℹ${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# ── 0. 权限检查 ──
if [[ $EUID -ne 0 ]]; then
  err "请以 root 身份运行: sudo bash $0"
fi

sep
echo "  RHYTHMIND IPv6 部署"
sep
echo ""

# ── 1. 检测当前网络环境 ──
info "[1/6] 检测当前网络配置"

echo "  IPv4 地址:"
ip -4 -o addr show "$IFACE" 2>/dev/null | awk '{print "    " $4}' || warn "    网卡 $IFACE 未找到 IPv4"

echo "  现有 IPv6 地址:"
EXISTING_IPV6=$(ip -6 -o addr show "$IFACE" 2>/dev/null | grep -v "fe80" | awk '{print $4}' | head -5)
if [[ -z "$EXISTING_IPV6" ]]; then
  warn "    网卡 $IFACE 未配置公网 IPv6"
else
  echo "$EXISTING_IPV6" | sed 's/^/    /'
fi

echo "  路由默认网关:"
ip -6 route show default 2>/dev/null | awk '{print "    " $0}' | head -3

echo "  IPv6 出口测试:"
if ping6 -c 2 -W 3 2402:4e00:c013:7500:b4ea:cdb0:622a:0 2>&1 | grep -q "1 packets received\|2 packets received"; then
  ok "    已可达云服务器 IPv6"
else
  warn "    暂无法 ping 通云服务器(可能需 ISP 路由配置)"
fi

echo ""

# ── 2. 获取/确认 IPv6 地址 ──
info "[2/6] 配置公网 IPv6 地址"

if [[ -z "$IPV6_ADDR" ]]; then
  echo ""
  echo "请选择 IPv6 地址来源:"
  echo "  1) 手动输入 (推荐:从 ISP/路由器管理界面查)"
  echo "  2) 尝试 SLAAC 自动配置 (等待 5s)"
  echo "  3) 跳过此步骤 (假设已配置好)"
  echo ""
  read -p "选择 [1/2/3]: " CHOICE

  case "$CHOICE" in
    1)
      read -p "输入公网 IPv6 地址 (如 2402:4e00:c013:7500::1): " IPV6_ADDR
      [[ -z "$IPV6_ADDR" ]] && err "地址不能为空"
      ;;
    2)
      info "等待 5s 让 SLAAC 自动配置..."
      sleep 5
      IPV6_ADDR=$(ip -6 -o addr show "$IFACE" 2>/dev/null | grep -v "fe80" | awk '{print $4}' | head -1 | cut -d/ -f1)
      if [[ -z "$IPV6_ADDR" ]]; then
        err "SLAAC 未配置 IPv6,请用 ISP 路由界面获取"
      fi
      ok "检测到 IPv6: $IPV6_ADDR"
      ;;
    3)
      IPV6_ADDR=$(ip -6 -o addr show "$IFACE" 2>/dev/null | grep -v "fe80" | awk '{print $4}' | head -1 | cut -d/ -f1)
      [[ -z "$IPV6_ADDR" ]] && err "网卡 $IFACE 无 IPv6"
      ok "使用现有 IPv6: $IPV6_ADDR"
      ;;
    *)
      err "无效选择"
      ;;
  esac
fi

info "将配置 IPv6: $IPV6_ADDR/$IPV6_PREFIX_LEN dev $IFACE"
echo ""

# ── 3. 添加 IPv6 地址 ──
info "[3/6] 添加 IPv6 地址到网卡 $IFACE"

# 检查是否已存在
if ip -6 addr show dev "$IFACE" 2>/dev/null | grep -q "$IPV6_ADDR"; then
  ok "IPv6 地址已存在,跳过"
else
  # 添加地址
  if ip -6 addr add "$IPV6_ADDR/$IPV6_PREFIX_LEN" dev "$IFACE" 2>/dev/null; then
    ok "已添加 IPv6: $IPV6_ADDR/$IPV6_PREFIX_LEN"
  else
    err "添加 IPv6 失败(可能需要 CAP_NETADMIN 或地址冲突)"
  fi
fi

# 添加默认路由(如果没有)
if ! ip -6 route show default 2>/dev/null | grep -q "."; then
  GATEWAY6=$(ip -6 route show | grep "via" | head -1 | awk '{print $3}')
  if [[ -n "$GATEWAY6" ]]; then
    ip -6 route add default via "$GATEWAY6" dev "$IFACE" 2>/dev/null || warn "默认路由添加失败"
    ok "默认路由: $GATEWAY6"
  else
    warn "未检测到 IPv6 网关,请手动配置"
  fi
fi

echo ""

# ── 4. 防火墙 ufw 配置 ──
info "[4/6] 配置 ufw 防火墙 (IPv4 + IPv6)"

if ! command -v ufw &> /dev/null; then
  warn "未安装 ufw,跳过(假设有其他防火墙)"
else
  # 启用 IPv6
  if grep -q "^IPV6=yes" /etc/ufw/ufw.conf 2>/dev/null; then
    ok "ufw IPv6 已启用"
  else
    sed -i 's/^IPV6=no/IPV6=yes/' /etc/ufw/ufw.conf
    ok "已启用 ufw IPv6"
  fi

  # 默认策略
  ufw default allow outgoing >/dev/null 2>&1
  ufw default deny incoming >/dev/null 2>&1

  # 放行 API 端口
  ufw allow "$API_PORT/tcp" comment "RHYTHMIND API (backend uvicorn)" 2>&1 | sed 's/^/    /'
  ufw allow "$HTTPS_PORT/tcp" comment "RHYTHMIND HTTPS (nginx)" 2>&1 | sed 's/^/    /'

  # 放行 SSH(防止锁住)
  ufw allow 22/tcp comment "SSH" 2>&1 | sed 's/^/    /'

  # 启用 ufw(若未启用)
  ufw --force enable 2>/dev/null || true
  ufw status numbered 2>&1 | head -20

  ok "ufw 配置完成"
fi

echo ""

# ── 5. nginx IPv6 监听 ──
info "[5/6] 配置 nginx IPv6 监听"

if ! command -v nginx &> /dev/null; then
  warn "未安装 nginx,跳过"
else
  NGINX_CONF="/etc/nginx/sites-enabled/qm_ipv6.conf"

  if [[ -f "$NGINX_CONF" ]]; then
    warn "$NGINX_CONF 已存在,跳过生成(可手动修改)"
  else
    cat > "$NGINX_CONF" << NGINX_EOF
# RHYTHMIND IPv6 + IPv4 dual-stack
# 由 scripts/ipv6/deploy_ipv6.sh 自动生成

server {
    listen $HTTPS_PORT ssl;
    listen [::]:$HTTPS_PORT ssl;  # IPv6
    http2 on;

    server_name aisport.tech _;

    ssl_certificate     /etc/ssl/certs/aisport.tech.pem;
    ssl_certificate_key /etc/ssl/private/aisport.tech.key;

    # 后端 API: /qm/api/* → 127.0.0.1:$API_PORT
    location /qm/api/ {
        proxy_pass http://127.0.0.1:$API_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
        proxy_buffering off;
    }

    # 前端静态文件
    location /qm/ {
        root /var/www;
        try_files \$uri \$uri/ /qm/index.html;
    }
}
NGINX_EOF
    ok "已生成 $NGINX_CONF"
  fi

  # 验证配置
  if nginx -t 2>&1; then
    ok "nginx 配置语法正确"
  else
    err "nginx 配置错误,请检查 $NGINX_CONF"
  fi
fi

echo ""

# ── 6. 最终验证 ──
info "[6/6] 验证 IPv6 配置"

echo "  最终 IPv6 地址:"
ip -6 addr show dev "$IFACE" 2>/dev/null | grep "inet6 " | grep -v "fe80" | awk '{print "    " $2}'

echo ""
echo "  测试 IPv6 出口:"
if ping6 -c 2 -W 3 2402:4e00:c013:7500:b4ea:cdb0:622a:0 2>&1 | tail -3; then
  ok "可 ping 通云服务器"
else
  warn "无法 ping 通云服务器(可能需调整安全组)"
fi

echo ""
echo "  测试 HTTPS (从本地):"
if curl -6 -s -o /dev/null -w "    HTTP=%{http_code} TIME=%{time_total}s\n" \
  --max-time 10 "https://[$IPV6_ADDR]:$HTTPS_PORT/qm/api/readyz" 2>&1; then
  ok "本地 IPv6 入口正常"
fi

sep
echo -e "${GREEN}  ✓ IPv6 部署完成${NC}"
echo ""
echo "下一步:"
echo "  1. 在云服务器 $IPV6_ADDR 上执行 verify_ipv6.sh 验证互通"
echo "  2. 如果云端无法访问,检查:"
echo "     - ISP 是否给本地分配了公网 IPv6 (有些是 CGNAT)"
echo "     - 本地路由器/防火墙是否允许入站 IPv6"
echo "     - 云安全组是否放行 2402:4e00:... 源地址"
sep
