# Code Context — Full Scan Results

## Files Retrieved

1. `k3s/README.md` (1-82) — K3s migration baseline docs
2. `edge/ansible/group_vars/all/public.yml` (1-126) — All shared variables (k3s, envoy, tailscale, vector)
3. `edge/ansible/host_vars/gtr/public.yml` (1-13) — GTR host vars (k3s_node_labels, proxy)
4. `edge/ansible/host_vars/aliyun/public.yml` (1-20) — Aliyun host vars (k3s server, registry mirrors)
5. `edge/ansible/host_vars/remote_proxy.yml` (1-20) — Remote proxy vars (tunnel, envoy routes)
6. `edge/ansible/host_vars/tencent.yml` (1-8) — Tencent host vars (k3s_node_labels)
7. `edge/ansible/inventory-edge.ini` (1-12) — Edge inventory (tailscale IPs for all hosts)
8. `tailscale-services/README.md` (1-270) — Tailscale Services docs (MagicDNS, serve, exit node)
9. `tailscale-services/apply-service-hosts.sh` (1-40) — Shell script to re-apply Tailscale service hosts
10. `tailscale-services/exit-node-troubleshooting-2026-05-31.md` (1-80) — Exit node + Mihomo TUN routing diagnostics
11. `tailscale-services/exit-node-implementation.md` — Exit node nftables fix
12. `edge/ansible/roles/edge-tailscale/tasks/main.yml` (1-25) — Tailscale install/enable
13. `edge/ansible/roles/k3s-server/tasks/main.yml` (1-110) — K3s server deployment
14. `edge/ansible/roles/k3s-server/templates/config.yaml.j2` (1-16) — K3s server config template
15. `edge/ansible/roles/k3s-server/templates/registries.yaml.j2` (1-12) — Containerd registry mirrors
16. `edge/ansible/roles/k3s-server/defaults/main.yml` (1-8) — K3s server defaults
17. `edge/ansible/roles/k3s-server/handlers/main.yml` (1-8) — K3s server restart handler
18. `edge/ansible/roles/k3s-agent/tasks/main.yml` (1-100) — K3s agent deployment
19. `edge/ansible/roles/k3s-agent/templates/config.yaml.j2` (1-4) — K3s agent config template
20. `edge/ansible/roles/k3s-prereq/tasks/main.yml` (1-25) — K3s prerequisites
21. `edge/ansible/roles/k3s-prereq/defaults/main.yml` (1-15) — K3s prereq packages/modules/sysctls
22. `edge/ansible/roles/k3s-prereq/templates/k3s-sysctl.conf.j2` (1-5) — Sysctl tuning
23. `edge/ansible/roles/edge-envoy/templates/envoy.yaml.j2` (1-30) — Edge Envoy bootstrap
24. `edge/ansible/roles/edge-envoy/templates/lds.yaml.j2` (1-130) — Edge Envoy listener config
25. `edge/ansible/roles/edge-envoy/templates/cds.yaml.j2` (1-60) — Edge Envoy cluster config
26. `edge/ansible/roles/edge-vector/tasks/main.yml` — Vector log shipper
27. `edge/ansible/roles/edge-vector/templates/vector.yaml.j2` — Vector config template
28. `edge/ansible/roles/mihomo/templates/config.yaml.j2` (1-200) — Mihomo TUN/proxy config
29. `edge/ansible/roles/tailscale-exitnode/tasks/main.yml` (1-120) — Exit node routing fix
30. `mihomo/ansible/group_vars/all/public.yml` (1-40) — Mihomo + exit node vars
31. `mihomo/ansible/inventory.ini` (1-10) — Mihomo inventory (gtr via tailscale)
32. `edge/ansible/deploy-gtr-k3s-server.yml` — K3s server playbook
33. `edge/ansible/deploy-gtr-k3s-agent.yml` — K3s agent playbook
34. `edge/ansible/verify-gtr-k3s-server.yml` — K3s server verify
35. `edge/ansible/verify-gtr-k3s-agent.yml` — K3s agent verify
36. `edge/ansible/deploy-edge.yml` — Edge baseline playbook
37. `edge/ansible/deploy-gtr-project-runtime.yml` — Project runtime (Podman) on GTR
38. `mihomo/ansible/deploy.yml` — Mihomo deployment
39. `.resource-manifest.yml` — Port/service registry
40. `.github/workflows/deploy-infra.yml` (1-400) — Full CI/CD pipeline
41. `docs/issues/001-k3s-platform-bootstrap.md` — Original K3s bootstrap plan
42. `docs/issues/002-argocd-sealed-secrets-tailscale-operator.md` — Platform operators plan
43. `docs/issues/003-corp-finance-monitor-helm-migration.md` — App migration plan
44. `docs/issues/004-corp-finance-monitor-data-migration.md` — Data migration plan
45. `docs/issues/005-private-secrets-repo-bootstrap.md` — Secrets vault bootstrap
46. `docs/issues/006-k3s-deploy-optimization.md` — K3s topology + CI optimization
47. `docs/issues/007-k3s-flannel-tailscale-crashloop.md` — Flannel/tailscale0 crashloop analysis
48. `docs/issues/008-docker-nftables-conflict-analysis.md` — Docker nftables conflict analysis
49. `docs/topic/infrastructure/decentralized-resource-isolation.md` — Resource manifest contract
50. `edge/ansible/verify-gtr-no-regression.yml` — GTR proxy regression check
51. `edge/ansible/deploy-gtr-ai-tools.yml` — AI tools on GTR
52. `project-runtime/README.md` — Podman runtime baseline

---

## 1. K3s/K3s-Related Files

### Cluster Topology
- **Status:** Active; migrated from GTR server → aliyun server after crashloop fix
- **Nodes:**
  | Role | Node | Tailscale IP | Labels |
  |------|------|-------------|--------|
  | **Server** (control-plane) | aliyun | 100.102.140.59 | `gtr.io/region: cn`, `gtr.io/visibility: public` |
  | **Agent** | gtr | 100.121.0.67 | `gtr.io/region: cn`, `gtr.io/visibility: internal` |
  | **Agent** | tencent | 100.99.48.76 | `gtr.io/region: cn`, `gtr.io/visibility: public` |
  | **Agent** | remote_proxy | 100.66.156.40 | (no explicit labels) |
- API server: `https://100.102.140.59:6443`
- Cluster CIDR: `10.60.0.0/16`, Service CIDR: `10.61.0.0/16`, Cluster DNS: `10.61.0.10`
- Flannel backend: `wireguard-native` (kernel WireGuard, avoids tailscale0 dependency, fixed crashloop from issue #007)
- Built-ins disabled: `cloud-controller-manager`, `traefik`, `servicelb`
- K3s channel: `stable`

### Key Files

```
k3s/README.md                          # Migration baseline docs
edge/ansible/roles/k3s-prereq/         # Prerequisites (packages, modules, sysctls)
edge/ansible/roles/k3s-server/         # Server role (tasks, templates, defaults, handlers)
edge/ansible/roles/k3s-agent/          # Agent role (tasks, templates, defaults, handlers)
edge/ansible/deploy-gtr-k3s-server.yml # Deploy server (hosts: edge_aliyun)
edge/ansible/deploy-gtr-k3s-agent.yml  # Deploy agents (hosts: gtr_core:edge_tencent)
edge/ansible/verify-gtr-k3s-server.yml
edge/ansible/verify-gtr-k3s-agent.yml
```

### K3s Server Config (`config.yaml.j2`)
```yaml
token: "{{ k3s_cluster_token }}"           # From sops-decrypted vault
write-kubeconfig-mode: "0640"
cluster-cidr: "10.60.0.0/16"
service-cidr: "10.61.0.0/16"
cluster-dns: "10.61.0.10"
advertise-address: "{{ k3s_server_effective_ip }}"  # Tailscale IP
node-ip: "{{ k3s_server_effective_ip }}"             # Tailscale IP
node-name: "{{ inventory_hostname }}"
flannel-backend: "wireguard-native"
disable-cloud-controller: true
disable:
  - traefik
  - servicelb
tls-san: [aliyun, 100.102.140.59, ...]
```

### K3s Agent Config (`config.yaml.j2`)
```yaml
server: "https://100.102.140.59:6443"
token: "{{ k3s_cluster_token }}"
node-ip: "{{ k3s_agent_effective_ip }}"  # Tailscale IP from `tailscale ip -4`
node-name: "{{ inventory_hostname }}"
```

### Idempotent Install
Both server and agent roles check runtime health before install:
- `systemctl is-active k3s` / `k3s-agent` → if active + API reachable → skip install
- Only renders config templates + ensures service started
- Uses installer script from mirror (CN: `rancher-mirror.rancher.cn`, overseas: `get.k3s.io`)

### Containerd Image Pull Proxy
```yaml
k3s_containerd_http_proxy: "http://gtr.tail414c32.ts.net:7890"  # default in group_vars
k3s_containerd_https_proxy: "http://gtr.tail414c32.ts.net:7890"
k3s_containerd_no_proxy: "localhost,127.0.0.1,10.0.0.0/8,100.0.0.0/8"
```
Per-host overrides: GTR uses `127.0.0.1:7890` (localhost mihomo), aliyun uses Aliyun Docker mirror (`quqdq6jy.mirror.aliyuncs.com`), remote_proxy has no proxy.

### Node Labels
```yaml
gtr.io/region: cn|us
gtr.io/visibility: public|internal
```

---

## 2. Tailscale References

### Tailscale Network: `tail414c32.ts.net`

**All nodes are on the same Tailnet:**
| Host | Tailscale IP | Ansible Connection |
|------|-------------|-------------------|
| GTR | 100.121.0.67 | `gtr.tail414c32.ts.net` (DNS name) |
| aliyun | 100.102.140.59 | Direct IP |
| tencent | 100.99.48.76 | Direct IP |
| remote_proxy | 100.66.156.40 | Direct IP |

Inventory uses **Tailscale IPs exclusively** for ansible connectivity:
```
[edge_remote_proxy]
remote_proxy ansible_host=100.66.156.40

[edge_aliyun]
aliyun ansible_host=100.102.140.59

[edge_tencent]
tencent ansible_host=100.99.48.76

[gtr_core]
gtr ansible_host=gtr.tail414c32.ts.net
```

### Tailscale Services (GTR)
Bare-metal services exposed via `tailscale serve`:
| Service | MagicDNS Name | Local Target | ACL Protection |
|---------|---------------|-------------|----------------|
| corp-finance-monitor | `corp-finance-monitor.tail414c32.ts.net` | `127.0.0.1:8190` | autogroup:member |
| Grafana | `grafana.tail414c32.ts.net` | `localhost:3000` | autogroup:member |
| Mihomo API | `mihomo-api.tail414c32.ts.net` | `127.0.0.1:9090` | autogroup:admin + Bearer Token |
| VictoriaMetrics | `victoriametrics.tail414c32.ts.net` | `localhost:8428` | tag:private |
| VictoriaLogs | `victorialogs.tail414c32.ts.net` | `localhost:8429` | tag:private |
| Envoy Admin | `envoy-admin.tail414c32.ts.net` | `127.0.0.1:9901` | autogroup:admin |

Key quote from `tailscale-services/README.md`:
> **TailVIP 与 Envoy 无冲突**：Tailscale Services 使用独立虚拟 IP，Envoy 监听 `0.0.0.0:443` 在主机网络层，两者互不干扰。

### Tailscale Exit Node (GTR)
GTR is configured as a Tailscale exit node. Routing:
```
Tailnet device → GTR (advertise-exit-node)
  → Mihomo TUN (mixed stack, auto-route)
    → Proxy groups (chain/direct depending on destination)
```
Mihomo TUN config excludes Tailscale addresses:
```yaml
route-exclude-address:
  - 192.168.0.0/16
  - 10.0.0.0/8
  - 172.16.0.0/12
  - 100.64.0.0/10        # ← Tailscale CGNAT range
```

### Tailscale Operator (K3s)
Planned but not yet installed — see `docs/issues/002-argocd-sealed-secrets-tailscale-operator.md`.

### nftables Routing Fixes
A `tailscale-exitnode-fix.service` injects:
1. MASQUERADE rule in POSTROUTING (dynamic WAN detection)
2. Policy route: `from 100.64.0.0/10 lookup 2022` → Mihomo TUN
3. Monitor timer: `tailscale-exitnode-monitor.timer` (30s interval, auto-fix)

This was necessary because Docker's nftables rules prevented Tailscale from properly installing `ts-postrouting` chain references.

---

## 3. Kubernetes Service Types

**No Kubernetes Service manifests exist in this repository.**

This repo (`nas-deployment-public`) owns only **host-level infrastructure** (K3s platform, edge Envoy, tailscale config, VM metrics/logs). Kubernetes resource manifests (Deployments, Services, Ingresses, etc.) are owned by **application repositories** under the target architecture.

The planned architecture from `docs/issues/003-corp-finance-monitor-helm-migration.md`:
> - Model frontend/backend Services and workloads
> - Register the app in Argo CD from `nas-deployment`

So `nas-deployment` will hold **Argo CD Application registration** YAMLs (not raw k8s Services), while apps hold their own Helm charts.

### Built-in K3s k8s Services Disabled
```yaml
k3s_disable_components:
  - traefik        # ← Ingress controller
  - servicelb      # ← LoadBalancer Service controller
```
This is deliberate — traffic goes through the host-level **Envoy** proxy instead.

### Relevant: K3s Service CIDR
```yaml
k3s_service_cidr: 10.61.0.0/16
k3s_cluster_dns: 10.61.0.10
```
These are set in `group_vars/all/public.yml` and wired into `config.yaml.j2`.

---

## 4. Service Mesh / Ingress Patterns

### Host-Level: Envoy Proxy (Primary Ingress)

**Every edge node runs Envoy** as the unified ingress:
- Binds `0.0.0.0:443` (TLS listener) + `0.0.0.0:80` (HTTP listener)
- Uses file-based dynamic config (LDS/CDS from `/etc/envoy/dynamic_config/`)
- Listener modes: `http_plaintext`, `tls_terminate_http`, `tls_passthrough`

**Edge Envoy Route Model** (`envoy_domain_routes` in group_vars):
```yaml
envoy_domain_routes:
  - name: node_exporter_metrics
    mode: http_plaintext
    path_prefix: /metrics
    cluster: node_exporter
  - name: envoy_admin_metrics
    mode: http_plaintext
    path_prefix: /stats/prometheus
    cluster: envoy_admin
  # remote_proxy ONLY:
  - name: shadowtls_passthrough
    mode: tls_passthrough
    sni_domains: ["www.microsoft.com", "*.microsoft.com"]
    cluster: shadow_tls_server
```

**Pre-defined clusters** (from `cds.yaml.j2`):
| Cluster | Target | Port |
|---------|--------|------|
| `shadow_tls_server` | 127.0.0.1 | 8443 |
| `node_exporter` | 127.0.0.1 | 9100 |
| `envoy_admin` | 127.0.0.1 | 9901 |
| Additional via `envoy_additional_clusters` | configurable | configurable |

**Request flow for external traffic:**
```
Internet → Edge Node (66.154.100.187:80/443)
  → Envoy (LDS: TLS inspect + path routing)
    → node_exporter (/metrics) / shadow-tls-server (SNI: microsoft.com)
```

**Request flow for internal traffic (Tailnet):**
```
Tailscale device → gtr.tail414c32.ts.net:8428/8429/3000
  → Tailscale serve (virtual IP)
    → localhost service (direct)
```

### Legacy: Shadowsocks + Shadow-TLS (Deprecated)
The old proxy stack is being superseded by Mihomo. The `shadowtls_passthrough` route in remote_proxy's Envoy still forwards traffic to `shadow-tls-server` for legacy compatibility.

### Envoy Administration
- Admin interface: `127.0.0.1:9901`
- Access logs: `/var/log/envoy/access.log`
- Config validation: `envoy --mode validate -c /etc/envoy/envoy.yaml`
- Systemd-managed, `CAP_NET_BIND_SERVICE` capability

### Envoy Resource Constraints
```yaml
overload_manager:
  resource_monitors:
    - name: fixed_heap
      max_heap_size_bytes: 2147483648   # 2GB
```

### Mihomo Proxy (TUN mode on GTR)
Mihomo operates at the **host network layer** with TUN mode, not as a Kubernetes mesh:
- Mixed HTTP/SOCKS proxy on port 7890
- TUN mode with `auto-route: true` for intercepting traffic
- Excludes Tailscale/LAN CIDRs from TUN
- DNS hijack on `any:53`
- Proxy groups: chain routing via self-hosted nodes (ShadowTLS/Hysteria2) → subscription nodes
- Tailscale traffic rules (hard-coded in Mihomo config):
  ```
  - DOMAIN-SUFFIX,ts.net,DIRECT
  - DOMAIN-SUFFIX,tailscale.com,DIRECT
  - DOMAIN-SUFFIX,tail414c32.ts.net,DIRECT
  - IP-CIDR,100.64.0.0/10,DIRECT
  ```

---

## 5. Network Architecture

### Infrastructure Topology

```
                  Internet
                     │
        ┌────────────┼────────────┐
        │            │            │
   remote_proxy   aliyun       tencent
   66.154.100.187  47.120.46.128 129.211.12.63
        │            │            │
        │  Tailscale (encrypted mesh via tail414c32.ts.net)
        └────────────┼────────────┘
                     │
                   GTR (Core)
              192.168.31.59 (LAN)
              100.121.0.67 (Tailscale)
```

### Data Flows

**Metrics (public edge → GTR VictoriaMetrics):**
```
Edge node_exporter (127.0.0.1:9100)
  → Edge Envoy (/metrics path, 0.0.0.0:80)
    → Prometheus scrape job
      → GTR tail414c32.ts.net:8428
```

**Logs (edge → GTR VictoriaLogs):**
```
Edge Envoy access.log
  → Edge Vector (parser/transform)
    → GTR tail414c32.ts.net:8429 (via Tailscale)
```

**Proxy traffic (GTR → Internet):**
```
GTR applications → Mihomo mixed proxy (127.0.0.1:7890)
  → TUN mode routes exclude Tailscale/private
  → Proxy chain (ShadowTLS/Hysteria2 → subscription nodes)
    → remote_proxy:443 (shadow-tls SNI: www.microsoft.com)
      → Internet
```

**Tailscale exit node (client → GTR → Internet):**
```
Client (exit-node=gtr) → Tailscale encrypted tunnel
  → GTR tailscale0 → Mihomo TUN
    → nftables MASQUERADE + policy route (100.64.0.0/10 → table 2022)
      → Mihomo proxy groups
        → Internet
```

### Edge Scrape Targets (VictoriaMetrics)
```yaml
edge_proxy_vm_scrape_jobs:
  - job_name: edge_proxy_aliyun
    target: 47.120.46.128:80        # Public IP, Envoy metrics
  - job_name: edge_proxy_remote_proxy
    target: 66.154.100.187:80        # Public IP, Envoy metrics
  - job_name: edge_proxy_tencent
    target: 129.211.12.63:80         # Public IP, Envoy metrics
```

### Port Registry (`.resource-manifest.yml`)
```yaml
ports:
  - 80/tcp → envoy (HTTP)
  - 443/tcp → envoy-tls (HTTPS)
  - 3000/tcp → grafana
  - 7890/tcp → mihomo
  - 8428/tcp → victoriametrics
  - 8429/tcp → victorialogs
  - 9090/tcp → mihomo-api
  - 9100/tcp → node_exporter
  - 9428/tcp → victoriatraces
  - 9901/tcp → envoy-admin
```

### DNS Architecture
- **Tailscale MagicDNS:** `*.tail414c32.ts.net` for all tailnet services
- **GTR Core:** Reachable as `gtr.tail414c32.ts.net`
- **Mihomo DNS:** `100.121.0.67:53` (GTR's Tailscale IP, enhanced-mode: redir-host)
- **No public DNS records** managed in this repo — all exposure is via Tailscale MagicDNS
- Service DNS: `10.61.0.10` (K3s cluster DNS for internal k8s service discovery)

### SSH Access
All nodes use SSH via their Tailscale IPs with `ci` user. No public SSH endpoints.

---

## Key Findings Summary

### K3s-Specific vs. Running Alongside K3s

| Component | Nature | Relationship to K3s |
|-----------|--------|---------------------|
| **K3s** | K3s-native | Core platform (k3s.io) |
| **Flannel (`wireguard-native`)** | K3s-native | Built-in CNI, configured in K3s config |
| **Traefik** | Disabled (explicitly) | Was built-in, now replaced by Envoy |
| **ServiceLB** | Disabled (explicitly) | Was built-in K8s LoadBalancer, not used |
| **Cloud Controller Manager** | Disabled | No cloud-provider integration |
| **Envoy (edge nodes)** | Running alongside | Host-level, not in K8s. Entry point for all external traffic |
| **Mihomo (GTR)** | Running alongside | Host-level TUN proxy, not in K8s. Exit node routing |
| **Tailscale** | Running alongside | Host-level. Tailscale operator planned but not installed |
| **VictoriaMetrics/Logs/Traces** | Running alongside | Host-level services, not in K8s |
| **Grafana** | Running alongside | Host-level, not in K8s |
| **Vector** | Running alongside | Host-level log shipper, not in K8s |
| **Argo CD** | Planned for K3s | Will be the GitOps reconciler inside K3s |
| **Sealed Secrets** | Planned for K3s | Will handle secrets inside K3s |
| **Tailscale Operator** | Planned for K3s | Will expose K8s services via Tailnet |

### Gaps & Open Questions

1. **No K8s Service manifests exist** — all actual Kubernetes resources live in application repos. This repo only manages the K3s cluster + Argo CD Application CRDs.
2. **Traffic model: Envoy → K3s is undefined** — Currently Envoy routes to host-level services (127.0.0.1). How Envoy will route into K3s pods (NodePort? HostPort? Tailscale Operator?) is not implemented.
3. **K3s `servicelb` is disabled** — So there's no LoadBalancer Service integration. Tailscale Operator will be the ingress mechanism.
4. **Docker was uninstalled** (per issue #008 analysis, GTR: Docker removed 2026-06-07). K3s containerd is the only container runtime.
5. **No service mesh** — the architecture is "Envoy at edge + K3s for orchestration". No Istio/Linkerd/service mesh layer.
6. **Remote proxy's k3s agent** (`100.66.156.40`) has no explicit node labels or container registry mirror config — may need attention.
7. **Argo CD + Sealed Secrets + Tailscale Operator** installation docs exist (issue #002) but implementation status is unclear — need to check if the actual install playbooks/scripts exist.
8. **The `flannel-iface: tailscale0` crashloop** from issue #007 has been fixed by switching to `flannel-backend: wireguard-native`, but the historical crashloop data suggests careful testing is needed for the current topology.
9. **Mihomo DNS** is set to GTR's Tailscale IP (`100.121.0.67:53`) — this routes DNS through the proxy chain. How this interacts with `k3s_cluster_dns: 10.61.0.10` on K3s nodes is worth clarifying.

### Start Here
To understand the full deployment flow, begin with:
1. `.github/workflows/deploy-infra.yml` — CI pipeline showing deployment order and dependencies
2. `edge/ansible/group_vars/all/public.yml` — Central vars file that ties everything together
3. `k3s/README.md` — K3s cluster topology and deployment docs
4. `tailscale-services/README.md` — How services are exposed internally
