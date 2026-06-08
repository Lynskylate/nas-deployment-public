# 阶段 0+1 节点操作命令

> 本文保留阶段化说明，但节点角色已更新为：`tencent` 是 server，`aliyun` 是 agent，`remote_proxy` 的 Kubernetes Node 名必须写成 `remote-proxy`。

## 部署流程概述

ArgoCD App-of-Apps 会自动 watch `platform/applications/`，因此：

```text
git push
  -> ArgoCD 发现新的/变更的 Application CRD
  -> 自动注册 Application
  -> 各 Application 从 platform/resources/ 或 Helm values 同步
```

原则：**不要手动 `kubectl apply` Application CRD；优先通过 GitOps。**

## 先决条件

- 已通过 Tailscale 连到集群
- `kubectl` 指向 `https://100.99.48.76:6443`
- `deploy-platform-argocd.yml` 已执行

## 0.1 agent 加入集群

```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml --limit aliyun,remote_proxy,gtr -v
```

说明：

- `remote_proxy` 是 inventory alias
- K8s Node 对象名固定为 `remote-proxy`
- 海外节点只运行 DaemonSet / 基础组件，不承载普通 workload

## 0.2 节点 taint / label

这些状态现在应优先由 Ansible 变量驱动：

- `host_vars/aliyun/public.yml` → `k3s_node_taints`
- `host_vars/remote_proxy.yml` → `k3s_node_taints` + `k3s_node_labels`

手动核对命令：

```bash
kubectl describe node aliyun | grep -A5 Taints
kubectl describe node remote-proxy | grep -A8 'Taints\\|Labels'
kubectl describe node tencent | grep -A5 Taints
```

预期：

- `aliyun` 含 `CriticalAddonsOnly=true:NoSchedule`
- `remote-proxy` 含 `NoSchedule=true:NoSchedule`
- `remote-proxy` 含 `topology.kubernetes.io/region=us-west`
- `tencent` 无额外业务 taint

## 0.3 Mihomo API SealedSecret

Mihomo 监控所需 Secret 应通过 SealedSecret 进入集群，不要长期手工创建明文 Secret。

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
