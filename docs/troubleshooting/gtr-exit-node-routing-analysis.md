# GTR Exit Node 路由规则分析

**日期:** 2026-06-08
**环境:** GTR (Ubuntu, Tailscale 1.98.4, Mihomo v1.19.20, K3s agent)
**目的:** 分析 GTR 作为 Tailscale exit node 时的完整路由规则，说明 2026-06-08 收敛后的配置与 DeepSeek / PackyAPI 访问修复

---

## 1. 当前路由架构概述

GTR 仍可见 **iptables-legacy + nftables** 混合状态，但 **exit node 角色本身已收敛**：

- **策略路由** 仍由 `tailscale-exitnode-fix.service` 安装 `rule 1000`
- **SNAT** 不再由自定义 nftables 规则补偿，而是回归 **Tailscale 自带 `ts-postrouting`**
- **站点分流** 新增 `deepseek.com` / `packyapi.com` 全域 `DIRECT`，避免代理链和站点 WAF 交互导致的异常

### 整体流量路径

```
客户端 (Tailscale IP: 100.x.x.x)
  │ Tailscale 加密隧道
  ▼
GTR tailscale0 接口
  │
  ├─ [iptables filter] ts-forward 链
  │     ├─ MARK 0x40000（标记 exit node 流量）
  │     └─ ACCEPT
  │
  ├─ [ip rule] 策略路由决策
  │     ├─ rule 1000: from 100.64.0.0/10 → table 2022 (Mihomo TUN)
  │     │      ├─ 目标=公网 IP     → Meta TUN → Mihomo 代理处理
  │     │      ├─ 目标=100.64.0.0/10 → 无路由（已排除）→ fallthrough
  │     │      ├─ 目标=192.168.x.x  → 无路由（已排除）→ fallthrough
  │     │      ├─ 目标=10.0.0.0/8   → 无路由（已排除）→ fallthrough
  │     │      └─ 目标=172.16.0.0/12 → 无路由（已排除）→ fallthrough
  │     ├─ rule 5270: from all → table 52 (Tailscale peer routes)
  │     ├─ rule 9000-9010: Mihomo TUN 自有规则
  │     └─ rule 32766: from all → main table（最终 fallback）
  │
  └─ [iptables nat] ts-postrouting
        └─ mark 0x40000 → MASQUERADE (Tailscale 管理 SNAT)
```

---

## 2. 策略路由详细分析

### 2.1 完整 ip rule 表（优先级从高到低）

```
优先级   规则
------   ----
0        from all lookup local                          # 本地流量
1000     from 100.64.0.0/10 lookup 2022                # 【Fix】Exit node 流量导入 Mihomo TUN
5210     from all fwmark 0x80000/0xff0000 lookup main   # K3s Flannel
5230     from all fwmark 0x80000/0xff0000 lookup default
5250     from all fwmark 0x80000/0xff0000 unreachable
5270     from all lookup 52                             # Tailscale peer routes
9000     from all to 198.18.0.0/30 lookup 2022          # Meta TUN loopback
9001     not from all dport 53 lookup main              # DNS bypass
9001     from all iif Meta goto 9010                    # Meta TUN 入站
9002     not from all iif lo lookup 2022                # 非 loopback 流量
9002     from 0.0.0.0 iif lo lookup 2022                # loopback 流量
9002     from 198.18.0.0/30 iif lo lookup 2022          # Meta loopback 流量
32766    from all lookup main                           # 主路由表 fallback
32767    from all lookup default                        # 默认路由表 fallback
```

### 2.2 关键规则解析

#### Rule 1000（exit node fix）
```bash
ip rule add from 100.64.0.0/10 lookup 2022 priority 1000
```
- **来源**: `tailscale-exitnode-fix.service` (Ansible 部署)
- **作用**: 将所有来自 Tailscale CGNAT 地址段（客户端 IP）的流量导入 Mihomo 的 table 2022
- **优先级 1000**: 高于 Tailscale 自有规则 (5270) 和 Mihomo TUN 规则 (9000-9010)
- **当前状态**: ✅ 已生效

#### Rule 5270（Tailscale）
```
from all lookup 52
```
- **来源**: Tailscale 自身
- **作用**: Tailscale peer 直连路由（如 100.100.99.70 → aliyun）
- **优先级 5270**: 低于 fix rule 1000，但高于 main table fallback

#### Rules 9000-9010（Mihomo TUN）
- **来源**: Mihomo `auto-route: true`
- **作用**: 控制 Meta TUN 接口的流量进出
- **优先级 9000+**: 低于 fix rule 1000，不影响 exit node 流量

### 2.3 Table 2022（Mihomo TUN 路由表）

由 Mihomo `auto-route: true` 创建，共约数百条路由，覆盖除排除段外的**所有公网 IP**：

```
0.0.0.0/5   via 198.18.0.2 dev Meta
8.0.0.0/7   via 198.18.0.2 dev Meta
...
223.0.0.0/5 via 198.18.0.2 dev Meta
```

**排除段**（由 Mihomo `route-exclude-address` 控制，不在 table 2022 中）：

| CIDR | 用途 | 排除原因 |
|------|------|---------|
| `192.168.0.0/16` | 本地 LAN | 防止 Mihomo TUN 劫持本地网络 |
| `10.0.0.0/8` | 私有网络 / K3s Pod CIDR | 防止破坏 K3s pod 网络 |
| `172.16.0.0/12` | Docker / 私有网络 | 防止破坏容器网络 |
| `100.64.0.0/10` | Tailscale CGNAT | 保持 Tailscale peer 直连 |
| `::/0` | 全部 IPv6 | 当前不使用 IPv6 |

> **注意**: 排除段中的流量会从 table 2022 fallthrough 到后续规则（table 52 或 main table），不会丢包。

### 2.4 Table 52（Tailscale peer routes）

```
100.100.99.70  dev tailscale0   # aliyun (control-plane)
100.99.48.76   dev tailscale0   # tencent (agent)
100.121.0.67   dev tailscale0   # gtr (self)
100.100.58.89  dev tailscale0   # WSL 客户端
...（共 22 条 peer 路由）
```

---

## 3. 防火墙规则分析

### 3.1 收敛后的职责分工

GTR 依然可能同时出现 `iptables-legacy` 与 `nftables`，但 **exit node 角色不再向 nftables 注入自定义 MASQUERADE 规则**：

| netfilter 表/链 | 后端 | 状态 | 说明 |
|----------------|------|------|------|
| `filter/FORWARD` | iptables-legacy | ✅ 生效 | Tailscale/K3s/kube-router 转发规则 |
| `nat/POSTROUTING` | iptables-legacy | ✅ 生效 | `ts-postrouting` + K3s/Flannel SNAT |
| `nat/POSTROUTING` | nftables | ⚠️ 可能存在 | 由 K3s/Flannel 或历史残留创建；**exit node 角色不依赖它** |
| `filter/INPUT` | iptables-legacy | ✅ 生效 | K3s 相关规则 |
| `filter/OUTPUT` | iptables-legacy | ✅ 生效 | K3s 相关规则 |

**关键收敛点**：

1. `tailscale-exitnode-fix.service` 只维护 `ip rule`
2. 旧版本遗留的 `nft add rule ip nat POSTROUTING oifname <WAN> masquerade` 会在部署时清理
3. Exit node 的 SNAT 统一回到 `tailscaled` 自己管理的 `ts-postrouting`

### 3.2 iptables-legacy filter/FORWARD（生效中）

```
Chain FORWARD (policy ACCEPT)
├─ KUBE-ROUTER-FORWARD    # kube-router 网络策略 (98K pkts, 53MB)
├─ KUBE-PROXY-FIREWALL    # K8s Service 防火墙 (709 pkts)
├─ KUBE-FORWARD           # K8s 转发规则 (60K pkts, 28MB)
├─ KUBE-SERVICES          # K8s Service (709 pkts)
├─ KUBE-EXTERNAL-SERVICES # K8s 外部 Service (709 pkts)
├─ ACCEPT (mark 0x20000)  # kube-router 网络策略放行 (644 pkts)
├─ ts-forward             # Tailscale forwarding (65 pkts, 18KB)
└─ FLANNEL-FWD            # Flannel 转发 (0 pkts)

Chain ts-forward (1 references)
├─ MARK 0x40000  (from tailscale0)  # 标记 exit node 入站流量 (74 pkts, 24KB)
├─ ACCEPT        (mark 0x40000)      # 放行已标记流量 (74 pkts, 24KB)
├─ DROP          (to tailscale0, src 100.64.0.0/10)  # 阻止 Tailscale IP 逆向出站 (0 pkts)
└─ ACCEPT        (to tailscale0)     # 放行其他出站流量 (0 pkts)
```

**ts-forward 链语义**：
1. 从 tailscale0 入站的流量 → 标记 `0x40000` → 放行（这包括 exit node 流量）
2. 以 tailscale0 为出接口、源 IP 在 100.64.0.0/10 的流量 → **DROP**（阻止 exit node 客户端流量反向注入 Tailscale 网络）
3. 其他出站 tailscale0 流量 → 放行

当前 exit node 流量统计：**74 个包 / 24KB**（有真实流量经过）。

### 3.3 iptables-legacy nat/POSTROUTING（exit node 依赖）

```
Chain POSTROUTING
├─ KUBE-POSTROUTING
├─ ts-postrouting
└─ FLANNEL-POSTRTG

Chain ts-postrouting
└─ MASQUERADE  mark match 0x40000/0xff0000
```

**ts-postrouting 语义**：

- 仅对被 `ts-forward` 标记为 `0x40000` 的 exit node 流量做 SNAT
- 比 “整块出接口全局 masquerade” 更精确
- 由 `tailscaled` 维护，角色只做存在性校验，不自行重建

### 3.4 nftables 状态（仅观察，不作为 exit node 依赖）

`nftables` 仍可能保留 `ip nat` / `ip6 nat` 表，原因通常有两类：

1. **K3s / Flannel** 在宿主机上注册自己的 NAT hook
2. **旧版 exit node role** 留下过 `oifname "<WAN>" masquerade` 规则

收敛后的角色会删除第 2 类旧规则，但 **不会擅自迁移 K3s / Flannel 的实现后端**。

### 3.5 nftables 完整表结构

GTR 上仍可能注册以下 nftables 表，这本身**不等于** exit node 还依赖 nftables：

| 表名 | 族 | 说明 |
|------|-----|------|
| `ip nat` | IPv4 | 可能由 Flannel/K3s 创建 |
| `ip mangle` | IPv4 | 可能存在但非 exit node 关键路径 |
| `ip raw` | IPv4 | 可能存在但非 exit node 关键路径 |
| `ip filter` | IPv4 | 可能存在但非 exit node 关键路径 |
| `ip6 mangle` | IPv6 | 可能存在但非 exit node 关键路径 |
| `ip6 filter` | IPv6 | 可能存在但非 exit node 关键路径 |
| `ip6 nat` | IPv6 | 可能存在但非 exit node 关键路径 |

---

## 4. Mihomo TUN 配置

### 4.1 TUN 接口

```yaml
tun:
  enable: true
  stack: mixed               # system + gvisor 混合栈
  auto-route: true           # 自动创建 table 2022 + ip rules 9000-9010
  auto-detect-interface: true
  dns-hijack:
    - any:53                 # 劫持所有 DNS 请求
    - tcp://any:53
  route-exclude-address:
    - 192.168.0.0/16
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 100.64.0.0/10
    - "::/0"
```

### 4.2 TUN 接口状态

```
Meta: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 9000
    inet 198.18.0.1/30    # Mihomo TUN 网关
    inet6 fdfe:dcba:9876::1/126
```

### 4.3 DNS 配置

```yaml
dns:
  enable: true
  listen: 100.121.0.67:53   # 监听 GTR Tailscale IP
  enhanced-mode: redir-host
  default-nameserver:
    - 223.5.5.5
    - 1.1.1.1
  nameserver:
    - 1.1.1.1
    - 8.8.8.8
```

### 4.4 代理链架构

```
┌─────────┐    ┌──────────────────┐
│ General  │───→│ Auto-via-Hy2Sal  │──→ Hysteria2-Salamander → subscription nodes
│(fallback)│    │ Auto-via-Hy2     │──→ Hysteria2-Remote    → subscription nodes
│          │    │ Auto-via-STLS    │──→ ShadowTLS-Remote    → subscription nodes
│          │    │ Auto             │──→ subscription nodes (直连, 无链式)
│          │    │ DIRECT           │──→ 直连
└─────────┘    └──────────────────┘
```

### 4.5 关键规则

```yaml
# Tailscale 直连（最高优先级）
- IP-CIDR,100.64.0.0/10,DIRECT
- IP-CIDR6,fd7a:115c:a1e0::/48,DIRECT

# 本地网络直连
- IP-CIDR,192.168.0.0/16,DIRECT
- IP-CIDR,10.0.0.0/8,DIRECT
- IP-CIDR,172.16.0.0/12,DIRECT

# 问题站点显式直连
- DOMAIN-SUFFIX,deepseek.com,DIRECT
- DOMAIN-SUFFIX,packyapi.com,DIRECT

# 域名级规则（依赖 Mihomo DNS 解析）
- DOMAIN-SUFFIX,github.com,GitHub
- DOMAIN-SUFFIX,openai.com,AI
- DOMAIN-SUFFIX,youtube.com,Streaming
...

# 兜底规则
- MATCH,General
```

---

## 5. 各场景流量路径追踪

### 5.1 场景 A：Exit node 客户端访问公网站点（如 github.com）

```
1. 客户端 (100.100.58.89) → github.com IP (20.205.243.166)
2. Tailscale 加密隧道 → GTR tailscale0
3. [iptables ts-forward] MARK 0x40000 → ACCEPT
4. [ip rule 1000] from 100.64.0.0/10 → table 2022
5. [table 2022] 20.0.0.0/7 → 198.18.0.2 dev Meta  ✅ 命中
6. Meta TUN → Mihomo 接收
7. Mihomo 规则匹配: 无域名信息 → IP 级规则 → MATCH,General
8. General fallback: Auto-via-Hy2Sal → Hysteria2-Salamander → 代理出口
9. 代理隧道 → 远端服务器 → Internet
10. 回程: 远端服务器 → GTR → Mihomo → Meta TUN → table 2022 → tailscale0 → 客户端

结果: ✅ 可访问（经 General 代理组）
```

### 5.2 场景 B：Exit node 客户端访问本地 LAN（192.168.31.59）

```
1. 客户端 (100.100.58.89) → 192.168.31.59 (GTR LAN IP)
2. Tailscale 加密隧道 → GTR tailscale0
3. [iptables ts-forward] MARK 0x40000 → ACCEPT
4. [ip rule 1000] from 100.64.0.0/10 → table 2022
5. [table 2022] 192.168.0.0/16 → 无路由（已排除） → fallthrough
6. [ip rule 5270] table 52 → 无 192.168 路由 → fallthrough
7. [ip rule 9000-9010] 不匹配 → fallthrough
8. [ip rule 32766] table main → 192.168.31.0/24 dev wlp4s0 ✅ 命中
9. [iptables nat] ts-postrouting MASQUERADE → src 100.x.x.x → 192.168.31.59
10. GTR 自身接收（dst 192.168.31.59）
11. GTR 服务响应 → conntrack UN-NAT → tailscale0 → 客户端

结果: ✅ 可访问
```

### 5.3 场景 C：Exit node 客户端访问 Tailscale 服务（如 argocd-argocd-server）

```
1. 客户端 → DNS 解析 grafana.tail414c32.ts.net → 100.100.99.70
2. Tailscale 加密隧道 → GTR tailscale0
3. [iptables ts-forward] MARK 0x40000 → ACCEPT
4. [ip rule 1000] from 100.64.0.0/10 → table 2022
5. [table 2022] 100.100.99.70 → 无路由（100.64.0.0/10 已排除） → fallthrough
6. [ip rule 5270] table 52 → 100.100.99.70 dev tailscale0 ✅ 命中
7. 经 tailscale0 → Tailscale 隧道 → aliyun → ArgoCD Server

结果: ✅ 可访问
```

### 5.4 场景 D：Exit node 客户端访问 K3s Pod（10.60.x.x）

```
1. 客户端 → 10.60.x.x (K3s Pod IP)
2. Tailscale 加密隧道 → GTR tailscale0
3. [iptables ts-forward] MARK 0x40000 → ACCEPT
4. [ip rule 1000] from 100.64.0.0/10 → table 2022
5. [table 2022] 10.0.0.0/8 → 无路由（已排除） → fallthrough
6. [ip rule 5270] table 52 → 无 10.60 路由 → fallthrough
7. [ip rule 9000-9010] 不匹配 → fallthrough
8. [ip rule 32766] table main → 10.60.0.0/24 via flannel.1 ✅ 命中
9. 经 flannel.1 VXLAN → K3s Pod

结果: ✅ 可访问
```

### 5.5 场景 E：Exit node 客户端访问 IPv6 站点

```
1. 客户端 → IPv6 目标
2. Tailscale 加密隧道 → GTR tailscale0
3. [ip rule 1000] from 100.64.0.0/10 → table 2022
4. [table 2022] IPv6 目标 → 无路由（::/0 已排除） → fallthrough
5. [ip rule 5270] table 52 → 无 IPv6 路由 → fallthrough
6. [ip rule 32766] table main → 无 IPv6 默认路由 → fallthrough
7. [ip rule 32767] table default → 无匹配 → 丢包

结果: ❌ 不可访问（IPv6 流量无路由）
```

### 5.6 场景 F：DNS 解析与域名规则

```
Exit node 客户端 DNS 解析路径（默认模式）：

1. 客户端 → DNS 查询 github.com
2. 客户端本地 DNS（非 Mihomo）→ 解析 → 20.205.243.166
3. 客户端 → 20.205.243.166:443（裸 IP，已无域名信息）
4. Mihomo 接收 → 规则匹配
   ├─ DOMAIN-SUFFIX,github.com,GitHub     → ❌ 不匹配（无域名）
   ├─ DOMAIN-SUFFIX,...                   → ❌ 均不匹配
   └─ MATCH,General                       → ✅ fallback 匹配

结果: ⚠️ 可访问，但走 General 而非 GitHub 专用代理组
```

**改进方式**: 在 Tailscale Admin Console 配置 exit node advertised DNS 为 GTR 的 Mihomo DNS（100.121.0.67:53），使客户端 DNS 查询经由 Mihomo 处理，启用完整域名级规则。

---

## 6. 已知问题与收敛结果

### 6.1 Exit node 自定义 nftables SNAT 冗余（已修复）

| 项目 | 详情 |
|------|------|
| **严重性** | 中（配置漂移 / 维护混淆） |
| **旧现象** | 角色额外注入 `nft add rule ip nat POSTROUTING oifname <WAN> masquerade` |
| **问题** | 与 Tailscale 自带 `ts-postrouting` 职责重叠，等于给 exit node 链路再叠一层自定义 NAT |
| **修复** | 角色停止创建该 nftables 规则，部署时清理旧遗留规则，SNAT 回归 `tailscaled` 管理 |
| **结论** | exit node 相关配置已收敛到“**自定义 ip rule + Tailscale 自带 SNAT**” |

### 6.2 DeepSeek / PackyAPI 分流不稳定（已修复）

| 项目 | 详情 |
|------|------|
| **严重性** | 高（直接对应用户故障） |
| **现象** | `deepseek.com` / `packyapi.com` 在 exit node 场景下命中代理组，表现为超时、WAF 或页面异常 |
| **原因** | 没有显式域名规则，DeepSeek 子域名会在 `DIRECT` / `General` 之间分裂；PackyAPI 落入 `MATCH,General` |
| **修复** | 新增 `DOMAIN-SUFFIX,deepseek.com,DIRECT` 与 `DOMAIN-SUFFIX,packyapi.com,DIRECT` |
| **结论** | 两个域名族统一直连，不再依赖代理链质量或节点地理位置 |

### 6.3 DNS 域名规则失效

| 项目 | 详情 |
|------|------|
| **严重性** | 中（功能降级，非中断） |
| **现象** | GitHub、AI、Streaming 等域名级规则全部跳过 |
| **原因** | Exit node 客户端使用本地 DNS 解析，Mihomo 只看到裸 IP |
| **影响** | 所有流量走 General fallback 组；无法按域名走最优代理 |
| **建议** | Tailscale Admin Console 配置 `advertised DNS = 100.121.0.67` |

### 6.4 监控指标语义已调整

| 项目 | 详情 |
|------|------|
| **旧指标** | `tailscale_exitnode_nft_masquerade_present` |
| **新指标** | `tailscale_exitnode_ts_postrouting_present` |
| **原因** | 监控目标从“角色自建 nftables MASQUERADE”切换为 “Tailscale 自带 ts-postrouting 是否仍存在” |
| **影响** | 监控口径与当前实现一致，不再鼓励恢复旧的自定义 nft 规则 |

### 6.5 IPv6 全面排除

| 项目 | 详情 |
|------|------|
| **严重性** | 中（对 IPv6-only 站点和客户端） |
| **配置** | `route-exclude-address: "::/0"` |
| **影响** | 所有 exit node 客户端 IPv6 流量无路由，直接丢包 |
| **建议** | 如有 IPv6 需求，调整为排除 `fc00::/7` + `fe80::/10`，保留全球 IPv6 路由 |

### 6.6 路由查找效率

| 项目 | 详情 |
|------|------|
| **严重性** | 低（性能影响极小） |
| **现象** | LAN/Tailscale peer 流量先被 rule 1000 引入 table 2022（无匹配），再逐条 fallthrough |
| **影响** | 每包多 3-5 次路由表查找，延迟增加 < 0.1ms |
| **建议** | 可优化 rule 1000 为仅在 table 2022 中有路由的目标才查表（需 ip rule 配合 suppress 参数） |

---

## 7. 关键配置来源

| 配置项 | 来源 | 文件 |
|--------|------|------|
| ip rule 1000 | Ansible | `mihomo/ansible/roles/tailscale-exitnode/templates/tailscale-exitnode-fix.service.j2` |
| ts-postrouting MASQUERADE | Tailscale 自身 | `iptables -t nat` |
| Mihomo TUN config | Ansible | `mihomo/ansible/roles/mihomo/templates/config.yaml.j2` |
| Tailscale peer routes | Tailscale 自身 | table 52 |
| ts-forward chain | Tailscale 自身 | iptables-legacy filter |
| K3s/Flannel rules | K3s + Flannel | iptables-legacy + nftables |

---

## 8. 故障排查命令速查

```bash
# 查看完整 ip rules
ip rule show

# 查看 Mihomo TUN 路由表
ip route show table 2022

# 查看 Tailscale peer 路由表
ip route show table 52

# 查看主路由表
ip route show table main

# 查看 iptables filter FORWARD（激活的）
sudo iptables -t filter -L FORWARD -n -v
sudo iptables -t filter -L ts-forward -n -v

# 查看 iptables nat POSTROUTING / ts-postrouting
sudo iptables -t nat -L POSTROUTING -n -v
sudo iptables -t nat -L ts-postrouting -n -v

# 如需确认是否仍有旧版角色遗留 nft 规则
sudo nft -a list chain ip nat POSTROUTING

# 查看 exit node fix 服务状态
systemctl status tailscale-exitnode-fix

# 查看 monitor 定时器状态
systemctl status tailscale-exitnode-monitor.timer

# 查看 Tailscale exit node 广告状态
tailscale status | grep "exit node"

# 跟踪实际 exit node 连接
sudo conntrack -L | grep -E 'src=100\.(6[4-9]|[7-9][0-9]|1[0-1][0-9]|12[0-7])'
```

---

## 9. 附录：修复脚本内容

### tailscale-exitnode-fix.service

```ini
[Unit]
Description=Tailscale Exit Node + Mihomo TUN routing fix
After=tailscaled.service mihomo.service
BindsTo=tailscaled.service
Wants=mihomo.service

[Service]
Type=oneshot
RemainAfterExit=yes

# Fix: Policy route Tailscale CGNAT traffic into Mihomo TUN
ExecStart=/bin/bash -c "/sbin/ip rule show | grep -q 'from 100.64.0.0/10 lookup 2022' || \
  /sbin/ip rule add from 100.64.0.0/10 lookup 2022 priority 1000"

# Cleanup on stop
ExecStop=/bin/bash -c "/sbin/ip rule show | grep -q 'from 100.64.0.0/10 lookup 2022' && \
  /sbin/ip rule del from 100.64.0.0/10 lookup 2022 priority 1000 || true"

[Install]
WantedBy=multi-user.target
```

### 当前设计说明

- `tailscale-exitnode-fix.service` 只负责 `ip rule`
- `ts-postrouting` 由 `tailscaled` 自己维护
- 如仍看到 `nftables POSTROUTING` 中有裸 `oifname "<WAN>" masquerade`，应视为旧版本残留并清理
