# [Issue] K3s Flannel + Tailscale0 网络架构问题与 crashloop 诊断

## 现状

K3s 集群目前处于不可用状态：GTR 上的 K3s server 持续 crashloop（已重启 59+ 次），tencent 上的 agent 连接断断续续，aliyun 上的 server 尚未部署。

### 节点状态（2026-06-06 诊断）

| 节点 | 角色 | 状态 | 说明 |
|------|------|------|------|
| GTR (`100.121.0.67`) | server (旧) | `activating` → crashloop | kube-proxy 启动失败导致循环重启 |
| tencent (`100.99.48.76`) | agent | `active` 但不健康 | 连接到 GTR server 反复断开 |
| aliyun (`100.102.140.59`) | — (目标 server) | k3s 未运行 | 仅有 flannel 配置残留，无 config.yaml |

### 关键日志

**GTR server — kube-proxy 崩溃导致 k3s 退出：**

```
level=error msg="Shutdown request received: \"kube-proxy exited: no support for primary IP family \\\"IPv4\\\"\""
```

**GTR server — kube-proxy 实际启动参数：**

```
Running kube-proxy --cluster-cidr=10.60.0.0/16 ... --hostname-override=gtr ... --proxy-mode=iptables
```

**tencent agent — 连接断开循环：**

```
Server 100.121.0.67:6443@ACTIVE*->FAILED from failed dial
Server 100.121.0.67:6443@FAILED*->RECOVERING from successful health check
Server 100.121.0.67:6443@RECOVERING*->FAILED from failed dial
error msg="Failed to connect to proxy. Empty dialer response" error="dial tcp 100.121.0.67:6443: connect: connection refused"
error msg="Remotedialer proxy error; reconnecting..." error="websocket: close 1006 (abnormal closure): unexpected EOF"
```

**GTR server — etcd/kine 错误：**

```
etcd-client retrying ... target="etcd-endpoints://...kine.sock" method="/etcdserverpb.KV/Range" error="rpc error: code = Canceled desc = grpc: the client connection is closing"
```

### GTR 当前配置 (`/etc/rancher/k3s/config.yaml`)

```yaml
token: "<token>"
write-kubeconfig-mode: "0640"
cluster-cidr: "10.60.0.0/16"
service-cidr: "10.61.0.0/16"
cluster-dns: "10.61.0.10"
advertise-address: "100.121.0.67"
node-ip: "100.121.0.67"
node-name: "gtr"
flannel-iface: "tailscale0"
disable:
  - traefik
  - servicelb
tls-san:
  - "gtr"
  - "gtr.tail414c32.ts.net"
  - "100.121.0.67"
```

### 网络接口（GTR）

```
tailscale0: 100.121.0.67/32  (Tailscale WireGuard 隧道)
flannel.1:  10.60.0.0/32     (VXLAN 覆盖网络)
cni0:       10.60.0.1/24     (Pod 网桥)
```

## 根因分析

### 问题 1：kube-proxy 不兼容 tailscale0 的 /32 地址

**核心错误：**

```
kube-proxy exited: no support for primary IP family "IPv4"
```

这是 K3s 的已知问题。当 `flannel-iface` 设置为 `tailscale0` 时：

1. K3s 使用 `node-ip: 100.121.0.67`（tailscale0 的地址）作为节点 IP
2. kube-proxy 绑定到该接口来识别节点的"primary IP family"
3. tailscale0 是 `/32` 点对点 WireGuard 接口，不是标准广播接口
4. kube-proxy 的 `bind-address` 检测逻辑无法从 `/32` 接口正确解析 IPv4 地址族，导致报 `no support for primary IP family "IPv4"` 后退出
5. kube-proxy 退出触发 K3s 整体重启 → crashloop

**影响：** K3s server 完全不可用，集群无控制面。

### 问题 2：flannel-iface: tailscale0 的架构缺陷

`flannel-iface: tailscale0` 让 Flannel 在 tailscale0 接口上建立 VXLAN 隧道。这存在以下结构性问题：

| 问题 | 说明 |
|------|------|
| **MTU 叠加** | tailscale0 MTU=1280，再叠加 VXLAN 头（50 bytes），实际 Pod MTU ≈ 1230，与 `subnet.env` 中 `FLANNEL_MTU=1230` 吻合但非常紧凑 |
| **路由耦合** | Flannel 在 tailscale0 上建 VXLAN 覆盖，但 tailscale0 的路由表是 Tailscale 控制的（table 52），Flannel 的路由操作可能与之冲突 |
| **单向 NAT 依赖** | Pod 间跨节点流量经过 tailscale0 → Tailscale 的 CGNAT 三层转发，增加了不必要的封装开销（VXLAN over WireGuard = 双重封装） |
| **P2P 接口特性** | tailscale0 是 `/32` 点对点接口，不参与 ARP/NDP，Flannel 的 VXLAN backend 依赖组播或直接 MAC 解析，在 tailscale0 上无法正常工作 |

### 问题 3：GTR 资源竞争

GTR 同时承担 7+ 个服务（mihomo, grafana, victoriametrics, victorialogs, victoriatraces, envoy, node_exporter）加 K3s server（etcd + kube-apiserver + controller-manager + scheduler）。K3s server crashloop 受到以下加剧：

- 内存不足导致 OOM 或 thrashing
- CPU 争抢导致 etcd 响应超时 → api-server 健康检查失败 → 重启

## 解决方案

### 方案：控制面迁移至 aliyun + 替代 flannel-iface

本次 006 年度优化已包含控制面迁移（server → aliyun），但 `flannel-iface: tailscale0` 的配置仍保留。需要额外修改：

#### 方案 A：改为 flannel-iface: 默认（移除该配置）

Flannel 默认会自动选择默认路由出口接口。在 aliyun（云 VM）上，默认接口是 eth0（公网 IP），这不是我们想要的。

#### 方案 B：改用 WireGuard 直连 backend（推荐）

使用 K3s 内置的 `--flannel-backend=wireguard-native` 替代 VXLAN，让 Flannel 直接用内核 WireGuard 建立 Pod 间加密隧道。这样：

- 不再依赖 tailscale0 作为 Flannel 接口
- Pod 间流量自动加密且无需双重封装（VXLAN over WireGuard）
- 不需要额外安装 WireGuard（内核 ≥ 5.6 内置支持）

配置变更：

```yaml
# 旧配置（有问题）
flannel-iface: "tailscale0"

# 新配置（移除 flannel-iface，改用 node-ip 指定 tailscale 地址）
# 同时在 K3s 启动参数中使用 --flannel-backend=wireguard-native
node-ip: "<tailscale-ip>"
advertise-address: "<tailscale-ip>"
# 不设置 flannel-iface，让 Flannel 绑定到 node-ip 对应的路由
```

同时在 k3s-server/agent role 启动参数中添加：

```
INSTALL_K3S_EXEC="server --flannel-backend=wireguard-native"
INSTALL_K3S_EXEC="agent --flannel-backend=wireguard-native"
```

#### 方案 C：Flannel host-gw backend（适合简单拓扑）

如果节点间通过 Tailscale 已经有一层三层可达路由，可以用 `host-gw` backend 避免 VXLAN/WireGuard 封装：

```yaml
flannel-iface: "tailscale0"
# 在 config.yaml 中加：
flannel-backend: "host-gw"
```

`host-gw` 模式下 Flannel 只添加路由规则不封装，但要求三层直接可达（Tailscale 已满足），且不支持跨网段需要手动维护路由。

**方案比较：**

| 方案 | 优点 | 缺点 |
|------|------|------|
| A: 移除 flannel-iface | 简单 | 默认用 eth0 公网 IP，Pod 流量走公网 |
| **B: wireguard-native** | 不依赖 tailscale0、无双重封装、自动加密 | 需要内核 ≥ 5.6（已满足） |
| C: host-gw | 零封装开销 | 依赖 Tailscale 路由表的稳定性 |

**推荐方案 B**：迁移后 aliyun server 和 tencent agent 都有公网接口，WireGuard native backend 可以直接走 Tailscale 提供的三层路由建立点对点加密隧道，不依赖 tailscale0 接口本身。

## 迁移前修复步骤

在部署 006 变更（控制面迁移到 aliyun）之前，需要先处理 GTR 上的旧 K3s server 残留：

### 1. 停止 GTR 上的旧 K3s server

```bash
ssh root@gtr.tail414c32.ts.net
systemctl stop k3s
systemctl disable k3s
k3s-killall.sh  # 清理残留进程
```

### 2. 清理旧数据（如需要全新集群）

```bash
rm -rf /var/lib/rancher/k3s/server
rm -rf /var/lib/rancher/k3s/agent
rm -f /etc/rancher/k3s/config.yaml
rm -f /etc/rancher/k3s/k3s.yaml
```

> ⚠️ 如果集群中有需要保留的数据（如 Sealed Secrets 的 master key），请先备份。

### 3. 修改配置后再以 agent 身份加入

修改后的 GTR agent 配置不应使用 `flannel-iface: tailscale0`。具体变更取决于选择的 Flannel 方案。

## 006 变更需要的额外修改

无论选择哪个方案，006 的 Ansible 配置需要更新：

| 文件 | 变更 |
|------|------|
| `group_vars/all/public.yml` | 移除或修改 `k3s_flannel_iface: tailscale0` |
| `roles/k3s-server/templates/config.yaml.j2` | 移除 `flannel-iface` 或改为条件渲染 |
| `roles/k3s-agent/templates/config.yaml.j2` | 同上 |
| `roles/k3s-server/defaults/main.yml` | 可选：新增 `k3s_flannel_backend` 变量 |
| `roles/k3s-prereq/tasks/main.yml` | 可选：如用 wireguard-native，加载 `wireguard` 内核模块 |

### k3s-prereq 内核模块更新（方案 B）

如选择 wireguard-native backend，需在 prereq 中添加 `wireguard` 模块：

```yaml
k3s_prereq_modules:
  - overlay
  - br_netfilter
  - wireguard   # 新增
```

并在 templates 中传入 flannel backend 参数。

## 参考

- [K3s Flannel networking options](https://docs.k3s.io/architecture/networking#flannel-options)
- [K3s `--flannel-backend` flag](https://docs.k3s.io/cli/server#networking)
- [K3s issue: kube-proxy crash with `flannel-iface` on point-to-point interfaces](https://github.com/k3s-io/k3s/issues/2758)
- [K3s issue: "no support for primary IP family" with /32 interfaces](https://github.com/k3s-io/k3s/issues/3757)
- [Flannel VXLAN backend documentation](https://github.com/flannel-io/flannel/blob/master/Documentation/backends.md#vxlan)
- [Flannel WireGuard backend](https://github.com/flannel-io/flannel/blob/master/Documentation/backends.md#wireguard)
- 006 优化规划文档: `docs/issues/006-k3s-deploy-optimization.md`