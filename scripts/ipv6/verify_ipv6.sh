#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND IPv6 连通性验证脚本
# ─────────────────────────────────────────────────────────────────────────────
#
# 测试 云 2402:4e00:c013:7500:b4ea:cdb0:622a:0 ↔ 本地 10.10.10.19 双向连通
# 在云服务器和本地服务器上各跑一次,对比结果
#
# 用法:
#   # 在云服务器上跑(测 → 本地)
#   LOCAL_IPV6=2402:4e00:c013:7500::1 bash verify_ipv6.sh
#
#   # 在本地 10.10.10.19 上跑(测 → 云)
#   CLOUD_IPV6=2402:4e00:c013:7500:b4ea:cdb0:622a:0 bash verify_ipv6.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

CLOUD_IPV6="${CLOUD_IPV6:-2402:4e00:c013:7500:b4ea:cdb0:622a:0}"
LOCAL_IPV4="${LOCAL_IPV4:-10.10.10.19}"
LOCAL_IPV6="${LOCAL_IPV6:-}"
LOCAL_DOMAIN="${LOCAL_DOMAIN:-aisport.tech}"
API_PORT="${API_PORT:-8000}"
HTTPS_PORT="${HTTPS_PORT:-443}"
API_PATH="${API_PATH:-/qm/api/readyz}"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

ok()   { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; ((WARN++)); }
info() { echo -e "${CYAN}ℹ${NC} $1"; }
sep()  { echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

sep
echo "  RHYTHMIND IPv6 连通性验证"
sep
echo ""
echo "  云 IPv6:    $CLOUD_IPV6"
echo "  本地 IPv4:  $LOCAL_IPV4"
[[ -n "$LOCAL_IPV6" ]] && echo "  本地 IPv6:  $LOCAL_IPV6"
echo "  域名:      $LOCAL_DOMAIN"
echo ""

# ── 1. IPv6 出口测试 ──
info "[1/5] IPv6 出口连通性"

if ping6 -c 3 -W 3 "$CLOUD_IPV6" > /dev/null 2>&1; then
  ok "ping6 → $CLOUD_IPV6 通"
else
  fail "ping6 → $CLOUD_IPV6 不通"
fi

if [[ -n "$LOCAL_IPV6" ]] && ping6 -c 3 -W 3 "$LOCAL_IPV6" > /dev/null 2>&1; then
  ok "ping6 → $LOCAL_IPV6 通"
else
  warn "本地 IPv6 未配置或不可达"
fi

echo ""

# ── 2. IPv4 出口测试 ──
info "[2/5] IPv4 出口连通性"

if ping -c 3 -W 3 "$LOCAL_IPV4" > /dev/null 2>&1; then
  ok "ping → $LOCAL_IPV4 通"
else
  fail "ping → $LOCAL_IPV4 不通(检查云安全组入站规则)"
fi

echo ""

# ── 3. HTTPS 端口测试 ──
info "[3/5] HTTPS 端口连通性"

# 测试 IPv6 → 本地 IPv4
echo "  [IPv6 → IPv4] curl https://[$LOCAL_IPV4]:$HTTPS_PORT$API_PATH"
if [[ -n "$LOCAL_IPV6" ]]; then
  RESP=$(curl -6 -s -k -o /dev/null -w "%{http_code}|%{time_total}" \
    --max-time 10 "https://[$LOCAL_IPV4]:$HTTPS_PORT$API_PATH" 2>&1)
  CODE=$(echo "$RESP" | cut -d'|' -f1)
  TIME=$(echo "$RESP" | cut -d'|' -f2)
  if [[ "$CODE" == "200" ]]; then
    ok "HTTP $CODE (${TIME}s)"
  elif [[ "$CODE" == "401" || "$CODE" == "403" ]]; then
    ok "HTTP $CODE (路由可达,需鉴权)"
  else
    fail "HTTP $CODE"
  fi
else
  warn "本地无 IPv6,跳过"
fi

# 测试 IPv6 → 域名
echo "  [IPv6 → 域名] curl https://$LOCAL_DOMAIN$API_PATH"
if [[ -n "$LOCAL_IPV6" ]]; then
  RESP=$(curl -6 -s -k -o /dev/null -w "%{http_code}|%{time_total}" \
    --max-time 10 "https://$LOCAL_DOMAIN$API_PATH" 2>&1)
  CODE=$(echo "$RESP" | cut -d'|' -f1)
  if [[ "$CODE" == "200" ]] || [[ "$CODE" == "401" ]] || [[ "$CODE" == "403" ]]; then
    ok "HTTP $CODE"
  else
    warn "HTTP $CODE (域名可能未配 AAAA 记录)"
  fi
fi

# 测试 IPv4 → 云(从云服务器视角)
echo "  [IPv4 → IPv4] curl http://$LOCAL_IPV4:$API_PORT/readyz"
RESP=$(curl -4 -s -o /dev/null -w "%{http_code}|%{time_total}" \
  --max-time 10 "http://$LOCAL_IPV4:$API_PORT/readyz" 2>&1)
CODE=$(echo "$RESP" | cut -d'|' -f1)
if [[ "$CODE" == "200" ]]; then
  ok "HTTP $CODE (${RESP##*|})"
else
  fail "HTTP $CODE"
fi

echo ""

# ── 4. 后端 API 端到端测试 ──
info "[4/5] 后端 API 端到端测试"

echo "  /readyz:"
RESP=$(curl -4 -s -w "\n%{http_code}" --max-time 10 "http://$LOCAL_IPV4:$API_PORT/readyz" 2>&1)
CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -n -1)
if [[ "$CODE" == "200" ]]; then
  ok "HTTP $CODE → $BODY"
else
  fail "HTTP $CODE"
fi

echo ""

# ── 5. IPv6 路由追踪 ──
info "[5/5] IPv6 路由追踪"

if command -v traceroute6 &> /dev/null || command -v tracepath6 &> /dev/null; then
  echo "  tracepath6 → $CLOUD_IPV6:"
  tracepath6 -m 5 "$CLOUD_IPV6" 2>&1 | head -8 | sed 's/^/    /'
else
  warn "未安装 traceroute6/tracepath6,跳过"
fi

echo ""

# ── 汇总 ──
sep
echo "  验证结果汇总"
sep
echo -e "  ${GREEN}✓ PASS: $PASS${NC}"
[[ $WARN -gt 0 ]] && echo -e "  ${YELLOW}⚠ WARN: $WARN${NC}"
[[ $FAIL -gt 0 ]] && echo -e "  ${RED}✗ FAIL: $FAIL${NC}" || echo -e "  ${GREEN}✗ FAIL: 0  ← 全部通过!${NC}"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo -e "${RED}  存在连通性问题,排查方向:${NC}"
  echo "  1. 检查 ISP/路由器是否给本地分配公网 IPv6 (CGNAT 不会有)"
  echo "  2. 检查本地 ufw 防火墙: ufw status"
  echo "  3. 检查云安全组入站规则是否放行 2402:4e00:... 源"
  echo "  4. 检查 nginx 监听: ss -tlnp | grep -E ':443|:8000'"
  echo "  5. 检查后端运行: curl http://127.0.0.1:8000/readyz"
  exit 1
fi

if [[ $WARN -gt 0 ]]; then
  echo -e "${YELLOW}  有警告,可能需要优化(但基本可用)${NC}"
fi

echo -e "${GREEN}  IPv6 互通验证通过!${NC}"
sep
