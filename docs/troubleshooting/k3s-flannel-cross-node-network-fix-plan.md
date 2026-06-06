# K3s Flannel 跨节点网络修复方案

## 问题复述

K3s 集群（aliyun server + GTR agent + tencent agent）跨节点 Pod 网络不通。

### 当前配置

```yaml
# group_vars/all/public.yml
k3s_flannel_backend: wireguard-native
k3s_cluster_cidr: 10.60.0.0/16
k3s_server_url: https://100.102.140.59:6443   # aliyun Tailscale IP
```

Server config.yaml.j2 渲染后：
```yaml
cluster-cidr: "10.60.0.0/16"
advertise-address: "100.102.140.59"   # Tailscale IP
node-ip: "100.102.140.59"             # Tailscale IP
flannel-backend: "wireguard-native"
```

Agent config.yaml.j2 渲染后（以 GTR 为例）：
```yaml
server: "https://100.102.140.59:6443"
node-ip: "100.121.0.67"              # Tailscale IP
```

### 现象

| 节点 | 角色 | Tailscale IP | eth0 IP | Flannel 自动检测的 PublicIP |
|------|------|-------------|---------|--------------------------|
| aliyun | server | 100.102.140.59 | 172.23.245.47 (VPC) | 172.23.245.47 |
| gtr | agent | 100.121.0.67 | 192.168.31.59 (LAN) | 192.168.31.59 |
| tencent | agent | 100.99.48.76 | 10.0.0.16 (VPC) | 10.0.0.16 |

三个节点的 eth0 IP **彼此不可达**，因此 Flannel WireGuard 隧道 endpoint 无法连接，跨节点 Pod 网络完全中断。

### 当前临时 workaround

- CoreDNS 通过 `nodeSelector` 固定到 GTR（仅 GTR 本地 Pod DNS 正常）
- ArgoCD repo-server 通过 mihomo 代理 (GTR:7890) 访问 GitHub，绕过 DNS 解析

---

## 根因确认

### Flannel WireGuard public-ip 检测机制

Flannel 的 `wireguard-native` 后端在启动时**独立检测**默认路由接口，取该接口的 IP 作为 WireGuard 隧道的 public-ip。K3s 的 `node-ip` 参数不会传递给 Flannel 的 WireGuard 后端。

具体链路：
```
K3s config.yaml
  └─ node-ip: 100.x.x.x            → 仅影响 kubelet --node-ip
  └─ advertise-address: 100.x.x.x  → 影响 API server 地址
  └─ flannel-backend: wireguard-native
       └─ Flannel 启动时独立检测默认路由
            └─ 取 eth0 (默认路由接口) 的 IP
            └─ 写入 flannel.alpha.coreos.com/public-ip annotation
            └─ 这个 IP 作为 WireGuard 隧道 endpoint
```

### 已排除的方案

| 方案 | 结果 | 原因 |
|------|------|------|
| `flannel-iface: tailscale0` + VXLAN (默认) | ❌ kube-proxy crashloop | tailscale0 是 /32 p2p 接口，kube-proxy 无法检测 primary IP family (issue 007) |
| 仅设 `node-ip` 不改 iface | ❌ Flannel 忽略 | Flannel WireGuard 不读 node-ip，只读默认路由接口 |

---

## 候选方案对比

### 方案 A：手动维护 public-ip annotation（不推荐）

**做法：** 在 K3s 启动后，通过 `kubectl annotate node` 手动设置
`flannel.alpha.coreos.com/public-ip: 100.x.x.x`。

| 维度 | 评价 |
|------|------|
| 技术可行性 | ✅ Flannel 读取该 annotation |
| 自动化难度 | ❌ 需要每次节点重启后重做（annotation 被 Flannel 覆盖） |
| 持久性 | ❌ Flannel 启动时会覆盖 annotation（除非修改 Flannel 源码） |
| 结论 | ❌ 不可靠，不适合自动化 |

### 方案 B：切换到 VXLAN 后端 + flannel-iface: tailscale0（验证可行性）

**做法：** 将 `flannel-backend` 从 `wireguard-native` 改为 `vxlan`（默认值），并设置 `flannel-iface: tailscale0`。

**关键验证：kube-proxy crashloop 是否仅影响 VXLAN？**

分析 issue 007 的 crashloop 记录：当时 GTR 使用 `flannel-iface: tailscale0` + **VXLAN 后端**，kube-proxy 报错退出：
```
kube-proxy exited: no support for primary IP family "IPv4"
```

该错误的根因是 kube-proxy 在检测节点的 primary IP family 时，遇到了 tailscale0（/32 点对点接口）。这是 kube-proxy/bind-address 的问题，**与 VXLAN 还是 WireGuard 后端无关**——只要 node-ip 设为 tailscale0 的 IP，kube-proxy 就需要解析这个接口。

但是进一步分析：
- K3s 将 `node-ip` 传递给 kubelet
- kubelet 将 `--node-ip` 传给 kube-proxy 作为 `--bind-address`
- 当 node-ip 指向 tailscale0 时，kube-proxy 会检查该接口的地址族

结论：**方案 B 与方案 D（wireguard-native + flannel-iface）在 kube-proxy crashloop 风险上等价**，只要 node-ip 指向 tailscale0 就可能触发。

| 维度 | 评价 |
|------|------|
| 技术可行性 | ⚠️ 可能触发 kube-proxy crashloop |
| WireGuard-over-WireGuard | ⚠️ VXLAN over WireGuard = 双重封装 |
| MTU | ⚠️ tailscale0 MTU 1280, VXLAN 头 50 = Pod MTU 1230 |
| 自动化 | ✅ 可 Ansible 自动化 |
| 结论 | ⚠️ 依赖 K3s 版本是否修复了 /32 接口问题 |

### 方案 C：wireguard-native + flannel-iface: tailscale0

**做法：** 保留 `wireguard-native`，添加 `flannel-iface: tailscale0`，强制 Flannel 使用 tailscale0 的 IP。

**分析：**
- 仍然有 kube-proxy crashloop 的相同风险（node-ip 指向 tailscale0）
- 新增 WireGuard-over-WireGuard 双重封装
  - tailscale0: WireGuard 一层
  - flannel-wg: WireGuard 二层
  - MTU: tailscale0 默认 1280，flannel-wg 默认 1420 → 需要在 1280 以内
- 性能开销明显

| 维度 | 评价 |
|------|------|
| 技术可行性 | ⚠️ 同方案 B 的 kube-proxy 风险 |
| 性能 | ❌ 双重 WireGuard 封装，CPU 和网络延迟高 |
| MTU | ⚠️ 尾部署 1280 内，需要调整 |
| 结论 | ❌ 不推荐，过度复杂且有性能损失 |

### 方案 D：wireguard-native + flannel-iface: 使用标准网络接口（不可行）

**做法：** 设置 `flannel-iface` 为 eth0 并使用公网 IP 做 WireGuard endpoint。

**分析：**
- aliyun eth0: 172.23.245.47（VPC 内网，公网需 NAT）
- gtr eth0: 192.168.31.59（家庭内网，无公网）
- tencent eth0: 10.0.0.16（VPC 内网，公网需 NAT）

| 维度 | 评价 |
|------|------|
| 可达性 | ❌ 三个节点不在同一 L2/L3 网络 |
| NAT 穿透 | ❌ 需要公网 IP 或中间跳板 |
| 结论 | ❌ 不适合分布式网络拓扑 |

### 方案 E：host-gw 后端 + Tailscale 子网路由（推荐）

**做法：**
1. 所有节点启用 Tailscale 子网路由接受：`tailscale up --accept-routes`
2. 切换 Flannel 后端为 `host-gw`
3. 设置 `flannel-iface: tailscale0`

**原理：** `host-gw` 后端只在各节点内核路由表中添加直连路由，不对 Pod 流量做任何封装。节点间通过 Tailscale WireGuard 隧道直接三层可达。

| 维度 | 评价 |
|------|------|
| 封装开销 | ✅ 零封装（纯路由） |
| MTU 问题 | ✅ 无需叠加头部，就是尾scale0 的 MTU (1280) |
| kube-proxy 风险 | ✅ host-gw 不需要 flannel 绑到特定接口的 IP，kube-proxy 不受影响 |
| 性能 | ✅ 最佳——没有 VXLAN/WireGuard 封装，只有内核路由转发 |
| 自动化 | ✅ 可 Ansible 自动化（配置 `k3s_flannel_backend: host-gw` + `k3s_flannel_iface: tailscale0`） |
| 复杂度 | ⚠️ 需要 Tailscale 子网路由配置一次性开启 |

**注意事项：**
- 需要在所有节点上开启 Tailscale 子网路由接受：`tailscale up --accept-routes`
- 无需子网路由通告（advertise-routes），因为不需要从集群外部访问 Pod IP。如果将来需要，可在 GTR 上 `tailscale up --accept-routes --advertise-routes=10.60.0.0/16` 并在 Tailscale 管理后台审批该路由
- 需要确认 Tailscale 的子网路由不会与现有路由冲突
- 所有节点上的 Tailscale 版本应一致

### 方案 F：使用 K3s `--flannel-external-ip` 参数（需验证）

K3s 有实验性参数 `--flannel-external-ip`，可以让 Flannel 使用 node 的 ExternalIP（而非 InternalIP）作为 public-ip。

**做法：** 在 K3s server/agent config 中添加：
```yaml
flannel-external-ip: true
```

然后在 node 上设置 ExternalIP 为 Tailscale IP。

**验证：** 该参数在 K3s 文档中标记为实验性，且部分版本不支持。需要确认当前 K3s 版本 (stable) 是否支持。

| 维度 | 评价 |
|------|------|
| 技术可行性 | ⚠️ 依赖 K3s 版本支持（实验性参数） |
| 自动化 | ✅ 可配置到 K3s config 模板 |
| 风险 | ⚠️ 实验性参数可能不稳定或被移除 |
| 结论 | ⚠️ 备选方案，需版本验证 |

---

## 方案对比总结

| 方案 | 封装开销 | kube-proxy 风险 | MTU 问题 | 自动化难度 | 维护成本 | 推荐度 |
|------|---------|----------------|---------|-----------|---------|-------|
| A: annotation 手动维护 | — | — | — | ❌ 高 | ❌ 极高 | ❌ |
| B: VXLAN + tailscale0 | ⚠️ VXLAN over WireGuard | ⚠️ | ⚠️ 1230 | ✅ 低 | 中 | ⚠️ |
| C: wg-native + tailscale0 | ❌ 双重 WireGuard | ⚠️ | ⚠️ | ✅ 低 | 中 | ❌ |
| D: 公网 IP endpoint | — | — | — | ❌ 不可行 | — | ❌ |
| **E: host-gw + Tailscale 路由** | ✅ **零封装** | ✅ **无风险** | ✅ **无叠加** | ✅ **低** | **低** | ⭐ **推荐** |
| F: flannel-external-ip | ✅ 不改变后端 | — | — | ✅ 低 | ⚠️ 实验性 | ⚠️ |

---

## 推荐方案：方案 E（host-gw + Tailscale 子网路由）

### 核心理由

1. **零封装开销**：`host-gw` 只添加路由，不对 Pod 流量做封装。节点之间通过 Tailscale 已经有一层 WireGuard 隧道，不增加额外封装层。
2. **kube-proxy 无 crash 风险**：`host-gw` 不需要 Flannel 绑定到特定接口获取 public-ip，Flannel 只需通过 `flannel-iface: tailscale0` 获取接口 IP 用于路由的下一跳地址。
3. **MTU 无叠加问题**：没有 VXLAN/WireGuard 多层封装头部叠加。
4. **Tailscale 已建立全互联**：三个节点已经通过 Tailscale (100.x.x.x) 互联，满足 `host-gw` 的 L3 直连要求。
5. **Ansible 可自动化**：只需修改 `group_vars` 中的变量和模板渲染即可，无需手动操作。
6. **维护成本低**：配置一次性完成，后续不需要额外维护。

### 前提条件验证

- [ ] 所有节点 Tailscale 运行正常：`tailscale status` 确认三个节点都可达
- [ ] 所有节点内核支持 `host-gw`：Linux 内核天然支持。
- [ ] K3s 版本支持 `flannel-backend: host-gw`：K3s 内置 Flannel 支持 host-gw (自 v1.0+ 就支持)。

### 实施风险

- Tailscale 子网路由可能与其他路由冲突（需要验证当前路由表）
- 如果未来增加新节点，需要确保新节点也开启 `--accept-routes`
- `tailscale up` 执行时会重新应用所有标志位；如果当前配置中使用了 `--authkey` 等标志，需一并带上以免丢失认证配置

---

## 具体实施步骤

### Step 0：预检

在所有节点上运行以下命令，确保基础条件：

```bash
# 检查 Tailscale 状态
tailscale status

# 检查各节点 Tailscale IP
tailscale ip -4

# 检查当前路由表（确认无冲突）
ip route show

# 检查各节点 K3s 状态
systemctl is-active k3s k3s-agent 2>/dev/null || echo "not running"

# 检查当前 flannel annotation
k3s kubectl get nodes -o json | jq '.items[].metadata.annotations["flannel.alpha.coreos.com/public-ip"]'

# 检查 PodCIDR 分配
k3s kubectl get nodes -o json | jq '.items[].spec.podCIDR, .items[].spec.podCIDRs'
```

### Step 1：配置 Tailscale 子网路由接受

> ⚠️ `tailscale up` 执行时会重新应用所有标志位；如果初始引导时使用了 `--authkey`、`--hostname` 等标志，此步骤需要一并带上。请先执行 `tailscale status --json` 确认当前配置。

**在三个节点上都执行相同操作：**

```bash
# 预检：查看当前 Tailscale 配置（确认是否有 authkey 等标志）
tailscale status --json | jq '.Self'

# 启用子网路由接受（保持现有其他标志）
# 示例：如果当前使用 --authkey，则需 append：
# tailscale up --accept-routes --authkey=<key>
# 若无其他标志，则直接：
tailscale up --accept-routes

# 验证配置生效
tailscale status --self | grep -i route
```

> **说明：** 当前方案只需 `--accept-routes`，无需子网路由通告（`--advertise-routes`）。如果某天需要从集群外部访问 Pod IP，才需在 GTR 上 `tailscale up --accept-routes --advertise-routes=10.60.0.0/16` 并在 Tailscale 管理后台审批该路由。本步骤无需此操作。


### Step 2：修改 Ansible 变量

```yaml
# edge/ansible/group_vars/all/public.yml
# 已有变量保持不变，修改以下：
k3s_flannel_backend: "host-gw"       # 从 wireguard-native 改为 host-gw

# 新增变量
k3s_flannel_iface: "tailscale0"      # 让 Flannel 使用 tailscale0 接口
```

```yaml
# edge/ansible/host_vars/gtr/public.yml
# 新增：GTR 子网路由需要额外的 containerd no_proxy 配置（保持现有）
# 不需要新增变量，Step 1 的 tailscale up 需单独执行或通过 ansible command 模块处理
```

```yaml
# edge/ansible/host_vars/aliyun/public.yml — 无需修改
# edge/ansible/host_vars/tencent.yml — 无需修改
```

### Step 3：修改 K3s 配置模板

```yaml
# roles/k3s-server/templates/config.yaml.j2
# 新增 flannel-iface
token: "{{ k3s_cluster_token }}"
write-kubeconfig-mode: "0640"
cluster-cidr: "{{ k3s_cluster_cidr }}"
service-cidr: "{{ k3s_service_cidr }}"
cluster-dns: "{{ k3s_cluster_dns }}"
advertise-address: "{{ k3s_server_effective_ip }}"
node-ip: "{{ k3s_server_effective_ip }}"
node-name: "{{ inventory_hostname }}"
flannel-backend: "{{ k3s_flannel_backend }}"
flannel-iface: "{{ k3s_flannel_iface }}"                    # ← 新增
disable-cloud-controller: true
disable:
{% for item in k3s_disable_components %}
  - {{ item }}
{% endfor %}
tls-san:
{% for item in k3s_server_effective_tls_sans %}
  - "{{ item }}"
{% endfor %}
```

```yaml
# roles/k3s-agent/templates/config.yaml.j2
# 新增 flannel-backend 和 flannel-iface
server: "{{ k3s_server_url }}"
token: "{{ k3s_cluster_token }}"
node-ip: "{{ k3s_agent_effective_ip }}"
node-name: "{{ inventory_hostname }}"
flannel-backend: "{{ k3s_flannel_backend }}"                # ← 新增（host-gw 也需要在 agent 指定）
flannel-iface: "{{ k3s_flannel_iface }}"                    # ← 新增
```

### Step 4：修改 Ansible 任务

```yaml
# roles/k3s-prereq/tasks/main.yml
# 确认 host-gw 不需要额外内核模块。host-gw 依赖标准路由表操作，无需加载额外模块。
# 但 wireguard 模块不再需要（切换为 host-gw 后不需要 flannel-wg），
# overlay 和 br_netfilter 仍需保留用于 Pod 网络。
```

```yaml
# roles/k3s-server/tasks/main.yml 和 roles/k3s-agent/tasks/main.yml
# 不需要额外修改，模板渲染 + handler 自动触发重启。
# 如果节点健康则跳过安装，但重启后 flannel backend 切换。
```

### Step 4.5（可选）：清理旧 flannel 接口

切换后端前，在各节点上清理由 `wireguard-native` 创建的旧接口（非必需，但可避免调试时产生混淆）：

```bash
# 清理旧 flannel-wg 接口（wireguard-native 创建）
ssh aliyun  'ip link del flannel-wg 2>/dev/null || true'
ssh gtr     'ip link del flannel-wg 2>/dev/null || true'
ssh tencent 'ip link del flannel-wg 2>/dev/null || true'

# 清理旧的 flannel.1 接口（VXLAN 创建，若有）
ssh aliyun  'ip link del flannel.1 2>/dev/null || true'
ssh gtr     'ip link del flannel.1 2>/dev/null || true'
ssh tencent 'ip link del flannel.1 2>/dev/null || true'
```

### Step 5：执行部署

> ⏱️ **预计维护窗口：10-15 分钟**
>
> server 重启后、agent 重启前，server（使用 host-gw）与 agent（仍使用旧 wireguard-native 后端）的 Flannel 后端不匹配，跨节点 Pod 网络将短暂中断。建议在 server 部署后立即部署 agent，以最小化中断窗口。
>
> 如需零中断（零间断），可在所有节点上先停掉 K3s 服务，再同时部署 server 和 agent——但此操作需要服务整体离线 5-10 分钟。

```bash
cd edge/ansible

# 先同步配置到 aliyun server
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml

# 立即部署 agent 节点（不等待，紧跟 server 之后）
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml

# 注意：由于 flannel backend 切换，所有节点上的 Pod 会短暂重建。
# 建议在维护窗口操作。
```

### Step 6：切换后的验证

```bash
# 1. 所有节点状态 Ready
k3s kubectl get nodes

# 2. 检查 flannel public-ip 是否正确（此时 host-gw 不需要 public-ip annotation）
# host-gw 模式下，Flannel 通过 flannel-iface 获取子网路由的源地址
# 验证方式：检查节点路由
k3s kubectl get nodes -o json | jq '.items[].metadata.annotations["flannel.alpha.coreos.com/backend-type"]'
# 应显示 host-gw

# 3. 检查 flannel 后端接口
ip -br addr show flannel.1 2>/dev/null
# host-gw 模式下没有 flannel.1 或 flannel-wg 虚拟接口

# 4. 检查节点路由（关键）
k3s kubectl get nodes -o json | jq '.items[].spec.podCIDR'
# 例如 aliyun: 10.60.0.0/24, gtr: 10.60.1.0/24, tencent: 10.60.2.0/24

# 在各节点上检查 Pod 子网路由
ip route show | grep 10.60.
# 应看到类似：
# 10.60.0.0/24 dev tailscale0 proto kernel scope link src 100.102.140.59
# 10.60.1.0/24 via 100.121.0.67 dev tailscale0
# 10.60.2.0/24 via 100.99.48.76 dev tailscale0

# 5. 跨节点 Pod 连通性测试
# 在 GTR 上创建一个测试 Pod
k3s kubectl run test-ping --image=busybox:1.36 --restart=Never -- sh -c "ping -c 3 10.60.0.1"
# 应成功 ping 通 aliyun 的 PodCIDR

# 6. DNS 解析测试
k3s kubectl run dns-test --image=busybox:1.36 --restart=Never -- sh -c "nslookup kubernetes.default.svc.cluster.local"
# 应能解析到 10.61.0.1

# 7. CoreDNS 多节点测试
# ⚠️ 仅在确认跨节点网络恢复后再执行此步骤
# 先检查当前是否有 nodeSelector 固定
test -n "$(k3s kubectl -n kube-system get deployment coredns -o jsonpath='{.spec.template.spec.nodeSelector.kubernetes\.io/hostname}' 2>/dev/null)" && \
  k3s kubectl -n kube-system patch deployment coredns --type json \
    -p '[{"op": "remove", "path": "/spec/template/spec/nodeSelector/kubernetes.io~1hostname"}]' \
  || echo "no nodeSelector to remove"
# 让 CoreDNS 可以调度到任意节点，确认跨节点 DNS 正常
# 稍后检查 CoreDNS Pod 是否分布在不同节点：
k3s kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide

# 8. ArgoCD 连通性测试
k3s kubectl -n argocd exec deploy/argocd-application-controller -- \
  curl -s -o /dev/null -w "%{http_code}" http://argocd-repo-server:8081/health
# 应返回 200
#
# 注意：ArgoCD 的 HTTP_PROXY 配置是为了通过 mihomo（GTR:7890）访问 GitHub，
# 与 Flannel 跨节点网络无关。即使跨节点网络恢复，该代理配置仍需保留。

# 9. 确认旧 flannel-wg 接口已清理
ip link show flannel-wg 2>/dev/null && echo "WARNING: flannel-wg still exists" || echo "OK: flannel-wg cleaned"
ip link show flannel.1 2>/dev/null && echo "WARNING: flannel.1 still exists" || echo "OK: flannel.1 cleaned"

# 10. 旧 PostStart 临时脚本清理
# 检查并移除任何用于修正 flannel annotation 的临时脚本
find /usr/local/bin -name "*flannel*" 2>/dev/null
find /etc/systemd/system -name "*flannel*" 2>/dev/null
```

---

## 回退计划

如果 `host-gw + Tailscale 子网路由` 方案出现问题（如路由冲突、跨节点网络无法恢复），按以下步骤回退到 `wireguard-native` 后端。

> ⚠️ **重要：** 回退操作会中断集群网络约 5-10 分钟。如有 ArgoCD ApplicationSets、Sealed Secrets master key 等有状态负载，建议先确认备份可用。

### 回退步骤

```bash
# 0. 备份确认（如需）
# k3s etcd 快照：如果使用 embedded etcd（aliyun server），可执行：
# k3s etcd-snapshot save --name pre-host-gw-rollback
# 如使用 SQLite/kine，备份 /var/lib/rancher/k3s/server/db/ 目录

# 1. 清理 flannel 后端残留
# 在各节点上执行（先 cleanup 再停服务，避免路由表被重启服务覆盖）：
ssh aliyun  'for cidr in $(ip route show | grep "10\.60\..*via" | awk "{print \$1}"); do ip route del $cidr; done; ip link del flannel-wg 2>/dev/null; ip link del flannel.1 2>/dev/null; echo "done"'
ssh gtr     'for cidr in $(ip route show | grep "10\.60\..*via" | awk "{print \$1}"); do ip route del $cidr; done; ip link del flannel-wg 2>/dev/null; ip link del flannel.1 2>/dev/null; echo "done"'
ssh tencent 'for cidr in $(ip route show | grep "10\.60\..*via" | awk "{print \$1}"); do ip route del $cidr; done; ip link del flannel-wg 2>/dev/null; ip link del flannel.1 2>/dev/null; echo "done"'

# 2. 停掉所有节点 K3s 服务
ssh aliyun  systemctl stop k3s
ssh gtr     systemctl stop k3s-agent
ssh tencent systemctl stop k3s-agent

# 3. 运行 killall 脚本彻底清理残留（可选但推荐）
# 注意：k3s-killall.sh 会清理网络接口和挂载点
ssh aliyun  'k3s-killall.sh || true'
ssh gtr     'k3s-killall.sh || true'
ssh tencent 'k3s-killall.sh || true'

# 4. 恢复 Ansible 配置
# git revert 或手动修改：
# - group_vars/all/public.yml: k3s_flannel_backend → wireguard-native
# - 移除 k3s_flannel_iface 或设为 ""
# - 恢复 config.yaml.j2 到之前版本（移除 flannel-iface 行）

# 5. 移除 Tailscale 子网路由配置（如果有通过 --advertise-routes 设置的）
# 当前方案无需 advertise-routes，但如果误操作或之前设置了，需清理：
ssh gtr 'tailscale set --advertise-routes="" 2>/dev/null; tailscale up --accept-routes=false'
ssh aliyun  'tailscale up --accept-routes=false'
ssh tencent 'tailscale up --accept-routes=false'

# 6. 重新启动 K3s 服务
ssh aliyun  systemctl start k3s
ssh gtr     systemctl start k3s-agent
ssh tencent systemctl start k3s-agent

# 7. 验证恢复后状态
k3s kubectl get nodes
sleep 30
k3s kubectl get nodes -o wide

# 8. 确认跨节点网络恢复（恢复后使用 wireguard-native，eth0 互不可达问题将重现）
# 检查 flannel annotation 是否回到 eth0 IP：
k3s kubectl get nodes -o json | jq '.items[].metadata.annotations["flannel.alpha.coreos.com/public-ip"]'
```

### 回退后已知问题

- 回退到 `wireguard-native` 后，Flannel WireGuard 隧道 endpoint 将再次使用 eth0 的 IP（互不可达），跨节点 Pod 网络将恢复为当前的中断状态。
- 回退后需要重新应用现有 workaround（CoreDNS pin 到 GTR、ArgoCD proxy 配置）。
- 如保留 Tailscale `--accept-routes`，不会影响 wireguard-native 的行为（host-gw 的路由已被清理）。

---

## 方案 F 备选说明

如果上述方案在实践中有未预期的问题，可测试 **方案 F（flannel-external-ip）**：

1. 在 K3s config 中添加 `flannel-external-ip: true`
2. 在 node 对象上设置 ExternalIP = Tailscale IP：
   ```bash
   kubectl patch node aliyun -p '{"spec":{"externalIP":["100.102.140.59"]}}'
   ```
3. 重启 K3s 服务

该方案的优点是无需更改 flannel backend（可保留 wireguard-native），但依赖 K3s 版本对 `flannel-external-ip` 的支持情况。

---

## 附录：Ansible 变更摘要

### 需要新增的变量

```yaml
# group_vars/all/public.yml
k3s_flannel_iface: "tailscale0"    # 新增
```

### 需要修改的模板

| 文件 | 变更 |
|------|------|
| `roles/k3s-server/templates/config.yaml.j2` | 新增 `flannel-iface: "{{ k3s_flannel_iface }}"` 行 |
| `roles/k3s-agent/templates/config.yaml.j2` | 新增 `flannel-backend: "{{ k3s_flannel_backend }}"` 和 `flannel-iface: "{{ k3s_flannel_iface }}"` |

### 需要修改的 group_vars

| 文件 | 变更 |
|------|------|
| `group_vars/all/public.yml` | `k3s_flannel_backend: "host-gw"`（从 wireguard-native 改） |

### 需要外部执行的步骤（非 Ansible）

| 步骤 | 执行范围 | 说明 |
|------|---------|------|
| `tailscale up --accept-routes` | 所有3个节点 | 启用子网路由接受（保持现有其他标志位） |

> 这些步骤可通过 Ansible `command` 模块或单独的 playbook 自动化，但当前建议手动执行一次以避免 `tailscale up` 参数冲突（默认会重置未显式指定的标志位）。

### 需要新增的 role defaults

`k3s_flannel_iface` 变量需要在两个 role 的 `defaults/main.yml` 中添加默认值，防止 `group_vars` 中未定义时 Ansible 报 `undefined variable` 错误：

```yaml
# roles/k3s-server/defaults/main.yml — 新增
k3s_flannel_iface: ""

# roles/k3s-agent/defaults/main.yml — 新增
k3s_flannel_iface: ""
```

空字符串表示不设置 `flannel-iface`（由 Flannel 自动检测），非空时模板渲染为具体值（如 `tailscale0`）。

---

## 版本历史

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| v1 | 2026-06-07 | — | 初始方案文档 |
