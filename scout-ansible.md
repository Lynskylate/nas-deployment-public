# Ansible Deployment Structure — Comprehensive Survey

Survey date: 2026-06-07
Survey scope: All `*/ansible/` directories in the repository

---

## 1. All Playbooks

### 1.1 Core Infrastructure (`edge/ansible/`)

| Playbook | Target Hosts | What It Deploys |
|---|---|---|
| `deploy-edge.yml` | `edge_hosts` (aliyun, tencent, remote_proxy) | **Edge baseline**: node_exporter, tailscale, vector, envoy. Pre-task switches apt to Aliyun mirror (China nodes). |
| `deploy-edge-tunnel-server.yml` | `edge_remote_proxy` | **Tunnel server**: shadowsocks-server + shadowtls-server (Shadowsocks + Shadow-TLS proxy stack) |
| `deploy-edge-victoriametrics-scrape.yml` | `gtr_core` | **VictoriaMetrics scrape config**: Updates `/usr/local/victoriametrics/victoriametrics_sd.yaml` with edge-proxy scrape jobs, then triggers VM restart |
| `deploy-gtr-k3s-server.yml` | `edge_aliyun` | **K3s server** on aliyun (control-plane): k3s-prereq → k3s-server. Applies node labels. |
| `deploy-gtr-k3s-agent.yml` | `gtr_core` + `edge_tencent` | **K3s agents** on GTR and tencent: k3s-prereq → k3s-agent. Applies node labels. |
| `deploy-gtr-ai-tools.yml` | `gtr_core` | **AI coding tools** + Slock daemon on GTR: Claude Code, Codex, OpenCode CLIs |
| `deploy-gtr-project-runtime.yml` | `gtr_core` | **Project runtime host**: rootless Podman, /srv/projects/ structure |
| `deploy-platform-argocd.yml` | `edge_aliyun` | **ArgoCD** on aliyun K3s via manifest + App-of-Apps |
| `deploy-platform-sealed-secrets.yml` | `edge_aliyun` | **Sealed Secrets** controller on aliyun K3s + kubeseal CLI |
| `deploy-platform-tailscale-operator.yml` | `edge_aliyun` | **Tailscale Operator** prerequisites on aliyun: namespace, OAuth secret, ProxyClass `gtr-only` |
| `deploy-resource-manifest.yml` | `gtr_core` | Copies `.resource-manifest.yml` → `/etc/gtr/resource-manifest.infra.yml` |

### 1.2 Mihomo (`mihomo/ansible/`)

| Playbook | Target Hosts | What It Deploys |
|---|---|---|
| `deploy.yml` | `client_server` (GTR) | **Mihomo** proxy on GTR (HTTP/SOCKS proxy, API, rule-based routing) |
| `deploy-aliyun.yml` | `aliyun_server` | **Mihomo + Envoy + Vector** on Aliyun (public proxy endpoint with auth) |
| `deploy-exitnode.yml` | `client_server` (GTR) | **Tailscale exit node fix**: nftables MASQUERADE, policy routing, DNS fix for Mihomo TUN |

### 1.3 VictoriaTraces (`victoriatraces/ansible/`)

| Playbook | Target Hosts | What It Deploys |
|---|---|---|
| `deploy.yml` | `gtr` (192.168.31.59 via root) | **VictoriaTraces** binary, user, systemd service |
| `configure-envoy-tracing.yml` | `gtr` (192.168.31.59 via root) | Patches Envoy CDS/LDS/bootstrap to add OTel tracing → VictoriaTraces |

### 1.4 Network Monitor (`network-monitor/ansible/`)

| Playbook | Target Hosts | What It Deploys |
|---|---|---|
| `deploy.yml` | `monitoring_servers` (GTR) | Cron-based network connectivity monitor + Vector log forwarding |

### 1.5 Mihomo Monitoring (`mihomo/monitoring/ansible/`)

| Playbook | Target Hosts | What It Deploys |
|---|---|---|
| `deploy.yml` | `client_server` (GTR root) | Mihomo metrics collector (systemd timer), log collector (WebSocket), Vector config for sending to VictoriaMetrics/VictoriaLogs |

### 1.6 Verify Playbooks (`edge/ansible/`)

| Playbook | Target | What It Checks |
|---|---|---|
| `verify-edge-common.yml` | `edge_hosts` | Services active, ports listening, forbidden proxy ports closed, envoy routes, tunnel services |
| `verify-edge-tunnel-server.yml` | `edge_remote_proxy` | SS/Shadow-TLS services, ports, SSL handshake |
| `verify-edge-victoriametrics-scrape.yml` | `gtr_core` | Scrape config has edge jobs, VM targets contain them |
| `verify-gtr-k3s-server.yml` | `edge_aliyun` | k3s service, kubectl get nodes |
| `verify-gtr-k3s-agent.yml` | `gtr_core + edge_tencent` | k3s-agent service, tailscale IP |
| `verify-gtr-no-regression.yml` | `gtr_core` | Proxy ports (1080, 7890), mihomo/shadowsocks-client not removed |
| `verify-gtr-project-runtime.yml` | `gtr_core` | Podman CLI, /srv/ directories |
| `verify-gtr-ai-tools.yml` | `gtr_core` | CLI binaries, config files, Slock daemon + API reachability |
| `verify-platform-argocd.yml` | `edge_aliyun` | ArgoCD pods, deployments, services, admin secret |
| `verify-platform-sealed-secrets.yml` | `edge_aliyun` | Controller pod, test secret, public key |
| `verify-platform-tailscale-operator.yml` | `edge_aliyun` | Namespace, pods, deployments, ArgoCD application sync |

---

## 2. All Roles

### 2.1 Core Edge Roles (`edge/ansible/roles/`)

| Role | Purpose | Key Tasks |
|---|---|---|
| **`node-exporter`** | Prometheus node metrics on edge hosts | Creates user, deploys systemd unit, downloads binary, enables+starts, waits for :9100 |
| **`edge-tailscale`** | Ensures Tailscale is installed+running on edge | Checks `tailscale version`, installs package if missing, starts tailscaled |
| **`edge-vector`** | Vector observability pipeline on edge hosts | Creates user+dirs, deploys systemd + `vector.yaml` template (sources: envoy access log, prometheus scrape, OTLP; sinks: victorialogs or local_file, victoriametrics, victoriatraces), downloads binary |
| **`edge-envoy`** | Envoy reverse proxy on edge hosts | Creates user+dirs+logrotate, deploys systemd + bootstrap config, downloads binary, deploys LDS/CDS from Jinja2 templates, opens firewall ports, enables service |
| **`k3s-prereq`** | OS prerequisites for K3s (kernel, sysctl, netfilter) | Installs packages (curl, conntrack, iptables, etc.), loads kernel modules (overlay, br_netfilter, wireguard), applies sysctl, optionally sets `tailscale --netfilter-mode=nodivert` |
| **`k3s-server`** | K3s control-plane on aliyun | Asserts token, reads Tailscale IP, renders config.yaml + registries.yaml, runs installer, configures containerd HTTP proxy, enables service |
| **`k3s-agent`** | K3s agent on GTR and tencent | Same pattern as server but for agent role: asserts server URL+token, renders agent config, runs installer, configures containerd proxy |
| **`argocd`** | Deploy ArgoCD on K3s | Creates namespace, applies install manifest, waits for rollout, retrieves admin password, creates App-of-Apps Application, downloads CLI, annotates svc for Tailscale |
| **`edge-victoriametrics-scrape`** | Update VM scrape config | Reads existing `victoriametrics_sd.yaml`, removes old edge jobs, appends new ones, writes merged config, notifies VM restart |
| **`gtr-ai-tools`** | AI coding tools on GTR | Installs npm global packages (claude-code, codex, opencode), copies config files from controller, deploys Slock daemon as user systemd service |
| **`project-runtime-host`** | Rootless Podman runtime on GTR | Installs podman + uidmap + slirp4netns + fuse-overlayfs packages, creates /srv/ directories, deploys runtime report script |
| **`deploy-mutex`** | Lock mechanism for concurrent deploys | Installs systemd target units and `/usr/local/bin/deploy-lock` helper |
| **`shadowsocks-server`** | Shadowsocks server on remote_proxy | Creates user, downloads binary, deploys config + systemd, starts service |
| **`shadowtls-server`** | Shadow-TLS server on remote_proxy | Creates user, downloads binary, deploys systemd, optionally pins SNI host, opens firewall |
| **`shadowsocks-client`** | Shadowsocks client (standalone, not used by GTR's mihomo) | Same pattern as server but with `sslocal` binary |
| **`shadowtls-client`** | Shadow-TLS client (standalone, not used by GTR's mihomo) | Same pattern as server but for client |

### 2.2 Mihomo Roles (`mihomo/ansible/roles/`)

| Role | Purpose | Key Tasks |
|---|---|---|
| **`mihomo`** | Deploy Mihomo proxy | Creates user+dirs, downloads binary, deploys config.yaml + systemd, enables service |
| **`tailscale-exitnode`** | Fix Tailscale exit node with Mihomo TUN | Deploys nftables MASQUERADE, policy routing, systemd-resolved DNS config, exit node monitor timer+script, textfile collector for Prometheus |

### 2.3 VictoriaTraces Roles (`victoriatraces/ansible/roles/`)

| Role | Purpose | Key Tasks |
|---|---|---|
| **`victoriatraces`** | Deploy VictoriaTraces | Creates user+dirs, downloads binary, deploys systemd, starts service |
| **`envoy-tracing`** | Configure Envoy OTel tracing | Patches CDS (adds opentelemetry_collector cluster), LDS (adds tracing), bootstrap (adds tracing config via `envoy.tracers.opentelemetry`) |

---

## 3. Inventory & Host Mapping

### 3.1 Inventory: `edge/ansible/inventory-edge.ini`

```
[edge_remote_proxy]
remote_proxy   → 100.66.156.40 (ci@:22) — overseas VPS, direct GitHub access

[edge_aliyun]
aliyun         → 47.120.46.128 (ci@:22) — China cloud, uses public IP for CI (Tailscale UDP broken)

[edge_tencent]
tencent        → 100.99.48.76 (ci@:22) — China cloud, Tailscale reachable

[edge_hosts:children] = edge_remote_proxy + edge_aliyun + edge_tencent

[gtr_core]
gtr            → gtr.tail414c32.ts.net (ci@:22) — home server, Tailscale-only
```

### 3.2 Host-Variable Mapping

| Host | Group | Tunnel Server | K3s Role | Vector Sink | Proxy | Labels |
|---|---|---|---|---|---|---|
| **gtr** | `gtr_core` | disabled (has mihomo client) | **Agent** | N/A (local logs) | Mihomo :7890 | region=cn, visibility=internal |
| **aliyun** | `edge_aliyun` | disabled | **Server** (control-plane) | victorialogs → GTR | Via GTR mihomo (containerd), direct for GitHub | region=cn, visibility=public |
| **tencent** | `edge_tencent` | disabled | **Agent** | victorialogs → GTR | Via GTR mihomo | region=cn, visibility=public |
| **remote_proxy** | `edge_remote_proxy` | **enabled** (SS + Shadow-TLS) | Not a K3s node (!) | victorialogs → GTR (via Tailscale) | Direct GitHub (overseas) | N/A |

### 3.3 Other Inventories

| Inventory | Target | Host |
|---|---|---|
| `mihomo/ansible/inventory.ini` | `[client_server]` | gtr.tail414c32.ts.net (ci) |
| `mihomo/ansible/inventory-aliyun.ini` | `[aliyun_server]` | 100.102.140.59 (ci) — old aliyun IP? |
| `mihomo/monitoring/ansible/inventory.ini` | `[client_server]` | 192.168.31.59 (root) |
| `victoriatraces/ansible/inventory.ini` | `[gtr]` | 192.168.31.59 (root) |
| `network-monitor/ansible/inventory.ini` | `[monitoring_servers]` | 192.168.31.59 (root) |

**Note on multiple GTR identities**: GTR is addressed as `gtr.tail414c32.ts.net` (via ci, Tailscale SSH) in `edge/ansible/` and `mihomo/ansible/`, but as `192.168.31.59` (via root, LAN) in `victoriatraces/`, `mihomo/monitoring/`, and `network-monitor/`. This is a legacy split — the newer playbooks use Tailscale addressing.

---

## 4. Service Classification: Infrastructure Essential vs Application

### 4.1 Infrastructure Essential (required for K3s or basic host operation)

| Service | Why Essential | Deployed By |
|---|---|---|
| **Tailscale** | Overlay network for all inter-node communication, K3s Flannel iface, CI access | `edge-tailscale` role (via `deploy-edge.yml`), also manually/managed elsewhere |
| **Tailscale netfilter=nodivert** | Prevents Tailscale iptables from dropping CGNAT traffic (aliyun, tencent) | `k3s-prereq` role when `k3s_prereq_tailscale_nodivert=true` |
| **Kernel modules** (overlay, br_netfilter, wireguard) | Required by K3s (overlay filesystem, bridge networking, WireGuard) | `k3s-prereq` role |
| **Sysctl settings** (ip_forward, bridge-nf-call-*) | Required by K3s networking | `k3s-prereq` role |
| **OS packages** (conntrack, iptables, socat, etc.) | Required by K3s | `k3s-prereq` role |
| **K3s itself** | Container orchestration platform | `k3s-server` / `k3s-agent` roles |
| **containerd HTTP proxy** | Allows pulling container images through proxy (China nodes) | `k3s-server` / `k3s-agent` roles |

### 4.2 Application Services (deployed as bare-metal processes on edge/GTR)

| Service | What It Does | Deployed By | Could Run as K3s Pod? |
|---|---|---|---|
| **node_exporter** | Prometheus node metrics | `node-exporter` role | Yes (but needs host access) |
| **Envoy** | Reverse proxy, TLS termination, routing | `edge-envoy` role (edge), also standalone on GTR | Potentially, but currently bare-metal for edge networking |
| **Vector** | Observability pipeline (logs, metrics, traces) | `edge-vector` role (edge), also `mihomo/ansible/`, `network-monitor/` | Yes |
| **Mihomo** | HTTP/SOCKS proxy (shadow-tls SIP003 client) | `mihomo` role | Less ideal (needs TUN, net admin) |
| **Shadowsocks-server** | Encrypted proxy backend | `shadowsocks-server` role | Potentially |
| **Shadow-TLS-server** | TLS camouflage for proxy | `shadowtls-server` role | Potentially |
| **VictoriaTraces** | Distributed tracing backend | `victoriatraces` role | Yes (already shown as deployable) |
| **Slock daemon** | AI tool connectivity daemon | `gtr-ai-tools` role | No (user-context service) |
| **AI CLIs** (claude, codex, opencode) | AI coding assistants | `gtr-ai-tools` role | No (interactive CLI tools) |
| **Podman + project runtime** | Rootless container runtime for projects | `project-runtime-host` role | N/A (complement to K3s) |
| **Network monitor** | Connectivity probing | `network-monitor/ansible/` | Could be, but cron-based |
| **Tailscale exit node fix** | NAT + routing for Mihomo TUN / Tailscale exit node | `tailscale-exitnode` role | No (needs host net) |
| **Mihomo monitoring** | Metrics + log collection for mihomo | `mihomo/monitoring/ansible/` | Could be, but currently bare |

### 4.3 K3s Platform Operators (deployed on K3s via Ansible, managed via ArgoCD)

| Component | Deploy Method | Notes |
|---|---|---|
| **ArgoCD** | Ansible manifest apply → ArgoCD manages itself + apps | Access via Tailscale: `argocd-argocd-server.tail414c32.ts.net` |
| **Sealed Secrets** | Ansible manifest apply + kubeseal setup | Key backup at `/var/lib/rancher/k3s/sealed-secrets-key-backup.yaml` |
| **Tailscale Operator** | Ansible prerequisites → ArgoCD Application | ProxyClass `gtr-only` pins pods to GTR node |

---

## 5. Shared Dependencies & Pre-Tasks

### 5.1 Proxy-based GitHub Downloads (China network)

The variable `github_download_proxy` (default: `http://gtr.tail414c32.ts.net:7890`) is used in **every role that downloads binaries from GitHub**:

- `node-exporter`, `edge-envoy`, `edge-vector` (edge roles)
- `k3s-server`, `k3s-agent` (for installer script)
- `mihomo`, `shadowsocks-*`, `shadowtls-*` (downloading binaries)
- `argocd` (for manifest + CLI download)
- `gtr-ai-tools` (uses npm's own mirror)
- `victoriatraces` (uses `http://127.0.0.1:7890` hardcoded)

**Pattern**: Every download task has a dual implementation:
```yaml
- name: Download with proxy
  get_url: ...
  environment:
    http_proxy: "{{ github_download_proxy }}"
  when: github_download_proxy | default('') | length > 0

- name: Download without proxy (fallback)
  get_url: ...
  when: github_download_proxy | default('') | length == 0
```

**Host overrides**:
- `aliyun`: `github_download_proxy: ""` (direct GitHub access via public IP)
- `remote_proxy`: `github_download_proxy: ""` (overseas, direct)
- `gtr`: `github_download_proxy: "http://127.0.0.1:7890"` (uses local mihomo)

### 5.2 K3s Channel Mirror (`k3s_mirror`)

- Default: `k3s_mirror: "cn"` → uses `https://rancher-mirror.rancher.cn/k3s/k3s-install.sh`
- `remote_proxy`: `k3s_mirror: ""` → uses upstream `https://get.k3s.io` (not a K3s node anyway)

### 5.3 containerd HTTP Proxy

- Default: `k3s_containerd_http_proxy: "http://100.121.0.67:7890"`, `k3s_containerd_https_proxy: "http://gtr.tail414c32.ts.net:7890"`
- Written to `/etc/systemd/system/k3s*.service.env` as blockinfile
- Used by both `k3s-server` and `k3s-agent` roles

### 5.4 Tailscale Network Dependency

**Critical constraint**: K3s requires Tailscale to be running *before* the K3s installer runs because:
- K3s Flannel uses `tailscale0` as the overlay interface (`k3s_flannel_iface: "tailscale0"`)
- The K3s server uses its Tailscale IP (`100.100.99.70`) as the API endpoint
- Agents connect via Tailscale IPs (except tencent which uses aliyun's public IP as fallback)

The `edge-tailscale` role in `deploy-edge.yml` handles this for edge hosts. For GTR (which is the K3s agent), Tailscale is assumed pre-existing (not managed by Ansible in the K3s-agent playbook — it's a prerequisite).

### 5.5 Tailscale Netfilter Mode

- `k3s_prereq_tailscale_nodivert: true` on **aliyun** and **tencent** (cloud nodes with CGNAT IP conflicts)
- Set to `false` on GTR (home server, no conflict)
- Ansible executes: `tailscale set --netfilter-mode=nodivert --accept-routes` if current mode ≠ nodivert

### 5.6 Apt Mirror Switching (China nodes)

In `deploy-edge.yml` pre_tasks: Switches apt sources to Aliyun mirror (uses `/var/lib/gtr-edge/apt-mirror-switched` as idempotent marker). Only runs when `github_download_proxy` is non-empty (indicating a China node).

### 5.7 Deploy Mutex (`deploy-mutex` role)

Systemd-based mutual exclusion mechanism (`deploy-mutex.target`, `deploy-mutex-busy.target`) + `/usr/local/bin/deploy-lock` script. Prevents concurrent Ansible + deployctl operations. Currently installed but not referenced in any deploy playbook.

### 5.8 Registry Mirrors for containerd

- `k3s_registry_mirrors` on **aliyun**: `docker.io → https://quqdq6jy.mirror.aliyuncs.com` (from gtr host_vars? Wait, that's in gtr's host_vars)
- Actually `k3s_registry_mirrors` is set in **gtr** host_vars (for the GTR K3s agent): `docker.io → Aliyun mirror`
- aliyun has `k3s_registry_mirrors: {}` (empty — direct pull)

---

## 6. Architecture & Deployment Order

### 6.1 Correct Deployment Sequence

```
1. deploy-edge.yml               → Edge baseline (tailscale, node_exporter, envoy, vector)
2. deploy-edge-tunnel-server.yml → Tunnel stack on remote_proxy (shadowsocks + shadow-tls)
3. deploy-gtr-k3s-server.yml     → K3s control-plane on aliyun (requires tailscale from step 1)
4. deploy-gtr-k3s-agent.yml      → K3s agents on GTR + tencent (requires server from step 3)
5. deploy-platform-argocd.yml    → ArgoCD on K3s (requires K3s from step 3)
6. deploy-platform-sealed-secrets.yml → Sealed Secrets on K3s
7. deploy-platform-tailscale-operator.yml → Tailscale Operator on K3s
8. deploy-gtr-ai-tools.yml       → AI tools on GTR (optional, standalone)
9. deploy-gtr-project-runtime.yml → Podman runtime on GTR (optional, standalone)
10. deploy-edge-victoriametrics-scrape.yml → Update VM scrape targets (iterative)
11. deploy-resource-manifest.yml → Copy infra manifest to GTR (iterative)
```

### 6.2 Data Flow

```
Edge Node (remote_proxy / aliyun / tencent)
  ┌─ node_exporter ──→ metrics ──→ Envoy (:80/:443/metrics)
  ├─ Envoy ───────────→ logs ────→ Vector (reads access.log)
  ├─ Vector ──────────→ logs ────→ VictoriaLogs on GTR (via Tailscale)
  ├─ Vector ──────────→ metrics ─→ VictoriaMetrics on GTR
  └─ Vector ──────────→ traces ──→ VictoriaTraces on GTR

remote_proxy only:
  ┌─ Shadowsocks :8388 ←→ Shadow-TLS :8443 → Envoy TLS passthrough :443
  └─ SNI: www.microsoft.com → TLS handshake forwarded to Shadow-TLS

GTR Core:
  ┌─ Mihomo :7890 (proxy for all China nodes)
  ├─ Envoy :443 + :80 (reverse proxy to Grafana, VM, VL, VT)
  ├─ VictoriaMetrics :8428
  ├─ VictoriaLogs :8429
  ├─ VictoriaTraces :9428
  ├─ Grafana :3000
  ├─ K3s agent → joins aliyun control-plane
  └─ AI tools + Slock daemon (user context)

K3s Cluster:
  ┌─ aliyun (control-plane) ─ 100.100.99.70:6443
  ├─ gtr (agent) ───────────── 100.121.0.67
  └─ tencent (agent) ───────── 100.99.48.76
  Pod CIDR: 10.60.0.0/16, Service CIDR: 10.61.0.0/16
  Flannel via tailscale0 (vxlan)
```

### 6.3 Key Constraints & Risks

1. **Tailscale MUST be running before K3s** — K3s uses `tailscale0` as Flannel interface
2. **remote_proxy is NOT a K3s node** — Do not add it to k3s groups
3. **Tencent → aliyun Tailscale TCP is broken** (DPI) — tencent K3s agent uses aliyun's public IP as server URL
4. **Aliyun Tailscale UDP is broken** (NAT randomization) — CI Ansible connects via public IP, but K3s traffic still routes through Tailscale
5. **`k3s_server_url` vs `k3s_agent_server_url`** — tencent overrides with public IP `https://47.120.46.128:6443`
6. **Containerd proxy per-node** — Each host_vars overrides `k3s_containerd_http_proxy` for its own best path
7. **Inventory fragmentation** — GTR has 3 different identities across inventories (Tailscale hostname, LAN IP with ci, LAN IP with root)

---

## 7. Start Here

If you need to understand or modify the deployment, start with:

**`edge/ansible/deploy-edge.yml`** — This is the entry point for all edge nodes. It deploys the 4-edge baseline services (node_exporter, tailscale, vector, envoy) and its pre_tasks handle China-network apt mirror switching. The host_vars files (`aliyun/public.yml`, `remote_proxy.yml`, `tencent.yml`) then modulate per-node behavior.

For K3s deployment order: follow `deploy-gtr-k3s-server.yml` → `deploy-gtr-k3s-agent.yml` → platform playbooks.

For understanding the proxy chain: start with `deploy-edge-tunnel-server.yml` (remote_proxy), then trace back through `mihomo/ansible/deploy.yml` (GTR client) and how edge nodes use `github_download_proxy` to reach GTR's mihomo.
