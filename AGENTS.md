# AGENTS.md

本仓库是 `gtr` 服务器及远程 edge/proxy 节点的**基础设施 runbook 与部署自动化**仓库。不含应用源码——只有 Ansible playbook、Shell 脚本、配置模板、监控面板和文档。

所有文档使用 **中文**。

## 核心规矩

1. **无明文凭据** — 所有敏感值在私有 `nas-deployment-vault` 仓库中（SOPS + AGE 加密），`.runtime.yml` 由 CI 解密生成且 gitignored。详见 [`docs/deployment/secrets-management.md`](docs/deployment/secrets-management.md)。

2. **Ansible 约定** — 详见 [`docs/topic/infrastructure/ansible-conventions.md`](docs/topic/infrastructure/ansible-conventions.md)。关键：assert > fail，notify + flush_handlers，CI 中 shell task 用 pipefail 必须加 `args: executable: /bin/bash`

3. **K3s 平台 CI 部署** — ArgoCD + SealedSecrets + Tailscale Operator 通过 GitHub Actions 自动部署。详见 [`docs/deployment/k3s-platform-ci-deployment-guide.md`](docs/deployment/k3s-platform-ci-deployment-guide.md)

4. **Pre-commit** — 提交前自动运行 `actionlint`（workflow lint）、`check-yaml`、明文凭据守卫等。安装：`bash scripts/setup-git-hooks.sh`。若有 `pre-commit` 则体验更完整：`pip install pre-commit && pre-commit install`

## 仓库结构

```
nas-deployment-public/
<<<<<<< HEAD
├── edge/ansible/             # Ansible playbooks, roles, host_vars（核心）
├── platform/                 # K3s 内平台组件（ArgoCD GitOps source）
│   ├── applications/         # ArgoCD Application CRDs
│   ├── helm-values/
│   └── resources/            # 直接应用的 K8s 资源（如 ProxyClass）
├── k3s/                      # K3s 平台文档
├── mihomo/                   # Mihomo 代理客户端（Ansible）
├── cigbutt/                  # 量化分析 CLI（Python, hatchling）
├── victoriatraces/           # VictoriaTraces 分布式追踪
├── network-monitor/          # 网络连通性监控
├── grafana/                  # Grafana 面板、告警
├── envoy/ victoriametrics/ victorialogs/ node_exporter/  # 各服务 runbook
├── .github/                  # CI/CD workflows + actions
├── scripts/
│   └── check-no-plaintext-secrets.py
└── docs/
    ├── deployment/           # 部署指南、CI guide、secrets management
    ├── topic/infrastructure/ # Ansible 约定等专题
    ├── troubleshooting/      # 排错分析
    └── issues/               # 实现跟踪（gitignored）
```

## 基础设施拓扑

```
K3s Cluster
├─ aliyun (control-plane): Tailscale 100.100.99.70
├─ gtr (agent):            100.121.0.67
└─ tencent (agent):        100.99.48.76
API: https://100.100.99.70:6443
Pod CIDR: 10.60/16, Service CIDR: 10.61/16, Flannel: vxlan (tailscale0)

GTR Core (192.168.31.59)
├─ Envoy → Grafana :3000 / VictoriaMetrics :8428 / VictoriaLogs :8429 / VictoriaTraces :9428
└─ Mihomo :7890（shadow-tls SIP003 代理）

Edge Nodes (remote_proxy, aliyun, tencent)
├─ Envoy :80/:443 + Node Exporter
└─ Vector → OTLP → forwards logs/traces to GTR via Tailscale

Remote Proxy (66.154.100.187)
└─ Shadow-TLS :443 (SNI: www.microsoft.com) → Shadowsocks :8388
```

### K3s Platform（已部署）

| Component | ArgoCD UI | Tailscale 访问 |
|-----------|-----------|---------------|
| **ArgoCD** | `https://argocd-argocd-server.tail414c32.ts.net` | ProxyClass gtr-only |
| **Sealed Secrets** | 集群内 | — |
| **Tailscale Operator** | 集群内 | 服务暴露 `tailscale.com/expose: "true"` |

## 常用部署命令

```bash
# === K3s 集群 ===
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml

# === Platform Operators ===
ansible-playbook -i inventory-edge.ini deploy-platform-argocd.yml
ansible-playbook -i inventory-edge.ini deploy-platform-sealed-secrets.yml
ansible-playbook -i inventory-edge.ini deploy-platform-tailscale-operator.yml

# === 验证 ===
ansible-playbook -i inventory-edge.ini verify-platform-argocd.yml
ansible-playbook -i inventory-edge.ini verify-platform-sealed-secrets.yml
ansible-playbook -i inventory-edge.ini verify-platform-tailscale-operator.yml

# === Edge ===
ansible-playbook -i inventory-edge.ini deploy-edge.yml

# === 完整 CI 触发 ===
gh workflow run deploy-infra.yml --ref main -f target=all
```

## 关键远程路径

| Path | Purpose |
|------|---------|
| `/etc/envoy/` | Envoy bootstrap + dynamic configs |
| `/usr/local/grafana/` | Grafana |
| `/var/lib/victoriametrics/data` | Metrics storage |
| `/var/lib/victorialogs/data` | Log storage |
| `/var/lib/rancher/k3s/` | K3s data + SealedSecrets 密钥备份 |
| `/etc/vector/` | Vector config |

## Gotchas

1. **`remote_proxy` 不是 K3s 节点:** 不要将其加入 K3s agent 组。

2. **Tunnel client 已从 GTR 移除:** Mihomo 内置 shadow-tls SIP003 处理所有代理流量。

3. **K3s 禁用了 servicelb + traefik:** 服务暴露走 Tailscale Operator。

4. **Tailscale proxy 调度:** 用 `ProxyClass gtr-only` 强制到 GTR（tencent 有 WireGuard TCP 阻断）。

5. **YAML name 冒号陷阱:** GitHub Actions 的 `name:` 值含 `: ` 必须加引号（如 `name: "Manual: backup"`），否则 YAML parser 误解析。

6. **Cigbutt:** Python CLI 量化分析，位于 `cigbutt/`。详见 `cigbutt/README.md`。

## 文档索引

| 主题 | 文档 |
|------|------|
| Ansible 约定 | [`docs/topic/infrastructure/ansible-conventions.md`](docs/topic/infrastructure/ansible-conventions.md) |
| Secrets 管理 | [`docs/deployment/secrets-management.md`](docs/deployment/secrets-management.md) |
| K3s 平台 CI 部署 | [`docs/deployment/k3s-platform-ci-deployment-guide.md`](docs/deployment/k3s-platform-ci-deployment-guide.md) |
| K3s 平台概述 | [`k3s/README.md`](k3s/README.md) |
| Vault 仓库 | `nas-deployment-vault/README.md`（私有仓库） |
| 排错文档 | [`docs/troubleshooting/`](docs/troubleshooting/)
