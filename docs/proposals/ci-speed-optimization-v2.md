# CI 部署速度优化方案 v2

> 基于 `a995a6a` (#27096211345) 的实测分析 | 2026-06-07

## 当前基线

```
总耗时: 17m25s  (全部通过 ✅)
关键路径: preflight(1m7s) → k3s-server(2m49s) → k3s-agent(11m24s) → platform-operators(1m50s) = 17m10s
并行: deploy-gtr(7m59s)  deploy-edge/tencent(9m25s)  deploy-edge/aliyun(3m17s)  deploy-edge/remote_proxy(1m31s)
```

## v1 已完成优化（a995a6a）

| 优化 | 效果 | 生效位置 |
|------|------|---------|
| `gather_facts: false` (8个playbook) | 每playbook ~5-15s | platform deploy/verify, mihomo/deploy, resource-manifest |
| kubeseal `--fetch-cert` 替代 port-forward+curl | 消除 sleep 4 + 端口竞争 | sealed-secrets deploy |
| Tailscale exitnode 条件重启 | 省去不必要的 systemd restart | deploy-gtr |
| ArgoCD CLI 下载删除 | 死代码消除 | argocd role |

**v1 总节省估计**: ~30-50s（主要在 platform-operators），对关键路径影响有限。

---

## 发现的问题

### P0: 最长 job (deploy-k3s-agent) 未被优化

| 指标 | 值 |
|------|-----|
| 耗时 | **11m24s**（占关键路径 66%） |
| Gathering Facts (GTR) | **~40s** (15:10:21 → 15:11:00) |
| `gather_facts` | ❌ 未设置 |

**根本原因**: `deploy-gtr-k3s-agent.yml` 没有 `gather_facts: false`。GTR 节点有大量磁盘/网卡/CPU，facts 采集耗时 40s。

**验证**: 所有 role 中均无 `ansible_*` facts 引用，加 `gather_facts: false` 安全。

### P1: 其他热路径 playbook 也未优化

| Playbook | 所在 job | 预估节省 |
|----------|---------|---------|
| `deploy-gtr-k3s-agent.yml` | k3s-agent | **~40s**（GTR facts） |
| `verify-gtr-k3s-agent.yml` | k3s-agent | ~5s（SSH 复用后较小） |
| `deploy-gtr-k3s-server.yml` | k3s-server | ~5s |
| `verify-gtr-k3s-server.yml` | k3s-server | ~5s |
| `deploy-edge.yml` | deploy-edge | ~9s（tencent facts） |
| `verify-edge-common.yml` | deploy-edge | ~3s |

### P2: k3s-agent playbook 中 task 串行瓶颈

`deploy-gtr-k3s-agent.yml` 在 GTR 和 tencent 两个节点上**串行**执行所有 task：
- GTR: 本地连接快（~10ms）
- tencent: Tailscale 跨洋 ~200ms 延迟，每个 task 多 ~400ms RTT

**观察**: 
- k3s-prereq 中 `Persist required kernel modules` 耗时 ~66s (15:11:17 → 15:12:24)
- k3s-agent 中 `Ensure K3s agent is enabled and started` 耗时 ~22s (15:16:00 → 15:16:23)
- Verify K3s agents 步骤又单独耗时

### P3: deploy-edge tencent 跨洋延迟

tencent edge 耗时 9m25s（对比 aliyun 3m17s、remote_proxy 1m31s）:
- 部分延迟来自 Tailscale 连接（跨洋 ~200ms）
- 下载 node_exporter / vector 二进制可能走 GitHub 直连（未经代理加速）

---

## 优化方案

### Phase 1: `gather_facts: false` 全覆盖（低风险，预计省 ~60s）

```yaml
# 对以下 playbook 加 gather_facts: false
deploy-gtr-k3s-agent.yml     # 省 ~40s (GTR facts 是大头)
verify-gtr-k3s-agent.yml     # 省 ~5s
deploy-gtr-k3s-server.yml    # 省 ~5s
verify-gtr-k3s-server.yml    # 省 ~5s
deploy-edge.yml              # 省 ~9s (tencent facts)
verify-edge-common.yml       # 省 ~3s
```

**风险评估**: 与 v1 一致 — 所有 role 都不依赖 ansible_facts，改动安全。

### Phase 2: ansible 并行执行优化（中风险，预计省 ~30s）

将 k3s-agent playbook 中对 GTR 和 tencent 的独立 task 用 `free` strategy 或 `async` 并行化:

```yaml
# 方案 A: 使用 free strategy（对两个节点独立 task 并行）
- name: Install K3s prerequisite packages (parallel)
  ansible.builtin.apt:
    name: "{{ k3s_packages }}"
    state: present
  strategy: free  # 但 playbook-level strategy 无法 per-task

# 方案 B: 用 async + poll 对长时间 task
- name: Persist required kernel modules
  ansible.builtin.copy:
    ...
  async: 60
  poll: 0
  register: kernel_modules_job

# ... 其他 task ...

- name: Wait for kernel modules job
  ansible.builtin.async_status:
    jid: "{{ kernel_modules_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 30
  delay: 2
```

**主要候选 task**:
- `Persist required kernel modules` (~66s)
- `Ensure K3s agent is enabled and started` (~22s)
- 节点间不依赖的 k3s-prereq task（apt install, kernel module load）

### Phase 3: 预缓存二进制下载（中风险，预计省 20-60s）

为跨洋节点（tencent、remote_proxy）预缓存大文件：

```yaml
# 方案: 在 aliyun 部署时，同时将二进制上传到 GTR 的 HTTP cache
- name: Stage binaries on GTR http cache
  ansible.builtin.copy:
    src: "{{ cached_binary }}"
    dest: "/var/cache/ansible-binaries/{{ cached_binary | basename }}"
  delegate_to: gtr

# edge 节点从 GTR 下载（Tailscale 内网，快于 GitHub）
- name: Download from GTR cache
  ansible.builtin.get_url:
    url: "http://gtr:8081/cache/{{ binary_name }}"
    dest: "/usr/local/bin/{{ binary_name }}"
```

**受益 task**:
- node_exporter 下载（~11s on tencent）
- vector 下载
- kubeseal 下载

### Phase 4: 并行化 Edge 部署（低风险，CI 层面）

当前 deploy-edge 使用 matrix strategy，三个 target（aliyun, tencent, remote_proxy）已经并行。无进一步优化空间。

### Phase 5: K3s agent deploy + verify 合并（低风险）

当前 deploy-k3s-agent 和 verify-k3s-agent 是两个独立 playbook。可以合并为一个 playbook，省去一次 SSH 建连开销：

```yaml
# deploy-gtr-k3s-agent.yml 中在 roles 后增加 post_tasks
- name: Deploy K3s agents on GTR and tencent
  hosts: gtr_core:edge_tencent
  become: true
  gather_facts: false

  roles:
    - role: k3s-prereq
    - role: k3s-agent
    - role: tailscale-p2p-heal

  post_tasks:
    - name: Verify K3s agent joined
      ansible.builtin.shell: |
        k3s kubectl get nodes -o wide 2>/dev/null || true
      changed_when: false
      delegate_to: aliyun
      run_once: true
    # ... 其他 verify tasks
```

---

## 预期效果汇总

| Phase | 优化内容 | 风险 | 预期节省 | 关键路径节省 |
|-------|---------|------|---------|-------------|
| 1 | `gather_facts: false` 全覆盖 | 🟢 低 | ~60s | **~55s** |
| 2 | ansible async 并行 | 🟡 中 | ~30s | **~30s** |
| 3 | 二进制预缓存 | 🟡 中 | ~20-60s | ~10s |
| 5 | deploy+verify 合并 | 🟢 低 | ~10s | **~10s** |
| **合计** | | | **~120-160s** | **~105s** |

**目标**: 关键路径从 17m10s → ~15m30s（节省 ~10%）

---

## 不建议的优化

1. **减少 rollout timeout** — 120s 是 K3s/ArgoCD 稳定启动所需，缩短会导致 CI 不稳定
2. **跳过 verify steps** — 收益太小（总 verify ~30s），但失去安全保障不值得
3. **并行化 K3s server + agent** — agent 依赖 server 的 token，有竞态风险

---

## 讨论要点

### 需要 reviewer 确认的决策:

1. **Phase 1 是否立即执行？** 低风险高收益，建议直接 PR
2. **Phase 2 async 并行化是否值得？** 增加 playbook 复杂度，换 ~30s，需评估维护成本
3. **Phase 3 二进制缓存架构？** GTR HTTP cache server 是否需要新增，还是复用现有 Envoy/nginx
4. **Phase 5 deploy+verify 合并是否破坏关注点分离？** 当前 deploy/verify 分离有利于故障定位

### 需要补充的 evidence:

- [ ] k3s-agent playbook 中各 task 的精确耗时（需要 `ANSIBLE_CALLBACK_PROFILE_TASKS` 输出）
- [ ] tencent 下载二进制走 GitHub 直连 vs 经代理的实际耗时对比
- [ ] `free` strategy 在 k3s-prereq + k3s-agent 中的兼容性测试（是否有 role 间 task 依赖）
