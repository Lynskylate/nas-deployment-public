# AGENTS.md

This repository is an **infrastructure runbook and deployment automation** repo for services running on the `gtr` server (Ubuntu 22.04, 192.168.31.59) and remote edge/proxy nodes. It contains **no application source code** — only Ansible playbooks, shell scripts, config templates, dashboards, and documentation.

All documentation is written in **Chinese**. Maintain this convention for new docs.

## Repository Structure

```
nas-deployment-public/
├── edge/                  # Unified edge proxy deployment (multi-node)
│   ├── ansible/           # Ansible playbooks, roles, host_vars for edge nodes
│   ├── patches/           # Deployment-related source patches
│   ├── pki/               # Root CA (bootstrapped locally, not committed)
│   └── scripts/           # bootstrap-root-ca.sh, helper scripts
├── shadowsocks-shadowtls/ # Legacy SS+Shadow-TLS deployment (being superseded by edge/)
├── mihomo/                # Mihomo proxy client (Ansible)
├── cigbutt/               # Cigbutt quantitative analysis CLI (Python, hatchling)
├── victoriatraces/        # VictoriaTraces distributed tracing (Ansible)
├── network-monitor/       # Network connectivity monitoring (shell + Ansible)
├── grafana/               # Grafana dashboards, alert rules, provisioning configs
├── envoy/                 # Envoy runbook (docs only)
├── victoriametrics/       # VictoriaMetrics runbook (docs only)
├── victorialogs/          # VictoriaLogs runbook (docs only)
├── node_exporter/         # Node exporter installer (shell)
└── docs/                  # Migration notes and vault bootstrap docs
```

## Architecture Overview

### Infrastructure Topology

```
Edge Nodes (remote_proxy, aliyun, tencent)
  └─ Envoy (80/443) → Node Exporter (/metrics) + Envoy stats (/stats/prometheus)
  └─ Vector → OTLP listener → forwards logs/traces to GTR via Tailscale

GTR Core (192.168.31.59)
  └─ Envoy → Grafana (3000) / VictoriaMetrics (8428) / VictoriaLogs (8429) / VictoriaTraces (9428)
  └─ Shadow-TLS client → Shadowsocks client (SOCKS5 :1080)
  └─ Mihomo (mixed proxy :7890)

Remote Proxy (66.154.100.187)
  └─ Shadow-TLS server (443, SNI: www.microsoft.com) → Shadowsocks server (:8388)
```

### Data Flows

- **Metrics:** node_exporter/envoy → VictoriaMetrics (Prometheus scrape) → Grafana
- **Logs:** Envoy access logs → Vector (parse/transform) → VictoriaLogs (Elasticsearch API) → Grafana
- **Traces:** OTLP-capable workloads → Vector (edge nodes) → VictoriaTraces (GTR)
- **Proxy:** GTR → Shadow-TLS client → internet via remote_proxy

## Deployment Commands

### Edge (primary deployment path)

```bash
cd edge/ansible

# Deploy edge baseline to all edge nodes
ansible-playbook -i inventory-edge.ini deploy-edge.yml

# Deploy tunnel server (remote_proxy only)
ansible-playbook -i inventory-edge.ini deploy-edge-tunnel-server.yml

# Deploy tunnel client (gtr only)
ansible-playbook -i inventory-edge.ini deploy-gtr-tunnel-client.yml

# Verify deployments
ansible-playbook -i inventory-edge.ini verify-edge-common.yml
```

### Shadowsocks + Shadow-TLS (legacy)

```bash
cd shadowsocks-shadowtls
./deploy.sh server   # Deploy to remote proxy
./deploy.sh client   # Deploy to gtr
./deploy.sh verify   # Verify
./deploy.sh all       # Full deployment
```

### Mihomo

```bash
cd mihomo/ansible
ansible-playbook -i inventory.ini deploy.yml
```

### Network Monitor

```bash
cd network-monitor
./deploy.sh deploy   # Deploy to gtr
./deploy.sh verify   # Check status
./deploy.sh logs     # View logs
```

## Ansible Conventions

### Inventory Structure

- **Edge** uses `inventory-edge.ini` with host groups: `edge_remote_proxy`, `edge_aliyun`, `edge_tencent`, `gtr_core`
- **Each service** (mihomo, shadowsocks) has its own `inventory.ini`
- `edge/ansible/ansible.cfg` sets `roles_path` to include both `./roles` and `../../shadowsocks-shadowtls/ansible/roles` (role reuse across deployments)

### Variable Layering

- `group_vars/all/public.yml` — shared non-secret defaults (versions, download URLs, paths)
- `group_vars/all/secret.runtime.yml` — deploy-time decrypted overlay from `nas-deployment-vault`
- `group_vars/<group>/public.yml` — group-specific non-secret defaults when a service needs multiple target profiles
- `group_vars/<group>/secret.runtime.yml` — deploy-time decrypted group-specific secret overlay
- `host_vars/<host>.yml` or `host_vars/<host>/public.yml` — per-host public overrides
- `host_vars/gtr/secret.runtime.yml` — deploy-time decrypted overlay for host-level secrets
- Role `defaults/main.yml` — role-level defaults with sensible fallbacks

### Role Patterns

Roles follow this structure:
```
role-name/
├── tasks/main.yml       # Main task list
├── handlers/main.yml    # Service restart/reload handlers
├── templates/*.j2       # Jinja2 config templates
├── defaults/main.yml    # Default variables (optional)
└── files/               # Static files to copy
```

Key patterns:
- Use `ansible.builtin.template` for config files (`.j2` templates)
- Use `notify: [reload systemd, restart <service>]` on template changes
- Use `ansible.builtin.meta: flush_handlers` before service start tasks
- Use `ansible.builtin.assert` for validation (not just `fail`)
- Conditionally include roles with `when: <feature>_enabled | bool`
- Always set `become: true` at playbook level for system packages

## Cigbutt Library

Located at `cigbutt/`. A Python CLI tool for quantitative stock analysis.

```bash
# Install (requires Python >=3.11)
cd cigbutt
uv sync          # or pip install -e .

# Commands
cigbutt analyze --ticker 0700.HK --market HK --financials a.json b.json --out-csv out.csv
cigbutt e2e-test
cigbutt scan-market --market HK --out-csv candidates.csv
cigbutt probe-providers --ticker 0700.HK --market HK
```

- **Build system:** hatchling (`pyproject.toml`, `[tool.hatch.build.targets.wheel]`)
- **Config:** `~/.config/cigbutt/config.toml` (DashScope LLM credentials). Also reads `CIGBUTT_CONFIG_FILE` env var.
- **Entry point:** `cigbutt.cli:main` registered as `cigbutt` console script
- **Subcommands:** `analyze`, `e2e-test`, `scan-hk`, `scan-market`, `probe-providers`
- **LLM:** DashScope (Alibaba Cloud) for AI-based analysis steps
- **Providers:** Multiple data providers (yfinance, akshare, polygon, fmp, etc.) with a `router.py` that selects by market
- **Tests:** In `cigbutt/tests/` — run with `pytest` from the `cigbutt/` directory

## Key Server Paths (on remote hosts)

| Path | Purpose |
|------|---------|
| `/etc/envoy/` | Envoy bootstrap + dynamic configs |
| `/etc/envoy/dynamic_config/` | LDS, CDS, RDS YAML files |
| `/etc/envoy/certs/` | TLS certificates |
| `/usr/local/envoy/` | Envoy binary |
| `/usr/local/grafana/` | Grafana (conf, data, bin) |
| `/var/lib/victoriametrics/data` | Metrics storage |
| `/var/lib/victorialogs/data` | Log storage |
| `/etc/vector/` | Vector config |
| `/etc/shadowsocks/` | Shadowsocks configs |
| `/usr/local/bin/cigbutt` | Cigbutt CLI (installed via pip) |

## Envoy Configuration Model

Envoy uses file-based dynamic configuration discovery:
- Bootstrap: `envoy.yaml` (static)
- Listeners: `lds.yaml` (dynamic)
- Clusters: `cds.yaml` (dynamic)
- Routes: `rds.yaml` (dynamic)

Edge Envoy uses a **unified domain routes model** (`envoy_domain_routes` in group_vars) supporting modes:
- `http_plaintext` — plain HTTP path routing
- `tls_terminate_http` — TLS termination with cert/key paths

## Grafana Dashboards

Dashboards are JSON files in `grafana/dashboards/`. Provisioning config in `grafana/provisioning/`. Alert rules in `grafana/alert-rules.yaml`.

Deploy alerts: `cd grafana && ./deploy-alerts.sh` (runs on gtr server).

## Gotchas and Non-Obvious Patterns

1. **Edge roles_path reuse:** `edge/ansible/ansible.cfg` adds `../../shadowsocks-shadowtls/ansible/roles` to `roles_path`. This means `edge` playbooks can use roles like `node-exporter`, `shadowsocks-server`, etc. from the shadowsocks directory. If you move/rename that directory, edge deployments break.

2. **Tailscale connectivity:** Edge nodes communicate with GTR's VictoriaMetrics/Logs via Tailscale (`gtr.tail414c32.ts.net`). Ensure Tailscale is running on both sides before deploying vector or verifying scrape targets.

3. **Inventory IP drift:** The `shadowsocks-shadowtls/ansible/inventory.ini` still references the old IP `142.171.205.19`, while `edge/ansible/inventory-edge.ini` uses `66.154.100.187` for the same `remote_proxy` host. The edge inventory is the current one.

4. **Cigbutt config resolution order:** CLI arg → `CIGBUTT_CONFIG_FILE` env → `~/.config/cigbutt/config.toml` default. DashScope credentials resolve: env vars (`DASHSCOPE_API_KEY`) → config file values.

5. **No application code to test locally:** This repo is deployment automation only. There is no build/test cycle for the repo itself (except the cigbutt Python package). The "test" is running the Ansible verify playbooks against live hosts.
