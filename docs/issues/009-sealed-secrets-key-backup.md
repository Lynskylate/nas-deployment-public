# [Follow-up] Sealed Secrets Private Key Backup

> **Status: Superseded** — 私钥已备份到 vault，后续管理见
> [sealed-secrets-argocd-unification.md](../proposals/sealed-secrets-argocd-unification.md)。
> 本 issue 不再适用。

## Summary

Sealed Secrets controller 安装后，其私钥需要备份到 `nas-deployment-vault` 仓库，以确保灾难恢复时能够解密已有的 SealedSecrets。

## Background

在 issue #4（`002-argocd-sealed-secrets-tailscale-operator.md`）中，Sealed Secrets 已经通过 Ansible playbook `deploy-platform-sealed-secrets.yml` 安装到 K3s 集群。安装过程中私钥被导出到 `/tmp/` 但随后被清理（安全措施），未完成备份流程。

## Steps

```bash
# 0. 前提：sops age key 已配置

# 1. 从 aliyun K3s 导出私钥
ssh root@100.102.140.59 \
  k3s kubectl get secret -n kube-system \
    -l sealedsecrets.bitnami.com/sealed-secrets-key \
    -o yaml > /tmp/sealed-secrets-key-backup.yaml

# 2. sops 加密
sops --encrypt --age <AGE_KEY> /tmp/sealed-secrets-key-backup.yaml \
  > /path/to/nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml

# 3. 删除本地明文
rm /tmp/sealed-secrets-key-backup.yaml

# 4. 提交到 vault 仓库
cd /path/to/nas-deployment-vault
git add infra/sealed-secrets/
git commit -m "chore: backup sealed-secrets private key"
git push
```

## Verification

备份提交后，验证：

```bash
# 从备份文件解密
sops --decrypt nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml \
  | kubectl get -f - -o jsonpath='{.items[0].metadata.name}'
# 期望：显示 sealed-secrets 密钥名称
```

## Out Of Scope

- CI 自动化备份（当前保留为手动步骤）
- 其他组件的密钥备份

## Acceptance Criteria

- [ ] 私钥已 sops 加密并提交到 `nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml`
- [ ] 从加密备份文件可以成功解密并恢复
