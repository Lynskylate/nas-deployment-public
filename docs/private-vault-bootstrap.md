# Public Repo + Private Vault Bootstrap

`nas-deployment-public` 只保存可公开的基础设施代码、Ansible playbook、模板和文档。
所有部署期 secrets 都来自 private 仓库 `nas-deployment-vault`，并通过 `sops + age` 在 workflow 内临时解密。

## GitHub 设置

public repo: `Lynskylate/nas-deployment-public`

- repo variable: `VAULT_REPO_SLUG=Lynskylate/nas-deployment-vault`
- environment: `production`
- environment secret: `SOPS_AGE_KEY`
- environment secret: `VAULT_REPO_SSH_KEY`

private repo: `Lynskylate/nas-deployment-vault`

- `.sops.yaml`
- `bootstrap/github-actions/prod.sops.yml`
- `ansible/edge/group_vars/all/secret.sops.yml`
- `ansible/edge/host_vars/gtr/secret.sops.yml`
- `ansible/mihomo/group_vars/all/secret.sops.yml`
- `ansible/mihomo/group_vars/aliyun/secret.sops.yml`
- `grafana/secret.sops.yml`

## Runtime Flow

1. public workflow checkout `nas-deployment-public`
2. public workflow 用 `actions/checkout@v6` + `VAULT_REPO_SSH_KEY` checkout `nas-deployment-vault`
3. workflow 使用 `SOPS_AGE_KEY` 解密 bootstrap 与 Ansible secret overlays
4. workflow 渲染：
   - `edge/ansible/group_vars/all/secret.runtime.yml`
   - `edge/ansible/host_vars/gtr/secret.runtime.yml`
   - `mihomo/ansible/group_vars/all/secret.runtime.yml`
   - `mihomo/ansible/group_vars/aliyun/secret.runtime.yml`
   - `grafana/secret.runtime.yml`
5. workflow 运行现有 playbook
6. job 结束时删除 `.vault/repo`、runtime overlays、临时 SSH key 与 AGE key 文件

## Public / Secret 边界

保留在 public repo:

- 版本号、下载地址、端口、CIDR、路径
- host/group 的非机密默认值
- playbook、roles、templates、runbook、dashboard

保留在 private vault repo:

- `k3s_cluster_token`
- `slock_ai_api_key`
- `shadowsocks_password`
- `shadowtls_password`
- `proxy_provider_url`
- `hysteria2_password`
- `hysteria2_sal_obfs_password`
- `mihomo_secret`
- `proxy_auth_password`
- `grafana_feishu_webhook_url`
- CA 私钥相关材料
- workflow bootstrap secrets（Tailscale OAuth、deploy SSH key）
