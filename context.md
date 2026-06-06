# K3s 跨节点网络不通 — 根因分析 & Troubleshooting 上下文

> 生成时间: 2026-06-07
> 任务: 分析 K3s 集群中 Pod 跨节点通信失败的根本原因，输出给后续 agent 进行修复

---

## 一、集群拓扑与当前配置

### 节点列表

| 角色 | 节点 | Tailscale IP | Ansible Inventory 组 | 当前部署 playbook |
|------|------|-------------|---------------------|-------------------|
| **Server** (control-plane) | aliyun | `100.102.140.59` | `edge_aliyun` | `deploy-gtr-k3s-server.yml` |
| **Agent** | gtr | `100.121.0.67` | `gtr_core` | `deploy-gtr-k3s-agent.yml` |
| **Agent** | tencent | `100.99.48.76` | `edge_tencent` | `deploy-gtr-k3s-agent.yml` |
| **(非 K3s 节点)** | remote_proxy | `100.66.156.40` | `edge_remote_proxy` | 无 K3s 部署 |

> ⚠️ `remote_proxy` **不是** K3s 节点。`deploy-gtr-k3s-agent.yml` 只覆盖 `gtr_core:edge_tencent`，不包含 `edge_remote_proxy`。

### 网络 CIDR

| 网段 | 值 | 说明 |
|------|-----|------|
| Pod CIDR (k3s) | `10.60.0.0/16` | Flannel 分配的子网 |
| Service CIDR (k3s) | `10.61.0.0/16` | K3s Service 虚拟 IP |
| Cluster DNS | `10.61.0.10` | CoreDNS Service IP |
| Tailscale CGNAT | `100.64.0.0/10` | 所有节点都在此范围 |
| Tailscale /32 端点 | `100.102.140.59/32`, `100.121.0.67/32`, `100.99.48.76/32` | 节点 IP 是点对点 /32 地址 |

### Flannel 配置

```
flannel-backend: "wireguard-native"
```

- 文件中无 `flannel-iface` 设置 → Flannel 使用默认接口（即 `node-ip` 对应的路由出口）
- `node-ip`: 每个节点设置为自己的 Tailscale IP
- `advertise-address` (server): `100.102.140.59`

### 关键配置文件路径

| 文件 | 说明 |
|------|------|
| `edge/ansible/group_vars/all/public.yml` | 共享变量，第 112-132 行是 k3s 配置 |
| `edge/ansible/host_vars/aliyun/public.yml` | aliyun 特有变量（server IP, registry mirrors） |
| `edge/ansible/host_vars/gtr/public.yml` | GTR 特有变量（localhost proxy） |
| `edge/ansible/host_vars/tencent.yml` | tencent 特有变量 |
| `edge/ansible/roles/k3s-server/templates/config.yaml.j2` | Server config 模板 |
| `edge/ansible/roles/k3s-agent/templates/config.yaml.j2` | Agent config 模板（仅 4 行） |
| `edge/ansible/roles/k3s-prereq/defaults/main.yml` | 预置包/模块/sysctl 清单 |
| `edge/ansible/roles/k3s-prereq/tasks/main.yml` | 预置安装逻辑 |
| `mihomo/ansible/group_vars/all/public.yml` | Mihomo 配置（DNS、TUN） |
| `docs/issues/007-k3s-flannel-tailscale-crashloop.md` | 历史 crashloop 诊断文档 |

---

## 二、跨节点网络不通的潜在根因（按可能性排序）

### ⚠️ 根因 1（最可能）：WireGuard-over-WireGuard 双重封装 + MTU 断裂

**问题机制：**

```
Pod A (10.60.1.2)
  └→ [flannel.wg] → WireGuard 封装 (加 60 bytes 头)
       └→ 目标: 100.99.48.76:51820 (Tailscale IP + Flannel WG 端口)
            └→ [tailscale0] → WireGuard 再次封装 (加 80 bytes 头)
                 └→ 目标: tencent 公网 IP
                      └→ [tailscale0] decap → [flannel.wg] decap → Pod B (10.60.2.3)
```

- Tailscale0 默认 MTU = **1280**
- Flannel WireGuard 添加 ~60 bytes 头
- 所以 Pod 实际可用 MTU = 1280 - 60 = **~1220**（甚至更少，取决于 IP/UDP 头叠加）
- 标准以太网 MTU = 1500，TCP 通常使用 MSS = 1460
- 应用层发 1460 bytes 的 TCP 数据包 → IP 层分片或 PMTUD 失败 → 连接黑洞

**受影响流量：** 所有跨节点的 Pod 间 TCP 连接。大包（>1220 bytes）会被静默丢弃。

**证据：** tailscale0 的 MTU 为 1280 是 Tailscale 默认值（在 `tailscale up` 时未指定 `--mtu` 的情况下）。Flannel WireGuard 封装头约 60 bytes。Pod 的 `subnet.env` 如无覆盖则默认 1500。

### ⚠️ 根因 2：Mihomo TUN 模式拦截 K3s Pod 流量（GTR 节点独有）

**问题机制：**

Mihomo TUN 的 `route-exclude-address` 列表：
```yaml
route-exclude-address:
  - 192.168.0.0/16
  - 10.0.0.0/8
  - 172.16.0.0/12
  - 100.64.0.0/10
  - "::/0"
```

- `10.0.0.0/8` 包括 `10.60.0.0/16`（K3s Pod CIDR）！
- 这意味着 GTR 上的 K3s Pod 发送到其他节点 Pod（10.60.x.x）的流量**只会被路由排除，不进入 TUN**
- 但 Tats 上排除路由 ≠ 不需要正确路由。排除只是说"不劫持到 TUN 接口"，但系统路由表必须正确指向 Flannel 的 WireGuard 接口
- 如果 Flannel 的 WireGuard 路由不存在或错误，排除路由的 Pod CIDR 流量会走**默认路由** → 丢包

**关键测试：** 在 GTR 上 `ip route show | grep 10.60` 查看 Flannel 子网路由是否正确指向 `flannel.wg` 接口。

**潜在冲突：**
- Tailscale 有自己的路由表（table 52）
- Flannel 在 main 表中操作路由
- Mihomo TUN 在 main 表中添加策略路由

### ⚠️ 根因 3：Flannel WireGuard 在 /32 地址上的路由问题

**问题机制：**

- Flannel `wireguard-native` backend 需要在每个节点上建立到其他节点的 WireGuard peer
- 每个 peer 的 Endpoint 是目标节点的 `node-ip`（Tailscale IP，如 `100.102.140.59`）
- Tailscale IP 是 **/32 点对点地址**，不是标准可路由广播地址
- Flannel WireGuard 需要发送 UDP 包到 `100.99.48.76:51820`，这个包必须被正确路由到 tailscale0
- 如果 tailscale0 的路由优先级、策略或 nftables 规则干扰，WireGuard 握手会失败
- Flannel WG peer 建立失败 → Pod 子网不通

**验证命令（在各节点执行）：**
```bash
# 检查 Flannel WireGuard 接口
ip link show flannel.wg 2>/dev/null || ip link show flannel.1 2>/dev/null

# 检查 wireguard peer 状态
wg show flannel.wg 2>/dev/null || echo "no flannel.wg"

# 检查 flannel 子网路由
ip route show | grep 10.60

# 检查 tailscale 路由表
ip route show table 52
```

### ⚠️ 根因 4：Flannel `net.bridge.bridge-nf-call-iptables=1` 对 WireGuard 接口的副作用

- K3s prereq 设置了 `net.bridge.bridge-nf-call-iptables=1`
- 这对 bridge 设备有用，但 WireGuard 接口**不是 bridge**
- nftables/iptables 的 FORWARD 链中存在的 DOCKER 遗留规则（见 issue #008）可能仍然存在
- GTR 上 Docker 已卸载，但 `nft` 规则中的 `DOCKER-FORWARD`、`FLANNEL-FWD` 等链可能仍有引用
- 当 Pod 流量经过 FORWARD 链时，被跳转到 DOCKER 规则造成额外延迟或丢弃

### ⚠️ 根因 5：GTR 旧 K3s server 残留 vs 新的 K3s agent

**历史背景：**
- 原拓扑：GTR = K3s server（已崩溃 crashloop，问题在 issue #007 分析）
- 新拓扑：aliyun = K3s server, GTR = K3s agent
- 迁移执行后，GTR 上的旧 `k3s` server service 需要被完全停止并清理

**可能的问题：**
- GTR 上旧 K3s server 的 `k3s-killall.sh` 未执行
- 残留的 `flannel.1`（VXLAN 接口）与新的 `flannel.wg`（WireGuard 接口）冲突
- 残留的 iptables/nftables 规则（FLANNEL-POSTRTG, FLANNEL-FWD）与新的 Flannel 规则冲突
- `/var/lib/rancher/k3s/server/` 中的数据未清理

### ⚠️ 根因 6：Cluster DNS (10.61.0.10) 与 Mihomo DNS (100.121.0.67:53) 的交互

- GTR 上 Mihomo DNS 监听 `100.121.0.67:53`，enhanced-mode: `redir-host`
- K3s Cluster DNS 在 `10.61.0.10`，是 CoreDNS Service 的 Cluster IP
- 当 GTR 上的 Pod 解析 `svc.cluster.local` 时，DNS 请求到 `10.61.0.10` → CoreDNS
- CoreDNS 需要解析外部域名时，会向节点 `/etc/resolv.conf` 指定的上游 DNS 查询
- 如果 `resolv.conf` 被 Mihomo TUN 的 DNS hijack 劫持 → CoreDNS 的外部查询可能被 Mihomo 重定向
- 虽然 10.0.0.0/8 在 route-exclude 中，但 DNS 是应用层（UDP 53），可能被 Mihomo 的 `dns-hijack: any:53` 捕获

---

## 三、建议的故障排查步骤

### 步骤 1：验证集群基本健康

在 aliyun server 上执行（SSH 可通过 CI 或直接通过 Tailscale）：

```bash
# 节点状态
k3s kubectl get nodes -o wide

# Pod 状态（检查 kube-system 核心组件）
k3s kubectl get pods -n kube-system -o wide

# Flannel Pod 日志
k3s kubectl -n kube-system logs -l k8s-app=flannel --tail=50
```

### 步骤 2：验证 Flannel WireGuard 隧道

**在 aliyun 上：**
```bash
# 确认 Flannel WG 接口存在
ip link show flannel.wg
wg show flannel.wg

# 检查 peer 列表（应该有 gtr 和 tencent 的 peer）
# 检查每个 peer 的 endpoint、allowed-ips、latest-handshake

# 检查路由
ip route show | grep 10.60

# MTU 确认
ip link show flannel.wg | grep mtu
```

**在 gtr 和 tencent 上重复同样的检查。**

### 步骤 3：MTU 测试

```bash
# 在 aliyun 部署一个测试 Pod
k3s kubectl run test-pod --image=alpine -- sleep 3600

# 从不同节点测试 MTU（在 aliyun / gtr / tencent 上分别部署并互相 ping）
k3s kubectl exec -it test-pod -- ping -c 3 -M do -s 1200 <other-pod-ip>
k3s kubectl exec -it test-pod -- ping -c 3 -M do -s 1400 <other-pod-ip>
k3s kubectl exec -it test-pod -- ping -c 3 -M do -s 1472 <other-pod-ip>

# -M do = DF flag set, -s = payload size
# 如果 1472 失败但 1200 成功，证明 MTU 问题
```

### 步骤 4：nftables/iptables 规则检查

**特别是 GTR 节点（曾运行 Docker，可能有残留规则）：**
```bash
# 检查 nat 表
nft list table ip nat

# 检查 filter 表 FORWARD 链
nft list chain ip filter FORWARD

# 检查是否有 FLANNEL 链和 DOCKER 链
nft list table ip filter | grep -E "chain (FLANNEL|DOCKER)"

# 检查 conntrack 对 WireGuard 流量的处理
conntrack -L | grep 51820
```

### 步骤 5：检查 GTR 旧 K3s server 残留

```bash
# 检查是否还有 k3s server 进程
systemctl status k3s
ps aux | grep k3s

# 检查残留接口
ip link show flannel.1 2>/dev/null && echo "OLD VXLAN interface still exists!"
ip link show cni0 2>/dev/null

# 检查残留数据
ls -la /var/lib/rancher/k3s/server/ 2>/dev/null

# check current k3s-agent
systemctl status k3s-agent
journalctl -u k3s-agent --no-pager -n 50
```

### 步骤 6：Flannel WireGuard 端口可达性

```bash
# Flannel WG 默认端口是 51820（UDP）
# 测试节点间 51820 端口是否可达（通过 Tailscale IP）
# 在 aliyun 上：
nc -zu -w 3 100.99.48.76 51820
nc -zu -w 3 100.121.0.67 51820

# 在 gtr 上：
nc -zu -w 3 100.102.140.59 51820
nc -zu -w 3 100.99.48.76 51820

# 在 tencent 上：
nc -zu -w 3 100.102.140.59 51820
nc -zu -w 3 100.121.0.67 51820
```

> 如果 `nc` 不可用，可用 `nmap` 或查看 `wg show` 的 `latest-handshake` 时间戳。

---

## 四、修复方案候选

### 方案 A：Flannel 改用 `host-gw` backend（推荐优先尝试）

```yaml
# group_vars/all/public.yml
k3s_flannel_backend: host-gw
```

- **原理：** 所有节点通过 Tailscale 三层可达，`host-gw` 只需添加静态路由，无需额外封装
- **优点：** 零封装开销，无 MTU 问题，无需 WireGuard 握手
- **缺点：** 无加密（但已有一层 Tailscale 加密），不支持跨网段自动路由
- **适用性：** 本次拓扑中所有节点都在 Tailscale 同一子网，完全满足条件

### 方案 B：Flannel 显式限制 MTU

保留 `wireguard-native` 但显式设置 Flannel MTU：

```yaml
# Flannel 配置中加 MTU
flannel-backend: wireguard-native
# 或在 K3s 启动参数中加
--flannel-backend=wireguard-native --flannel-mtu=1200
```

> K3s 支持 `--flannel-mtu` 参数，但需要在 installer 脚本中传递到 K3s exec 参数。

### 方案 C：将 Flannel backend 改为 VXLAN（非 tailscale0）

```yaml
k3s_flannel_backend: vxlan
# 需要指定正确的接口（tailscale0 在 issue #007 被证明有 crashloop 问题）
# 但用 vxlan 不加 flannel-iface 的话，Flannel 会自动选 eth0（公网 IP），Pod 流量走公网明文
```

### 方案 D：Tailscale subnet routes + 禁用 Flannel

```yaml
k3s_disable_network_policy: true
# 在 Tailscale 上为各节点设置 subnet routes
# 但需要大幅修改架构，不推荐
```

### 推荐优先级

1. **先执行故障排查步骤 1-6**，确认确切根因
2. 如果确定是 **MTU 断裂**（步骤 3 确认）：采用**方案 A（host-gw）**
3. 如果确定是 **WireGuard 握手失败**（步骤 6 确认）：检查防火墙规则，采用**方案 A（host-gw）**
4. 如果确定是 **GTR 旧 server 残留**：执行 issue #007 中的清理步骤
5. 如果确定是 **Mihomo TUN 拦截**：在 Mihomo config 中明确添加 `10.60.0.0/16` 到 `route-exclude-address`

---

## 五、关键文件索引

| 文件路径 | 行号 | 内容相关 |
|----------|------|---------|
| `edge/ansible/group_vars/all/public.yml` | L112-132 | K3s 全局变量（CIDR, flannel-backend, containerd proxy） |
| `edge/ansible/group_vars/all/public.yml` | L117 | `k3s_flannel_backend: wireguard-native` |
| `edge/ansible/host_vars/aliyun/public.yml` | L6-9 | aliyun server vars: `k3s_server_tailscale_ip`, `k3s_server_tls_sans` |
| `edge/ansible/host_vars/aliyun/public.yml` | L12-15 | aliyun 的 containerd registry mirrors（阿里云镜像） |
| `edge/ansible/host_vars/gtr/public.yml` | L4-6 | GTR 使用 localhost proxy（`127.0.0.1:7890`） |
| `edge/ansible/roles/k3s-server/templates/config.yaml.j2` | L1-16 | Server config: `flannel-backend`, `cluster-cidr`, `service-cidr`, `advertise-address`, `node-ip` |
| `edge/ansible/roles/k3s-server/tasks/main.yml` | L3-9 | 断言 `k3s_cluster_token` |
| `edge/ansible/roles/k3s-server/tasks/main.yml` | L12-30 | 读取 Tailscale IP, 渲染 config.yaml + registries.yaml |
| `edge/ansible/roles/k3s-agent/templates/config.yaml.j2` | L1-4 | Agent config: `server: https://100.102.140.59:6443`, `node-ip` |
| `edge/ansible/roles/k3s-agent/tasks/main.yml` | L17-20 | Agent 通过 `tailscale ip -4` 获取 node-ip |
| `edge/ansible/roles/k3s-prereq/defaults/main.yml` | L16-20 | sysctl: `net.ipv4.ip_forward=1`, `bridge-nf-call-iptables=1` |
| `edge/ansible/roles/k3s-prereq/defaults/main.yml` | L10-12 | 内核模块: `wireguard`, `overlay`, `br_netfilter` |
| `edge/ansible/inventory-edge.ini` | L1-12 | 所有节点经 Tailscale IP 连接 |
| `edge/ansible/deploy-gtr-k3s-agent.yml` | L3 | **只部署到** `gtr_core:edge_tencent`，不含 `edge_remote_proxy` |
| `mihomo/ansible/group_vars/all/public.yml` | L40 | `mihomo_dns_listen: 100.121.0.67:53` |
| `mihomo/ansible/group_vars/all/public.yml` | L41 | `mihomo_enhanced_mode: redir-host` |
| `mihomo/ansible/roles/mihomo/templates/config.yaml.j2` | L30-34 | `route-exclude-address` 含 `10.0.0.0/8`（涵盖 `10.60.0.0/16`）|
| `mihomo/ansible/roles/mihomo/templates/config.yaml.j2` | L27 | `dns-hijack: any:53` |
| `docs/issues/007-k3s-flannel-tailscale-crashloop.md` | 全文 | 旧 crashloop 分析（flannel-iface: tailscale0 导致 kube-proxy 崩溃） |
| `docs/issues/008-docker-nftables-conflict-analysis.md` | 全文 | Docker nftables 残留规则分析 |

---

## 六、已知约束和注意事项

1. **`remote_proxy` 不是 K3s 节点** — 如果有 Pod 需要调度到 remote_proxy，需要修改 `deploy-gtr-k3s-agent.yml` 增加 `edge_remote_proxy` 组，并添加对应 host_vars。

2. **Flannel 从 issue #007 的 `flannel-iface: tailscale0` 改为现在的 `wireguard-native` 无 `flannel-iface`** — 不再使用 tailscale0 作为 Flannel 接口，但 `node-ip` 仍为 Tailscale IP，Flannel WG 隧道建在 Tailscale IP 之上。

3. **K3s 禁用了 `servicelb` 和 `traefik`** — LoadBalancer Service 和 Ingress Controller 都不可用。服务暴露走 Tailscale Operator（已部署但 SealedSecret OAuth 可能未就位）。

4. **GTR 曾运行旧 K3s server（已 crashloop）** — 迁移到 aliyun server 后，GTR 上的旧 k3s server 需要完全清理。但 deploy playbook 的 idempotency 检查（`systemctl is-active k3s-agent`）只在已有 agent 运行时跳过安装，不会主动清理旧 server 残留。

5. **Mihomo TUN 运行在 GTR 上** — 它劫持所有非排除地址的流量。K3s Pod CIDR `10.60.0.0/16` 被 `10.0.0.0/8` 排除规则覆盖，所以不被 TUN 劫持。但 K3s Service CIDR `10.61.0.0/16` **也在** `10.0.0.0/8` 范围内，同样被排除。所以 K3s 内部流量理论上不会被 Mihomo 劫持，但需要验证路由表正确。

6. **containerd image pull proxy** 已配置 — 非 GTR 节点通过 `gtr.tail414c32.ts.net:7890`（Mihomo HTTP proxy）拉取镜像，GTR 用 `127.0.0.1:7890`，aliyun 用阿里云镜像。这不应影响数据面网络。

7. **Docker 已于 2026-06-07 从 GTR 卸载** — 但 nftables 中的 DOCKER 遗留规则可能仍然存在（`DOCKER-FORWARD`, `DOCKER-CT` 等链），见 issue #008。这些规则可能干扰 Flannel 的 FORWARD 处理。
