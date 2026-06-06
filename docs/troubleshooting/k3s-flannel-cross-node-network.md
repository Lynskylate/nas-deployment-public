# K3s 跨节点网络故障分析

## 问题现象

K3s 集群中跨节点的 Pod 网络（10.60.0.0/16）不通。具体表现：
- CoreDNS 在 tencent 节点 → GTR 和 aliyun 上的 Pod 无法做 DNS 解析
- Argo CD 的 `application-controller`（跑在 GTR）无法连接 `argocd-repo-server` 服务名（DNS 解析超时）
- 新 Pod 创建后无法分配到 Pod IP（`ContainerCreating` 卡住）

### 集群拓扑

| 节点 | 角色 | Tailscale IP | 网络位置 | 硬件 |
|------|------|-------------|----------|------|
| aliyun | control-plane (server) | 100.102.140.59 | 阿里云 ECS (1.7GB RAM) | Ubuntu 22.04 |
| gtr | agent | 100.121.0.67 | 家里局域网 (192.168.31.x) | Ubuntu 22.04 |
| tencent | agent | 100.99.48.76 | 腾讯云 CVM | Ubuntu 24.04 |

### 网络配置

```yaml
# K3s server config (aliyun)
cluster-cidr: "10.60.0.0/16"
service-cidr: "10.61.0.0/16"
cluster-dns: "10.61.0.10"
advertise-address: "100.102.140.59"   # Tailscale IP
node-ip: "100.102.140.59"             # Tailscale IP
flannel-backend: "wireguard-native"
```

```yaml
# K3s agent config (gtr)
node-ip: "100.121.0.67"               # Tailscale IP
```

```yaml
# K3s agent config (tencent)
node-ip: "100.99.48.76"               # Tailscale IP
```

## 根因分析

### Flannel WireGuard 选择了错误的 Public IP

K3s 日志显示：
```
The interface eth0 with ipv4 address 172.23.245.47 will be used by flannel
```

Flannel WireGuard 后端自动检测默认路由接口，选择了 `eth0` 的 IP 作为 WireGuard 隧道的 `public-ip`。但三个节点各自的 `eth0` IP **彼此不可达**：

| 节点 | Flannel 选择的 PublicIP | 来源接口 | 从其他节点可达？ |
|------|------------------------|----------|----------------|
| aliyun | **172.23.245.47** | eth0 (阿里云 VPC) | ❌ GTR/tencent 不可达 |
| gtr | **192.168.31.59** | eth0 (家里 LAN) | ❌ aliyun/tencent 不可达 |
| tencent | **10.0.0.16** | eth0 (腾讯云 VPC) | ❌ aliyun/GTR 不可达 |

### 为什么 `node-ip` 设置被忽略？

K3s config 中设置了 `node-ip: 100.x.x.x`（Tailscale IP），但 flannel **不使用 `node-ip` 作为 WireGuard 隧道的 PublicIP**。Flannel 独立检测默认路由接口，取 `eth0` 的 IP。

在 K3s 源码中，`node-ip` 用于：
- `--advertise-address`（API server 地址）
- Kubelet `--node-ip`
- 但 flannel 的 WireGuard 后端**只读** `flannel.alpha.coreos.com/public-ip` annotation，这个 annotation 由 flannel 启动时自动检测设置

### Flannel Annotation 状态

```json
aliyun:  flannel.alpha.coreos.com/public-ip: 172.23.245.47   ← docker0 的 IP！
gtr:     flannel.alpha.coreos.com/public-ip: 192.168.31.59   ← LAN IP
tencent: flannel.alpha.coreos.com/public-ip: 10.0.0.16       ← VPC IP
```

### WireGuard 隧道状态

K3s server 日志显示 WireGuard 隧道已创建，但 endpoint 为不可达 IP：
```
Subnet 10.60.2.0/24 (GTR) via 192.168.31.59:51820   ← ❌ 从 aliyun 无法访问 192.168.31.x
Subnet 10.60.1.0/24 (tencent) via 10.0.0.16:51820    ← ❌ 从 aliyun 无法访问 10.0.0.x
```

### Flannel-wg 接口 IP 异常

```
aliyun: flannel-wg IP: 10.60.0.0/32   ← 这是 subnet network address，不是合法 host IP！
```

`10.60.0.0` 是 `10.60.0.0/16` 的网段地址（network address），不能作为 host IP 使用。正常应为 `10.60.0.x`（其中 x 是该节点的 PodCIDR 分配的 host IP）。

## 当前临时工作

已实施的 workaround：
1. **CoreDNS 调度到 GTR**（和 Argo CD pods 同节点）：`kubectl -n kube-system patch deployment coredns -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/hostname":"gtr"}}}}}'`
   - 效果：GTR 上的 Pod DNS 恢复正常
   - 问题：tencent 和 aliyun 上的 Pod 仍然无法做 DNS

2. **Argo CD repo-server proxy 配置**（mihomo 代理 SSH/HTTPS 到 GitHub）
   - repo URL 改为 `https://` 格式
   - `HTTP_PROXY=http://100.121.0.67:7890` (GTR 的 mihomo 代理)

## 建议修复方案

### 方案 A：修复 Flannel 使用 Tailscale IP（推荐）

让 flannel 使用 `tailscale0` 接口的 IP（100.x.x.x）作为 WireGuard 的 public-ip。

**原理：** 所有节点通过 Tailscale 互联（100.x.x.x 段），使用 Tailscale IP 作为 WireGuard endpoint 可以保证端到端可达。

**执行步骤：**

```bash
# 1. 在每个节点上，停掉 K3s 服务
systemctl stop k3s   # 或 k3s-agent

# 2. 修改 flannel annotation —— 需要手动更新
# 实际上需要重启 K3s 时传递 --flannel-iface=tailscale0 参数
```

**K3s 配置文件修改（aliyun server）：**
```yaml
# /etc/rancher/k3s/config.yaml
flannel-iface: "tailscale0"
```

**GTR agent 修改：**
```bash
# 在 k3s-agent 启动参数中加 --flannel-iface=tailscale0
# 或通过 systemd drop-in
mkdir -p /etc/systemd/system/k3s-agent.service.d
cat > /etc/systemd/system/k3s-agent.service.d/flannel-iface.conf <<'EOF'
[Service]
Environment=K3S_FLANNEL_IFACE=tailscale0
EOF
systemctl daemon-reload
systemctl restart k3s-agent
```

**注意：** 这种方法会产生 WireGuard-over-WireGuard 隧道（flannel-wg 包封装在 Tailscale 的 WireGuard 隧道中），MTU 需要调整。Flannel-wg 默认 MTU 可能需从 1420 降为 1380 或更低。

### 方案 B：切换到 VXLAN 后端

```yaml
# /etc/rancher/k3s/config.yaml
# 删除 flannel-backend: "wireguard-native"
# 或者改为：
# flannel-backend: "vxlan"
```

**优点：** VXLAN 工作在任何 IP 网络上，使用 Tailscale 100.x.x.x IP 即可，没有 double-WireGuard 的 MTU 问题。
**缺点：** 需要 drain 所有节点、重启所有 K3s 组件，有短暂的 Pod 迁移。

### 方案 C：配置 Tailscale 子网路由（最彻底）

1. 在 GTR 上启用 Tailscale 子网路由：
```bash
tailscale up --advertise-routes=10.60.0.0/16 --accept-routes
```

2. 在其他节点上也设置 `--accept-routes`

3. 然后 flannel 切换为 `host-gw` 后端（不需要跨节点封装）

## 验证命令

```bash
# 检查 flannel public-ip
k3s kubectl get nodes -o json | jq '.items[].metadata.annotations["flannel.alpha.coreos.com/public-ip"]'

# 检查 flannel-wg 接口
ip -br addr show flannel-wg

# 检查 WireGuard 隧道（部分节点有 wg-tools）
wg show

# 跨节点 Pod 连通性测试
k3s kubectl run test-ping --image=busybox --restart=Never -- sh -c "ping -c 3 <other-pod-ip>"

# 检查 CoreDNS 服务
k3s kubectl -n kube-system get svc kube-dns
k3s kubectl -n kube-system get endpoints kube-dns

# DNS 解析测试
k3s kubectl run dns-test --image=busybox:1.36 --restart=Never -- sh -c "nslookup kubernetes.default.svc.cluster.local"
```

## 附：已验证可用的 Argo CD 配置

repo-server 的代理配置（mihomo 在 GTR 100.121.0.67:7890）：
```yaml
# 已通过 kubectl patch 设置
env:
  - name: HTTP_PROXY
    value: "http://100.121.0.67:7890"
  - name: HTTPS_PROXY
    value: "http://100.121.0.67:7890"
  - name: NO_PROXY
    value: "localhost,127.0.0.1,10.0.0.0/8,100.0.0.0/8"
```

注意：`status.hostIP` 的 Downward API field ref 虽可获取宿主机 IP，但 `$(HOST_IP)` 变量替换仅在 `command`/`args` 中生效，不适用于 `env[].value`。
