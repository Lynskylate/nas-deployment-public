# K3s 集群重建 SOP

> 基于 GitHub Actions CI 流程，用于从零重建整个 K3s + Platform 基础设施。
> 最后更新：2026-06-08，集群从 aliyun 迁移到 tencent 后。

## 变更摘要（迁移做了什么）

| 变更 | 说明 |
|------|------|
| K3s server | aliyun(100.100.99.70) → **tencent(100.99.48.76)** |
| 节点角色 | aliyun: control-plane → agent |
| 节点拓扑 | +remote_proxy(100.66.156.40) 作为 agent（美国，NoSchedule；K8s Node 名为 `remote-proxy`） |
| SealedSecrets | Ansible 直接部署 → ArgoCD Helm chart 管理；新增 `bootstrap-platform-sealed-secrets-key.yml` 恢复旧密钥 |
| ArgoCD repo auth | SSH key → PAT (`github_username` + `github_token`) |
| CI 拓扑验证 | 重写为 tencent-as-server 拓扑 |
| kubeseal | 不再安装到节点（运维人员在本地使用）；verify playbook 不再依赖 kubeseal |
| Token 处理 | 集群 token 使用 SOPS **加密字符串**（非明文），禁止手动解密写入 config.yaml |
| aliyun agent | 通过 Tailscale IP `100.99.48.76:6443` 直连 tencent（非公网 IP） |
| aliyun DNS | 禁用 Tailscale MagicDNS 覆盖，`/etc/resolv.conf` 恢复为 `systemd-resolved` stub；基础设施统一走 `100.121.0.67` |

**本地运行时文件（可生成但不可提交）：**
- `edge/ansible/group_vars/all/secret.runtime.yml`
- `edge/ansible/group_vars/all/github-token.runtime.yml`
- `edge/ansible/host_vars/gtr/secret.runtime.yml`

**禁止出现在 public repo 工作树中的文件：**
- `edge/ansible/**/secret.sops.yml`
- `edge/ansible/**/github-token.sops.yml`

---

## 前置条件

### GitHub Actions Secrets/Vars（CI 方式）

| Secret/Var | 说明 |
|------------|------|
| `VAULT_REPO_SLUG` | nas-deployment-vault 仓库名（如 `Lynskylate/nas-deployment-vault`） |
| `VAULT_REPO_SSH_KEY` | 访问 vault 仓库的 SSH deploy key |
| `SOPS_AGE_KEY` | 解密 SOPS 文件的 AGE 私钥 |
| `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET` | Tailscale OAuth（CI runner 接入 tailnet） |

### 节点前置

所有节点需要：
- Ubuntu 22.04/24.04
- Tailscale 已安装并接入 tailnet
- SSH key 已配置（`ci` 用户或无密码 sudo）
- 防火墙：tencent 公网 IP **不需要**开放 6443（节点通过 Tailscale 连接）

---

## CI 重建流程

### 1. 触发完整部署

```bash
gh workflow run deploy-infra.yml --ref main -f target=all
```

CI 自动解析依赖顺序：

```
preflight (解析部署计划)
  ├─ deploy-gtr (Mihomo, 资源清单, AI工具)
  │     └─ 需要 Tailscale
  ├─ deploy-edge (edge baseline: Envoy, Tailscale, Vector)
  │     └─ matrix: remote_proxy, aliyun, tencent
  ├─ deploy-k3s-server (K3s server on tencent)
  │     └─ 不需要 Tailscale（走 ansible_host=129.211.12.63 SSH）
  ├─ deploy-k3s-agent (K3s agents: gtr, aliyun, remote_proxy -> node `remote-proxy`)
  │     └─ 通过 Tailscale IP 连接 server
  └─ deploy-platform-operators
        ├─ deploy-platform-argocd.yml
        ├─ bootstrap-platform-sealed-secrets-key.yml  ← 从 vault 恢复密钥
        ├─ verify-platform-sealed-secrets.yml
        ├─ deploy-platform-tailscale-operator.yml
        └─ verify-platform-tailscale-operator.yml
```

### 2. 部署完成后等待 ArgoCD 同步

ArgoCD Application `platform-apps`（type: Directory）会自动同步子 Applications：
- `sealed-secrets` (Helm chart 2.x)
- `tailscale-operator` (Helm chart 2.x)
- `network-monitor`
- `mihomo-monitoring`

同步完成后所有 application 显示 `Synced / Healthy`。

### 3. 验证

```bash
# 4 节点全部 Ready
ssh ci@129.211.12.63 "sudo k3s kubectl get nodes"

# ArgoCD 应用状态
ssh ci@129.211.12.63 "sudo k3s kubectl -n argocd get application"

# 关键 Pod 运行
ssh ci@129.211.12.63 "sudo k3s kubectl -n monitoring get pods"
```

---

## 手动重建流程（CI 不可用时）

### 环境准备

```bash
# 从 vault 解密 SOPS 文件到 Ansible 目录
export SOPS_AGE_KEY_FILE=/path/to/age-key.txt

sops -d .vault/repo/ansible/edge/group_vars/all/secret.sops.yml \
  > edge/ansible/group_vars/all/secret.runtime.yml

sops -d .vault/repo/ansible/edge/host_vars/gtr/secret.sops.yml \
  > edge/ansible/host_vars/gtr/secret.runtime.yml

sops -d .vault/repo/infra/argocd/github-token.sops.yml \
  > edge/ansible/group_vars/all/github-token.runtime.yml

sops -d .vault/repo/infra/sealed-secrets/key-backup.enc.yaml \
  > .vault/repo/infra/sealed-secrets/key-backup.runtime.yaml
```

### 步骤

```bash
cd edge/ansible

# 1. 部署 K3s server（tencent）
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml -v
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-server.yml -v

# 2. 部署 K3s agents（gtr, aliyun, remote_proxy -> node `remote-proxy`）
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml -v
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-agent.yml -v

# 3. 部署 ArgoCD
ansible-playbook -i inventory-edge.ini deploy-platform-argocd.yml -v
ansible-playbook -i inventory-edge.ini verify-platform-argocd.yml -v

# 4. 恢复 SealedSecrets 私钥（关键步骤！）
ansible-playbook -i inventory-edge.ini bootstrap-platform-sealed-secrets-key.yml -v
ansible-playbook -i inventory-edge.ini verify-platform-sealed-secrets.yml -v

# 5. Tailscale Operator 前置条件（创建 OAuth secret 等）
ansible-playbook -i inventory-edge.ini deploy-platform-tailscale-operator.yml -v

# 6. 等待 ArgoCD 同步所有应用
# ArgoCD Application 'platform-apps' 会同步 sealed-secrets, tailscale-operator 等
# 持续检查直到所有 sub-apps 变为 Synced/Healthy
```

---

## 关键 Gotchas

### 1. Token 处理 🔴 致命

K3s server / agent 必须使用**同一份解密后的 cluster token**。重建时应始终从 vault 解密到 `*.runtime.yml`，不要手工抄写、重置或混用旧 token。

如果 token 与现有 bootstrap data 不一致，server 重启会报错：
```
fatal: bootstrap data already found and encrypted with different token
```

修复方式：

- 统一以 vault 中的 `secret.sops.yml` 为唯一真源
- 只让 Ansible 读取 `*.runtime.yml`
- 运行前清理 public repo 工作树中残留的 `*.sops.yml`

### 2. kubeseal `--raw` 模式 🔴

kubeseal v0.37.0 的 `--raw` 模式有 bug，生成的加密数据 controller 无法解密。**必须使用管道模式**：
```bash
# ❌ 错误
echo -n "secret" | kubeseal --raw ...

# ✅ 正确
kubectl create secret generic xxx --dry-run=client -o yaml \
  --from-literal=KEY=secret | kubeseal --format=yaml ...
```

### 3. SealedSecrets 不再由 Ansible 部署

- `deploy-platform-sealed-secrets.yml` **已删除**（之前用 `kubectl apply` 部署 raw manifest，造成双 Controller 冲突）
- 现在由 ArgoCD Helm chart 管理
- 新集群必须先用 `bootstrap-platform-sealed-secrets-key.yml` 恢复旧私钥，否则所有 SealedSecret CRD 都解不开
- bootstrap playbook 会先比较 vault 证书指纹；如果集群里已有同指纹 key，则跳过重复 apply
- 如果发现 Helm 首启自动生成了与 vault 不同指纹的新 key，bootstrap playbook 会删除这些 non-matching key 并重启 controller，避免 `SealedSecret` 在成功/失败之间反复翻转
- 旧私钥备份位置：vault `infra/sealed-secrets/key-backup.enc.yaml`

### 4. 网络拓扑

| 通信路径 | 方式 | 说明 |
|----------|------|------|
| tencent ↔ gtr | Tailscale (100.x) | 稳定 |
| tencent ↔ aliyun | Tailscale (100.x) | 两者均为国内节点，稳定 |
| tencent ↔ remote_proxy | Tailscale | 跨洋 ~200ms，可接受 |
| CI runner → gtr | Tailscale | 需要 OAuth |
| CI runner → tencent | 公网 SSH (129.211.12.63) | 不需要 Tailscale |
| CI runner → aliyun | 公网 SSH (47.120.46.128) | 不需要 Tailscale |
| CI runner → remote_proxy | 公网 SSH (66.154.100.187) | 不需要 Tailscale |

### 5. remote_proxy 特殊配置

- `k3s_mirror: ""`（海外节点不用 CN mirror）
- `github_download_proxy: ""`（海外直接访问 GitHub）
- `k3s_node_name: remote-proxy`（RFC1123-safe K8s Node 名）
- 打 `NoSchedule` taint：不调度业务 Pod
- `k3s_flannel_iface: tailscale0`（从 group_vars 继承）

### 6. ArgoCD 同步时序

`platform-apps` Application 使用 `syncPolicy.automated.prune=true` + `selfHeal=true`。在部署完 ArgoCD 后，平台 Operators 的 Applications 会自动创建和同步。注意 `sealed-secrets` sub-application 有 `sync-wave: "-10"` 确保优先同步。

---

## 验证清单

- [ ] 4 节点全部 `Ready`：`kubectl get nodes`（其中海外节点名应为 `remote-proxy`）
- [ ] ArgoCD 所有 apps `Synced / Healthy`：`kubectl -n argocd get application`
- [ ] mihomo-metrics pod `Running`：`kubectl -n monitoring get pods`
- [ ] `mihomo-api` Secret 有正确值：`kubectl -n monitoring get secret mihomo-api -o jsonpath='{.data.MIHOMO_SECRET}' | base64 -d | head -c 32`
- [ ] SealedSecrets controller 至少有一个活跃 key：`kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key`
- [ ] Tailscale Operator pod `Running`：`kubectl -n tailscale get pods`
- [ ] CI topology validation passes：`python3 scripts/validate_ci_topology.py`
