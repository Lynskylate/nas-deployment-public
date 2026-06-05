## Tailscale Exit Node + Mihomo TUN 链式路由故障排查与修复

**日期:** 2026-05-31
**环境:** GTR (Ubuntu, Tailscale 1.98.4, Mihomo v1.19.20, Docker) + Windows 客户端 (tele)
**修复状态:** 已通过 Ansible 固化部署，端到端验证通过

---

## 问题现象

将 GTR 设为 Tailscale exit node 后，客户端无法访问 github.com（以及所有国际站点）。Tailscale 基础连通性正常——`tailscale ping gtr` 可以 pong，gtr 自身 `curl github.com` 返回 HTTP 200。

---

## 根因分析

故障由两个独立问题叠加导致，二者缺一不可。

### 问题 1：Tailscale 未安装 MASQUERADE 规则

GTR 的 nftables NAT 表中，`ts-postrouting` 链虽然被 Tailscale 创建了，但从未被挂载到主 POSTROUTING 链上，链内也没有任何 MASQUERADE 规则。

```
# 实际状态（修复前）
table ip nat {
    chain POSTROUTING {
        type nat hook postrouting priority srcnat; policy accept;
        # 空的 —— 没有 jump 到 ts-postrouting，没有 masquerade
    }
    chain ts-postrouting {
        # 空的，且从未被引用
    }
}
```

Tailscale 的配置显示 `NoSNAT: false`、`NetfilterMode: 2`（on）、`firewallmode: "ipt-default"`，说明它"认为"自己应该做 SNAT，但规则实际上没有被写入。

**推测原因：** GTR 上同时运行 Docker，Docker 也在 nftables 中创建了自己的链（DOCKER、DOCKER-USER、DOCKER-BRIDGE 等）。Docker 的链管理与 Tailscale 的链管理产生了冲突，导致 Tailscale 的 MASQUERADE 规则没有被正确安装。

**影响：** Exit node 转发的流量带着 Tailscale 私有源 IP（100.64.0.0/10）直接离开物理网卡 wlp4s0，上游路由器因源地址不可路由而丢弃。

### 问题 2：Exit node 流量完全绕过了 Mihomo TUN

GTR 上的策略路由规则表如下：

```
0:    from all lookup local
5210: from all fwmark 0x80000/0xff0000 lookup main
5250: from all fwmark 0x80000/0xff0000 unreachable
5270: from all lookup 52                              # Tailscale 路由表
9001: from all iif Meta goto 9010 [unresolved]        # Mihomo TUN 捕获
32766: from all lookup main
32767: from all lookup default
```

关键规则 9001 只对从 `Meta`（Mihomo TUN 接口）**进入**内核的流量生效。而 exit node 的流量是从 `tailscale0` 接口进入内核的，其路由路径为：

```
tailscale0 入站 → rule 5270 (table 52, 只有 peer 路由) → 无匹配
→ rule 32766 (main table) → default via 192.168.31.1 dev wlp4s0 → 直接出去
```

Mihomo 的路由表 table 2022（包含通过 Meta TUN 的全量路由）只在 rule 9001 中被引用，而 rule 9001 要求入站接口为 Meta。Exit node 流量从 tailscale0 入站，完全跳过了 table 2022，因此没有进入 Mihomo TUN，也没有经过任何代理处理。

**影响：** 即使 MASQUERADE 存在，流量也是直连出去（不经代理），在中国网络环境下被 GFW 阻断。

---

## 修复方案

### Fix 1：手动添加 MASQUERADE

```bash
sudo nft add rule ip nat POSTROUTING oifname wlp4s0 masquerade
```

确保从 tailscale0 转发出来的流量在离开 wlp4s0 时做源地址伪装。

### Fix 2：策略路由将 Tailscale 流量导入 Mihomo

```bash
sudo ip rule add from 100.64.0.0/10 lookup 2022 priority 5260
```

让源 IP 属于 Tailscale CGNAT 地址段的流量走 Mihomo 的 table 2022，从而进入 Meta TUN 被 Mihomo 处理。Priority 5260 位于 Tailscale 的 5250 和 5270 之间。

### 流量路径（修复后）

```
客户端 → Tailscale 隧道 → gtr tailscale0
    → ip rule 5260 (from 100.64.0.0/10) → table 2022
    → Meta TUN → Mihomo 规则匹配 → 代理出口
    → wlp4s0 (MASQUERADE) → 互联网
```

---

## 永久固化：Ansible 部署

### 文件结构

```
mihomo/ansible/
├── deploy-exitnode.yml              # 部署 playbook
├── verify-exitnode.yml              # 验证 playbook
├── group_vars/all/public.yml        # 追加了 exit node 相关公开变量
└── roles/tailscale-exitnode/
    ├── tasks/main.yml               # 前置检查 + 部署 + 验证
    ├── templates/
    │   └── tailscale-exitnode-fix.service.j2   # systemd oneshot service
    └── handlers/main.yml            # reload systemd / restart service
```

### 关键变量（group_vars/all/public.yml）

```yaml
tailscale_exitnode_wan_iface: wlp4s0     # GTR 的物理出网接口
tailscale_cidr: 100.64.0.0/10            # Tailscale CGNAT 地址段
mihomo_route_table: 2022                  # Mihomo auto-route 的路由表 ID
tailscale_exitnode_rule_priority: 5260    # ip rule 优先级
nft_binary: /usr/sbin/nft
ip_binary: /sbin/ip
```

### Systemd Service 设计

`tailscale-exitnode-fix.service` 是一个 oneshot 服务，`RemainAfterExit=yes`，在启动时添加规则，停止时清理规则。所有操作均为幂等设计（先检查是否存在，再决定是否添加/删除），避免重复执行时报错。

```ini
[Unit]
After=tailscaled.service mihomo.service
Wants=tailscaled.service mihomo.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'nft list ... | grep -q masquerade || nft add rule ...'
ExecStart=/bin/bash -c 'ip rule show | grep -q ... || ip rule add ...'
ExecStop=/bin/bash -c '... nft delete rule ... || true'
ExecStop=/bin/bash -c '... ip rule del ... || true'
```

### 部署命令

```bash
cd mihomo/ansible
ansible-playbook -i inventory.ini deploy-exitnode.yml
ansible-playbook -i inventory.ini verify-exitnode.yml
```

---

## 验证结果

### 端到端测试（WSL tele-1 → gtr exit node → 互联网）

| 目标 | HTTP 状态 | 响应时间 | 备注 |
|------|----------|---------|------|
| github.com | 200 | 0.44s | 通过 General 代理组（香港 IEPL） |
| google.com | 200 | 0.37s | 通过 General 代理组（香港 IEPL） |
| api.ipify.org | 200 | — | 出口 IP: 103.151.172.13（代理节点） |

### Mihomo 日志确认

```
[TCP] 100.100.58.89:38488 --> 20.205.243.166:443 match Match using General[香港A02 | IEPL]
[TCP] 100.100.58.89:52516 --> 104.26.13.205:443 match Match using General[香港A02 | IEPL]
[TCP] 100.100.58.89:49324 --> 142.251.150.119:443 match Match using General[香港A02 | IEPL]
```

源 IP 100.100.58.89 为 WSL 客户端的 Tailscale IP，确认流量经过了 Mihomo TUN 和代理链。

---

## 已知遗留：DNS 与域名级规则

当前 exit node 客户端的 DNS 解析走本地 DNS（非 Mihomo），导致 Mihomo 没有 domain→IP 的映射记录。后果是域名级规则（如 GitHub 专用代理组）无法匹配，流量只能通过 IP 级规则（GeoIP）或 Match fallback 到 General 组。

功能上不影响使用（github.com 通过 General 组正常访问），但未走最优路由策略。

**后续修复方向：** 通过 Tailscale Admin Console 配置 exit node  advertised DNS 为 100.121.0.67（GTR 的 Mihomo DNS 监听地址），使客户端 DNS 查询经由 Mihomo 处理，从而启用完整的域名级规则匹配。

---

## 排查过程中的关键命令参考

```bash
# 检查 Tailscale exit node 状态
tailscale status
tailscale exit-node list
tailscale debug prefs

# 检查 GTR 上的 nftables NAT 规则
sudo nft list table ip nat
sudo iptables -t nat -S

# 检查 GTR 上的策略路由
sudo ip rule show
sudo ip route show table 2022

# 检查 Mihomo TUN 接口
ip addr show Meta

# 检查 Mihomo 日志（过滤特定客户端 IP）
sudo journalctl -u mihomo --no-pager -n 20 | grep <client-tailscale-ip>

# 检查 Tailscale firewall 模式
sudo journalctl -u tailscaled --no-pager | grep firewallmode
```
