## Observability Stack: Bare-metal → K3s 迁移方案

### 概述

将 GTR 节点上以 systemd 服务运行的 VictoriaMetrics、VictoriaLogs、VictoriaTraces、node-exporter 迁移到现有的 K3s + Argo CD GitOps 体系中。

迁移后的架构：

| 组件 | 部署方式 | 调度 | 持久化 |
|---|---|---|---|
| VictoriaMetrics | Helm chart `victoria-metrics-single` | gtr nodeSelector | hostPath PV → `/var/lib/victoriametrics/data` |
| VictoriaLogs | Helm chart `victoria-logs-single` | gtr nodeSelector | hostPath PV → `/var/lib/victorialogs/data` |
| VictoriaTraces | Helm chart `victoria-traces-single` | gtr nodeSelector | hostPath PV → `/var/lib/victoriatraces/data` |
| node-exporter | DaemonSet (raw manifests) | 所有 K3s 节点 | 无状态 |
| VM Operator | Helm chart `victoria-metrics-operator` | 任意节点 | 无状态 |
| VMAgent | CRD (Operator 管理) | gtr nodeSelector | 无状态 |
| Prometheus CRDs | Helm chart `prometheus-operator-crds` | — | — |

**抓取架构**: `ServiceMonitor` / `VMStaticScrape` → Operator 生成配置 → `VMAgent` 抓取 → remote_write → `VictoriaMetrics`

所有 Victoria* 组件通过 Argo CD App-of-Apps 自动管理。同步顺序：`prometheus-operator-crds` (wave -2) → `observability-pv` / `victoria-metrics-operator` (wave -1) → 其余。

---

### 新增文件清单

```
platform/applications/
  prometheus-operator-crds.yaml  # Argo App: Prometheus Operator CRDs (sync-wave -2)
  observability-pv.yaml          # Argo App: hostPath PV/PVC (sync-wave -1)
  victoria-metrics-operator.yaml # Argo App: VM Operator Helm chart (sync-wave -1)
  victoriametrics.yaml           # Argo App: Helm victoria-metrics-single
  victorialogs.yaml              # Argo App: Helm victoria-logs-single
  victoriatraces.yaml            # Argo App: Helm victoria-traces-single
  node-exporter.yaml             # Argo App: directory → node-exporter/
  vmagent.yaml                   # Argo App: directory → vmagent/

platform/resources/
  observability-pv/pv-pvc.yaml  # 3 组 hostPath PV + PVC
  node-exporter/daemonset.yaml  # DaemonSet + headless Service
  vmagent/vmagent.yaml          # VMAgent + ServiceMonitor + VMStaticScrape

grafana/datasources.yaml         # localhost → K8s Service DNS
platform/resources/mihomo-monitoring/deployment.yaml  # VM 端点 → K8s Service DNS
```

---

### 迁移步骤

#### Phase 1: 准备（不中断服务）

```bash
# 1. SSH 到 GTR，确认现有服务运行正常
ssh gtr
systemctl status victoriametrics victorialogs victoriatraces node_exporter

# 2. 备份现有数据（可选但推荐）
sudo tar -czf /tmp/vm-backup-$(date +%Y%m%d).tar.gz /var/lib/victoriametrics/data
sudo tar -czf /tmp/vl-backup-$(date +%Y%m%d).tar.gz /var/lib/victorialogs/data
sudo tar -czf /tmp/vt-backup-$(date +%Y%m%d).tar.gz /var/lib/victoriatraces/data

# 3. 修复数据目录权限（容器以 UID 65534/nobody 运行）
sudo chown -R 65534:65534 /var/lib/victoriametrics/data
sudo chown -R 65534:65534 /var/lib/victorialogs/data
sudo chown -R 65534:65534 /var/lib/victoriatraces/data
```

#### Phase 2: 合并并部署

```bash
# 4. 合并 feature 分支到 main 并 push
cd /path/to/nas-deployment-public
git merge feat/observability-k8s-migration
git push origin main

# 5. Argo CD 自动检测到新的 Applications 后开始同步
#    同步顺序: observability-pv (wave -1) → victoriametrics/victorialogs/victoriatraces/node-exporter
#    此时 K8s pods 会启动但因端口冲突可能 CrashLoop（bare-metal 服务仍占用端口）
```

#### Phase 3: 切换（短暂中断）

```bash
# 6. 停止 GTR 上的 bare-metal 服务
ssh gtr
sudo systemctl stop victoriametrics victorialogs victoriatraces
sudo systemctl disable victoriametrics victorialogs victoriatraces

# 7. 停止 GTR 上的 bare-metal node_exporter（DaemonSet 需要端口 9100）
sudo systemctl stop node_exporter
sudo systemctl disable node_exporter

# 8. K8s pods 会自动重启并成功绑定端口
#    验证:
kubectl -n monitoring get pods -l app=victoriametrics
kubectl -n monitoring get pods -l app=victorialogs
kubectl -n monitoring get pods -l app=victoriatraces
kubectl -n monitoring get pods -l app=node-exporter

# 9. 验证数据完整性
curl http://100.121.0.67:8428/api/v1/query?query=up  # VM
curl http://100.121.0.67:8429/health                  # VL
curl http://100.121.0.67:9428/health                  # VT
```

#### Phase 4: 更新 edge 节点

```bash
# 10. 更新 edge 节点 Vector 配置，指向 K8s Service（通过 Tailscale IP 或 K8s NodePort）
#     如果 Grafana 仍然是 bare-metal，也需要更新 datasources 指向 GTR 的 Tailscale IP
#     edge Vector 配置 (group_vars/all/public.yml) 中的 host/port 不需要改，
#     因为 K8s Service 仍然监听同样的端口（通过 ClusterIP → Pod），
#     外部流量需要通过 Tailscale IP 到达 GTR 节点上的 Pod。
#
#     方案 A: 给 Service 加 annotation tailscale.com/expose=true (推荐)
#     方案 B: 改用 NodePort 或 hostNetwork
#
#     如果选择方案 A，在 Argo Application 的 Helm values 中添加:
#       service:
#         annotations:
#           tailscale.com/expose: "true"
#           tailscale.com/proxy-class: "gtr-only"

# 11. 重新部署 Grafana 以使用新的 datasources
#     如果 Grafana 也是 Ansible 部署:
ansible-playbook edge/ansible/deploy-gtr-grafana.yml
```

#### Phase 5: 清理

```bash
# 12. 确认一切正常后，删除 bare-metal systemd unit files（可选）
ssh gtr
sudo rm /etc/systemd/system/victoriametrics.service
sudo rm /etc/systemd/system/victorialogs.service
sudo rm /etc/systemd/system/victoriatraces.service
# node_exporter 在 edge 节点仍需要（非 K3s 节点）
sudo systemctl daemon-reload
```

---

### Grafana 连接问题

Grafana 如果仍然以 bare-metal 运行在 GTR 上，它无法解析 K8s 内部 DNS（`*.monitoring.svc`）。

解决方案（选一）：

**方案 A: Grafana 也迁入 K8s（推荐）**
使用 `grafana/grafana` Helm chart，同样 pin 到 GTR 节点，就可以直接使用 K8s Service DNS。

**方案 B: 用 Tailscale Operator 暴露 Service**
给 VM/VL/VT 的 Service 加 `tailscale.com/expose: "true"` annotation，Grafana 通过 Tailscale DNS 访问。

**方案 C: Grafana datasources 用 GTR 的 Tailscale IP**
直接把 `datasources.yaml` 中的 URL 改为 `http://100.121.0.67:<port>`，前提是 K8s Pod 可以通过 Tailscale IP 从外部访问。这需要在 Service 上加 `tailscale.com/expose` 或使用 `hostNetwork`。

---

### 回滚方案

```bash
# 1. 停止 K8s pods（通过 Argo CD disable 或直接 delete）
kubectl -n monitoring delete statefulset victoriametrics
kubectl -n monitoring delete statefulset victorialogs
kubectl -n monitoring delete deployment victoriatraces
kubectl -n monitoring delete daemonset node-exporter

# 2. 重新启动 bare-metal 服务
ssh gtr
sudo systemctl start victoriametrics victorialogs victoriatraces node_exporter

# 3. 数据完整（hostPath PV 指向同一目录，K8s pods 写入的数据也在同一位置）
```

---

### 注意事项

1. **端口冲突**: node-exporter DaemonSet 使用 `hostNetwork: true`，必须先停掉 bare-metal node_exporter 才能启动。所有 K3s 节点（gtr/tencent/aliyun/remote_proxy）都需要停。

2. **数据目录权限**: 容器默认以 UID 65534 (nobody) 运行，而 bare-metal 服务各自有独立用户。迁移前必须 `chown -R 65534:65534` 数据目录。

3. **PV 不可 auto-prune**: `observability-pv` Application 设置了 `prune: false`，防止 Argo CD 误删 PV/PVC 导致数据丢失。

4. **Helm chart targetRevision `0.x`**: 首次部署后建议锁定到具体版本号，避免 Argo CD 自动升级到不兼容版本。

5. **VMAgent 中 `127.0.0.1:9901` (local envoy)**: VMAgent pod 通过 overlay 网络访问 `127.0.0.1` 时，访问的是 pod 自身的 loopback，不是 GTR 宿主机。如果无法 scrape 到 local envoy，需要在 VMStaticScrape 中将目标改为 GTR 的节点 IP（如 `192.168.31.59`）。

6. **edge Vector 的 sink 端点**: 当前 Vector 通过 `gtr.tail414c32.ts.net:<port>` 访问 VM/VL/VT。迁移到 K8s 后，Service 已配置 `tailscale.com/expose` annotation，Tailscale Operator 会自动创建代理，edge Vector 可直接通过 Tailscale DNS 访问。
