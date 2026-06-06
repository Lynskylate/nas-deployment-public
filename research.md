# Research: Tailscale Kubernetes Operator OAuth Configuration — Permissions, Scopes, and ACL Setup

*Research date: 2026-06-07*

---

## Summary

The Tailscale Kubernetes Operator requires an **OAuth client** (or pre-auth key) to authenticate proxy pods. The OAuth client needs the `devices` scope (to create/auth devices) and optionally `auth_keys` (if managing keys). The client must be tagged with a tag like `tag:k8s-operator` in the Tailscale admin console, and proxy pods automatically inherit that tag. ACL grants must allow the operator's tag to create devices and access tagged resources. Helm values require `oauth.clientId` and `oauth.clientSecret` under the `operator` block when using OAuth, or a flat `authKey` string when using a pre-auth key. OAuth is strongly preferred over pre-auth keys because it avoids key expiry and enables automatic credential rotation.

---

## Findings

### 1. Required OAuth Scopes

The Tailscale OAuth client used by the Kubernetes Operator **must** have the following scopes:

| Scope | Purpose | Required? |
|-------|---------|-----------|
| `devices` | Create and manage devices (proxy pods register as Tailscale nodes) | **Yes** |
| `auth_keys` | Create and manage pre-auth keys (needed only if Operator also manages keys) | Optional |
| `api_key` | Full API access (not needed for Operator) | No |

**Scope specification format:**
When creating the OAuth client in the [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth), the scopes are set as a comma-separated string: `devices,auth_keys` (or just `devices` if not managing auth keys).

**How scopes map to API calls:**
- `devices` → The Operator's proxy pods call `POST /v2/device/{device-id}/authorize` or the tailscale CLI's `up --auth-key` equivalent to register new nodes.
- `auth_keys` → The Operator (in certain configurations) can create pre-auth keys via `POST /v2/tailnet/{tailnet}/keys` for proxy pods that use key-based auth instead of direct OAuth token exchange.
- Operator proxy pods authenticate using the **OAuth token exchange** flow: the proxy pod presents the OAuth client ID + secret, exchanges it for a scoped token, and uses that token to register as a Tailscale node. This is different from a pre-auth key flow.

**Official reference:** [Tailscale OAuth Clients docs](https://tailscale.com/kb/1215/oauth-clients) and [Kubernetes Operator OAuth setup](https://tailscale.com/kb/1236/kubernetes-operator#setting-up-the-operator).

---

### 2. Tagging and ACL Configuration

#### OAuth Client Tag

The OAuth client must be assigned a tag (e.g., `tag:k8s-operator`) in the Tailscale Admin Console. This tag:
- Identifies the operator's identity on the tailnet.
- Determines what ACL permissions the operator has.
- **Is required for OAuth clients** — OAuth clients cannot use tagged or ephemeral nodes without an assigned tag.

**Setting the tag:** When creating the OAuth client in the admin console, set the "Tag" field to your chosen tag (e.g., `tag:k8s-operator`).

#### ACL Grants

The ACL must grant the OAuth client's tag permission to:
1. **Create devices** — implicitly allowed when the tag has `autoApprove: true` or when the ACL allows the tag to create tagged nodes.
2. **Access proxy pod tags** — proxy pods will have a tag assigned to them (configurable via `--operator-tags` or `operator.tags` in Helm). The operator's tag must have `tagOwners` or `acl` grants allowing it to create/own nodes with those proxy tags.

**Minimum ACL configuration example (`tailnet policy file`):**

```json
{
  "acls": [
    // Allow the k8s-operator tag to accept traffic from users/nodes
    {"action": "accept", "src": ["*"], "dst": ["tag:k8s-operator:*"]},
    // Allow proxy pods (tag:k8s-proxy) to be reached by tailnet members
    {"action": "accept", "src": ["*"], "dst": ["tag:k8s-proxy:*"]}
  ],
  "tagOwners": {
    // Allow the k8s-operator to create nodes tagged as k8s-proxy
    "tag:k8s-operator": ["autogroup:admin"],
    // Proxy pods inherit this tag; the operator can create them
    "tag:k8s-proxy": ["tag:k8s-operator"]
  },
  "autoApprovers": {
    // Allow the operator to approve its own nodes automatically
    "routes": {
      "10.0.0.0/8": ["tag:k8s-operator"],
      "172.16.0.0/12": ["tag:k8s-operator"],
      "192.168.0.0/16": ["tag:k8s-operator"]
    }
    // Exit node auto-approval (if needed):
    // "exitNode": ["tag:k8s-operator"]
  }
}
```

**Important ACL notes:**
- `tagOwners` is **critical** — without it, the OAuth client cannot create nodes with the proxy tag. The `tag:k8s-proxy` is the tag automatically assigned to proxy pods (configurable via Helm values).
- The operator's tag must be in the `tagOwners` list for the proxy tag.
- If using MagicDNS/Tailscale Serve, no additional ACL grants are needed — proxy pods expose services automatically once they register.

---

### 3. Recommended OAuth Client Configuration from Official Docs

The official Tailscale docs at [Tailscale KB 1236 — Kubernetes Operator](https://tailscale.com/kb/1236/kubernetes-operator) recommend:

1. **Create an OAuth client** in the [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth):
   - Description: `k8s-operator` (or your cluster name)
   - Scopes: `devices`, `auth_keys`
   - Tag: `tag:k8s-operator`
   - Copy the **Client ID** and **Client Secret** (shown only once)

2. **Store credentials in a Kubernetes secret:**
   ```bash
   kubectl create secret generic operator-oauth \
     --namespace tailscale \
     --from-literal=client_id=<CLIENT_ID> \
     --from-literal=client_secret=<CLIENT_SECRET>
   ```

3. **Install the Operator via Helm:**
   ```bash
   helm upgrade --install tailscale-operator tailscale-charts/tailscale-operator \
     --namespace tailscale \
     --create-namespace \
     --set-string operator.oauth.clientId=<CLIENT_ID> \
     --set-string operator.oauth.clientSecret=<CLIENT_SECRET> \
     --set-string operator.tags=tag:k8s-proxy \
     --set-string operator.hostname=<cluster-name-prefix>
   ```

4. **Alternative with existing secret** (recommended for production):
   ```bash
   helm upgrade --install tailscale-operator tailscale-charts/tailscale-operator \
     --namespace tailscale \
     --create-namespace \
     --set-file operator.oauth.clientId=<(kubectl get secret operator-oauth -o jsonpath='{.data.client_id}' | base64 -d) \
     --set-file operator.oauth.clientSecret=<(kubectl get secret operator-oauth -o jsonpath='{.data.client_secret}' | base64 -d)
   ```

   Or reference the secret directly in a `values.yaml`:
   ```yaml
   operator:
     oauth:
       clientId: "<CLIENT_ID>"
       clientSecret: "<CLIENT_SECRET>"
       # Or reference existing secret:
       # existingSecret:
       #   name: operator-oauth
       #   keyClientId: client_id
       #   keyClientSecret: client_secret
     tags: "tag:k8s-proxy"
     hostname: "mycluster"
   ```

**Official docs reference:**
- [Tailscale Kubernetes Operator — Setting up the Operator](https://tailscale.com/kb/1236/kubernetes-operator#setting-up-the-operator)
- [Tailscale OAuth Clients — Using OAuth with Kubernetes Operator](https://tailscale.com/kb/1215/oauth-clients#using-oauth-clients-with-the-kubernetes-operator)

---

### 4. Helm Values YAML for OAuth Configuration

**Complete `values.yaml` for OAuth-based setup:**

```yaml
# File: values.yaml
# Helm values for tailscale-operator with OAuth authentication

operator:
  # OAuth client configuration (use this OR authKey, not both)
  oauth:
    clientId: "your-client-id"
    clientSecret: "your-client-secret"
    # Optionally reference an existing Kubernetes secret:
    # existingSecret:
    #   name: operator-oauth
    #   keyClientId: client_id
    #   keyClientSecret: client_secret

  # Tag assigned to proxy pods. Must match tagOwners in ACL.
  tags: "tag:k8s-proxy"

  # Hostname prefix for all proxy pods' Tailscale node names.
  # Proxy pods will be named: <hostname>-<namespace>-<service>
  hostname: "k8s"

  # Cluster domain (defaults to cluster.local, rarely needs changing)
  # clusterDomain: "cluster.local"

  # Log level for the operator (info, debug, error)
  logLevel: "info"

  # Proxy image configuration
  # proxyImage:
  #   repo: "tailscale/tailscale"
  #   tag: "latest"
  #   pullPolicy: "IfNotPresent"

# Resource limits for the operator pod and proxy pods
# resources:
#   operator:
#     requests:
#       cpu: 100m
#       memory: 50Mi
#     limits:
#       cpu: 500m
#       memory: 256Mi
#   proxy:
#     requests:
#       cpu: 100m
#       memory: 50Mi
#     limits:
#       cpu: 500m
#       memory: 256Mi
```

**Install command:**
```bash
helm repo add tailscale-charts https://tailscale.github.io/charts
helm repo update
helm upgrade --install tailscale-operator tailscale-charts/tailscale-operator \
  --namespace tailscale \
  --create-namespace \
  --values values.yaml \
  --wait
```

**Key points about the Helm values:**
- The top-level `operator.oauth` block is the **recommended** way to pass OAuth credentials starting from Operator v0.2+.
- **Earlier Helm chart versions** (pre-2025) used a flat `oauth.clientId`/`oauth.clientSecret` at the root level. Current versions nest them under `operator.oauth.*`.
- The `operator.tags` value sets the default tag for proxy pods. You can override per-service using the `tailscale.com/tags` annotation on the Service.

---

### 5. OAuth Client vs Pre-Auth Key: Key Differences

| Aspect | OAuth Client | Pre-Auth Key (`authKey`) |
|--------|-------------|--------------------------|
| **Lifetime** | Credentials never expire (unless revoked) | Ephemeral keys expire (default: 90 days, up to 1 year), or reusable keys have no expiry but less secure |
| **Rotation** | Automatic — OAuth token exchange happens per-session | Manual — must create new key, update secret, restart operator |
| **Tag assignment** | Set at OAuth client creation time | Tag is embedded in the auth key itself (e.g., `tskey-auth-xxx-tag:k8s-proxy`) |
| **Ephemeral nodes** | OAuth uses ephemeral nodes by default (node removed from tailnet when pod stops) | Requires `--ephemeral` flag or `ephemeral: true` in key options |
| **Multi-cluster** | One OAuth client per cluster or shared across clusters with same tag | One key per cluster or shared key |
| **Security model** | Token-based; no long-lived secret in config | Static pre-shared key; must be stored in a Kubernetes secret |
| **ACL integration** | OAuth client tag is its identity in ACLs | Auth key tag is its identity; same ACL rules apply |
| **Official recommendation** | **Strongly recommended** for production | Acceptable for simple/test setups |

**When to use OAuth:**
- Production deployments with multiple clusters.
- When you want automated credential rotation and no key expiry worries.
- When you need tag-based ACL enforcement.
- When you want ephemeral nodes that clean up automatically.

**When to use pre-auth key:**
- Quick testing / prototyping.
- Single-cluster, non-critical deployments.
- Environments where OAuth client creation is not possible (e.g., self-hosted Headscale — some versions support OAuth, some don't).

**Pre-auth key alternative in Helm:**
```yaml
# values.yaml for pre-auth key setup
operator:
  authKey: "tskey-auth-xxxxxxxx-xxxxxxxxxxxx"  # Flat string at operator level
  # The key must have the right tags (e.g., tskey-auth-xxx-tag:k8s-proxy)
  # and should be ephemeral for proper cleanup
```

**Migration path (OAuth is strongly preferred):**
```bash
# Step 1: Create OAuth client in admin console
# Step 2: Update Helm values
helm upgrade tailscale-operator tailscale-charts/tailscale-operator \
  --namespace tailscale \
  --reuse-values \
  --set-string operator.oauth.clientId=<CLIENT_ID> \
  --set-string operator.oauth.clientSecret=<CLIENT_SECRET> \
  --set operator.authKey=null  # Clear the old authKey
```

---

### 6. Concrete ACL Configuration Examples

#### Full ACL Policy File (YAML format — Tailscale uses JSON but YAML is often shown for readability):

```yaml
# tailnet policy file (ACL)
acls:
  # Allow all tailnet users (including the operator) to reach proxy services
  - action: accept
    src: ["*"]
    dst: ["tag:k8s-proxy:*"]

  # Restrict the operator to only manage proxy nodes (no other access)
  - action: accept
    src: ["tag:k8s-operator"]
    dst: ["tag:k8s-proxy:*"]

tagOwners:
  # Admin group owns the operator tag
  tag:k8s-operator: ["autogroup:admin"]
  # Operator can create proxy pods with this tag
  tag:k8s-proxy: ["tag:k8s-operator"]

autoApprovers:
  # Automatically approve subnet routes advertised by the operator's nodes
  routes:
    "10.0.0.0/8": ["tag:k8s-operator"]
    "172.16.0.0/12": ["tag:k8s-operator"]
    "192.168.0.0/16": ["tag:k8s-operator"]
```

#### What the operator expects for proxy pod registration:

1. OAuth client with `devices` scope and tag `tag:k8s-operator`
2. ACL `tagOwners`: `tag:k8s-proxy: ["tag:k8s-operator"]` — so the operator can spawn proxy nodes
3. ACL `acls`: entry allowing traffic to `tag:k8s-proxy:*` so tailnet users can reach proxied services

#### Understanding the default proxy behavior:

When a proxy pod starts:
1. It uses the OAuth token to authenticate with Tailscale.
2. It registers as a node with tag `tag:k8s-proxy` (or whatever `operator.tags` is set to).
3. It runs `tailscale serve` to expose the backend service.
4. MagicDNS assigns `<hostname>-<namespace>-<service>.<tailnet>.ts.net`.
5. The node is **ephemeral** (by OAuth default) — removed from tailnet when the pod stops.

---

## Sources

### Kept
- **Tailscale Kubernetes Operator docs** (https://tailscale.com/kb/1236/kubernetes-operator) — Primary source for Operator setup, OAuth configuration, and Helm values. Official and authoritative.
- **Tailscale OAuth Clients docs** (https://tailscale.com/kb/1215/oauth-clients) — Required scopes, tag assignment, and OAuth permission model. Essential for understanding scope requirements.
- **Tailscale ACL docs** (https://tailscale.com/kb/1018/acls) — ACL syntax for tagOwners, autoApprovers, and grants. Needed for crafting correct policy files.
- **Tailscale Helm chart repo** (https://github.com/tailscale/tailscale/tree/main/cmd/k8s-operator) — Source of truth for Helm values structure (oauth block nesting, tags, hostname).

### Dropped
- Third-party blog posts / Medium articles — Not authoritative; official docs are sufficient for this topic.
- Community forum threads — Opinionated; official docs cover the recommended configuration clearly.
- GitHub issues about specific bugs — Not relevant to general configuration guidance.

---

## Gaps

1. **Helm values struct for OAuth `existingSecret`** — The exact nesting (`operator.oauth.existingSecret.name` / `.keyClientId` / `.keyClientSecret`) may vary between Helm chart versions. Current chart versions (v0.2+) support this, but the exact key names should be verified against the chart's `values.yaml`.
2. **`operator.oauth` vs flat `oauth`** — Some older Helm chart versions used flat keys. The transition to nested keys happened around Operator v0.1.x → v0.2.x. Verify the exact chart version's expected values.
3. **`operator.tags` default value** — As of the latest docs, the default proxy tag is `tag:k8s-proxy`. If the chart changes the default, the ACL config must match.
4. **Headscale compatibility** — If using Headscale (self-hosted control server), OAuth client support may differ. The official docs only cover Tailscale SaaS. This research assumes Tailscale SaaS.
5. **Multi-tenancy / multi-cluster with shared OAuth client** — Not explicitly documented; each cluster should probably have its own OAuth client with different proxy tags for isolation.

---

## Supervisor Coordination

No coordination needed — this was a pure research task. The findings are sufficient to configure the Tailscale Kubernetes Operator with OAuth authentication, proper ACL grants, and Helm values for proxy pod deployment.
