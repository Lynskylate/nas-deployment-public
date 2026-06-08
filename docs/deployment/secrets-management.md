# Secrets Management

## 原则

- **公共仓库（`nas-deployment-public`）不包含任何明文凭据**
- 所有敏感值存储在私有的 `nas-deployment-vault` 仓库中（SOPS + AGE 加密）
- `*.runtime.yml` 文件在 `.gitignore` 中，由 CI 在运行时解密生成
- `*.sops.yml` 只能存在于 vault 仓库；如果它们出现在 `nas-deployment-public/edge/ansible/**`，应先清理再运行 Ansible
- `scripts/check-no-plaintext-secrets.py` 作为明文凭据守卫，在 PR CI 中自动运行

## Vault Repository Layout

```
nas-deployment-vault/
├── .sops.yaml                                # SOPS AGE 公钥配置
├── README.md
├── bootstrap/
│   └── github-actions/
│       └── prod.sops.yml                     # CI OAuth creds, SSH deploy key
├── ansible/
│   └── edge/
│       ├── group_vars/
│       │   └── all/
│       │       └── secret.sops.yml           # 共享 secret overlay
│       └── host_vars/
│           └── gtr/
│               └── secret.sops.yml           # GTR 特有 secret
├── infra/
│   ├── sealed-secrets/
│   │   └── key-backup.enc.yaml              # SealedSecrets 私钥备份
│   └── tailscale-operator/
│       └── oauth.sops.yml                   # Tailscale Operator OAuth
```

## Decrypt Flow

### CI 环境

CI 通过 `bootstrap-deploy-env` 复合 action（`.github/actions/bootstrap-deploy-env/action.yml`）自动解密：

1. Checkout vault repo（使用 GitHub deploy key）
2. 安装 `sops` + `age`
3. 解密所有 `.sops.yml` → 写入对应的 `*.runtime.yml`
4. 校验 public repo 工作树中不存在残留的 `*.sops.yml`
5. 导出 Tailscale OAuth 凭据到 job outputs
6. Job 结束后 `cleanup-vault.sh` 删除所有 `.runtime.yml` 文件

### 手动部署

```bash
# 1. 安装依赖
sudo apt install age
curl -fsSL https://github.com/getsops/sops/releases/download/v3.13.1/sops-v3.13.1.linux.amd64 -o /usr/local/bin/sops
chmod +x /usr/local/bin/sops

# 2. 设置 AGE 私钥
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
# 或直接
export SOPS_AGE_KEY="AGE-SECRET-KEY-..."

# 3. Decrypt
sops --decrypt nas-deployment-vault/ansible/edge/group_vars/all/secret.sops.yml \
  > edge/ansible/group_vars/all/secret.runtime.yml
sops --decrypt nas-deployment-vault/ansible/edge/host_vars/gtr/secret.sops.yml \
  > edge/ansible/host_vars/gtr/secret.runtime.yml

# 4. 确认 public repo 中没有残留 .sops 文件
find edge/ansible -name '*.sops.yml' -print
# 预期：无输出
```

## Runtime Variable Layering

解密后的 `*.runtime.yml` 文件与 `public.yml` 叠加：

| 优先级 | 文件 | 说明 |
|--------|------|------|
| 低 | `group_vars/all/public.yml` | 公开默认值 |
| 高 | `group_vars/all/secret.runtime.yml` | 解密后的 secret overlay |

Ansible 自动合并同目录下的所有 YAML 文件，后者覆盖前者。

因此：

- `secret.runtime.yml` 应该是执行时唯一的 secret overlay
- `secret.sops.yml` 不应被复制到 public repo 工作树内，否则可能覆盖 runtime 变量

## Sealed Secrets Key Management

Sealed Secrets controller 的私钥存储在 `nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml`（SOPS + AGE 加密），是私钥的 single source of truth。

### 集群重建时恢复私钥

CI 在部署 Sealed Secrets 前会自动从 vault 解密私钥并 apply 到集群：

1. `bootstrap-deploy-env` action 解密 `key-backup.enc.yaml` → `key-backup.runtime.yaml`
2. `bootstrap-platform-sealed-secrets-key.yml` playbook 先比对 vault 证书指纹与集群现有 key；只有同指纹 key 不存在时才 apply
3. Argo CD 部署 controller，controller 检测到已有私钥，复用

### 首次部署（全新集群，仅首次需要）

首次部署时集群中没有私钥，controller 会自动生成新密钥对。生成后需手动备份到 vault：

```bash
# 导出
ssh root@<server-ip> k3s kubectl get secret -n kube-system \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o yaml > /tmp/sealed-secrets-key-backup.yaml

# 加密并存入 vault
sops --encrypt --age <AGE_KEY> /tmp/sealed-secrets-key-backup.yaml \
  > nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml

# 清理
rm -f /tmp/sealed-secrets-key-backup.yaml

# 提交
cd nas-deployment-vault && git add infra/sealed-secrets/ && \
  git commit -m 'backup sealed-secrets key' && git push
```

## Checking for Plaintext Secrets

```bash
python3 scripts/check-no-plaintext-secrets.py
```

该脚本扫描仓库中是否包含已知凭据模式的明文（API key、private key header、OAuth token 等）。在 `validate-pr.yml` 中作为 CI 步骤运行。
