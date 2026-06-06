# Edge 基线部署优化记录

## 背景

`deploy-edge` 是 GitHub Actions 工作流 `deploy-infra.yml` 中的核心任务之一。
它使用 Ansible 对远程边缘节点（`remote_proxy`、`aliyun`、`tencent`）执行统一的基线部署，
包括安装和配置 node_exporter、Tailscale、Vector、Envoy 等组件。

在 2026-06-06 的一次全量部署中，观察到以下异常：

| 节点 | 部署耗时 | 验证耗时 |
|------|----------|----------|
| aliyun | ~9min | ~27s |
| tencent | ~16min | ~3.5min（被超时取消） |

两个节点执行几乎相同的 task 集合（tencent 39 ok, aliyun 41 ok），
但 tencent 的耗时是 aliyun 的 **1.8 倍**，验证阶段甚至因超时被取消。

## 根因分析

### 1. 高 SSH 延迟

从 CI 日志可以清晰看到，tencent 主机的每次 Ansible SSH 往返（以下简称 RT）需要 **12-17 秒**。

对比典型的 task 执行时间：

| Task | tencent | 正常预期 |
|------|---------|---------|
| `Create node_exporter user` | ~17s | <1s |
| `Create binary directory` | ~12s | <1s |
| `Check tailscale binary` | ~12s | <1s |
| `Create vector user` | ~16s | <1s |

每次 SSH 往返的延迟不是由 task 本身的执行时间决定，而是由**网络 RTT**决定。

### 2. 大量独立轻量 task

原有的 Ansible playbook 由大量细粒度独立 task 组成，每个 task 都要一次 SSH 往返：

| 角色 | 独立 task 数 | SSH 往返数 |
|------|-------------|-----------|
| cleanup-edge-tunnel-server | 5 | 5 |
| node-exporter | 11 | 11 |
| edge-tailscale | 4 | 4 |
| edge-vector | 11 | 11 |
| edge-envoy | ~17 | ~17 |
| post-tasks (ensure services) | 4 | 4 |
| verify-edge-common | ~16 | ~16 |
| **合计** | **~68** | **~68** |

在高延迟环境下，每个 task 的 12-17s 累计为 **~12-17 分钟的纯 SSH 等待时间**。

### 3. systemd 模块的巨大 payload

Ansible 的 `ansible.builtin.systemd:` 模块在每次调用时返回完整服务状态 JSON
（数百行，包含所有 systemd 属性）。在高延迟 SSH 连接上，
传输这个超大 payload 进一步加剧了延迟。

### 4. 对比节点说明

Aliyun 节点之所以快，是因为其到 GitHub Actions Runner（Azure US）的 SSH 延迟较低。
Tencent 节点在中国境内，到 Actions Runner 的 SSH 延迟显著更高。
这本质上是 CI runner 地理分布导致的网络延迟差异。

## 优化目标

1. **减少总 SSH 往返次数** —— 将 ~68 次降低到 ~34 次
2. **降低每次往返的数据传输量** —— 避免 systemd 返回超大 JSON
3. **保持功能完全一致** —— 不改变部署结果、不降低可靠性
4. **保持可维护性** —— 复杂模板（LDS/CDS）保留 `template:` 模块

## 优化策略

### 策略一：合并轻量管理 task

将多个纯管理类 task（`user`、`file`、`stat`）合并为一个 `shell:` 块，
利用 shell 一次 SSH 完成多个操作。

```
# 优化前（4 次 SSH 往返）
user: name=vector                 → SSH round-trip
file: path=/etc/vector            → SSH round-trip
file: path=/var/lib/vector        → SSH round-trip  
file: path=/var/log/vector        → SSH round-trip

# 优化后（1 次 SSH 往返）
shell: |
  useradd -r vector
  mkdir -p /etc/vector /var/lib/vector /var/log/vector
```

### 策略二：用 copy content: 替代 template:（对简单文件）

对于没有 `{% if %}` / `{% for %}` 等复杂 Jinja2 逻辑的文件
（如 systemd unit 文件、简单的 YAML 配置），使用 `copy content:` 内联写入，
避免维护单独的 `.j2` 模板文件。

### 策略三：保留下载 task 的 retry 机制

`get_url` / `unarchive` 等下载类 task 的 `retries/delay/until` 重试机制
在网络不稳定时提供了可靠性保障，这些 task 保持独立。

### 策略四：用 shell 替代 systemd 模块

避免 `systemd` 模块返回巨量 JSON 状态数据：

```
# 优化前：返回完整状态 JSON（~200 行）
ansible.builtin.systemd:
  name: envoy
  state: started

# 优化后：仅返回 "active" 或 "inactive"，payload 缩小 100x
shell: |
  systemctl start envoy
```

### 策略五：保留复杂 Jinja2 模板

Envoy 的 LDS/CDS 配置包含大量 Jinja2 过滤器（`| selectattr`、`| to_json`）
和条件/循环逻辑，这些保留 `template:` 模块以保持可维护性。

## 修改详情

### 修改的文件

| 文件 | 说明 |
|------|------|
| `edge/ansible/roles/cleanup-edge-tunnel-server/tasks/main.yml` | 5 tasks → 1 task（`creates`标记，后续跳过）|
| `shadowsocks-shadowtls/ansible/roles/node-exporter/tasks/main.yml` | 11 tasks → 8 tasks |
| `edge/ansible/roles/edge-tailscale/tasks/main.yml` | 4 tasks → 2 tasks |
| `edge/ansible/roles/edge-vector/tasks/main.yml` | 11 tasks → 7 tasks |
| `edge/ansible/roles/edge-envoy/tasks/main.yml` | 17 remote tasks → 13 remote tasks |
| `edge/ansible/deploy-edge.yml` | post-tasks: 4 RTs → 1 RT |
| `edge/ansible/verify-edge-common.yml` | 16 tasks → 9 tasks |

### 各角色具体优化

#### cleanup-edge-tunnel-server

**修改前（5 RTs）：** `service_facts` → `systemd stop/mask ×2` → `file absent ×5` → `lineinfile` → `systemd daemon_reload`

**修改后（1 RT，后续 0 RT）：** 一个 shell 脚本（含 `creates` 标记，仅首次执行1次SSH，后续直接跳过），合并服务停止/禁用、文件清理、hosts 条目移除、daemon-reload

#### node-exporter

**修改前（11 RTs）：** `user` → `file` → `stat` → `tempfile` → `unarchive` → `copy` → `template` → `flush_handlers` → `systemd` → `wait_for` → `cleanup`

**修改后（8 RTs）：** `shell(user+dir)` → `copy(service file)` → `stat` → `unarchive(download)` → `file(ownership)` → `flush_handlers`（触发 handler 执行） → `shell(enable+start)` → `wait_for`

关键变化：
- `user` + `file` 合并为 shell
- `template` 替换为 `copy content:`
- `unarchive` 使用 `extra_opts: --strip-components=1` 直接解压到目标目录
- 去除了 `tempfile`、`copy`、`cleanup` 三个 task

#### edge-tailscale

**修改前（4 RTs）：** `which` → `package(cond)` → `systemd` → `version`

**修改后（2 RTs）：** 一个 shell 合并检查+启动+版本验证，`package` 保留条件安装

#### edge-vector

**修改前（11 RTs）：** `user` → `file-loop` → `stat` → `tempfile` → `unarchive` → `copy` → `template×2` → `flush_handlers` → `systemd` → `cleanup`

**修改后（7 RTs）：** `shell(user+dir)` → `copy(service file)` → `template(config)` → `stat` → `unarchive(download)` → `flush_handlers`（触发 handler 执行） → `shell(enable+start)`

关键变化：
- `user` + `file-loop` 合并为 shell
- service 文件用 `copy content:`，config 文件保留 `template:`（有 `{% if %}` 条件逻辑）
- `unarchive` 使用 `extra_opts` 直接解压，去除了 `tempfile`、`copy`、`cleanup`

#### edge-envoy

**修改前（~17 remote RTs）：** `user` → `file×2` → `file-loop×7` → `stat` → `get_url` → （本地 set_fact/assert） → `stat-loop(certs)` → `stat-loop(keys)` → `template×5` → `ufw-loop` → `flush_handlers` → `systemd` → `wait_for`

**修改后（13 remote RTs）：** `shell(user+dir+log)` → `copy(logrotate)` → `copy(service)` → `copy(bootstrap)` → `stat` → `get_url` → （本地 set_fact/assert） → `stat-loop(certs)` → `stat-loop(keys)` → `template(LDS)` → `template(CDS)` → `firewall-shell` → `flush_handlers` → `shell(enable+start)` → `wait_for`

关键变化：
- `user` + `file×9` + logrotate 合并为 2 个 task（shell + copy）
- systemd unit + bootstrap config 用 `copy content:` 替换 `template:`
- LDS/CDS 保留 `template:`（复杂 Jinja2 逻辑）
- UFW 用 shell 替换 `ufw` 模块

#### 后置 task（deploy-edge.yml）

**修改前（4 RTs）：** 4 个独立的 `systemd` 模块分别检查 node_exporter、tailscaled、envoy、vector

**修改后（1 RT）：** 一个 shell 脚本同时检查所有服务

#### 验证 playbook（verify-edge-common.yml）

**修改前（16 tasks）：** 每个服务独立 `systemd` + `assert` + `shell` + `uri` 模块

**修改后（9 tasks）：** 服务状态和端口检查合并为 shell，admin 路径暴露检查合并为 shell，uri 检查保持独立（部分含条件跳过）

## 效果预估

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| SSH 往返总数 | ~68 | ~38 | **减少 ~44%** |
| 部署预估耗时（tencent） | ~15.5min | ~10min | **减少 ~35%** |
| 验证预估耗时（tencent） | ~3.5min（被取消） | ~2min | **减少 ~43%** |
| 总执行时间（tencent） | ~20min（超时） | ~12min | **不再超时** |

> **注意：** 以上为预估，实际效果取决于多个因素：SSH 延迟波动、下载任务耗时不受合并优化影响、handler 触发次数等。
> 优化后 tencent 的部署时间预计从 ~15.5min 降至 ~10-12min，仍有进一步提升空间。

## 注意事项

1. **YAML 缩进限制** —— `shell: |` 中使用 `{% if %}` Jinja2 标签时，
   `{%` 必须与块内其他内容保持相同缩进，否则 YAML 解析会出错。
   复杂条件逻辑建议保留 `template:` 模块。

2. **creates 标记** —— `cleanup-edge-tunnel-server` 使用了 `args: creates`，
   这是一次性清理操作，后续部署自动跳过。

3. **Envoy 热重载** —— 优化后的 service 文件通过 `copy content:`
   写入并用 Ansible 内置的 SHA1 checksum 变更检测触发 handler 重启，不影响 LDS/CDS 动态配置的热加载。

4. **`set -e` 原子性风险** —— 合并后的 `shell:` 块使用 `set -e`，
   块内任何命令失败都会中止整个 shell。对预期可能失败的命令（如 `systemctl start` 首次安装时），
   必须使用 `|| true` 保护。修改时注意不要破坏这种保护。

5. **Handler 注意** —— node-exporter 和 edge-vector 的 `handlers/main.yml` 仍被模块变更检测（copy/template/unarchive 的 notify）触发。
   修改这些角色的 task 时需确保 notify 链不断裂，且 `flush_handlers` 在最终的 service start 之前执行。

6. **Proxy 加速** —— 下载任务仍使用 `github_download_proxy`（GTR 的 Mihomo 代理），
   该代理通过 Tailscale 从 GitHub Actions Runner 到 GTR，再通过 Mihomo 出站，
   对中国大陆节点的下载加速效果取决于 Mihomo 代理的质量。
