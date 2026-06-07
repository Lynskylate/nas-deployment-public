# Code Context: Observability Stack & Edge Services

## Files Retrieved

### Runbooks (service overview)
- `grafana/README.md` — Grafana on GTR, port 3000, SQLite, data `/usr/local/grafana/data/`
- `victoriametrics/README.md` — VM on GTR, port 8428, retention 360h, data `/var/lib/victoriametrics/data/`
- `victorialogs/README.md` — VL on GTR, port 8429, data `/var/lib/victorialogs/data/`
- `victoriatraces/README.md` — VT on GTR, port 9428, data `/var/lib/victoriatraces/data/`
- `envoy/README.md` — Envoy on every node, ports 80/443, admin 9901, dynamic config `/etc/envoy/dynamic_config/`
- `node_exporter/README.md` — Node Exporter on every node, port 9100

### Ansible group/host vars (all config knobs)
- `edge/ansible/group_vars/all/public.yml` (lines 1-115) — **master config file** with all defaults
- `edge/ansible/host_vars/gtr/public.yml` (lines 1-20) — GTR-specific overrides (proxy ports, k3s node labels)
- `edge/ansible/host_vars/aliyun/public.yml` (lines 1-35) — Aliyun edge node specific
- `edge/ansible/host_vars/remote_proxy.yml` (lines 1-24) — Overseas proxy node (tunnel server enabled)
- `edge/ansible/host_vars/tencent.yml` (lines 1-17) — Tencent edge node (Tailscale TCP broken workaround)

### Envoy templates (routing topology)
- `edge/ansible/roles/edge-envoy/templates/envoy.yaml.j2` (lines 1-35) — Bootstrap: node ID, admin, dynamic resources
- `edge/ansible/roles/edge-envoy/templates/lds.yaml.j2` (lines 1-115) — Listeners: TLS passthrough, TLS terminate, HTTP plaintext
- `edge/ansible/roles/edge-envoy/templates/cds.yaml.j2` (lines 1-70) — Clusters: shadow_tls_server, node_exporter, envoy_admin + `envoy_additional_clusters`
- `edge/ansible/roles/edge-envoy/templates/envoy.service.j2` (lines 1-30) — systemd unit with `CAP_NET_BIND_SERVICE`

### Edge deployment roles
- `edge/ansible/roles/edge-envoy/tasks/main.yml` (lines 1-100) — Deploy envoy: user, dirs, configs, binary download, firewall
- `edge/ansible/roles/edge-vector/tasks/main.yml` (lines 1-60) — Deploy Vector: user, dirs, config, binary
- `edge/ansible/roles/edge-vector/templates/vector.yaml.j2` (lines 1-60) — Edge Vector config: reads Envoy access log, scrapes prometheus, ships to VM/VL/VT
- `edge/ansible/roles/edge-victoriametrics-scrape/tasks/main.yml` (lines 1-55) — Merge `edge_proxy_vm_scrape_jobs` into `/usr/local/victoriametrics/victoriametrics_sd.yaml`
- `edge/ansible/deploy-edge.yml` (lines 1-40) — Unified edge baseline: node-exporter + tailscale + vector + envoy
- `edge/ansible/deploy-edge-victoriametrics-scrape.yml` (lines 1-20) — Update VM scrape jobs from gtr

### Mihomo
- `mihomo/ansible/group_vars/all/public.yml` (lines 1-55) — Mihomo core config: ports, providers, proxies, DNS, Tailscale exit node
- `mihomo/ansible/group_vars/aliyun/public.yml` (lines 1-30) — Aliyun mihomo config: points to GTR via Tailscale for logs/traces
- `mihomo/ansible/roles/mihomo/templates/config.yaml.j2` (lines 1-140) — Full Mihomo config: general, TUN, DNS, proxy-providers, proxy-groups, rules
- `mihomo/ansible/roles/mihomo/templates/vector.yaml.j2` (lines 1-55) — Mihomo Vector config: reads journald, ships to VL at `127.0.0.1:8429`
- `mihomo/monitoring/README.md` (full) — Architecture: metrics collector (shell script→VM), WS logs collector→VL
- `mihomo/monitoring/templates/mihomo-metrics.sh.j2` (lines 1-130) — Shell script: pulls Mihomo API `/traffic`, `/connections`, `/proxies`, pushes to VM `127.0.0.1:8428`

### Network Monitor
- `network-monitor/README.md` (full) — Cron-based script testing sites through Mihomo proxy, logs JSON to file → Vector → VL
- `network-monitor/network-monitor.sh` (lines 1-120) — Tests ~25 sites through `127.0.0.1:7890`, categories domestic vs international
- `network-monitor/vector.yaml` (lines 1-75) — Vector config: reads Envoy logs + network-monitor logs, ships to `localhost:8429`
- `network-monitor/ansible/deploy.yml` (lines 1-60) — Ansible: copies scripts, cron job, logrotate

### ArgoCD Platform Apps
- `platform/applications/sealed-secrets.yaml` (lines 1-20) — ArgoCD Application: Bitnami chart, `kube-system` namespace
- `platform/applications/tailscale-operator.yaml` (lines 1-25) — ArgoCD Application: Tailscale chart, `tailscale` namespace, headless — needs `operator-oauth` Secret
- `platform/resources/tailscale-proxyclass-gtr-only.yaml` (lines 1-15) — ProxyClass pinning proxy pods to GTR node

---

## Key Code

### 1. Port Map

| Service | Port | Host | Notes |
|---------|------|------|-------|
| Envoy HTTPS | 443 | 0.0.0.0 | `envoy_listener_port` |
| Envoy HTTP | 80 | 0.0.0.0 | `envoy_http_listener_port` (enabled only on edge nodes) |
| Envoy Admin | 9901 | 127.0.0.1 | `envoy_admin_port` |
| Grafana | 3000 | 127.0.0.1 | Hardcoded in Envoy CDS (no variable) |
| VictoriaMetrics | 8428 | 127.0.0.1 | `victoriametrics_port` |
| VictoriaLogs | 8429 | 127.0.0.1 | `victorialogs_port` |
| VictoriaTraces | 9428 | 127.0.0.1 | `victoriatraces_http_port` |
| Node Exporter | 9100 | 127.0.0.1 | `node_exporter_port` |
| Mihomo Mixed | 7890 | 0.0.0.0 | `mihomo_mixed_port` |
| Mihomo API | 9090 | 127.0.0.1 | `mihomo_external_controller` |
| Mihomo DNS | 100.121.0.67:53 | Local LAN | `mihomo_dns_listen` |
| Vector API | 8686 | 127.0.0.1 | |
| Vector OTLP gRPC | 4317 | 127.0.0.1 | `edge_vector_otlp_grpc_listen` |
| Vector OTLP HTTP | 4318 | 127.0.0.1 | `edge_vector_otlp_http_listen` |

### 2. Key Configuration Variables (from `group_vars/all/public.yml`)

```yaml
# --- Envoy ---
envoy_version: v1.37.0
envoy_admin_port: 9901
envoy_listener_port: 443
envoy_http_listener_enabled: true
envoy_http_listener_port: 80
envoy_log_path: /var/log/envoy
envoy_log_rotate: 7
envoy_dynamic_config_dir: /etc/envoy/dynamic_config
envoy_tls_cert_dir: /etc/envoy/certs
envoy_domain_routes:          # <-- Routes defined per-node
  - name: node_exporter_metrics
    mode: http_plaintext
    path_prefix: /metrics
    cluster: node_exporter
  - name: envoy_admin_metrics
    mode: http_plaintext
    path_prefix: /stats/prometheus
    cluster: envoy_admin
envoy_additional_clusters: [] # <-- G/Observability clusters (grafana, vm, vl) NOT defined here!

# --- Vector ---
edge_vector_enabled: true
vector_version: 0.53.0
edge_vector_sink_type: local_file   # "victorialogs" on non-GTR edges
victorialogs_host: gtr.tail414c32.ts.net
victorialogs_port: 8429
victoriametrics_host: gtr.tail414c32.ts.net
victoriametrics_port: 8428
victoriatraces_host: gtr.tail414c32.ts.net
victoriatraces_http_port: 9428

# --- VM Scrape ---
edge_vm_scrape_config_path: /usr/local/victoriametrics/victoriametrics_sd.yaml
edge_proxy_vm_scrape_jobs:    # <-- Edge proxy targets
  - job_name: edge_proxy_aliyun
    target: 47.120.46.128:80
  - job_name: edge_proxy_remote_proxy
    target: 66.154.100.187:80
  - job_name: edge_proxy_tencent
    target: 129.211.12.63:80

# --- K3s ---
k3s_server_url: https://100.100.99.70:6443
k3s_flannel_iface: tailscale0
k3s_containerd_http_proxy: "http://100.121.0.67:7890"
```

### 3. Envoy Routing to Observability (WHAT'S MISSING)

The Envoy CDS template (`cds.yaml.j2`) **only** generates clusters from `envoy_additional_clusters` + hardcoded `shadow_tls_server`, `node_exporter`, `envoy_admin`. There is **no variable-driven cluster** for Grafana, VictoriaMetrics, or VictoriaLogs.

On GTR specifically, the Envoy config on disk is static (not generated by this Ansible) — the runbook shows hardcoded clusters:
- `grafana_service` → `127.0.0.1:3000`
- `victoriametrics_service` → `127.0.0.1:8428`
- `logs_service` → `127.0.0.1:8429`
- `web_service` → `httpbin.org:80`

These clusters are **not represented in any Ansible template or variable**. They are manually maintained on GTR's `/etc/envoy/dynamic_config/cds.yaml`.

### 4. Data Flow Summary

```
Edge Node (aliyun/tencent/remote_proxy)
  Envoy :80/:443 → logs to /var/log/envoy/access.log
  Vector → reads access.log + scrapes :9901/stats/prometheus + :9100/metrics
    → ships logs to {{ victorialogs_host }}:{{ victorialogs_port }}/insert/elasticsearch/
    → ships metrics to {{ victoriametrics_host }}:{{ victoriametrics_port }}/api/v1/write
    → ships traces to {{ victoriatraces_host }}:{{ victoriatraces_http_port }}/insert/opentelemetry/v1/traces

GTR Core
  Envoy :443 → routes to Grafana :3000, VM :8428, VL :8429
  VictoriaMetrics scrapes itself + node_exporter + edge_proxy targets
  VictoriaLogs receives from Vector (edge + local network-monitor + mihomo)
  VictoriaTraces receives from edge OTLP
  Grafana → reads VM :8428 (data source) + VL :8429 (plugin)
  Network Monitor → cron script → through Mihomo :7890 → JSON logs → Vector → VL
  Mihomo Metrics → shell script → Mihomo API :9090 → push to VM :8428
  Mihomo Logs → Vector reads journald → VL :8429
```

### 5. Interdependencies

| Dependency | Direction | What breaks |
|-----------|-----------|-------------|
| Envoy → Grafana/VM/VL | GTR Envoy → localhost | All dashboard/metrics/log access via :443 breaks |
| Vector → VM/VL/VT | Every node → GTR Tailscale | Metrics/logs/traces stop flowing if Tailscale breaks or GTR IP changes |
| Grafana → VM | Grafana → localhost:8428 | Dashboards have no data |
| Grafana → VL | Grafana → localhost:8429 | Logs dashboards have no data |
| VictoriaMetrics scrape → edge targets | GTR → public IPs | Edge proxy metrics missing |
| Network Monitor → Mihomo | Script → 127.0.0.1:7890 | Routing validation stops |
| Mihomo → remote_proxy | GTR → 66.154.100.187:443 | No outbound proxy (ShadowTLS) |
| Mihomo metrics → VM | Script → 127.0.0.1:8428 | Mihomo dashboards blank |
| Mihomo logs → VL | Vector → 127.0.0.1:8429 | Mihomo logs not searchable |

---

## Architecture

### Physical Topology (Observability)

```
┌─────────────────────────────────────────────────────────┐
│                    GTR (192.168.31.59)                  │
│                                                          │
│  ┌─────────┐     ┌──────────────┐    ┌───────────────┐  │
│  │ Grafana │◄────│   Envoy :443 │◄───│  Tailscale    │  │
│  │ :3000   │     │   Admin:9901 │    │  100.121.0.67 │  │
│  └────┬────┘     └──────┬───────┘    └───────────────┘  │
│       │                 │                                │
│       ▼                 ▼                                │
│  ┌─────────┐     ┌──────────────┐                       │
│  │  VM     │     │   VL        │                       │
│  │ :8428   │     │ :8429       │                       │
│  └────┬────┘     └──────┬──────┘                       │
│       │                 │                               │
│       ▼                 ▼                               │
│  ┌─────────┐     ┌──────────────┐                       │
│  │  VT     │     │   Mihomo     │  Network Mon.         │
│  │ :9428   │     │ :7890/:9090  │  cron→:7890→VL        │
│  └─────────┘     └──────────────┘                       │
│                                                          │
└──────────────────────────┬──────────────────────────────┘
                           │ Tailscale (tail414c32.ts.net)
     ┌─────────────────────┼─────────────────────┐
     ▼                     ▼                     ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│   Aliyun     │  │   Tencent    │  │  remote_proxy     │
│   Envoy :80  │  │   Envoy :80  │  │  Envoy :80/:443   │
│   Vector→VL  │  │   Vector→VL  │  │  Vector→VL        │
│               │  │              │  │  Tunnel Servers   │
└──────────────┘  └──────────────┘  └──────────────────┘
```

### ArgoCD App-of-Apps

There is **no umbrella Application**. The `platform/applications/` directory contains two standalone Application manifests (`sealed-secrets.yaml`, `tailscale-operator.yaml`). These are applied manually or via CI — not aggregated by a root App. There is no `applicationset.yaml` or umbrella `argocd-apps.yaml`.

---

## Start Here

Open **`edge/ansible/group_vars/all/public.yml`** — it is the single source of truth for all edge and observability configuration variables. Every port, host, version, and feature flag is set here.

---

## What Would Break If a Service Moved to a Different IP/Port

### Hardcoded References (Will break immediately)

| What's hardcoded | Where | Impact |
|-----------------|-------|--------|
| Grafana → `http://localhost:8428` | Grafana data source config (provisioning, manual) | VM data source fails |
| Grafana → `http://localhost:8429` | Grafana VictoriaLogs plugin data source | VL data source fails |
| GTR Envoy → `127.0.0.1:3000/8428/8429` | `/etc/envoy/dynamic_config/cds.yaml` (manual, not templated) | All proxy routes fail |
| Vector on GTR → `http://localhost:8429` | `network-monitor/vector.yaml`, `mihomo/monitoring/` | Log shipping breaks on GTR-local Vector |
| Mihomo metrics → `http://127.0.0.1:8428` | `mihomo-metrics.sh.j2` | Mihomo dashboard metrics stop |
| Network Monitor → `127.0.0.1:7890` | `network-monitor.sh` | Routing validation fails if Mihomo port changes |
| Vector (GTR) scrape → `127.0.0.1:9901` | `edge/ansible/roles/edge-vector/templates/vector.yaml.j2` (line 13) | Envoy metrics not collected locally |

### Configurable References (Will work with variable change)

| What's variable-bound | Variable | Nodes affected |
|----------------------|----------|---------------|
| Edge Vector sinks → `victorialogs_host:port` | `victorialogs_host`, `victorialogs_port` | All edge nodes |
| Edge Vector → `victoriametrics_host:port` | `victoriametrics_host`, `victoriametrics_port` | All edge nodes |
| Edge Vector → `victoriatraces_host:port` | `victoriatraces_host`, `victoriatraces_http_port` | All edge nodes |
| GTR Envoy CDS clusters (node_exporter, admin) | `node_exporter_port`, `envoy_admin_port` | All edge nodes |
| VM scrape targets | `edge_proxy_vm_scrape_jobs` | GTR VM |
| Mihomo proxies → `shadowtls_server:port` | `shadowtls_server`, `shadowtls_port` | All Mihomo nodes |

### Critical: Tailscale MagicDNS

Most cross-node references use `gtr.tail414c32.ts.net` (Tailscale MagicDNS). If Tailscale IPs change or MagicDNS breaks, all remote Vector shipping stops. The actual Tailscale IP of GTR is `100.121.0.67`, which is also used directly in:
- `mihomo_dns_listen: 100.121.0.67:53`
- `k3s_containerd_http_proxy: http://100.121.0.67:7890`
- Mihomo rules matching Tailscale CIDR `100.64.0.0/10`

### Observability from non-GTR machines

If you want to run Grafana dashboards from a machine that ISN'T GTR, the following ALL route through Envoy on GTR `:443`:
- Grafana UI
- VictoriaMetrics queries
- VictoriaLogs queries
- VictoriaTraces queries (via Jaeger API at `http://gtr:9428/select/jaeger`)

These are NOT exposed through any other entry point. The ArgoCD services (e.g., `argocd-server`) are exposed via Tailscale Operator with `ProxyClass gtr-only`, also pinning to GTR.

---

## Constraints & Risks

1. **GTR is a single point of failure** for the entire observability stack and proxy routing.
2. **Envoy observability clusters are not in Ansible** — Grafana, VM, VL clusters on GTR are hand-maintained in `/etc/envoy/dynamic_config/cds.yaml`. Any redeploy of GTR Envoy from this repo will lose those clusters unless `envoy_additional_clusters` is populated.
3. **VictoriaMetrics scrape config is managed in two places**: the initial config is deployed by the victoriametrics install playbook, then `deploy-edge-victoriametrics-scrape.yml` merges edge-proxy jobs into it. This is brittle if the initial config changes structure.
4. **Vector on GTR reads from multiple Vector config files** — `vector.yaml`, `mihomo.yaml`, and possibly others. The systemd service only references `--config /etc/vector/vector.yaml`. Additional configs must either be included or Vector must be restarted with an expanded `--config` argument.
5. **Network-monitor Vector config** (`network-monitor/vector.yaml`) copies over `/etc/vector/vector.yaml`, potentially overwriting the edge Vector config on GTR. This is a conflict if both the edge role and network-monitor ansible run on GTR.
6. **No ArgoCD umbrella Application** — `platform/applications/` contains two independent Application manifests with no root App-of-Apps. There's no single `ApplicationSet` or umbrella `Application` that aggregates them.
7. **Tailscale ACLs are documented but not in repo** — The aliyun-telemetry doc describes ACL tags (`tag:aliyun-envoy`, `tag:gtr-monitoring`) that must be configured in Tailscale admin console. These are not version-controlled.
