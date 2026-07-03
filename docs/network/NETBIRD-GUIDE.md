# RHYTHMIND NetBird VPN 部署指南

> **目标**: 在腾讯云 106.53.168.73 (域名 qingmulife.cn) 部署 NetBird Management + Signal + Relay + Coturn + Authentik OIDC,实现 P2P WireGuard mesh VPN,客户端加入: CT109 (10.10.10.19) + 腾讯云本机
> **日期**: 2026-07-03

---

## 一、NetBird 架构

```
                       ┌────────────────────────────────────────┐
                       │   106.53.168.73 (腾讯云 qingmulife.cn)  │
                       │                                        │
                       │   ┌────────────────────────────────┐  │
                       │   │  Docker Compose                 │  │
                       │   │  ├─ management:443 (HTTPS/gRPC)│  │
   ┌──────────┐         │   │  ├─ signal:443 (WebSocket)     │  │
   │ CT109    │         │   │  ├─ relay:443 (WebSocket)      │  │
   │ 10.10.   │ ───┐    │   │  ├─ coturn:3478 (STUN/TURN)    │  │
   │ 10.19    │    │    │   │  ├─ authentik-server:9000      │  │
   └──────────┘    │    │   │  ├─ authentik-worker           │  │
                   │    │   │  ├─ postgres:5432              │  │
                   │    │   │  └─ caddy:443 (LE + 反代)      │  │
   ┌──────────┐    │    │   └────────────────────────────────┘  │
   │ 腾讯云   │ ───┤    │                                        │
   │ 本机     │    │    │         ICE / WireGuard / TLS         │
   └──────────┘    └────►                                        │
                                                          INTERNET │
                                                                ▲
                                                                │
                                            ┌───────────────────┘
                                            │ STUN/TURN (UDP 3478)
                                            │ Signal Exchange (443)
                                            ▼
                                  ┌──────────────────────┐
                                  │  Coturn + Relay      │
                                  │  P2P 打洞失败时回落  │
                                  └──────────────────────┘
```

---

## 二、核心组件说明

| 组件 | 作用 | 端口 |
|------|------|------|
| **Management** | 中心控制: 网络状态、peer IP、策略、分发配置 | TCP 443 |
| **Signal** | ICE 候选地址交换 (WebSocket + gRPC) | TCP 443 (合并) |
| **Relay** | NAT 穿透失败时回落的 TURN-like 中继 | TCP 443 (合并) |
| **Coturn** | STUN/TURN 服务器 (开源) | UDP 3478 + 49152-65535 |
| **Authentik** | OIDC IdP (用户登录认证) | TCP 9000 (内部),通过 Caddy 443 |
| **Caddy** | 反向代理 + Let's Encrypt 自动 HTTPS | TCP 80, 443 |
| **Postgres** | Authentik 数据库 | TCP 5432 (内部) |

---

## 三、端口要求

### 入站 (外部 → 腾讯云 106.53.168.73)

| 端口 | 协议 | 服务 | 说明 |
|------|------|------|------|
| 80 | TCP | Caddy | HTTP (LE 验证 + 301→443) |
| 443 | TCP | Caddy | HTTPS (合并管理 + Signal + Relay) |
| 3478 | UDP | Coturn | STUN/TURN |
| 49152-65535 | UDP | Coturn | TURN 中继端口 (v0.29 兼容旧客户端) |

### 出站 (腾讯云 → 客户端)
- 无需特殊规则 (任意出站)

### 云安全组入站规则 (腾讯云控制台)

```
入站规则:
  协议 TCP  端口 80,443    源 0.0.0.0/0   策略 ACCEPT
  协议 UDP  端口 3478      源 0.0.0.0/0   策略 ACCEPT
  协议 UDP  端口 49152-65535 源 0.0.0.0/0  策略 ACCEPT
  协议 TCP  端口 22        源 <你的 IP>    策略 ACCEPT  (SSH 维护)
```

---

## 四、架构组件代码结构 (NetBird 仓库)

```
netbird/
├── client/          # 终端 Agent (Go)
│   ├── cmd/         # 主入口
│   ├── internal/    # WireGuard 接口管理、ICE
│   └── ui/          # 客户端 UI (Wails/Web)
├── management/      # 管理服务 (Go)
│   └── cmd/         # API + Dashboard
├── signal/          # 信令服务 (Go)
├── relay/           # 中继服务 (Go)
├── dns/             # DNS 模块
├── route/           # 路由模块
├── flow/            # 流量日志
├── idp/             # IdP 集成 (Auth0/OIDC)
├── stun/            # STUN 客户端
├── proxy/           # TLS 反代支持
└── infrastructure_files/
    ├── setup.env.example
    ├── configure.sh
    └── artifacts/    # 生成的 docker-compose.yml
```

---

## 五、自托管完整流程

### 步骤 1: DNS 配置 (已完成 ✓)
```
qingmulife.cn    A    106.53.168.73
```

### 步骤 2: 部署 Management + Authentik (一键脚本)
```bash
ssh root@qingmulife.cn
bash install_all.sh
```

### 步骤 3: 安装客户端 (CT109 + 腾讯云本机)
```bash
# CT109 (PVE 容器)
ssh root@10.10.10.19
curl -sSL https://pkgs.netbird.io/install.sh | sh
netbird up --setup-key <从 dashboard 拿>
```

### 步骤 4: 验证 VPN 隧道
```bash
netbird status          # 显示: Connected, peers
wg show                 # 显示: wg0 接口, peers
ping <peer-ip>          # 测试 mesh 互通
```

---

## 六、Authentik + NetBird OIDC 集成

### 6.1 Authentik 端
```
1. 登录 https://qingmulife.cn/if/admin/ (默认 admin / 设置密码)
2. 创建 OIDC Provider:
   - Name: netbird
   - Authorization flow: default-provider-authorization-explicit-consent
   - Client type: Confidential
   - Redirect URI: https://qingmulife.cn/oauth2/callback
   - Scopes: openid, email, profile
3. 记下:
   - Issuer URL: https://qingmulife.cn/application/o/netbird/
   - Client ID: <UUID>
   - Client Secret: <secret>
```

### 6.2 NetBird 端 (写入 .env)
```bash
NETBIRD_USE_AUTH0=false
NETBIRD_AUTH_OIDC_CONFIGURATION_ENDPOINT=https://qingmulife.cn/application/o/netbird/.well-known/openid-configuration
NETBIRD_AUTH_CLIENT_ID=<Client ID>
NETBIRD_AUTH_AUDIENCE=netbird
```

---

## 七、P2P 隧道建立原理

```
1. 客户端启动 → 连 Management 注册 (443 HTTPS/gRPC)
2. Management 通过 Signal (443 WS) 交换 ICE 候选
   - 候选包括: 内网 IP、公网 IP、STUN 探测的公网 IP
3. 双方尝试直接 UDP 打洞 (WireGuard 51820/UDP)
4. 失败时:
   - 经 Coturn TURN 中继 (UDP 3478) 转发流量
   - 或经 Relay (TCP 443) WebSocket 兜底
5. 隧道建立后,分配 100.x.x.x mesh IP (NetBird 默认 100.64.0.0/10)
```

### 验证 P2P 状态
```bash
netbird status
# 显示:
#   Management: Connected to https://qingmulife.cn:443
#   Signal: Connected
#   ICE: Relaying (TURN)  ← 中继模式
#   ICE: Direct           ← P2P 打洞成功
```

---

## 八、客户端常用命令

```bash
# 状态
netbird status

# 列出 peers
netbird peer list

# 查看路由
netbird routes list

# 退出网络 (不禁用客户端)
netbird down

# 重新连接
netbird up

# 查看日志
journalctl -u netbird -f

# 允许 SSH/特定流量
netbird port add 22    # 把本机 22 端口暴露给所有 peer
```

---

## 九、故障排查

### 问题 1: 客户端连不上 Management
```bash
# 检查域名 DNS
dig +short A qingmulife.cn

# 检查防火墙
sudo ufw status
sudo iptables -L -n

# 检查管理服务
docker compose ps
docker compose logs management | tail -20

# 测试端点
curl -I https://qingmulife.cn/
```

### 问题 2: OIDC 登录失败
- 检查 Authentik redirect_uri 是否包含 `https://qingmulife.cn/oauth2/callback`
- 检查 NetBird .env 中 OIDC endpoint
- Authentik 日志: `docker compose logs authentik-server`

### 问题 3: P2P 一直 Relaying (不 Direct)
- 检查 UDP 3478 是否可达
- 检查路由器/防火墙是否阻挡 UDP 打洞
- 强制使用 relay: 在 dashboard 配置

### 问题 4: 客户端无法访问对方服务
- 检查路由表: `netbird routes list`
- 检查 ACL/Policy: dashboard → Policies
- 检查防火墙规则: 客户端本地 ufw

---

## 十、监控 + 维护

### 健康检查
```bash
# Management 健康
curl -s https://qingmulife.cn/api/readyz | jq

# Coturn 状态
docker compose logs coturn --tail 10
```

### 日志位置
```bash
# 服务端
/opt/netbird/artifacts/docker compose logs -f

# 客户端
journalctl -u netbird -f
```

### 备份
```bash
# Postgres 数据
docker compose exec postgres pg_dump -U authentik authentik > backup_$(date +%F).sql

# NetBird 配置
docker compose cp management:/var/lib/netbird/ ./backup/
```

### 升级
```bash
cd /opt/netbird/artifacts
docker compose pull
docker compose up -d --force-recreate
```

---

## 附录: 关键链接

- 官网: https://netbird.io
- 文档: https://docs.netbird.io
- GitHub: https://github.com/netbirdio/netbird
- License: BSD-3 (默认) + AGPLv3 (management/signal/relay)
- Authentik: https://goauthentik.io

---

**最后更新**: 2026-07-03
**部署主机**: 106.53.168.73 (qingmulife.cn)
**客户端**: CT109 (10.10.10.19) + 腾讯云本机
**相关文件**:
- `scripts/netbird/install_all.sh` (一键部署)
- `scripts/netbird/install_client.sh` (客户端安装)
- `scripts/netbird/verify_vpn.sh` (隧道验证)