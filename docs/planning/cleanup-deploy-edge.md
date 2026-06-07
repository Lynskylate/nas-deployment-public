# Cleanup Plan: deploy-edge.yml 精简

## 背景

在 PR #3（`cleanup/remove-obsolete-install-steps`）合并后，`shadowsocks-shadowtls/` 遗留目录已被删除，5 个仍被引用的 role 已迁移到 `edge/ansible/roles/`，`ansible.cfg` 的 `roles_path` 已简化为 `./roles`。

但 `deploy-edge.yml` 本身仍有几个可精简的一次性 cleanup pre_task 和众多无用变量。

**假设**：所有一次性 cleanup（旧代理清理、旧 tunnel server 清理）已在对应主机上完成，marker 文件已存在。本计划不再保留这些操作的执行入口。

## 目标

在 PR #3 的基础上，对 `deploy-edge.yml` 及其周边变量做"瘦身"清理，移除所有不再需要的 deployment steps 和变量。

## 改动清单

### 1. `deploy-edge.yml` — pre_tasks 段精简

删除两个一次性 cleanup pre_task，保留 apt 镜像切换（仍有实际作用）。

**改动 (3 处)**：

```yaml
# 1. 删除 cleanup-aliyun-legacy-proxy pre_task
# 原代码：
- name: Run legacy proxy cleanup on aliyun only
  ansible.builtin.include_role:
    name: cleanup-aliyun-legacy-proxy
  when: cleanup_legacy_proxy | bool

# 2. 删除 cleanup-edge-tunnel-server pre_task
# 原代码：
- name: Cleanup tunnel server components on non-tunnel edge nodes
  ansible.builtin.include_role:
    name: cleanup-edge-tunnel-server
  when: not (edge_tunnel_server_enabled | bool)

# 3. 删除 post_task debug 中 legacy cleanup 行
# 原代码：
- "Legacy cleanup applied: {{ cleanup_legacy_proxy | bool }}"
```

**保留**的 pre_task：
- `Switch apt to Aliyun mirror` — 对 aliyun/tencent 的包安装速度有意义，幂等（`creates` 保护）

### 2. `group_vars/all/public.yml` — 清理无用变量

#### 删除的变量（10 个）

**Legacy cleanup 相关 (4 个)**：
- `cleanup_legacy_proxy`
- `legacy_proxy_cleanup_marker`
- `legacy_proxy_services`
- `legacy_proxy_paths`

**Shadowsocks/Shadow-TLS Client 相关 (5 个)**：
- `shadowsocks_client_port`
- `shadowsocks_client_local_address`
- `shadowtls_client_listen_port`
- `ss_client_bin_path`
- `stls_client_bin_path`

这些变量只被 `shadowsocks-client` / `shadowtls-client` role 引用，这两个 role 当前没有任何 active playbook 使用。保留它们会误导维护者以为这些角色在活跃部署中。

**`remote_server_ip`**：
- 原标记为"保留"，但经核实仅被 `shadowtls-client/templates/shadow-tls-client.service.j2` 引用（非活跃 role）。无其他 playbook 或模板使用。
- → **改为删除**

> **说明**：`shadowsocks-client` / `shadowtls-client` role 仍保留在 `edge/ansible/roles/` 中（PR #3 已迁移），如果未来需要重新启用，需补充对应的变量定义。

#### 保留的变量（理由）

| 变量 | 使用方 |
|------|--------|
| `shadowsocks_version`, `shadowsocks_download_url` | `shadowsocks-server` role（被 `deploy-edge-tunnel-server.yml` 使用） |
| `shadowtls_version`, `shadowtls_download_url` | `shadowtls-server` role（同上） |
| `shadowsocks_method`, `shadowsocks_timeout` | `shadowsocks-server` role |
| `shadowsocks_server_port` | `shadowsocks-server` role + `shadowtls-server` role + `verify-edge-common.yml` + `verify-edge-tunnel-server.yml` + `deploy-edge-tunnel-server.yml` |
| `shadowtls_tls_port` | `shadowtls-server` role + `deploy-edge-tunnel-server.yml` + `verify-edge-tunnel-server.yml` |
| `shadowtls_sni_server`, `shadowtls_sni_port` | `shadowtls-server` role + `verify-edge-tunnel-server.yml` |
| `shadowtls_server_listen_port` | `cds.yaml.j2` + `deploy-edge-tunnel-server.yml` + `verify-edge-common.yml` + `verify-edge-tunnel-server.yml` |
| `ss_server_bin_path`, `stls_server_bin_path` | `shadowsocks-server` / `shadowtls-server` roles |

### 3. `host_vars/` — 清理 `cleanup_legacy_proxy` 变量

- `host_vars/aliyun/public.yml`：删除 `cleanup_legacy_proxy: true`
- `host_vars/remote_proxy.yml`：删除 `cleanup_legacy_proxy: false`
- `host_vars/tencent.yml`：删除 `cleanup_legacy_proxy: false`

### 4. 删除整个 role 目录

- `edge/ansible/roles/cleanup-aliyun-legacy-proxy/` — 一次性 cleanup role，已完成使命
- `edge/ansible/roles/cleanup-edge-tunnel-server/` — 同上

### 5. 删除独立 verify playbook

- `edge/ansible/verify-aliyun-cleanup.yml` — 已有 marker 证明 cleanup 完成，不再需要验证

### 6. 移除 `edge-ca-issuer` / `edge-ca-trust` roles 及相关文件

当前两个 role 条件为 `edge_ca_issue_enabled: false` 和 `edge_ca_trust_enabled: false`，永远被跳过。删除后减轻 playbook 解析和 reader 认知负担。

**改动清单**：

从 `deploy-edge.yml` 的 `roles:` 段移除两行。

从 `group_vars/all/public.yml` 删除变量：
- `edge_ca_issue_enabled`
- `edge_ca_trust_enabled`
- `edge_ca_local_issued_dir`
- `edge_ca_trust_target_path`
- `envoy_tls_certificates`（仅被 CA role 和 verify-ca-trust.yml 引用）

删除对应的 role 目录：
- `edge/ansible/roles/edge-ca-issuer/`
- `edge/ansible/roles/edge-ca-trust/`

删除依赖的 verify playbook：
- `edge/ansible/verify-ca-trust.yml`

### 7. `verify-edge-common.yml` — 修复 forbidden proxy ports 硬编码

**当前问题**：`edge_forbidden_proxy_ports` 变量定义了 `[1080, 7890, 8888]`，但 verify 脚本中硬编码了端口号。

**改动**：将 for 循环改为引用变量：

```yaml
# 当前（硬编码）：
for fport in 1080 7890 8888; do
# 改为（引用变量）：
for fport in {{ edge_forbidden_proxy_ports | join(' ') }}; do
```

### 8. 更新文档

- `edge/README.md`：移除对 `verify-aliyun-cleanup.yml`（第20、32行）和 `verify-ca-trust.yml`（第22行）的引用，更新"aliyun 执行历史代理清理"的描述文字

---

## 不动的内容（确认保留）

| 内容 | 理由 |
|------|------|
| `shadowsocks-server` / `shadowtls-server` roles | 被 `deploy-edge-tunnel-server.yml`（remote_proxy）使用 |
| `shadowsocks-server` / `shadowtls-server` 相关变量 | 被 active 的 tunnel server playbook、verify playbook 和 CDS 模板引用 |
| `shadowsocks-client` / `shadowtls-client` roles（仅目录保留） | PR #3 已迁移，被 `verify-gtr-no-regression.yml` 引用检查，未来可能用于 GTR tunnel client。删除变量后需重新部署时需补充变量定义 |
| `edge_tunnel_server_enabled` | 被 `verify-edge-common.yml` 用于条件检测 tunnel server 状态 |
| `envoy_tls_certificates` 外的 TLS 变量（`envoy_tls_cert_dir`） | 在 LDS 模板中引用，为未来 TLS 配置保留扩展点 |
| `deploy-edge.yml` 中的 apt 镜像切换 pre_task | 对 aliyun/tencent 的包安装速度有实际意义 |
| `deploy-edge.yml` 中的 post_tasks 段（除 legacy cleanup debug 行） | 确保 services 运行 + 打印摘要 |

## 验证

每个改动执行后需要：

1. **Ansible syntax check**：`ansible-playbook -i inventory-edge.ini deploy-edge.yml --syntax-check`
2. **存量 playbook syntax check**：`ansible-playbook -i inventory-edge.ini deploy-edge-tunnel-server.yml --syntax-check`
3. **PR 验证 CI**：确认 `validate-pr.yml` 中所有 syntax check 通过
4. **变量引用检查**：用 `grep -r` 确认被删变量没有在其他活跃 playbook/template 中被引用
5. **README 一致性检查**：确认 `edge/README.md` 中所有引用的 playbook 文件都存在

## 执行顺序建议（可选）

本计划可拆分为 3 个独立 PR 以降低风险：

| PR | 内容 | 风险 |
|----|------|------|
| **PR-A** | 第 1-5 节（删除 cleanup role、verify、无用变量） | 低 — 纯删除，无行为变更 |
| **PR-B** | 第 6 节（删除 CA role、verify-ca-trust.yml） | 低 — 死代码清理 |
| **PR-C** | 第 7-8 节（修复 verify 硬编码 + README 更新） | 最低 — 仅重构 |
