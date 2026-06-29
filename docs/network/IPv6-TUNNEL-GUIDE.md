# RHYTHMIND IPv6 隧道部署指南

> **目标**: 实现云服务器 `2402:4e00:c013:7500:b4ea:cdb0:622a:0` (IPv6) ↔ 本地 `10.10.10.19` (IPv4) 双向 API 互访
> **方案**: 方案 1 — 本地 ISP 已支持 IPv6
> **日期**: 2026-06-29

---

## 架构图

```
┌────────────────────────┐                              ┌──────────────────────────┐
│  云服务器 (IPv6 only)  │                              │  本地 aisport.tech        │
│  2402:4e00:c013:7500:  │                              │  10.10.10.19 (IPv4)       │
│  b4ea:cdb0:622a:0      │                              │  2402:xxx::xxx (IPv6)     │
│                        │                              │                           │
│  ┌──────────────────┐  │         IPv6 互联网         │  ┌────────────────────┐  │
│  │ 后端/客户端       │  │   ◄───────────────────►   │  │  nginx (dual-stack) │  │
│  │ curl /api/...     │  │   HTTPS / 443              │  │  listen [::]:443     │  │
│  │                  │  │   ───────────────────►    │  │         │            │  │
│  │                  │  │                              │  │  proxy_pass         │  │
│  │                  │  │                              │  │    127.0.0.1:8000   │  │
│  │                  │  │                              │  │  ┌────────────────┐ │  │
│  │                  │  │                              │  │  │ uvicorn 后端  │ │  │
│  │                  │  │                              │  │  └────────────────┘ │  │
│  └──────────────────┘  │                              │  └────────────────────┘  │
└────────────────────────┘                              └──────────────────────────┘
```

---

## 步骤 0: 前提条件

- [x] 本地 ISP 已开通 IPv6 (向运营商确认)
- [x] 本地路由器/防火墙支持 IPv6 透传
- [x] 云服务器 `2402:4e00:c013:7500:b4ea:cdb0:622a:0` 可达
- [x] 本地有公网 IPv6 地址 (向运营商或路由器管理页面查询)

---

## 步骤 1: 服务器端部署 (10.10.10.19)

### 1.1 上传并执行部署脚本

```bash
# 在本地 Mac 上
scp scripts/ipv6/deploy_ipv6.sh root@10.10.10.19:/tmp/

# SSH 登录服务器
ssh root@10.10.10.19

# 在服务器上执行(交互式)
bash /tmp/deploy_ipv6.sh

# 或带参数
IPV6_ADDR="2402:xxx::xxx" IFACE=eth0 bash /tmp/deploy_ipv6.sh
```

### 1.2 部署脚本会做 6 件事

1. **检测现有 IPv6 配置** (网卡、路由、连通性)
2. **确认/添加公网 IPv6 地址** 到指定网卡
3. **添加默认 IPv6 路由** (若缺失)
4. **配置 ufw 防火墙** — 启用 IPv6,放行 8000/443/22
5. **生成 nginx dual-stack 配置** — 同时监听 IPv4 + IPv6
6. **验证本地 IPv6 出口** — ping6 云 + curl HTTPS

### 1.3 加载 nginx 新配置

```bash
sudo cp /etc/nginx/sites-enabled/qm_dual_stack.conf /etc/nginx/sites-enabled/qm_dual_stack.conf.bak
# (脚本已自动生成,只需测试 + 加载)
sudo nginx -t
sudo systemctl reload nginx
```

---

## 步骤 2: 云端配置 (2402:4e00:c013:7500:b4ea:cdb0:622a:0)

### 2.1 云安全组入站规则

| 协议 | 端口 | 源 | 用途 |
|------|------|-----|------|
| TCP | 443 | 本地 IPv6 段 | API HTTPS |
| TCP | 22 | 你的 IP | 维护 SSH |

### 2.2 云端 hosts / DNS 解析

如果想用域名 `aisport.tech` 访问本地(而不是 IPv6 地址),需要云端有 DNS 解析:
- 在云端的 `/etc/hosts` 加: `2402:xxx::xxx aisport.tech` (本地 IPv6)
- 或在云 DNS 服务商加 AAAA 记录

---

## 步骤 3: 验证双向互通

### 3.1 在云端执行(测 → 本地)

```bash
# 上传验证脚本到云
scp scripts/ipv6/verify_ipv6.sh root@2402:4e00:c013:7500:b4ea:cdb0:622a:0:/tmp/

# 在云上跑
ssh root@2402:4e00:c013:7500:b4ea:cdb0:622a:0
LOCAL_IPV4=10.10.10.19 LOCAL_IPV6=2402:xxx::xxx bash /tmp/verify_ipv6.sh
```

**期望结果**:
```
✓ ping6 → 2402:xxx::xxx 通
✓ ping → 10.10.10.19 通
✓ HTTP 200 (or 401/403)
✗ FAIL: 0
IPv6 互通验证通过!
```

### 3.2 在本地执行(测 → 云)

```bash
# 10.10.10.19 上
CLOUD_IPV6=2402:4e00:c013:7500:b4ea:cdb0:622a:0 bash /tmp/verify_ipv6.sh
```

---

## 步骤 4: 故障排查清单

### 问题 1: ping6 不通
- 检查本地 `ip -6 addr show` 是否有公网 IPv6
- 检查 ISP 是否真的给了 IPv6(部分运营商 CGNAT)
- 检查路由器是否放行 IPv6 入站
- 检查云安全组是否放行本地 IPv6 段

### 问题 2: HTTPS 502 Bad Gateway
- 检查后端 uvicorn: `curl http://127.0.0.1:8000/readyz`
- 检查 nginx: `sudo nginx -t` + `systemctl status nginx`
- 查看日志: `tail -f /var/log/nginx/aisport.tech.error.log`

### 问题 3: ufw 阻挡
- `sudo ufw status verbose`
- `sudo ufw allow from 2402:4e00:c013:7500::/48 to any port 443`
- 重启 ufw: `sudo systemctl restart ufw`

### 问题 4: 域名不解析(返回 IPv4)
- 检查 DNS AAAA 记录: `dig +short AAAA aisport.tech`
- 云端 hosts 文件加临时解析(测试用)

### 问题 5: SSH 失败
- 服务器换了 SSH key
- ufw 阻挡了 22
- 路由器限制了 IPv6 SSH

---

## 附录 A: 关键命令速查

### 本地服务器
```bash
# 查看 IPv6
ip -6 addr show
ip -6 route show

# 测试连通
ping6 2402:4e00:c013:7500:b4ea:cdb0:622a:0
curl -6 -k https://[2402:xxx::xxx]/qm/api/readyz

# 防火墙
sudo ufw status verbose
sudo ufw allow from 2402:4e00::/16 to any port 443

# nginx
sudo nginx -t
sudo systemctl reload nginx
sudo ss -tlnp | grep -E ':443|:8000'
```

### 云服务器
```bash
# 查看 IPv6
ip -6 addr show

# 测试到本地
ping6 2402:xxx::xxx
curl -6 -k https://[2402:xxx::xxx]/qm/api/readyz

# 监控
ss -tn | grep ':443'  # 看哪些客户端连接
```

---

## 附录 B: 常用 IPv6 资料

- [RFC 4291 - IPv6 Addressing Architecture](https://tools.ietf.org/html/rfc4291)
- [IPv6 入门 - 阿里云](https://help.aliyun.com/document_detail/44030.html)
- [Hurricane Electric Free IPv6 Tunnel](https://tunnelbroker.net/) (备选方案 2)
- [Test-IPv6.com](https://test-ipv6.com/) - 测试本地 IPv6 连通性

---

## 附录 C: 监控指标

部署后建议监控:
- `ip -6 addr show dev eth0` 是否有公网 IPv6
- `ufw status | grep 443` 规则是否生效
- `ss -tlnp | grep -E ':443|:8000'` nginx/uvicorn 监听
- `journalctl -u nginx -f` 实时 nginx 日志
- `journalctl -u rhythmind-api -f` 实时后端日志

---

**最后更新**: 2026-06-29
**相关文件**:
- `scripts/ipv6/deploy_ipv6.sh` (部署)
- `scripts/ipv6/verify_ipv6.sh` (验证)
- `deploy/nginx_dual_stack.conf` (nginx 配置)
