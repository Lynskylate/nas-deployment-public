# Migration Issues

这些文档是 K3s 迁移过程中编写的 GitHub issue 描述。

## 使用方法

1. 基于本目录中的文档在 GitHub 上创建 issue。
2. 保持 issue 标题与文档标题一致。
3. 每个迁移 PR 都要链接到对应 issue。

## PR 链接规范

每个迁移 PR 都应包含：

- `Closes #<issue-number>` 或 `Refs #<issue-number>`
- `Planning doc: docs/issues/<file>.md`

## 当前 Queue

- `003-corp-finance-monitor-helm-migration.md` -> GitHub issue `#5`
- `004-corp-finance-monitor-data-migration.md` -> GitHub issue `#6`
- `009-sealed-secrets-key-backup.md` -> GitHub issue `#9`（待创建）

## 已归档（已完成的分析/实现）

以下 issue 已完成，文档已移入 `docs/issues/archive/`：

| Issue | 文件 | 完成节点 |
|-------|------|----------|
| #3 — K3s Platform Bootstrap | `archive/001-k3s-platform-bootstrap.md` | commit `98f7403` |
| #4 — ArgoCD + Sealed Secrets + Tailscale Operator | `archive/002-argocd-sealed-secrets-tailscale-operator.md` | commit `aa780e7` |
| #6 — K3s 部署优化（拓扑+CI+幂等性） | `archive/006-k3s-deploy-optimization.md` | commits `98f7403`, `a995a6a`, `6e42b2d` |
| #8 — 私有 Secrets 仓库引导 | `archive/005-private-secrets-repo-bootstrap.md` | Vault 仓库已建立使用 |
| — Flannel+Tailscale Crashloop 分析 | `archive/007-k3s-flannel-tailscale-crashloop.md` | 分析完成，问题已解决 |
| — Docker nftables 冲突分析 | `archive/008-docker-nftables-conflict-analysis.md` | 分析完成，docker-cleanup 已移除 |
| — Aliyun 重装 Tailscale 诊断 | `archive/010-aliyun-reinstall-tailscale-diagnostics.md` | CI 已改用公网 IP 部署 |
