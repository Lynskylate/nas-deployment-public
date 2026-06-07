# [Optimization] K3s 部署拓扑重构与 CI 并行化 + 幂等性

## Summary

对 K3s 集群部署进行三项优化：

1. **控制面迁移** — 将 K3s server 从 GTR 迁移到 aliyun，降低 GTR 资源压力
2. **CI 解耦拆分** — 拆分 server/agent 为独立 job，server 与 edge 并行部署
3. **安装幂等性** — 已健康运行的节点跳过重装，仅渲染配置

## Problem

### 控制面负载

GTR 作为家庭服务器，同时运行 mihomo / grafana / victoriametrics / victorialogs / victoriatraces / envoy / node_exporter 共 7+ 个服务。再承担 K3s 控制面（etcd/kube-apiserver/controller-manager/scheduler）会造成：

- CPU/内存争抢，集群 API 响应延迟
- GTR 重启/维护时整个集群不可用
- 没有资源预留机制

aliyun 是云 VM，资源独立且更稳定，更适合作为控制面。

### CI 串行瓶颈

旧 workflow 依赖链：

```
deploy-gtr → deploy-edge → deploy-k3s-platform(server+agent) → deploy-tunnel
```

问题是 `deploy-edge`（部署 aliyun/tencent/remote_proxy 的 envoy/vector）与 K3s server 部署完全无关，但被强制串行等待。K3s server 只需 deploy-gtr 完成即可开始。

### 无幂等保护

旧逻辑仅检查二进制文件是否存在：

```yaml
when: not k3s_server_binary.stat.exists or not k3s_server_service.stat.exists
```

每次 CI 触发都会无条件执行 `get.k3s.io` 安装脚本，即使集群已健康运行。

## Solution

### 1. 拓扑变更

| 角色 | 旧 | 新 |
|------|----|----|
| Server（控制面）| GTR (`100.121.0.67`) | **aliyun** (`100.102.140.59`) |
| Agent | aliyun, tencent | **GTR**, tencent |

**涉及文件：**

| 文件 | 变更 |
|------|------|
| `edge/ansible/group_vars/all/public.yml` | `k3s_server_url: https://100.102.140.59:6443` |
| `edge/ansible/host_vars/gtr/public.yml` | 移除 `k3s_server_tailscale_ip` / `k3s_server_tls_sans` |
| `edge/ansible/host_vars/aliyun.yml` | 新增 `k3s_server_tailscale_ip: 100.102.140.59` + TLS SANs |
| `edge/ansible/deploy-gtr-k3s-server.yml` | `hosts: edge_aliyun` |
| `edge/ansible/deploy-gtr-k3s-agent.yml` | `hosts: gtr_core:edge_tencent` |
| `edge/ansible/verify-gtr-k3s-server.yml` | `hosts: edge_aliyun` |
| `edge/ansible/verify-gtr-k3s-agent.yml` | `hosts: gtr_core:edge_tencent` |

### 2. CI 并行化

将单一 `deploy-k3s-platform` job 拆为两个独立 job，优化依赖链：

```
旧链（串行）：
  deploy-gtr (12min)
    → deploy-edge (13min)
      → deploy-k3s-platform (server+agent, ~15min)
        → deploy-tunnel

新链（server 与 edge 并行）：
  deploy-gtr (12min)
    ├→ deploy-k3s-server (~5min) ──┐
    └→ deploy-edge (13min) ────────┤→ deploy-k3s-agent (~5min) → deploy-tunnel
```

**涉及文件：**
- `.github/workflows/deploy-infra.yml` — 替换 `deploy-k3s-platform` 为 `deploy-k3s-server` + `deploy-k3s-agent`
- `.github/workflows/validate-pr.yml` — 新增 4 个 playbook 的 syntax-check

### 3. 安装幂等性

在 server 和 agent role 的 `tasks/main.yml` 中增加健康检查步骤：

**Server 判断逻辑：**

```
Check K3s server runtime health:
  ├─ systemctl is-active k3s?  → NO  → needs_install=true
  ├─ k3s kubectl get nodes?    → NO  → needs_install=true (degraded)
  └─ 全部通过                   → healthy → needs_install=false (跳过安装)
```

**Agent 判断逻辑：**

```
Check K3s agent runtime health:
  ├─ systemctl is-active k3s-agent? → NO → needs_install=true
  └─ active                          → healthy → needs_install=false (跳过安装)
```

二次部署时：已健康的节点跳过 `get.k3s.io` 下载安装，仅执行配置模板渲染（模板幂等，仅在变化时触发 restart handler）。

**涉及文件：**
- `edge/ansible/roles/k3s-server/tasks/main.yml`
- `edge/ansible/roles/k3s-agent/tasks/main.yml`

## Files Changed

```
.github/workflows/deploy-infra.yml          # split deploy-k3s-platform → server + agent jobs
.github/workflows/validate-pr.yml           # add 4 new playbook syntax checks
edge/ansible/group_vars/all/public.yml      # k3s_server_url → aliyun IP
edge/ansible/host_vars/gtr/public.yml       # remove server vars
edge/ansible/host_vars/aliyun.yml           # add server vars
edge/ansible/deploy-gtr-k3s-server.yml      # NEW: server-only playbook (hosts: edge_aliyun)
edge/ansible/deploy-gtr-k3s-agent.yml       # NEW: agent-only playbook (hosts: gtr_core:edge_tencent)
edge/ansible/verify-gtr-k3s-server.yml      # NEW: server verify (hosts: edge_aliyun)
edge/ansible/verify-gtr-k3s-agent.yml       # NEW: agent verify (hosts: gtr_core:edge_tencent)
edge/ansible/roles/k3s-server/tasks/main.yml # add health check + needs_install logic
edge/ansible/roles/k3s-agent/tasks/main.yml  # add health check + needs_install logic
k3s/README.md                                # update topology & deployment docs
```

## Verification

```bash
# All 4 new playbooks pass syntax check
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml --syntax-check  # OK
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml --syntax-check   # OK
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-server.yml --syntax-check  # OK
ansible-playbook -i inventory-edge.ini verify-gtr-k3s-agent.yml --syntax-check   # OK

# Both workflow YAML files parse correctly
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-infra.yml'))"  # OK
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/validate-pr.yml'))"   # OK
```

## Out Of Scope

- 历史 GTR server 数据的清理/迁移（若 GTR 上已有 etcd 数据）
- etcd 自动快照备份
- K3s metrics 接入 VictoriaMetrics
- GTR 上 k3s-agent 的安装（需在 deploy-gtr job 中协调，当前 k3s-agent 由 deploy-k3s-agent job 部署）

## PR Linking

- Suggested PR title: `feat: migrate k3s server to aliyun, parallelize CI, add idempotency`
- GitHub issue: `#6`
- PR body should include: `Closes #6`
- Planning doc path: `docs/issues/006-k3s-deploy-optimization.md`
