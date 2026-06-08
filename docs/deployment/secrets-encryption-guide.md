# Secrets 加密操作指南

## 原则

本仓库**不存储任何明文凭据**。所有敏感值在入库前必须加密。

敏感值按使用场景分两层：

| 层 | 加密工具 | 存储位置 | 解密方 |
|----|---------|---------|--------|
| **节点层**（Ansible host_vars/group_vars） | SOPS + AGE | 私有 `nas-deployment-vault` | CI / 手动 `sops --decrypt` |
| **K8s 层**（集群内 Secret） | kubeseal → SealedSecret CRD | 本仓库 `platform/resources/` | 集群内 SealedSecrets controller |

**快速判断用哪种：**

```
这个 secret 是给 Ansible playbook 用的？
  → 是：SOPS + AGE → vault 仓库
  → 否：是给 K8s Pod 用的？
         → 是：kubeseal → SealedSecret → 本仓库
         → 否：重新审视是否真的是 secret
```

---

## 一、K8s Secret → SealedSecret（kubeseal）

### 适用场景

- K8s 集群内 Pod 需要的 Secret（API key、密码、token 等）
- 通过 ArgoCD GitOps 管理，Secret 随 Application 自动同步

### 前置条件

- `kubectl` 已配置指向 K3s 集群（`https://100.99.48.76:6443`，通过 Tailscale 可达）
- SealedSecrets controller 已在集群中运行（ArgoCD Application `sealed-secrets`）
- `kubeseal` CLI 已安装

### 安装 kubeseal

```bash
KUBESEAL_VERSION=0.27.3
curl -fsSL \
  "https://github.com/bitnami-labs/sealed-secrets/releases/download/v${KUBESEAL_VERSION}/kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz" \
  | tar -xz kubeseal
sudo mv kubeseal /usr/local/bin/
kubeseal --version
```

### 加密流程

```bash
# 1. 准备原始 Secret（用 --dry-run 生成 YAML 而不真的创建）
kubectl -n <namespace> create secret generic <secret-name> \
  --from-literal=<KEY>='<plaintext-value>' \
  --dry-run=client -o yaml > /tmp/raw-secret.yaml

# 2. 用 kubeseal 加密
kubeseal --controller-namespace kube-system \
  --controller-name sealed-secrets \
  -o yaml < /tmp/raw-secret.yaml > platform/resources/<service>/sealedsecret.yaml

# 3. 清理临时文件
rm /tmp/raw-secret.yaml

# 4. 提交到 git
git add platform/resources/<service>/sealedsecret.yaml
git commit -m "add SealedSecret <secret-name> for <service>"
```

### 多值 Secret

```bash
kubectl -n monitoring create secret generic my-api-secret \
  --from-literal=API_KEY='<key>' \
  --from-literal=API_SECRET='<secret>' \
  --dry-run=client -o yaml | \
  kubeseal --controller-namespace kube-system \
    --controller-name sealed-secrets -o yaml > \
  platform/resources/my-service/sealedsecret.yaml
```

### 示例：Mihomo API Secret

```bash
# 从 vault 获取 mihomo API secret（详见第二节 SOPS 解密）
MIHOMO_SECRET=$(sops --decrypt nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml | \
  yq '.mihomo_api_secret')

# 密封并提交
kubectl -n monitoring create secret generic mihomo-api \
  --from-literal=MIHOMO_SECRET="${MIHOMO_SECRET}" \
  --dry-run=client -o yaml | \
  kubeseal --controller-namespace kube-system \
    --controller-name sealed-secrets -o yaml > \
  platform/resources/mihomo-monitoring/sealedsecret.yaml
```

### Pod 引用

Deployment/Pod 中通过 `secretKeyRef` 引用（无需改动，SealedSecrets controller 自动解密为普通 Secret）：

```yaml
env:
  - name: MIHOMO_SECRET
    valueFrom:
      secretKeyRef:
        name: mihomo-api        # 与 kubectl create secret 的 name 一致
        key: MIHOMO_SECRET      # 与 --from-literal 的 key 一致
```

### 验证

```bash
# 确认 SealedSecret 已创建
kubectl -n monitoring get sealedsecret mihomo-api

# 确认 controller 已解密并生成普通 Secret
kubectl -n monitoring get secret mihomo-api

# 确认 Secret 内容（base64 解码查看）
kubectl -n monitoring get secret mihomo-api -o jsonpath='{.data.MIHOMO_SECRET}' | base64 -d
```

### 常见问题

**Q: `error: cannot fetch certificate`**

A: kubeseal 无法连接到 SealedSecrets controller 获取公钥。确认：
- `kubectl` 能访问集群：`kubectl get nodes`
- controller 在运行：`kubectl -n kube-system get pods -l app.kubernetes.io/name=sealed-secrets`

**Q: 重新加密已有 SealedSecret**

A: 步骤相同——用原始明文重新 `kubectl create secret` + `kubeseal`，覆盖原文件即可。

**Q: 多个 namespace 需要同一个 Secret？**

A: SealedSecret 是 namespace-scoped。需在不同 namespace 各创建一个（SealedSecrets controller 会在对应 namespace 生成 Secret）。

---

## 二、Ansible Secret → SOPS + AGE

### 适用场景

- Ansible playbook 运行在节点上需要的敏感值（SSH key、API secret、数据库密码）
- 不进入 K8s 集群，由 CI 在运行时解密

### 前置条件

- `sops` CLI 已安装
- `age` 已安装
- AGE 私钥已配置

### 安装工具

```bash
# age
sudo apt install age

# sops
SOPS_VERSION=3.9.1
curl -fsSL "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64" \
  -o /usr/local/bin/sops
chmod +x /usr/local/bin/sops
sops --version
```

### 加密流程

```bash
# 1. 获取 Vault 仓库的 AGE 公钥（从 .sops.yaml）
AGE_PUBKEY=$(grep 'age' nas-deployment-vault/.sops.yaml | head -1 | awk '{print $2}')

# 2. 创建 secret 文件（或编辑已有）
cat > nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml << 'EOF'
# GTR host secrets
mihomo_api_secret: "<plaintext-secret>"
victoriametrics_password: "<plaintext-password>"
EOF

# 3. 加密
sops --encrypt --age "$AGE_PUBKEY" \
  nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml \
  > nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml.tmp
mv nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml.tmp \
  nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml

# 4. 提交到 vault 仓库
cd nas-deployment-vault
git add ansible/edge/host_vars/gtr/secret.sops.yml
git commit -m "update GTR host secrets"
git push
```

### 解密查看

```bash
# 解密并查看内容
sops --decrypt nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml

# 解密并提取单个字段
sops --decrypt nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml | \
  yq '.mihomo_api_secret'
```

### 编辑已有加密文件（无需解密-修改-重新加密）

```bash
# sops 直接编辑加密文件（自动解密→编辑→重新加密）
sops nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml
```

### 如何获取 AGE 私钥

AGE 私钥存储在 CI 的 GitHub Secrets 中。团队成员手动部署时需获取私钥：

1. 从 1Password / 团队密码管理器获取
2. 或由已有访问权限的成员通过安全渠道传递

私钥文件格式：
```
# AGE-SECRET-KEY-1XXXXXX...
```

存放位置：
```bash
mkdir -p ~/.config/sops/age
echo "AGE-SECRET-KEY-1..." > ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
```

### CI 自动解密流程

CI（`.github/workflows/deploy-infra.yml`）通过 `bootstrap-deploy-env` action 自动解密：

1. Checkout vault repo（使用 GitHub deploy key）
2. 安装 `sops` + `age`
3. 用 `SOPS_AGE_KEY`（GitHub Secret）解密所有 `.sops.yml` → 生成 `*.runtime.yml`
4. Job 结束后自动删除所有 `.runtime.yml`

---

## 三、快速对照表

| 场景 | 工具 | 命令摘要 |
|------|------|---------|
| 新建 K8s Secret | kubeseal | `kubectl create secret ... --dry-run \| kubeseal` |
| 编辑已有 K8s Secret | kubeseal | 重新密封（覆盖原 SealedSecret 文件） |
| 新建 Ansible secret | sops | `sops --encrypt --age <KEY> file.yml` |
| 编辑已有 Ansible secret | sops | `sops file.yml`（直接编辑加密文件） |
| 查看 Ansible secret | sops | `sops --decrypt file.yml` |
| 检查仓库中是否有明文 | check script | `python3 scripts/check-no-plaintext-secrets.py` |

---

## 四、检查清单

在提交前确认：

- [ ] 没有任何 `*.runtime.yml` 文件被 staged（.gitignore 保护）
- [ ] 没有 `--from-literal=...` 命令残留在脚本中
- [ ] SealedSecret YAML 文件包含 `kind: SealedSecret` 且 `spec.encryptedData` 有非空值
- [ ] SOPS 加密文件头部有 `sops:` 块和 `age:` 公钥哈希
- [ ] PR CI 中的 `check-no-plaintext-secrets.py` 通过
- [ ] 原始 Secret / 明文凭据不在 shell history 中（用 `set +o history` 或带空格前缀执行敏感命令）

## 五、紧急轮换流程

当凭据泄漏或需要周期轮换时：

```bash
# 1. 更新源（Mihomo API、外部服务等）的凭据

# 2. 按上述加密流程重新生成 SealedSecret / SOPS 文件

# 3. 提交 + push → ArgoCD 自动更新 K8s Secret → Pod 在下次重启时使用新凭据

# 4. 对于 Ansible secret，手动触发 CI 重新部署相关 playbook

# 5. 验证：确认旧凭据已失效，新凭据生效
```

---

## 相关文档

- [Secrets 架构与 Vault 仓库结构](secrets-management.md)
- [K3s 平台 CI 部署指南](k3s-platform-ci-deployment-guide.md)
- [Ansible 约定](../topic/infrastructure/ansible-conventions.md)
