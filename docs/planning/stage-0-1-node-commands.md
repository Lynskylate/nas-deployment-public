# 阶段 0+1 节点操作命令

## 部署流程概述

ArgoCD 的 **App-of-Apps** 已在 `edge/ansible/roles/argocd/tasks/main.yml` 中创建，
自动 watch `platform/applications/` 目录（`directory: { recurse: true }`）。

```
git push → ArgoCD App-of-Apps 发现新 Application CRD
         → 自动注册到 ArgoCD
         → 各 Application 从 platform/resources/<service>/ sync 资源
```

**无需手动 `kubectl apply` Application CRD 文件。** 只需提交并 push 即可。

## 先决条件

- 已通过 Tailscale 连接到 K3s 集群
- `kubectl` 已配置指向 `https://100.100.99.70:6443`
- ArgoCD App-of-Apps 已部署（`deploy-platform-argocd.yml` 已执行过）

---

## 0.1 remote_proxy 加入 K3s agent

```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml --limit remote_proxy -v
```

> **注意：** remote_proxy 在美国（跨洋 ~200ms 延迟），加入 K3s 仅用于运行 DaemonSet（node_exporter、Vector）。

## 0.2 节点 Taint 配置

### aliyun — 禁止调度业务容器（仅系统组件）

```bash
kubectl taint nodes aliyun CriticalAddonsOnly=true:NoSchedule --overwrite
```

验证：
```bash
kubectl describe node aliyun | grep -A5 Taints
# Taints: node-role.kubernetes.io/control-plane:NoSchedule
#          CriticalAddonsOnly=true:NoSchedule
```

### tencent — 允许调度无状态工作负载（不打 taint）

```bash
kubectl taint nodes tencent NoSchedule- 2>/dev/null || true
```

验证：
```bash
kubectl describe node tencent | grep -A5 Taints
# 预期：无 Taints
```

### remote_proxy — 禁止调度（跨洋延迟）

```bash
kubectl taint nodes remote_proxy NoSchedule=true:NoSchedule --overwrite
kubectl label nodes remote_proxy topology.kubernetes.io/region=us-west --overwrite
```

验证：
```bash
kubectl describe node remote_proxy | grep -A5 Taints
# Taints: NoSchedule=true:NoSchedule
```

## 0.3 GTR 节点标签

```bash
kubectl label nodes gtr node-role.kubernetes.io/workload=true --overwrite
```

---

## 0.4 创建 Mihomo API SealedSecret

Mihomo 监控需要 Mihomo API secret 才能访问 `/traffic`、`/connections`、`/proxies` 等端点。

### 方式一：通过 SealedSecret（推荐，GitOps 管理）

SealedSecrets controller 已在集群中运行（ArgoCD Application `sealed-secrets`）。

**在能访问 K3s 集群的机器上执行（如通过 Tailscale 连接的机器）：**

```bash
# 1. 安装 kubeseal（如未安装）
KUBESEAL_VERSION=0.27.3
curl -fsSL \
  "https://github.com/bitnami-labs/sealed-secrets/releases/download/v${KUBESEAL_VERSION}/kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz" \
  | tar -xz kubeseal
sudo mv kubeseal /usr/local/bin/

# 2. 从 private vault 获取 Mihomo API secret
#    位置：nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml
#    字段：mihomo_api_secret（或类似名称）
MIHOMO_SECRET_VALUE='<从 vault 解密后获取>'

# 3. 密封 Secret
kubectl -n monitoring create secret generic mihomo-api \
  --from-literal=MIHOMO_SECRET="${MIHOMO_SECRET_VALUE}" \
  --dry-run=client -o yaml | \
  kubeseal --controller-namespace kube-system \
    --controller-name sealed-secrets -o yaml > \
  platform/resources/mihomo-monitoring/sealedsecret.yaml

# 4. 提交到 git
git add platform/resources/mihomo-monitoring/sealedsecret.yaml
git commit -m 'add mihomo-api SealedSecret for stage 1'

# 5. Push → ArgoCD 自动同步 SealedSecret → Secret 创建
#    然后 mihomo-metrics Deployment 的 secretKeyRef 即可正常启动
```

### 方式二：手动创建（仅限测试，不推荐长期使用）

```bash
kubectl -n monitoring create secret generic mihomo-api \
  --from-literal=MIHOMO_SECRET='<mihomo-api-secret>' \
  --dry-run=client -o yaml | kubectl apply -f -
```

> **注意：** 方式二不在 GitOps 管理范围内。如果 namespace 被删除，需手动重建。
> 生产环境务必使用方式一（SealedSecret）。

---

## 0.5 部署到集群

### 自动部署（推荐）

`platform/applications/` 下的 Application CRD 文件已提交到 git。
ArgoCD App-of-Apps 自动发现并注册为 ArgoCD Application：

```bash
# 查看 App-of-Apps 状态
kubectl -n argocd get application platform-apps

# 等待自动同步（默认 3 分钟）或手动触发
argocd app sync platform-apps
```

ArgoCD 同步 `network-monitor` 和 `mihomo-monitoring` Application 后，
各 Application 会自动从 `platform/resources/<service>/` 同步实际资源。

### 手动测试（绕过 ArgoCD，仅用于调试）

```bash
kubectl apply -f platform/resources/network-monitor/cronjob.yaml
kubectl apply -f platform/resources/mihomo-monitoring/deployment.yaml
```

### 手动触发 ArgoCD sync

```bash
# 安装 argocd CLI（如未安装）
# curl -sSL -o argocd ... https://github.com/argoproj/argo-cd/releases/...

# 或通过 kubectl 硬刷新
kubectl -n argocd patch application network-monitor \
  --type merge -p '{"operation":{"sync":{"revision":"main"}}}'

kubectl -n argocd patch application mihomo-monitoring \
  --type merge -p '{"operation":{"sync":{"revision":"main"}}}'
```

---

## 验证

```bash
# 1. 确认 ArgoCD Application 已注册
kubectl -n argocd get application network-monitor mihomo-monitoring

# 2. 确认资源已创建
kubectl -n monitoring get cronjob network-monitor
kubectl -n monitoring get deployment mihomo-metrics

# 3. 确认 Pod 正在运行
kubectl -n monitoring get pods

# 4. 查看日志（CronJob 在触发后才有 Pod）
# 手动触发一次 CronJob：
kubectl -n monitoring create job --from=cronjob/network-monitor network-monitor-test
kubectl -n monitoring logs -l app=network-monitor --tail=30

# 5. Mihomo 指标收集器日志
kubectl -n monitoring logs -l app=mihomo-metrics --tail=20
# 预期输出（每次循环）：
#   Mihomo metrics collector starting (interval=30s)
#   2026-06-07T... Metrics pushed (HTTP 204)

# 6. 验证指标是否到达 VictoriaMetrics（裸金属 :8428）
curl -s 'http://100.121.0.67:8428/api/v1/label/__name__/values' \
  | jq '.[]' | grep mihomo_scrape_success
```
