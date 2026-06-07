# AGENTS.md

本仓库是 `gtr` 服务器（Ubuntu 22.04, 192.168.31.59）及远程 edge/proxy 节点的**基础设施 runbook 与部署自动化**仓库。**不含应用源码**——只有 Ansible playbook、Shell 脚本、配置模板、监控面板和文档。

所有文档使用 **中文**。新增文档遵循此约定。

## Repository Structure

```
nas-deployment-public/
├── edge/                     # 统一 edge proxy 部署（多节点）
│   ├── ansible/              # Ansible playbooks, roles, host_vars
│   │   ├── roles/            # k3s-prereq, k3s-server, k3s-agent, argocd, envoy, ...
│   │   ├── group_vars/       # 共享变量分层
│   │   └── host_vars/        # 各节点覆盖
│   ├── patches/              # 部署相关源码 patch
│   ├── pki/                  # Root CA（本地 bootstrap，未提交）
│   └── scripts/
├── platform/                 # K3s 内平台组件声明式配置（ArgoCD GitOps）
│   ├── applications/         # ArgoCD Application CRDs (App-of-Apps)
│   ├── helm-values/          # Helm values 覆盖
│   └── resources/            # 直接应用的 Kubernetes 资源（如 ProxyClass）
├── k3s/                      # K3s 平台文档
├── shadowsocks-shadowtls/    # 旧 SS+Shadow-TLS 部署（正被 edge/ 取代）
├── mihomo/                   # Mihomo 代理客户端（Ansible）
├── cigbutt/                  # Cigbutt 量化分析 CLI（Python, hatchling）
├── victoriatraces/           # VictoriaTraces 分布式追踪（Ansible）
├── network-monitor/          # 网络连通性监控（shell + Ansible）
├── grafana/                  # Grafana 面板、告警规则、provisioning
├── envoy/                    # Envoy runbook（纯文档）
├── victoriametrics/          # VictoriaMetrics runbook（纯文档）
├── victorialogs/             # VictoriaLogs runbook（纯文档）
├── node_exporter/            # Node exporter 安装器（shell）
├── scripts/                  # 仓库工具脚本
│   └── check-no-plaintext-secrets.py  # 明文凭据守卫
├── .github/                  # GitHub Actions CI/CD
│   ├── workflows/            # deploy-infra.yml, validate-pr.yml
│   └── actions/              # 复合 action：bootstrap-deploy-env
├── .pre-commit-config.yaml   # Pre-commit hooks（actionlint, yaml, whitespace）
└── docs/                     # 部署指南、排错文档、issue 跟踪
    ├── deployment/           # 部署指南
    ├── troubleshooting/      # 排错分析文档
    ├── issues/               # 实现跟踪（gitignored）
    └── topic/                # 专题文档
```

## Infrastructure Topology

### 全貌

```
Edge Nodes (remote_proxy, aliyun, tencent)
  ├─ Envoy (80/443) → Node Exporter (/metrics) + Envoy stats (/stats/prometheus)
  └─ Vector → OTLP listener → forwards logs/traces to GTR via Tailscale

K3s Cluster (3 节点)
  ├─ aliyun (control-plane): Tailscale 100.100.99.70
  ├─ gtr (agent):            Tailscale 100.121.0.67
  └─ tencent (agent):        Tailscale 100.99.48.76
  API Server: https://100.100.99.70:6443
  Pod CIDR: 10.60.0.0/16, Service CIDR: 10.61.0.0/16
  Flannel: vxlan, flannel-iface: tailscale0

GTR Core (192.168.31.59)
  └─ Envoy → Grafana (3000) / VictoriaMetrics (8428) / VictoriaLogs (8429) / VictoriaTraces (9428)
  └─ Mihomo (mixed proxy :7890) — built-in shadow-tls SIP003 处理所有代理流量
  └─ node_exporter (/metrics)

Remote Proxy (66.154.100.187)
  └─ Shadow-TLS server (443, SNI: www.microsoft.com) → Shadowsocks server (:8388)
```

### Data Flows

- **Metrics:** node_exporter/envoy → VictoriaMetrics (Prometheus scrape) → Grafana
- **Logs:** Envoy access logs → Vector (parse/transform) → VictoriaLogs (Elasticsearch API) → Grafana
- **Traces:** OTLP-capable workloads → Vector (edge nodes) → VictoriaTraces (GTR)
- **Proxy:** GTR → Mihomo (shadow-tls SIP003) → internet via remote_proxy
- **K3s Images:** 非 GTR 节点通过 Mihomo proxy 拉取镜像 (`gtr.tail414c32.ts.net:7890`)

### K3s Platform Components

| Component | Management | Status |
|-----------|-----------|--------|
| **K3s** (server + agents) | Ansible (`edge/ansible/`) | ✅ |
| **Argo CD** | Ansible bootstrap → self-managed via App-of-Apps | ✅ |
| **Sealed Secrets** | Ansible bootstrap → ArgoCD Application | ✅ |
| **Tailscale Operator** | ArgoCD Application (GitOps) | ✅ |

部署顺序：K3s → ArgoCD → Sealed Secrets → Tailscale Operator → 业务应用

ArgoCD 暴露在 Tailscale：`argocd-argocd-server.tail414c32.ts.net`

## Deployment Commands

### Full CI Pipeline（推荐）

推送到 `main` 分支自动触发 `.github/workflows/deploy-infra.yml`：

```
deploy-gtr → deploy-edge ──────────┐
              deploy-k3s-server ──┤
                deploy-k3s-agent ─┤
                  deploy-platform-operators
                    ├─ deploy-platform-argocd
                    ├─ deploy-platform-sealed-secrets
                    └─ deploy-platform-tailscale-operator
```

也可以用 `workflow_dispatch` 手动选择 target（`all` / `gtr_core` / `gtr_k3s_platform` / `edge_*`）。

### Edge（主要部署路径）

```bash
cd edge/ansible

ansible-playbook -i inventory-edge.ini deploy-edge.yml
ansible-playbook -i inventory-edge.ini deploy-edge-tunnel-server.yml
ansible-playbook -i inventory-edge.ini verify-edge-common.yml
```

### K3s 集群

```bash
cd edge/ansible

# Server
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-server.yml

# Agents
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-agent.yml
```

### Platform Operators

```bash
cd edge/ansible

ansible-playbook -i inventory-edge.ini deploy-platform-argocd.yml
ansible-playbook -i inventory-edge.ini deploy-platform-sealed-secrets.yml
ansible-playbook -i inventory-edge.ini deploy-platform-tailscale-operator.yml

# 验证
ansible-playbook -i inventory-edge.ini verify-platform-argocd.yml
ansible-playbook -i inventory-edge.ini verify-platform-sealed-secrets.yml
ansible-playbook -i inventory-edge.ini verify-platform-tailscale-operator.yml
```

### Legacy

```bash
# Shadowsocks + Shadow-TLS
cd shadowsocks-shadowtls && ./deploy.sh all

# Mihomo
cd mihomo/ansible && ansible-playbook -i inventory.ini deploy.yml

# Network Monitor
cd network-monitor && ./deploy.sh deploy
```

## Secrets Management

- **公共仓库** 不包含任何明文凭据
- `*.runtime.yml` 文件在 `.gitignore` 中，由 CI 在运行时从 vault repo 解密生成
- 所有敏感值存储在私有的 `nas-deployment-vault` 仓库中（SOPS + AGE 加密）
- CI 通过 `bootstrap-deploy-env` 复合 action 解密 vault repo
- 本地部署需要手动运行 vault bootstrap 脚本
- `scripts/check-no-plaintext-secrets.py` 检查明文凭据（在 `validate-pr.yml` 中自动运行）

### Vault Repository Layout

```
nas-deployment-vault/
├── bootstrap/github-actions/prod.sops.yml    # CI OAuth credentials, SSH deploy key
├── ansible/
│   └── edge/
│       ├── group_vars/all/secret.sops.yml    # 共享 secret overlay
│       └── host_vars/gtr/secret.sops.yml     # GTR 特有 secret
├── infra/
│   ├── sealed-secrets/key-backup.enc.yaml    # SealedSecrets 私钥备份
│   └── tailscale-operator/oauth.sops.yml    # Tailscale Operator OAuth
└── .sops.yaml                                # SOPS AGE 公钥配置
```

## Ansible Conventions

### Inventory Structure

- **Edge** 使用 `inventory-edge.ini`，host groups: `edge_remote_proxy`, `edge_aliyun`, `edge_tencent`, `gtr_core`
- **各服务**（mihomo, shadowsocks）有自己的 `inventory.ini`
- `edge/ansible/ansible.cfg` 的 `roles_path` 包含 `./roles` 和 `../../shadowsocks-shadowtls/ansible/roles`（跨部署复用 role）

### Variable Layering

- `group_vars/all/public.yml` — 共享非机密默认值（版本、下载 URL、路径）
- `group_vars/all/secret.runtime.yml` — 部署时从 `nas-deployment-vault` 解密的 overlay
- `group_vars/<group>/public.yml` — group 级非机密默认值
- `group_vars/<group>/secret.runtime.yml` — 部署时解密的 group 级 secret overlay
- `host_vars/<host>.yml` 或 `host_vars/<host>/public.yml` — 各节点公开覆盖
- `host_vars/gtr/secret.runtime.yml` — 部署时解密的 host 级 secret overlay
- Role `defaults/main.yml` — role 级默认值（优先级最低）

### Role Patterns

```
role-name/
├── tasks/main.yml       # 主 task 列表
├── handlers/main.yml    # 服务 restart/reload handler
├── templates/*.j2       # Jinja2 配置模板
├── defaults/main.yml    # 默认变量（可选）
└── files/               # 静态文件
```

关键模式：
- 用 `ansible.builtin.template` 渲染配置（`.j2` 模板）
- 模板变更时 `notify: [reload systemd, restart <service>]`
- 服务启动前用 `ansible.builtin.meta: flush_handlers`
- 用 `ansible.builtin.assert` 做校验（不要直接用 `fail`）
- 用 `when: <feature>_enabled | bool` 条件引入 role
- playbook 级别设 `become: true`（安装系统包需要）

### CI 兼容性

- CI runner 使用 Ubuntu，`/bin/sh` 是 `dash`，不支持 `set -o pipefail`
- 所有使用 `pipefail` 的 shell task 必须加 `args: executable: /bin/bash`
- 模板中用到的变量必须在 `group_vars/all/public.yml` 中定义默认值
- Ansible 断言失败在 CI 中表现为 task failed → job failed

## GitHub Actions & Pre-commit

### Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `deploy-infra.yml` | push to `main` / `workflow_dispatch` | 全栈部署流水线 |
| `validate-pr.yml` | PR → `main` | 多目录 Ansible syntax check + 明文凭据守卫 |

### Pre-commit

```bash
# Install
pip install pre-commit
pre-commit install

# Run manually
pre-commit run --all-files
```

Pre-commit hooks:
- `trailing-whitespace` / `end-of-file-fixer` — 基础格式化
- `check-yaml` — YAML 语法检查（排除 `.sops.yml`）
- `check-json` / `check-merge-conflict`
- **`actionlint`** — GitHub Actions workflow 静态分析（Go 编译安装）

### actionlint 安装

系统需安装 Go 1.21+：

```bash
go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.7
# 或者用 pre-commit 自动下载编译
pre-commit run actionlint --all-files
```

## Cigbutt Library

位于 `cigbutt/`。Python CLI 量化分析工具。

```bash
cd cigbutt
uv sync          # 或 pip install -e .

cigbutt analyze --ticker 0700.HK --market HK --financials a.json b.json --out-csv out.csv
cigbutt scan-market --market HK --out-csv candidates.csv
cigbutt probe-providers --ticker 0700.HK --market HK
```

- **构建系统:** hatchling（`pyproject.toml`）
- **配置:** `~/.config/cigbutt/config.toml`（DashScope LLM 凭据），也读 `CIGBUTT_CONFIG_FILE` 环境变量
- **入口点:** `cigbutt.cli:main`
- **LLM:** DashScope（阿里云）AI 分析
- **测试:** `cigbutt/tests/`，运行 `pytest`

## Key Server Paths（远程主机）

| Path | Purpose |
|------|---------|
| `/etc/envoy/` | Envoy bootstrap + 动态配置 |
| `/etc/envoy/dynamic_config/` | LDS, CDS, RDS YAML |
| `/etc/envoy/certs/` | TLS 证书 |
| `/usr/local/envoy/` | Envoy 二进制 |
| `/usr/local/grafana/` | Grafana（配置、数据、二进制） |
| `/var/lib/victoriametrics/data` | 指标存储 |
| `/var/lib/victorialogs/data` | 日志存储 |
| `/etc/vector/` | Vector 配置 |
| `/etc/shadowsocks/` | Shadowsocks 配置 |
| `/var/lib/rancher/k3s/` | K3s 数据和 SealedSecrets 密钥备份 |
| `/usr/local/bin/cigbutt` | Cigbutt CLI（pip 安装） |

## Platform (K3s) Conventions

### ArgoCD GitOps Model

- `platform/applications/` 包含 ArgoCD Application CRDs（App-of-Apps 模式）
- `platform-apps` Application 指向 `main` 分支的 `platform/applications/` 目录
- 下游 Application（`sealed-secrets`, `tailscale-operator`）各自指向自己的 Helm chart
- `platform/resources/` 存放非 ArgoCD 管理的 Kubernetes 资源（如 ProxyClass，需在 Tailscale Operator CRD 就绪后应用）

### Tailscale Operator

- Tailscale Operator 通过 ArgoCD Application 部署
- 使用 `ProxyClass gtr-only` 将 proxy pods 调度到 GTR 节点（tencent 有 Tailscale TCP WireGuard 阻断）
- 服务暴露：annotation `tailscale.com/expose: "true"` + `tailscale.com/proxy-class: gtr-only`
- 访问：`<service>-<namespace>.tail414c32.ts.net`

### Sealed Secrets

- 私钥备份保存在 `/var/lib/rancher/k3s/sealed-secrets-key-backup.yaml`
- SOPS 加密后存入 vault repo：`nas-deployment-vault/infra/sealed-secrets/key-backup.enc.yaml`
- 创建 SealedSecret：`kubeseal --controller-name sealed-secrets-controller --controller-namespace kube-system`

## Gotchas and Non-Obvious Patterns

1. **Edge roles_path 复用:** `edge/ansible/ansible.cfg` 添加了 `../../shadowsocks-shadowtls/ansible/roles` 到 `roles_path`。这意味着 `edge` playbook 可以使用 shadowsocks 目录中的 role（如 `node-exporter`, `shadowsocks-server`）。如果移动/重命名该目录，edge 部署会中断。

2. **Tailscale 连通性:** Edge 节点通过 Tailscale（`gtr.tail414c32.ts.net`）与 GTR 的 VictoriaMetrics/Logs 通信。部署 vector 或验证 scrape target 前，确保两端 Tailscale 都在运行。

3. **Inventory IP 漂移:** `shadowsocks-shadowtls/ansible/inventory.ini` 仍引用旧 IP `142.171.205.19`，而 `edge/ansible/inventory-edge.ini` 对同一个 `remote_proxy` 主机使用 `66.154.100.187`。edge inventory 是当前的。

4. **Tunnel client 已从 GTR 移除:** 独立的 `shadow-tls-client` + `shadowsocks-client` 已从 GTR 移除。Mihomo 内置的 shadow-tls SIP003 插件现在通过 edge Envoy 基础设施处理所有代理流量。

5. **Cigbutt 配置解析顺序:** CLI arg → `CIGBUTT_CONFIG_FILE` env → `~/.config/cigbutt/config.toml`。DashScope 凭据解析：env vars（`DASHSCOPE_API_KEY`）→ config 文件值。

6. **K3s Flannel 约束:** Flannel 后端为 `vxlan`，接口 `tailscale0`。K3s 禁用了 `servicelb` 和 `traefik`。GTR 上的 Mihomo TUN 的 `route-exclude-address` 包含 `10.0.0.0/8`（涵盖 Pod CIDR `10.60.0.0/16` 和 Service CIDR `10.61.0.0/16`）。

7. **`remote_proxy` 不是 K3s 节点:** 不要尝试将 `remote_proxy` 加入 K3s agent 组。

8. **YAML name 中的冒号:** GitHub Actions 的 `name:` 字段如果值中包含 `: `（冒号+空格），必须加引号。例：`name: "Manual: backup key"`，否则 YAML parser 会误解析为 mapping key。

9. **无应用程序代码需本地测试:** 本仓库仅是部署自动化。除了 cigbutt Python 包外，没有构建/测试循环。"测试"就是在目标主机上运行 Ansible verify playbook。
