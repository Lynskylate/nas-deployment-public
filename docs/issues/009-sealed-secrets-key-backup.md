# [Follow-up] Sealed Secrets Private Key Backup

> **Status: Closed** — 私钥已经备份到 vault，当前流程以 vault 为 single source of truth。

## 当前状态

Sealed Secrets controller 私钥存储在私有仓库 `nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml` 中，并通过 SOPS + AGE 加密。

当前集群重建流程不再依赖“从集群导出私钥再手动备份”的旧路径，而是：

1. CI / 手工部署先从 vault 解密私钥备份
2. 执行 `edge/ansible/bootstrap-platform-sealed-secrets-key.yml` 恢复到集群
3. 由 Argo CD 同步 Sealed Secrets controller，并复用该私钥

## 当前操作入口

- 私钥管理与恢复说明：[`docs/deployment/secrets-management.md`](../deployment/secrets-management.md)
- CI 平台部署流程：[`docs/deployment/k3s-platform-ci-deployment-guide.md`](../deployment/k3s-platform-ci-deployment-guide.md)
- 集群重建 SOP：[`docs/deployment/k3s-cluster-rebuild-sop.md`](../deployment/k3s-cluster-rebuild-sop.md)
- 恢复 playbook：`edge/ansible/bootstrap-platform-sealed-secrets-key.yml`

## 结论

本 issue 中记录的旧步骤（从节点导出私钥、手动加密、手动提交）已经完成历史使命，不再作为当前 runbook 使用。
