# [Plan] 应用服务从 Ansible 迁移到 K3s/ArgoCD

> 注：本文是迁移规划文档。当前真实拓扑以 `AGENTS.md` 与 `k3s/README.md` 为准：`tencent` 是 control-plane，`aliyun` 是 agent，`remote_proxy` 的 Kubernetes Node 名为 `remote-proxy`。

## 概述

**目标：** 将当前由 Ansible 裸金属部署的非必要应用服务迁移到 K3s 集群中，由 ArgoCD 管理。Ansible 仅保留 K3s 运行所必需的基础设施层。

**核心决策：**

| 决策 | 结论 |
|------|------|
| 历史数据 | **清零重建** — K3s 上新实例从零开始，裸金属数据可后续手动清理 |
| 服务暴露 | **Tailscale Operator** — 废弃所有 Envoy 代理，每个服务独立 Tailscale 域名 |
| Helm chart | **社区现成 chart** — 仅写 values 覆盖，无社区 chart 的（CronJob）自写 |
| ArgoCD 管理 | **独立 Application** — 每个服务一个 Application，不搞自举/伞形 |
| remote_proxy | **加入 K3s agent** — 打 taint 不调度，跨洋延迟需注意 |
| aliyun/remote_proxy | **打 taint** — 默认不调度普通 Pod，仅系统组件 |

**产物：** 9 个 ArgoCD Application + 对应的 Helm values + 节点 taint/调度策略 + API 废弃清单。

---

## 架构变更总览

### 节点拓扑（变更后）

```
K3s Cluster (4 nodes)
├─ tencent      (control-plane)
│   Tailscale: 100.99.48.76   |  位置: 中国腾讯云  |  调度: control-plane
│
├─ gtr          (agent, 无 taint)
│   Tailscale: 100.121.0.67   |  位置: 家庭服务器   |  调度: 主要工作负载
│
├─ aliyun       (agent, taint: CriticalAddonsOnly)
│   Tailscale: 100.100.99.70  |  位置: 中国阿里云  |  调度: 仅系统组件
│
└─ remote-proxy (agent, taint: NoSchedule)
    Tailscale: 100.66.156.40  |  位置: 美国 VPS     |  调度: 仅系统组件 (跨洋 ~200ms)
```

### 服务迁移对照表

| 服务 | 当前部署 | 迁移后 | Chart 来源 |
|------|---------|--------|-----------|
| Network Monitor | Ansible cron 脚本 (GTR) | **K8s CronJob** | 自写 |
| Mihomo 监控采集 | Ansible systemd timer (GTR) | **K8s Deployment** (30s 循环) | 自写 |
| VictoriaTraces | Ansible 裸金属 (GTR) | **K8s StatefulSet** | [VictoriaMetrics 官方 chart](https://github.com/VictoriaMetrics/helm-charts) |
| VictoriaLogs | Ansible 裸金属 (GTR) | **K8s StatefulSet** | VictoriaMetrics 官方 chart |
| VictoriaMetrics | Ansible 裸金属 (GTR) | **K8s StatefulSet** | VictoriaMetrics 官方 chart |
| Grafana | Ansible 裸金属 (GTR) | **K8s Deployment** | [Grafana 社区 chart](https://github.com/grafana/helm-charts) |
| Node Exporter | Ansible 裸金属 (4 节点) | **K8s DaemonSet** | [Prometheus 社区 chart](https://github.com/prometheus-community/helm-charts) |
| Vector | Ansible 裸金属 (边缘节点 + GTR) | **K8s DaemonSet** ⚠️ | [Vector 社区 chart](https://github.com/vectordotdev/helm-charts) |

### 彻底废弃清单

| 废弃项 | 节点 | 原因 |
|--------|------|------|
| **Envoy** (所有 4 节点) | GTR / aliyun / tencent / remote_proxy | Tailscale Operator 替代服务暴露 |
| **Shadow-TLS server** | remote_proxy | Tailscale WireGuard 替代伪装层 |
| **Shadow-TLS client role** | (未活跃使用) | Mihomo 内置 SIP003 |
| **Shadowsocks server** | remote_proxy | Mihomo 改用订阅 + Hysteria2，不再需要 |
| **Shadowsocks client role** | (未活跃使用) | 同上 |
| **aliyun 公网代理方案** | aliyun | 整套 Mihomo + Envoy + Vector 方案废弃 |
| `mihomo/ansible/deploy-aliyun.yml` | — | 关联 playbook |
| `mihomo/ansible/deploy-docker.yml` | — | 已在前序 plan 中处理 |
| `edge/ansible/deploy-edge-tunnel-server.yml` | — | 隧道方案废弃 |
| `edge/ansible/roles/shadowsocks-server/` | — | 角色废弃 |
| `edge/ansible/roles/shadowtls-server/` | — | 角色废弃 |
| `edge/ansible/roles/shadowsocks-client/` | — | 角色废弃 |
| `edge/ansible/roles/shadowtls-client/` | — | 角色废弃 |
| `edge/ansible/roles/edge-envoy/` | — | 所有 Envoy 角色废弃 |
| `edge/ansible/roles/edge-vector/` | — | 由 K8s DaemonSet 替代 |
| `edge/ansible/roles/node-exporter/` | — | 由 K8s DaemonSet 替代 |
| `edge/ansible/roles/edge-victoriametrics-scrape/` | — | 由 K8s 内部 ServiceMonitor/PodMonitor 替代 |
| `victoriatraces/ansible/` | — | 完整目录废弃 |
| `victoriatraces/install.sh` | — | 由 Helm chart 替代 |
| `network-monitor/ansible/` | — | 由 K8s CronJob 替代 |
| `mihomo/monitoring/ansible/` | — | 由 K8s CronJob 替代 |

### 保留在 Ansible（仅基础设施层）

| # | 服务 | 原因 | 相关 playbook |
|---|------|------|--------------|
| 1 | **Tailscale** (edge-tailscale role) | K3s Flannel 走 tailscale0，必须前置 | `deploy-edge.yml` (精简后) |
| 2 | **K3s server** | 平台本身 | `deploy-gtr-k3s-server.yml` |
| 3 | **K3s agent** | 平台本身 | `deploy-gtr-k3s-agent.yml` |
| 4 | **k3s-prereq** (kernel, sysctl, packages) | K3s 运行必需的 OS 配置 | 各 K3s playbook 的 pre_tasks |
| 5 | **containerd HTTP proxy** | 国内节点镜像拉取 | K3s playbook 内配置 |
| 6 | **Mihomo** (GTR) | TUN + net admin + 订阅/Hysteria2 代理出口 | `mihomo/ansible/deploy.yml` |
| 7 | **Tailscale exit node fix** | nftables + policy routing | `mihomo/ansible/deploy-exitnode.yml` |
| 8 | **ArgoCD 引导** | K3s 平台层引导 | `deploy-platform-argocd.yml` |
| 9 | **Sealed Secrets 私钥恢复** | 同上 | `bootstrap-platform-sealed-secrets-key.yml`（controller 由 Argo CD 管理） |
| 10 | **Tailscale Operator 引导** | 同上 | `deploy-platform-tailscale-operator.yml` |
| 11 | **AI tools** (Claude/Codex/OpenCode) | 用户交互 CLI | `deploy-gtr-ai-tools.yml` |
| 12 | **Podman + project runtime** | K3s 互补运行时 | `deploy-gtr-project-runtime.yml` |
| 13 | **Slock daemon** | 用户级 systemd 服务 | (含在 AI tools 中) |

---

## 迁移阶段

### 阶段 0：前置准备（无服务中断）

#### 0.1 节点调整

**remote_proxy 加入 K3s agent：**
```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml --limit remote_proxy -v
```

**aliyun/remote_proxy 打 taint：**
```bash
# aliyun (已有 control-plane taint)
kubectl taint nodes aliyun CriticalAddonsOnly=true:NoSchedule --overwrite

# tencent (remove any existing taint — can schedule stateless workloads)
kubectl taint nodes tencent NoSchedule- 2>/dev/null || true

# remote-proxy (额外标注跨洋延迟)
kubectl taint nodes remote-proxy NoSchedule=true:NoSchedule
kubectl label nodes remote-proxy topology.kubernetes.io/region=us-west
```

**GTR 添加 toleration 以承载工作负载：**
确保 GTR 对所有 taint 有 toleration（或保持无 taint）。

#### 0.2 ArgoCD Application 目录结构

```
platform/
├── applications/                    # 已有
│   ├── sealed-secrets.yaml
│   ├── tailscale-operator.yaml
│   └── app-of-apps.yaml            # 已存在（Ansible 创建），自动发现目录内所有 Application CRD
│
├── helm-values/                     # 已有
│   ├── tailscale-operator/
│   ├── victoriatraces/             # 新增
│   │   └── values.yaml
│   ├── victorialogs/               # 新增
│   │   └── values.yaml
│   ├── victoriametrics/            # 新增
│   │   └── values.yaml
│   ├── grafana/                    # 新增
│   │   └── values.yaml
│   ├── node-exporter/              # 新增
│   │   └── values.yaml
│   └── vector/                     # 新增
│       └── values.yaml
│
└── resources/                       # 新增
    ├── network-monitor/
    │   └── cronjob.yaml
    └── mihomo-monitoring/
        └── deployment.yaml
```

---

### 阶段 1：低风险验证（CronJob，无状态）

#### 1.1 Network Monitor → K8s CronJob

**现状：** cron 脚本在 GTR 上通过 systemd timer 运行，经 Mihomo :7890 测试 ~25 个站点连通性，JSON 日志由 Vector 采集到 VL。

**迁移：**
- 容器化 `network-monitor/network-monitor.sh`，通过 Mihomo Service Endpoint 访问代理
- CronJob 每 5 分钟运行，输出 JSON 到 stdout（由 Vector DaemonSet 采集）
- 无需 PV/PVC

**ArgoCD Application（`platform/resources/network-monitor-cronjob.yaml`）：**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: network-monitor
  namespace: monitoring
spec:
  schedule: "*/5 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          tolerations:
            - key: "NoSchedule"
              operator: "Exists"
          nodeSelector:
            kubernetes.io/hostname: gtr
          containers:
            - name: monitor
              image: curlimages/curl:latest
              command: ["/bin/sh", "-c"]
              # 脚本内容通过 ConfigMap 挂载
              volumeMounts:
                - name: script
                  mountPath: /scripts
          volumes:
            - name: script
              configMap:
                name: network-monitor-script
          restartPolicy: OnFailure
```

**依赖：** Mihomo 代理端点 `http://100.121.0.67:7890`（通过 Tailscale IP）

#### 1.2 Mihomo 监控采集 → K8s Deployment

**现状：** GTR 上 `mihomo-metrics.sh` 通过 systemd timer (15s) 定期拉取 Mihomo API (`127.0.0.1:9090`)，推送到 VM (`127.0.0.1:8428`)。

**迁移：**
- Deployment (非 CronJob) — K8s CronJob 最小粒度约 1 分钟，且会引入 jitter。改为单 Pod + `while true; sleep 30` 循环，更稳定可靠
- 通过 VictoriaMetrics Service（待阶段 2 部署）的 K8s ClusterIP 写入
- 访问 Mihomo API 通过 Tailscale IP `http://100.121.0.67:9090`
- MIHOMO_SECRET 从 K8s Secret `mihomo-api` 注入

**ArgoCD Application：** `platform/resources/mihomo-monitoring/deployment.yaml` (同目录)

**退化说明：** 采集间隔从原始 15s → 30s，流量细粒度降低一半，对长期趋势分析影响可接受。

---

### 阶段 2：可观测后端（StatefulSet，核心收益）

#### 2.1 VictoriaTraces → StatefulSet

**社区 chart：** `victoria-metrics-traces` (来自 `https://victoriametrics.github.io/helm-charts/`)

**Values 关键配置：**
```yaml
# platform/helm-values/victoriatraces/values.yaml
server:
  persistentVolume:
    enabled: true
    size: 20Gi
    storageClass: local-path  # K3s 内置
  
  service:
    # 通过 Tailscale Operator 暴露，不使用 LoadBalancer/NodePort
  
  resources:
    requests:
      memory: 256Mi
      cpu: 100m
  
  # Pin to GTR
  nodeSelector:
    kubernetes.io/hostname: gtr

# Tailscale 暴露
serviceAnnotations:
  tailscale.com/expose: "true"
```

**暴露域名：** `victoriatraces-<ns>.tail414c32.ts.net`

**数据接收：** 边缘 Vector (阶段 3) → OTLP gRPC → `victoriatraces:4317` (ClusterIP)

#### 2.2 VictoriaLogs → StatefulSet

**社区 chart：** `victoria-logs-single` (来自 VictoriaMetrics helm-charts)

**Values 关键配置：**
```yaml
# platform/helm-values/victorialogs/values.yaml
server:
  persistentVolume:
    enabled: true
    size: 50Gi
    storageClass: local-path
  
  retentionPeriod: 30  # 天

  resources:
    requests:
      memory: 512Mi
      cpu: 200m
  
  nodeSelector:
    kubernetes.io/hostname: gtr

serviceAnnotations:
  tailscale.com/expose: "true"
```

**暴露域名：** `victorialogs-<ns>.tail414c32.ts.net`

**数据接收：** Vector DaemonSet (阶段 3) → Elasticsearch bulk API → `victorialogs:8429` (ClusterIP)

#### 2.3 VictoriaMetrics → StatefulSet

**社区 chart：** `victoria-metrics-single` (来自 VictoriaMetrics helm-charts)

**⚠️ 待定：** 是否启用 Prometheus Operator ServiceMonitor 抓取集群内 `/metrics` 端点。本次方案暂不涉及（标注为后续迭代需求）。

**Values 关键配置：**
```yaml
# platform/helm-values/victoriametrics/values.yaml
server:
  persistentVolume:
    enabled: true
    size: 30Gi
    storageClass: local-path
  
  retentionPeriod: 15  # 天

  resources:
    requests:
      memory: 512Mi
      cpu: 200m
  
  nodeSelector:
    kubernetes.io/hostname: gtr

  # 静态 scrape targets（边缘代理节点）
  extraScrapeConfigs:
    - job_name: edge_proxy_aliyun
      scrape_interval: 15s
      static_configs:
        - targets: ["47.120.46.128:80"]
          labels: { server: aliyun, role: edge_proxy }
    - job_name: edge_proxy_remote_proxy
      scrape_interval: 15s
      static_configs:
        - targets: ["66.154.100.187:80"]  # 需确认 Envoy 废弃后此端口是否仍开放
          labels: { server: remote_proxy, role: edge_proxy }
    - job_name: edge_proxy_tencent
      scrape_interval: 15s
      static_configs:
        - targets: ["129.211.12.63:80"]
          labels: { server: tencent, role: edge_proxy }

serviceAnnotations:
  tailscale.com/expose: "true"
```

**暴露域名：** `victoriametrics-<ns>.tail414c32.ts.net`

#### 2.4 Grafana → Deployment

**社区 chart：** `grafana` (来自 `https://grafana.github.io/helm-charts`)

**Values 关键配置：**
```yaml
# platform/helm-values/grafana/values.yaml
persistence:
  enabled: true
  size: 5Gi
  storageClass: local-path

# 数据源 — 指向 K8s Service
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: VictoriaMetrics
        type: prometheus
        url: http://victoriametrics:8428
        access: proxy
        isDefault: true
      - name: VictoriaLogs
        type: victorialogs-datasource
        url: http://victorialogs:8429
        access: proxy

resources:
  requests:
    memory: 256Mi
    cpu: 100m

nodeSelector:
  kubernetes.io/hostname: gtr

# 禁用 testFramework（节省资源）
testFramework:
  enabled: false

serviceAnnotations:
  tailscale.com/expose: "true"
```

**暴露域名：** `grafana-<ns>.tail414c32.ts.net`

**数据源迁移：** VM/VL 改为 K8s Service DNS (`victoriametrics:8428`, `victorialogs:8429`)，不再用 `localhost`。

---

### 阶段 3：采集层（DaemonSet，逐步替换裸金属）

#### 3.1 Node Exporter → DaemonSet

**社区 chart：** `prometheus-node-exporter` (来自 `https://prometheus-community.github.io/helm-charts`)

**Values 关键配置：**
```yaml
# platform/helm-values/node-exporter/values.yaml
# DaemonSet 自动在所有节点运行
hostNetwork: true
hostPID: true

tolerations:
  - operator: "Exists"  # 在所有节点运行，无视 taint

resources:
  requests:
    memory: 64Mi
    cpu: 50m

# 不需要 serviceAnnotations — node_exporter 由 VM 内部抓取即可
# 指标端口: :9100 (hostNetwork)
```

> **注意：** Node Exporter 使用 `hostNetwork: true`，听众节点 `:9100`。VM 通过 Tailscale IP 抓取各节点 `:9100/metrics`。
> **废弃后影响：** 原 `edge_proxy_vm_scrape_jobs` 中的 Envoy 抓取目标（`:80/metrics`, `:80/stats/prometheus`）将不可用。需确认是否需要保留节点级 metrics。

#### 3.2 Vector → DaemonSet ⚠️ 待定

**社区 chart：** `vector` (来自 `https://helm.vector.dev`)

**⚠️ 此阶段标记为待定，原因：**

1. Envoy 废弃后，原 Vector 读取 `/var/log/envoy/access.log` 的 source 不存在
2. Vector 的新职责待明确（见下方待定问题）
3. 可在阶段 1/2 完成并验证后，再决定 Vector 的最终配置

**待 Vector 职责确认后的参考配置：**
```yaml
# platform/helm-values/vector/values.yaml
role: Agent  # DaemonSet

tolerations:
  - operator: "Exists"

# 待定：收集 pod logs (kubernetes_logs source)
# 待定：收集 journald
# 待定：Prometheus scrape

# sinks：发送到 VictoriaLogs/VictoriaMetrics/VictoriaTraces ClusterIP
sinks:
  victorialogs:
    type: elasticsearch
    inputs: ["kubernetes_logs"]
    endpoints: ["http://victorialogs:8429/insert/elasticsearch/"]
  victoriametrics:
    type: prometheus_remote_write
    inputs: ["prometheus_scrape"]
    endpoint: "http://victoriametrics:8428/api/v1/write"
  victoriatraces:
    type: otlp
    inputs: ["otlp_source"]
    endpoint: "http://victoriatraces:4317"
```

---

### 阶段 4：Envoy 废弃 & 清理

#### 4.1 废弃所有 Envoy 实例

| 节点 | 当前职责 | 替代方案 |
|------|---------|---------|
| **GTR** | 反向代理 → Grafana/VM/VL/VT | Tailscale Operator 暴露每个服务独立域名 |
| **aliyun** | HTTP 路由 `/metrics` + `/stats/prometheus` | Node Exporter DaemonSet + K8s 内部采集 |
| **tencent** | 同上 | 同上 |
| **remote_proxy** | ① SNI TLS passthrough (已废弃) ② HTTP 路由 | ① Shadow-TLS 废弃 + Tailscale WireGuard ② 同上 |

**操作步骤（每台机器）：**
```bash
ssh root@<node>
systemctl stop envoy
systemctl disable envoy
# 保留 /etc/envoy/ 目录和证书作为备份，不删除
# 后续通过 Ansible 清理 role 统一管理
```

#### 4.2 清理防火墙规则

移除 Envoy 开放的端口（由原 `edge-envoy` role 中的 ufw 规则管理）：
```bash
# 每台机器
ufw delete allow 443/tcp
ufw delete allow 80/tcp
# 或直接禁用 ufw（如果 K3s + Tailscale 已提供足够的网络隔离）
```

#### 4.3 Ansible Role & Playbook 清理

随后在单独的 PR 中进行（不属于本次迁移的 ArgoCD 配置部分）：

删除内容：
- `edge/ansible/roles/edge-envoy/`
- `edge/ansible/roles/shadowsocks-server/`
- `edge/ansible/roles/shadowtls-server/`
- `edge/ansible/roles/shadowsocks-client/`
- `edge/ansible/roles/shadowtls-client/`
- `edge/ansible/roles/edge-vector/`
- `edge/ansible/roles/node-exporter/`
- `edge/ansible/roles/edge-victoriametrics-scrape/`
- `edge/ansible/deploy-edge-tunnel-server.yml`
- `mihomo/ansible/deploy-aliyun.yml` 及其关联 role
- `victoriatraces/ansible/` (整个目录)
- `network-monitor/ansible/` (整个目录)
- `mihomo/monitoring/ansible/` (整个目录)

精简 `deploy-edge.yml`，仅保留：
- Tailscale (edge-tailscale role)
- Apt 镜像切换 (pre_task)

关联变量清理在 `group_vars/all/public.yml` 和 `host_vars/*.yml` 中同步进行。

---

### 阶段 5：服务暴露（Tailscale Operator）

#### 5.1 暴露配置

所有迁移到 K3s 的服务通过 Tailscale Operator 的 `tailscale.com/expose: "true"` annotation 暴露：

| 服务 | Tailscale 域名 (自动生成) | 访问方式 |
|------|--------------------------|---------|
| Grafana | `grafana-monitoring.tail414c32.ts.net` | 直接 HTTPS |
| VictoriaMetrics | `victoriametrics-monitoring.tail414c32.ts.net` | 直接 HTTP (或通过 Grafana 代理) |
| VictoriaLogs | `victorialogs-monitoring.tail414c32.ts.net` | 同上 |
| VictoriaTraces | `victoriatraces-monitoring.tail414c32.ts.net` | 同上 |
| ArgoCD | `argocd-argocd-server.tail414c32.ts.net` | 已有，无变化 |

#### 5.2 ProxyClass 策略

所有服务使用 `gtr-only` ProxyClass（已有），确保 Tailscale 代理 Pod 调度到 GTR：
```yaml
# 已有 platform/resources/tailscale-proxyclass-gtr-only.yaml
# 在 service annotation 中引用：
tailscale.com/proxy-class: "gtr-only"
```

---

## 待定决策（后续迭代）

### A. VictoriaMetrics 集群 Prometheus Scrape

**问题：** VictoriaMetrics 是否通过 ServiceMonitor/PodMonitor 自动发现并抓取集群内 Pod 的 `/metrics` 端点？

**当前状态：** 待定。本次迁移保持 VM 的静态 scrape config 模式（仅抓取已知的边缘代理 endpoint + Node Exporter 节点 IP）。

**后续评估：** 如果引入 Prometheus Operator (kube-prometheus-stack)，可与 VM 集成。或者 VM 的 `vmagent` 可作为 DaemonSet 部署以实现 K8s SD。

### B. Vector DaemonSet 日志采集范围

**问题：** Vector DaemonSet 应采集哪些日志？

**当前状态：** 待阶段 1/2 完成后评估。候选范围：
- **A)** 仅 K8s pod stdout/stderr → VictoriaLogs
- **B)** Pod logs + 主机 journald
- **C)** Pod logs + Prometheus scrape (替代 VM 静态抓取)
- **D)** 全部（A+B+C）

### C. Grafana 仪表板 & 告警迁移

**问题：** 现有 Grafana 的仪表板和告警规则如何迁移到 K8s Grafana？

**策略：** 使用 Grafana sidecar 自动加载 ConfigMap 中的仪表板 JSON（社区 chart 内置支持）。告警规则通过 Grafana 的 provisioning 文件管理。

---

## 依赖关系 & 执行顺序

```
阶段 0 (前置)
  └─ remote_proxy 加入 K3s、节点 taint、目录结构
      │
      ▼
阶段 1 (CronJob，可独立)
  ├─ Network Monitor CronJob          ← 无依赖
  └─ Mihomo 监控 CronJob             ← 依赖阶段 2 的 VM (可延迟激活)
      │
      ▼
阶段 2 (StatefulSet，核心依赖链)
  ├─ VictoriaTraces  ← 无依赖 (最先部署)
  ├─ VictoriaLogs    ← 无依赖
  ├─ VictoriaMetrics ← 无依赖
  └─ Grafana         ← 依赖 VM + VL (数据源指向这两个 Service)
      │
      ▼
阶段 3 (DaemonSet，依赖阶段 2 的后端)
  ├─ Node Exporter   ← 无依赖 (但 VM 需要抓取)
  └─ Vector          ← 依赖 VictoriaLogs/VictoriaMetrics/VictoriaTraces ClusterIP
      │
      ▼
阶段 4 (Envoy 废弃)
  └─ 所有节点 Envoy 停止 + 禁用
      │
      ▼
阶段 5 (Tailscale 暴露)
  └─ 所有服务 annotation 验证 + Tailscale ACL 更新
```

**可并行执行：**
- 阶段 1 中的两个 CronJob 可同时部署
- 阶段 2 中的 VictoriaTraces/VictoriaLogs/VictoriaMetrics 可同时部署（无相互依赖）
- Grafana 必须在 VM+VL 之后部署（数据源配置引用）

**关键路径：** 阶段 0 → 阶段 2 (VM+VL+VT+VTraces) → 阶段 2 (Grafana) → 阶段 3 → 阶段 5

---

## 验证检查清单

### 阶段 1 验证

- [ ] Network Monitor CronJob 成功执行，Pod 日志中有测试结果 JSON
- [ ] Mihomo 监控 CronJob 成功拉取 Mihomo API 数据

### 阶段 2 验证

- [ ] `kubectl get pods -n monitoring` 所有 Pod Running
- [ ] `kubectl get pvc -n monitoring` 所有 PVC Bound
- [ ] `kubectl port-forward` 到各 Service 确认端口响应
- [ ] VM scrape targets 中 Node Exporter 节点指标正常
- [ ] Grafana 登录成功，数据源 (VM/VL) 连接正常
- [ ] 各服务 Tailscale 域名可访问

### 阶段 3 验证

- [ ] `kubectl get ds -n monitoring` Node Exporter 在所有节点 Running
- [ ] VM 可访问各节点 `:9100/metrics`
- [ ] Vector DaemonSet 在所有节点 Running
- [ ] Vector 日志/指标/追踪成功发送到对应后端

### 阶段 4 验证

- [ ] 所有节点 `systemctl is-active envoy` 返回 `inactive`
- [ ] Tailscale 域名访问各服务正常（替代 Envoy 路径）
- [ ] 原 Envoy 端口 80/443 不再监听

### 阶段 5 验证

- [ ] `tailscale status` 显示所有暴露服务
- [ ] Tailscale ACL 配置正确（如有修改）
- [ ] 从 Tailscale 客户端可直接访问所有服务

---

## 风险矩阵

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| remote_proxy 跨洋 K3s 延迟导致 control-plane 不稳定 | 中 | 高 | 打 taint 不调度 Pod；仅作为 edge node 运行 DaemonSet；监控 etcd 延迟 |
| Grafana 数据源从 localhost 改为 K8s Service DNS 后不可达 | 低 | 中 | 阶段 2 部署后立即 `port-forward` 测试数据源连通性 |
| VM scrape config 丢失边缘代理 metrics | 中 | 低 | 静态 scrape jobs 写入 Helm values；Enovy 废弃后这些 endpoint 可能不再存在，需确认 |
| PVC 空间不足 | 低 | 中 | 初始分配保守值 + `allowVolumeExpansion: true` |
| Tailscale Operator ProxyClass 负载集中在 GTR | 低 | 低 | GTR 当前已承载所有 Tailscale 代理，状态不变 |
| 社区 chart 版本更新与 values 不兼容 | 中 | 低 | 锁定 chart 版本；CI 中包含 Helm lint/dry-run |
| 数据清零后丢失历史可观测数据 | 确定 (已接受) | 低 | 裸金属数据目录保留 30 天作为备份，确认迁移正常后手动清理 |
| aliyun/remote_proxy taint 阻止必要 Pod 调度 | 低 | 中 | 所有 DaemonSet 配置 `tolerations: [{operator: Exists}]`；灰度验证 |
| Envoy 废弃后，原 Envoy 暴露的 `/metrics` 端点不可用 | 确定 | 低 | Node Exporter 替代节点 metrics；边缘代理 metrics 如不需要则接受 |

---

## 相关文档

- [K3s 平台 CI 部署指南](../deployment/k3s-platform-ci-deployment-guide.md)
- [Ansible 约定](../topic/infrastructure/ansible-conventions.md)
- [Secrets 管理](../deployment/secrets-management.md)
- [K3s 平台概述](../../k3s/README.md)
- [各服务 Runbook](../../grafana/README.md) (Grafana/VM/VL/VT/Envoy/Node Exporter)

---

## 后续 PR 拆分建议

| PR | 内容 | 阶段 | 风险 |
|----|------|------|------|
| PR-1 | 目录结构 + CronJob (Network Monitor + Mihomo 监控) | 0 + 1 | 低 |
| PR-2 | VictoriaTraces Helm values + Application | 2 | 低 |
| PR-3 | VictoriaLogs Helm values + Application | 2 | 低 |
| PR-4 | VictoriaMetrics Helm values + Application | 2 | 低 |
| PR-5 | Grafana Helm values + Application | 2 | 低 |
| PR-6 | Node Exporter Helm values + Application | 3 | 低 |
| PR-7 | Vector Helm values + Application (待定 B 澄清后) | 3 | 中 |
| PR-8 | Envoy 废弃 + Ansible Role/Playbook 清理 | 4 | 中 |
| PR-9 | Tailscale Operator expose annotation 验证 + ACL 更新 | 5 | 低 |
