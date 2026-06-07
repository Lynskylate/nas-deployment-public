# K3s 平台 CI 部署指南

## 部署拓扑

| 节点 | 角色 | Tailscale IP | 云厂商 | 特殊配置 |
|------|------|-------------|--------|---------|
| aliyun | K3s server (control-plane) | 100.100.99.70 | 阿里云 ECS | TLS SANs 含公网 IP `47.120.46.128` |
| gtr | K3s agent | 100.121.0.67 | 家庭服务器 | 本地 mihomo 代理 `127.0.0.1:7890` |
| tencent | K3s agent | 100.99.48.76 | 腾讯云 CVM | API server 走公网 IP（Tailscale TCP 阻断） |

---

## CI 部署流程

### 部署顺序（当前 workflow）

```
preflight
  ├→ deploy-gtr
  ├→ deploy-edge (按变更选择 remote_proxy / aliyun / tencent)
  └→ deploy-k3s-server (aliyun)
       └→ deploy-k3s-agent (gtr, tencent)
            └→ deploy-platform-operators
                 ├→ deploy-platform-argocd
                 ├→ bootstrap-platform-sealed-secrets-key
                 └→ deploy-platform-tailscale-operator
```

说明：

- `push` 触发不再默认全量部署，而是由 `scripts/resolve_deploy_plan.py` 按变更路径决定需要运行的 job 与子步骤
- `preflight` 只在 runner 真的需要访问 tailnet 私网节点时才 bootstrap 并连接 Tailscale
- `deploy-platform-operators` 现在会按组件粒度选择 ArgoCD / Sealed Secrets / Tailscale Operator，而不是每次全跑

### 各阶段说明

| 阶段 | Playbook | 目标 | 前置条件 |
|------|---------|------|---------|
| 1 | `deploy-gtr-k3s-server.yml` | 在 aliyun 上安装 K3s server | Tailscale 已认证，ci 用户可用 |
| 2 | `deploy-gtr-k3s-agent.yml` | 在 gtr/tencent 上安装 K3s agent | K3s server API 可达 |
| 3 | `deploy-platform-argocd.yml` | 安装 ArgoCD + App-of-Apps | K3s 集群健康 |
| 4 | `bootstrap-platform-sealed-secrets-key.yml` | 从 vault 恢复私钥到集群 | ArgoCD 运行中 |
| 5 | `deploy-platform-tailscale-operator.yml` | 预设 Tailscale Operator 基础环境 + HelmChart | ArgoCD 运行中 |

---

## CI 与手动部署的关键区别

### 0. CI 稳定性契约

当前仓库**刻意不把 aliyun 的 Tailscale 直连当作 CI 前提**。稳定路径是：

| 路径 | 固定策略 | 原因 |
|------|---------|------|
| GitHub Actions → remote_proxy SSH | `inventory-edge.ini` 中 `remote_proxy ansible_host=<公网 IP>` | runner 与 remote_proxy 都在美国，没有必要先接入 tailnet 再跨洋转发 |
| GitHub Actions → aliyun SSH | `inventory-edge.ini` 中 `aliyun ansible_host=<公网 IP>` | aliyun↔gtr 的 Tailscale 直连会受云厂商/运营商 UDP 路径影响，不能作为 CI 依赖 |
| K3s 默认 API | `group_vars/all/public.yml` 中 `k3s_server_url=https://<aliyun Tailscale IP>:6443` | gtr、本地控制面默认仍优先走 Tailscale |
| tencent → K3s API | `host_vars/tencent.yml` 中 `k3s_agent_server_url=https://<aliyun 公网 IP>:6443` | tencent→aliyun 的 Tailscale TCP 路径不可靠，需显式走公网 |
| aliyun Tailscale | `k3s_prereq_tailscale_nodivert: true` | 防止云厂商 100.x 地址与 Tailscale netfilter 冲突导致失联 |

以上契约已写入：

- `scripts/validate_ci_topology.py`
- `validate-pr.yml`
- `deploy-infra.yml` 的 `preflight`
- `verify-gtr-k3s-server.yml`
- `verify-gtr-k3s-agent.yml`

其中 `scripts/validate_ci_topology.py` 还会显式阻止：

- `remote_proxy ansible_host` 被改回 Tailscale CGNAT 地址
- `aliyun ansible_host` 被改回 Tailscale CGNAT 地址
- `tencent` 的 agent API 回退到不稳定的 Tailscale TCP 路径

如果未来要改回“CI 全量依赖 Tailscale 直连”，必须先证明 aliyun/tencent 的真实网络路径稳定，再同步更新这些校验。

### 1. 手动步骤 CI 需自动化

| 手动步骤 | CI 处理方式 | 优先级 |
|---------|------------|--------|
| `tailscale up --auth-key=...` | 节点预配置（CI 假定节点已加入 tailnet） | — |
| `tailscale set --netfilter-mode=nodivert` | 已集成到 `k3s-prereq` role，通过 `k3s_prereq_tailscale_nodivert` 变量控制 | ✅ 已实现 |
| ArgoCD pod 绑定到 GTR | **当前为手动 kubectl patch**——需写入 ArgoCD role 或使用 Helm values | ⚠️ 待实现 |
| kubeconfig 权限修复 (`chmod 644`) | K3s server 配置中 `write-kubeconfig-mode: "0640"` 应已处理 | ✅ 已配置 |
| 阿里云安全组开放端口 | 云控制台操作，非 Ansible 范围 | — |

### 2. 阿里云重置后的 IP 漂移

当前 Tailscale IP (`100.100.99.70`) 由 ipPool 动态分配。服务器重置后可能变化。

**CI 应对方案：**
- `host_vars/aliyun/public.yml` 中 `k3s_server_tailscale_ip` 需与 `tailscale ip -4` 返回值一致
- `k3s_server_url` 在 `group_vars/all/public.yml` 中硬编码——重置后需手动更新
- **建议：** 在 Tailscale admin console 中固定 aliyun 的 IP，或使用 MagicDNS (`vmaliyun.tail414c32.ts.net`)

### 3. Github Actions 中的 Proxy

所有从中国节点下载 GitHub raw content 的任务需要 proxy：

| 任务 | Proxy 变量 | 状态 |
|------|-----------|------|
| K3s 安装脚本下载 | `github_download_proxy` | ✅ 已有 |
| ArgoCD CLI 下载 | `github_download_proxy` | ✅ 已有 |
| ArgoCD manifest 下载 | `github_download_proxy` | ✅ 本次修复已添加 |
| SealedSecrets manifest 下载 | 先下载本地再 apply | ✅ 已有 |

### 4. 避免重复部署与下载

当前 CI 已增加以下快路径：

| 组件 | 快路径判断 | 节省点 |
|------|-----------|-------|
| preflight | 仅当 `gtr/tencent` 等私网目标参与时才连 Tailscale | 避免美国 runner 为无关 job 先接入 tailnet |
| K3s server / agent | 仅在二进制、service 或健康检查不满足时才下载安装脚本 | 避免重复下载 `k3s-install.sh` |
| ArgoCD | deployment 已 ready、版本匹配、bootstrap 资源存在时跳过 reapply | 避免重复下载 install manifest / CLI 与长时间 rollout |
| Sealed Secrets | controller image/rollout 正常且测试 secret 正常解封时跳过重装 | 避免重复下载 manifest、重复备份私钥 |
| deploy-platform-operators | 仅执行受本次变更影响的 operator | 避免 platform 全量串行重跑 |

### 5. Shell 兼容性

CI runner 使用 Ubuntu，`/bin/sh` 是 `dash`，不支持 `set -o pipefail`。

**修复：** 所有使用 `pipefail` 的 shell task 必须加 `args: executable: /bin/bash`

**已修复文件：**
- `roles/argocd/tasks/main.yml` — repo credential 任务
- 待检查：其他 role 中的 shell task

---

## 已知限制与 Workaround

### 1. tencent 节点 Pod 访问 API server 受限

**原因：** 腾讯云 DPI 阻断 Tailscale WireGuard 隧道中的 TCP 流量。

**影响：** 调度到 tencent 的 Pod 无法 exec/logs，kubelet 健康检查可能失败。

**当前 Workaround：**
- ArgoCD 所有 Deployment 绑定到 GTR（`nodeSelector: kubernetes.io/hostname: gtr`）
- tencent 的 k3s-agent 通过 aliyun 公网 IP 连接 API server

**CI 待实现：** 在 ArgoCD install manifest 或 Helm values 中添加 nodeSelector。

### 2. 跨节点 Pod 网络

**原因：** Flannel VXLAN over tailscale0 在 tencent↔aliyun 之间不可靠（同问题 1）。

**当前 Workaround：** 所有控制器 Pod 固定在 GTR 节点，跨节点 Pod 通信非必需。

### 3. embedded-registry 镜像共享

**配置：** `embedded-registry: true`（仅在 server 端生效）

**效果：** 当一个节点拉取镜像后，其他节点可从 server 的内嵌 registry 获取，减少重复拉取。

### 4. 旧 Tailscale Proxy 节点残留

**原因：** 当 Tailscale proxy pod 在 tencent 节点上因为 TCP 阻断开无法正常通信时，operator 删除 pod 后可能无法正常清理 Tailscale 节点注册。

**影响：** MagicDNS 仍解析到旧离线节点。新 proxy pod 会注册为 `servicename-ns-1`。

**Workaround：**
- 在 Tailscale admin console 手动删除旧离线节点
- 删除新 proxy pod 后会重新注册，回收原始 hostname
- URL: https://login.tailscale.com/admin/machines

---

## 部署后验证清单

```bash
# 1. 所有节点 Ready
k3s kubectl get nodes

# 2. ArgoCD 控制器（7/7 Running）
k3s kubectl -n argocd get pods

# 3. ArgoCD Applications 同步
k3s kubectl -n argocd get application
# platform-apps: Synced + Healthy
# sealed-secrets: Synced + Healthy
# tailscale-operator: Synced + Healthy

# 4. Sealed Secrets
k3s kubectl -n kube-system get deploy sealed-secrets
k3s kubectl -n kube-system logs deploy/sealed-secrets --tail=1
# → "HTTP server serving" :8080

# 5. Tailscale Operator
k3s kubectl -n tailscale get deploy operator
# → 1/1 Running

# 6. 跨节点 DNS
k3s kubectl run dns-test --image=busybox:1.36 --restart=Never --rm -it -- \
  nslookup kubernetes.default.svc.cluster.local

# 7. 安全组确认
# - aliyun 安全组：允许 tencent/公网访问端口 6443
# - tencent 安全组：允许出站到 47.120.46.128:6443
```

---

## 故障排查快速参考

| 症状 | 可能原因 | 检查点 |
|------|---------|--------|
| aliyun 不可达 | Tailscale CGNAT iptables | `iptables -L ts-input -n` → DROP 规则应覆盖 `100.100.96.0/20` 而非 `100.64.0.0/10` |
| Pod 卡在 ContainerCreating | 镜像拉取失败 | `k3s kubectl describe pod` → 检查 containerd proxy 配置 |
| ArgoCD Application Unknown | GitHub 不可达 | `kubectl -n argocd exec deploy/argocd-repo-server -- curl -sI https://github.com` |
| ArgoCD Application OutOfSync | repo-server 服务不可达 | `kubectl -n argocd get endpoints argocd-repo-server` |
| tencent 节点 Pod 异常 | API server tunnel 阻断 | tencent k3s-agent 配置中 server 应为公网 IP |
| SealedSecrets 密钥丢失 | 备份被删除 | 检查 `/var/lib/rancher/k3s/sealed-secrets-key-backup.yaml` |
| tailscale netfilter 重置 | tailscaled 重启 | `tailscale debug prefs | grep NetfilterMode` → 应为 `1` |

---

## 本次部署中修复的 CI 兼容性问题

| 文件 | 问题 | 修复 |
|------|------|------|
| `roles/argocd/tasks/main.yml` | `set -o pipefail` 在 dash 下报错 | 添加 `args: executable: /bin/bash` |
| `roles/argocd/tasks/main.yml` | manifest 下载无 proxy | 添加 `environment:` 块使用 `github_download_proxy` |
| `deploy-platform-argocd.yml` | 依赖 secret.runtime.yml 中的 deploy key | vault 中有 `argocd_repo_ssh_key`（已确认） |
| `deploy-platform-tailscale-operator.yml` | 缺少 ServiceAccount/RBAC | 改用 K3s HelmChart CRD（Helm chart 自带 RBAC） |
| `group_vars/all/public.yml` | 重复 YAML key | 删除重复的 `k3s_containerd_https_proxy` |
| `bootstrap-platform-sealed-secrets-key.yml`（原 `deploy-platform-sealed-secrets.yml`） | 私钥备份被立即删除 | 改为从 vault 恢复；controller 由 Argo CD 管理 |
| `deploy-platform-tailscale-operator.yml` | Proxy pods 误调度到 tencent（Tailscale TCP 不通） | 创建 `ProxyClass gtr-only` 强制 proxy pods 到 gtr |
| `platform/applications/tailscale-operator.yaml` | 无 proxy nodeSelector | 添加 `defaultProxyClass: gtr-only` |
| `roles/argocd/tasks/main.yml` | Service annotation 无 proxy-class | 添加 `tailscale.com/proxy-class=gtr-only` |
| `docs/issues/002-...md` | 包含 Tailscale OAuth 明文凭据 | 已 redact，指向 vault repo |

---

## 版本历史

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| v1.1 | 2026-06-07 | — | 添加 ProxyClass gtr-only，修复 tailscale proxy 节点调度；redact 明文凭据；更新平台 playbooks 语法检查 |
| v1 | 2026-06-07 | — | 初始 CI 部署指南 |
