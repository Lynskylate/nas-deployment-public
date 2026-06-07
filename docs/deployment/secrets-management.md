# Secrets Management

## 原则

- **公共仓库（`nas-deployment-public`）不包含任何明文凭据**
- 所有敏感值存储在私有的 `nas-deployment-vault` 仓库中（SOPS + AGE 加密）
- `*.runtime.yml` 文件在 `.gitignore` 中，由 CI 在运行时解密生成
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
4. 导出 Tailscale OAuth 凭据到 job outputs
5. Job 结束后 `cleanup-vault.sh` 删除所有 `.runtime.yml` 文件

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
```

## Runtime Variable Layering

解密后的 `*.runtime.yml` 文件与 `public.yml` 叠加：

| 优先级 | 文件 | 说明 |
|--------|------|------|
| 低 | `group_vars/all/public.yml` | 公开默认值 |
| 高 | `group_vars/all/secret.runtime.yml` | 解密后的 secret overlay |

Ansible 自动合并同目录下的所有 YAML 文件，后者覆盖前者。

## Sealed Secrets Key Backup

SealedSecrets 的私钥是集群内自动生成的，需要手动备份：

```bash
# 导出
ssh root@<aliyun-tailscale-ip> kubectl get secret -n kube-system \
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

私钥在 K3s 节点上持久化到 `/var/lib/rancher/k3s/sealed-secrets-key-backup.yaml`。

## Checking for Plaintext Secrets

```bash
python3 scripts/check-no-plaintext-secrets.py
```

该脚本扫描仓库中是否包含已知凭据模式的明文（API key、private key header、OAuth token 等）。在 `validate-pr.yml` 中作为 CI 步骤运行。
