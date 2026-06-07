# Ansible 约定与模式

> 完整部署指南见仓库根目录 `AGENTS.md`

## 目录结构

```
edge/ansible/
├── ansible.cfg              # roles_path 含 ../..//shadowsocks-shadowtls/ansible/roles
├── inventory-edge.ini       # 主 inventory（edge 节点 + gtr_core）
├── group_vars/
│   ├── all/
│   │   ├── public.yml       # 共享非机密默认值
│   │   └── secret.runtime.yml  # CI 运行时解密（gitignored）
│   └── <group>/
│       ├── public.yml       # group 级非机密覆盖
│       └── secret.runtime.yml
├── host_vars/
│   ├── <host>.yml           # 各节点覆盖
│   └── gtr/
│       └── secret.runtime.yml
├── roles/
│   └── <role>/
│       ├── tasks/main.yml
│       ├── handlers/main.yml
│       ├── templates/*.j2
│       ├── defaults/main.yml
│       └── files/
└── deploy-*.yml / verify-*.yml
```

## Inventory

### Edge 主 Inventory (`inventory-edge.ini`)

Host groups: `edge_remote_proxy`, `edge_aliyun`, `edge_tencent`, `gtr_core`

所有节点通过 Tailscale IP 连接。`ansible_ssh_common_args` 中设置 `-o StrictHostKeyChecking=no`。

### 其他 Inventory

- `mihomo/ansible/inventory.ini` — Mihomo 部署
- `shadowsocks-shadowtls/ansible/inventory.ini` — 旧 SS 部署（IP 已过时）
- `network-monitor/ansible/inventory.ini` — 网络监控

## Variable Layering（优先级从低到高）

| Layer | 路径 | 说明 |
|-------|------|------|
| Role defaults | `roles/<role>/defaults/main.yml` | 最低优先级 |
| Group all public | `group_vars/all/public.yml` | 共享非机密默认值 |
| Group all secret | `group_vars/all/secret.runtime.yml` | 运行时解密 overlay |
| Group public | `group_vars/<group>/public.yml` | Group 级非机密覆盖 |
| Group secret | `group_vars/<group>/secret.runtime.yml` | Group 级 secret overlay |
| Host public | `host_vars/<host>.yml` | 各节点公开覆盖 |
| Host secret | `host_vars/gtr/secret.runtime.yml` | Host 级 secret overlay |

## Role 模式

```yaml
# 标准 role 内 task 模式
- name: Render config
  ansible.builtin.template:
    src: config.yaml.j2
    dest: /etc/service/config.yaml
    mode: "0644"
  notify:
    - reload systemd
    - restart service

- name: Flush handlers before starting service
  ansible.builtin.meta: flush_handlers

- name: Ensure service running
  ansible.builtin.systemd:
    name: service
    state: started
    enabled: true
```

### 关键约定

1. **Template > copy:** 使用 `ansible.builtin.template`（`.j2`）渲染配置，而非 `copy`
2. **Notify + flush:** 模板变更时 `notify: [reload systemd, restart <service>]`；服务启动前用 `meta: flush_handlers`
3. **assert > fail:** 用 `ansible.builtin.assert` 做校验，不用 `fail`
4. **条件引入 role:** `when: <feature>_enabled | bool`
5. **become:** playbook 级别设 `become: true`（安装系统包需要）
6. **Idempotency:** role 先检查 `systemctl is-active` / API 可达性，健康时 skip install，只 render config
7. **CI shell 兼容:** 所有使用 `pipefail` 的 shell task 必须加 `args: executable: /bin/bash`（CI runner 的 `/bin/sh` 是 dash）

## Roles Path 复用

`edge/ansible/ansible.cfg` 的 `roles_path` 包含：
```
roles_path = ./roles:../../shadowsocks-shadowtls/ansible/roles
```

这意味着 `edge` playbook 可以使用 `shadowsocks-shadowtls` 目录中的 role（如 `node-exporter`、`shadowsocks-server`）。如果移动/重命名该目录，edge 部署会中断。

## 常用 Playbook 清单

| Playbook | 目标 | 覆盖 |
|----------|------|------|
| `deploy-edge.yml` | edge baseline | `edge_*` |
| `deploy-edge-tunnel-server.yml` | tunnel server | `edge_remote_proxy` |
| `deploy-gtr-k3s-server.yml` | K3s server | `edge_aliyun` |
| `deploy-gtr-k3s-agent.yml` | K3s agents | `gtr_core:edge_tencent` |
| `deploy-gtr-ai-tools.yml` | AI tools + Slock daemon | `gtr_core` |
| `deploy-resource-manifest.yml` | resource manifest | `gtr_core` |
| `deploy-platform-argocd.yml` | ArgoCD bootstrap | `edge_aliyun` |
| `deploy-platform-sealed-secrets.yml` | SealedSecrets bootstrap | `edge_aliyun` |
| `deploy-platform-tailscale-operator.yml` | Tailscale Operator | `edge_aliyun` |
| `verify-edge-common.yml` | edge 验证 | `edge_*` |
| `verify-gtr-k3s-server.yml` | K3s server 验证 | `edge_aliyun` |
| `verify-gtr-k3s-agent.yml` | K3s agent 验证 | `gtr_core:edge_tencent` |
| `verify-platform-argocd.yml` | ArgoCD 验证 | `edge_aliyun` |
| `verify-platform-sealed-secrets.yml` | SealedSecrets 验证 | `edge_aliyun` |
| `verify-platform-tailscale-operator.yml` | Tailscale Operator 验证 | `edge_aliyun` |

## 模板中用到的关键变量

### K3s

| 变量 | 定义位置 | 说明 |
|------|---------|------|
| `k3s_version` | `group_vars/all/public.yml` | K3s 版本 |
| `k3s_cluster_token` | `secret.runtime.yml`（vault） | Cluster token |
| `k3s_flannel_backend` | `group_vars/all/public.yml` | Flannel 后端（`vxlan`） |
| `k3s_cluster_cidr` | `group_vars/all/public.yml` | Pod CIDR |
| `k3s_service_cidr` | `group_vars/all/public.yml` | Service CIDR |
| `k3s_server_tailscale_ip` | `host_vars/aliyun/public.yml` | API server 地址 |
| `k3s_containerd_https_proxy` | `group_vars/all/public.yml` | 镜像拉取代理 |
| `k3s_mirror` | `group_vars/all/public.yml` | Rancher CN 镜像源 |

### ArgoCD

| 变量 | 定义位置 | 说明 |
|------|---------|------|
| `argocd_version` | `roles/argocd/defaults/main.yml` | ArgoCD 版本 |
| `argocd_repo_url` | `roles/argocd/defaults/main.yml` | 平台 GitOps 仓库 URL |
| `argocd_repo_ssh_key` | `secret.runtime.yml`（vault） | GitHub deploy key |

### Tailscale Operator

| 变量 | 定义位置 | 说明 |
|------|---------|------|
| `tailscale_operator_oauth_client_id` | `secret.runtime.yml`（vault） | OAuth client ID |
| `tailscale_operator_oauth_client_secret` | `secret.runtime.yml`（vault） | OAuth client secret |
| `tailscale_operator_version` | `group_vars/all/public.yml` | Helm chart 版本 |
