# K3s 平台 CI 部署指南

## 当前拓扑

| 节点 | 角色 | 连接方式 | 备注 |
|------|------|---------|------|
| tencent | K3s server (control-plane) | 公网 SSH + Tailscale API | 当前唯一 control-plane |
| gtr | K3s agent | Tailscale SSH / API | 主要 workload 与持久化节点 |
| aliyun | K3s agent | 公网 SSH + Tailscale API | 原 server，现已降级为 agent |
| remote_proxy | K3s agent | 公网 SSH + Tailscale API | K8s Node 名必须为 `remote-proxy` |

固定参数：

- K3s API: `https://100.99.48.76:6443`
- Pod CIDR: `10.60.0.0/16`
- Service CIDR: `10.61.0.0/16`
- Flannel: `vxlan` over `tailscale0`

## CI 流程

当前 workflow 的主顺序：

```text
preflight
  -> deploy-gtr
  -> deploy-edge
  -> deploy-k3s-server (tencent)
  -> deploy-k3s-agent (gtr, aliyun, remote_proxy)
  -> deploy-platform-operators
       -> deploy-platform-argocd
       -> bootstrap-platform-sealed-secrets-key
       -> deploy-platform-tailscale-operator
```

说明：

- `scripts/resolve_deploy_plan.py` 按变更路径决定是否全量或部分执行。
- `deploy-edge.yml` 现在只负责 edge 基线，不再安装 bare-metal `node_exporter`。
- 集群内应用由 ArgoCD 管理；Ansible 只负责 K3s 与平台引导层。

## CI 拓扑契约

这些约束由 `scripts/validate_ci_topology.py` 和相关 verify playbook 保证：

| 约束 | 当前要求 |
|------|---------|
| `remote_proxy ansible_host` | 必须是公网 IP |
| `aliyun ansible_host` | 必须是公网 IP |
| `k3s_server_url` | 必须指向 tencent 的 Tailscale API 地址 |
| `host_vars/tencent.yml:k3s_server_tailscale_ip` | 必须与当前 server Tailscale IP 一致 |
| `host_vars/remote_proxy.yml:k3s_node_name` | 必须固定为 `remote-proxy` |
| `host_vars/aliyun/public.yml:k3s_agent_server_url` | 必须指向 tencent API |

如果这些约束变化，必须同步更新：

- `scripts/validate_ci_topology.py`
- `edge/ansible/verify-gtr-k3s-server.yml`
- `edge/ansible/verify-gtr-k3s-agent.yml`
- `.github/workflows/deploy-infra.yml`

## Secrets 与运行时文件

CI 通过 `.github/actions/bootstrap-deploy-env` 完成：

1. checkout `nas-deployment-vault`
2. `sops --decrypt` 生成 `*.runtime.yml`
3. 恢复 Sealed Secrets 私钥 runtime 文件
4. 结束后由 `.github/scripts/cleanup-vault.sh` 清理 runtime 文件

约束：

- `*.sops.yml` 只能留在 vault 仓库中
- `nas-deployment-public/edge/ansible/**` 在执行时只应出现 `*.runtime.yml`
- 任何出现在 public repo 工作树中的 `*.sops.yml` 都应视为脏环境并先清理

## 部署后验证

```bash
# 节点
ssh ci@129.211.12.63 "sudo k3s kubectl get nodes -o wide"

# ArgoCD
ssh ci@129.211.12.63 "sudo k3s kubectl -n argocd get applications"

# Sealed Secrets / Tailscale Operator
ssh ci@129.211.12.63 "sudo k3s kubectl -n kube-system get deploy,pods | grep sealed-secrets"
ssh ci@129.211.12.63 "sudo k3s kubectl -n tailscale get deploy,pods"

# Observability
ssh ci@129.211.12.63 "sudo k3s kubectl -n monitoring get pods"
ssh ci@129.211.12.63 "sudo k3s kubectl -n monitoring get pv,pvc"
```

验收标准：

- `tencent`、`gtr`、`aliyun`、`remote-proxy` 全部 `Ready`
- `argocd` namespace 下 applications 不再出现 `Unknown` / `ComparisonError`
- `sealed-secrets`、`tailscale-operator` 正常 rollout
- `victoriametrics`、`victorialogs`、`victoriatraces`、`vmagent`、`node-exporter` 正常运行

## 常见故障

| 症状 | 优先检查 |
|------|---------|
| `remote_proxy` agent 无法注册 | `k3s_node_name` 是否为 `remote-proxy` |
| ArgoCD Application `Unknown` | `argocd-repo-server` / cluster DNS 是否正常 |
| `node-exporter` DaemonSet 起不来 | 是否仍有 bare-metal `node_exporter` 占用 `9100` |
| SealedSecret 无法解密 | vault 私钥是否已通过 `bootstrap-platform-sealed-secrets-key.yml` 恢复 |
| agent 连接 API 失败 | `k3s_server_url`、Tailscale 连通性、`tailscale0` flannel 配置 |
| v1 | 2026-06-07 | — | 初始 CI 部署指南 |
