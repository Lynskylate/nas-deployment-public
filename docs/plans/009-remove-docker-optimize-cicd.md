# [Plan] 移除 GTR Docker 并优化 CI/CD

## 概述

**目标：** 从 GTR 彻底卸载 Docker，清理 repo 中所有 docker-cleanup 相关代码和变量，移除 CI 中的 Docker 部署阶段。

**依据：** [docs/issues/008-docker-nftables-conflict-analysis.md](../issues/008-docker-nftables-conflict-analysis.md) 分析结论——Docker 的 nftables 遗留规则干扰 Tailscale exit-node 路由，GTR 上无容器使用 Docker，`docker-cleanup` playbook 已完成历史使命。

**影响范围：**

| 组件 | 变更类型 |
|------|---------|
| GTR 服务器（`192.168.31.59`） | 卸载 docker.io / containerd / snap-docker 包，清理 nftables 残留规则 |
| `mihomo/ansible/deploy-docker.yml` | **删除** |
| `mihomo/ansible/roles/docker-cleanup/` | **删除**（整个目录） |
| `mihomo/ansible/group_vars/all/public.yml` | 删除 `docker_bridges` / `docker_registry_mirrors` / `docker_remove_snap` 变量 |
| `.github/workflows/deploy-infra.yml` | 移除 "Deploy Docker cleanup" 步骤 |
| `.github/workflows/validate-pr.yml` | 移除 `deploy-docker.yml --syntax-check` 行 |
| `mihomo/ansible/roles/tailscale-exitnode/templates/tailscale-exitnode-monitor.sh.j2` | 移除 Docker bridge 检查和 Prometheus metrics |
| `deploy-exitnode.yml` | **保留**，重新部署以刷新 monitor 脚本 |

**不做变更的文件（仅含 docker.com 域名代理规则，与 Docker 守护进程无关）：**
- `mihomo/ansible/roles/mihomo/templates/config.yaml.j2:378` — `DOMAIN-SUFFIX,docker.com` 代理路由
- `mihomo/ansible/roles/mihomo/templates/config-aliyun.yaml.j2:194` — 同上
- `network-monitor/mihomo-improved-rules.yml:164` — 同上
- `edge/ansible/group_vars/all/public.yml:122` — K3s containerd 镜像拉取代理配置（注释，与 Docker 无关）
- `edge/ansible/host_vars/aliyun/public.yml:14` — `docker.io` registry mirror（K3s containerd 配置，与 Docker 无关）

---

## 阶段一：GTR 现场卸载（SSH 直连）

> **⚠️ 执行顺序关键：** 必须在 repo 清理之前执行。先停止服务 → 卸载包 → 清理 nftables → 重启 Tailscale。

### Step 1: 停止并禁用 Docker

```bash
ssh root@gtr.tail414c32.ts.net
sudo systemctl stop docker docker.socket
sudo systemctl disable docker docker.socket
```

### Step 2: 卸载包

```bash
# GTR 安装的是 Ubuntu docker.io（非 docker-ce），containerd 仅被 docker.io 依赖
sudo apt purge -y docker.io docker-compose-v2 containerd
sudo apt autoremove -y
```

### Step 3: 清除 snap Docker 残留

```bash
# 当前状态：disabled 但未 purge
sudo snap remove --purge docker
```

### Step 4: 清理数据目录和网桥接口

```bash
sudo rm -rf /var/lib/docker /etc/docker /run/docker.sock
# 删除残留 Docker 网桥（已无容器使用）
sudo ip link delete docker0 2>/dev/null; true
sudo ip link delete br-9257ae6e34da 2>/dev/null; true
```

### Step 5: 清理 nftables 中 Docker 遗留规则

> **必须先从主链删除 jump 引用，再删除 DOCKER 子链。** 顺序颠倒会导致 dangling reference 或删除失败。

```bash
# Step 5a: 删除主链中所有 jump DOCKER* 引用（基于 rule handle）
# filter 表 FORWARD 链
for handle in $(sudo nft -a list chain ip filter FORWARD 2>/dev/null | grep -E 'jump\s+DOCKER' | awk '{print $NF}'); do
    echo "  Deleting FORWARD rule handle $handle"
    sudo nft delete rule ip filter FORWARD handle "$handle"
done

# nat 表 PREROUTING 链
for handle in $(sudo nft -a list chain ip nat PREROUTING 2>/dev/null | grep -E 'jump\s+DOCKER' | awk '{print $NF}'); do
    echo "  Deleting PREROUTING rule handle $handle"
    sudo nft delete rule ip nat PREROUTING handle "$handle"
done

# nat 表 OUTPUT 链
for handle in $(sudo nft -a list chain ip nat OUTPUT 2>/dev/null | grep -E 'jump\s+DOCKER' | awk '{print $NF}'); do
    echo "  Deleting OUTPUT rule handle $handle"
    sudo nft delete rule ip nat OUTPUT handle "$handle"
done

# nat 表 POSTROUTING 链 — 清理 Docker bridge MASQUERADE 残留
for handle in $(sudo nft -a list chain ip nat POSTROUTING 2>/dev/null | grep -E '(docker0|br-9257ae6e34da).*masquerade' | awk '{print $NF}'); do
    echo "  Deleting POSTROUTING MASQUERADE rule handle $handle"
    sudo nft delete rule ip nat POSTROUTING handle "$handle"
done

# Step 5b: 刷新并删除所有 DOCKER 子链
for chain in DOCKER DOCKER-USER DOCKER-FORWARD DOCKER-CT DOCKER-BRIDGE DOCKER-INTERNAL; do
    for table in filter nat; do
        if sudo nft list chain ip "$table" "$chain" &>/dev/null; then
            echo "  Flushing $table $chain"
            sudo nft flush chain ip "$table" "$chain"
            echo "  Deleting $table $chain"
            sudo nft delete chain ip "$table" "$chain"
        fi
    done
done

# Step 5c: 验证清理结果
echo "=== 残留 DOCKER 引用检查 ==="
sudo nft list ruleset | grep -i docker && echo "⚠️  仍有残留" || echo "✅ 清理干净"
```

### Step 6: 重启 Tailscale 以重建 ts-postrouting

```bash
sudo systemctl restart tailscaled
sleep 5

# 检查 ts-postrouting 是否被正确引用
sudo nft list chain ip nat POSTROUTING | grep ts-postrouting
# 如果 ts-postrouting 仍未被引用，tailscale-exitnode-fix.service 的定时任务会自动注入 MASQUERADE
```

### Step 7: 验证 exit node 功能

从客户端测试：
```bash
# 通过 Tailscale exit node 访问国际站点
curl --connect-timeout 10 -I https://github.com
# 预期：HTTP/2 200
```

---

## 阶段二：Repo 代码清理

> **执行顺序：** 阶段一的 GTR 卸载验证通过后，再提交 repo 变更。

### 变更 1: 删除 `mihomo/ansible/deploy-docker.yml`

```bash
rm mihomo/ansible/deploy-docker.yml
```

### 变更 2: 删除 `mihomo/ansible/roles/docker-cleanup/` 目录

```bash
rm -rf mihomo/ansible/roles/docker-cleanup/
```

### 变更 3: 清理 `mihomo/ansible/group_vars/all/public.yml` 中的 Docker 变量

**文件:** `mihomo/ansible/group_vars/all/public.yml`

删除以下三个变量块：

```yaml
# --- Docker Cleanup ---
docker_bridges:
  - bridge: docker0
    subnet: 172.17.0.0/16
  - bridge: br-9257ae6e34da
    subnet: 172.18.0.0/16

docker_registry_mirrors:
  - "https://docker.m.daocloud.io"
  - "https://docker.1panel.live"
  - "https://hub.rat.dev"

docker_remove_snap: false
```

**替换为：**

```yaml
# --- Docker Cleanup (removed 2026-06-07) ---
# Docker 已从 GTR 卸载，docker_bridges 保留为空列表以防止
# tailscale-exitnode-monitor.sh.j2 模板渲染时报 undefined variable 错误
docker_bridges: []
```

### 变更 4: 更新 `tailscale-exitnode-monitor.sh.j2` 模板

**文件:** `mihomo/ansible/roles/tailscale-exitnode/templates/tailscale-exitnode-monitor.sh.j2`

移除 Docker bridge 相关的两个区块：

**区块 A（第 51-65 行）** — Docker bridge MASQUERADE 检查/修复循环：
```jinja2
# --- Check & fix Docker bridge MASQUERADE rules ---
# With iptables=false, Docker no longer manages these. Required for container NAT.
{% for bridge in docker_bridges %}
BRIDGE_{{ loop.index }}_OK=0
if ${NFT} list chain ip nat POSTROUTING 2>/dev/null | grep -q 'saddr {{ bridge.subnet }}.*masquerade'; then
    BRIDGE_{{ loop.index }}_OK=1
else
    ${NFT} insert rule ip nat POSTROUTING ip saddr {{ bridge.subnet }} oifname != "{{ bridge.bridge }}" masquerade 2>/dev/null && {
        BRIDGE_{{ loop.index }}_OK=1
        FIXES=$((FIXES + 1))
        logger -t exitnode-monitor "FIXED: added Docker bridge MASQUERADE for {{ bridge.subnet }}"
    } || {
        logger -t exitnode-monitor "FAIL: could not add Docker bridge MASQUERADE for {{ bridge.subnet }}"
    }
fi
{% endfor %}
```

**区块 B —** Prometheus metrics 中的 Docker bridge 部分：
```jinja2
{% for bridge in docker_bridges %}
# HELP tailscale_exitnode_docker_bridge_masquerade 1 if Docker bridge MASQUERADE exists
# TYPE tailscale_exitnode_docker_bridge_masquerade gauge
tailscale_exitnode_docker_bridge_masquerade{bridge="{{ bridge.bridge }}",subnet="{{ bridge.subnet }}"} ${BRIDGE_{{ loop.index }}_OK}
{% endfor %}
```

> 由于 `docker_bridges` 已设为 `[]`，这两个 `{% for %}` 循环渲染时不会产生任何输出（零次迭代）。保留空列表可以确保即使忘记删除模板中的 Jinja2 代码也不会出错。

### 变更 5: 移除 `.github/workflows/deploy-infra.yml` 中的 Docker cleanup 步骤

**文件:** `.github/workflows/deploy-infra.yml`

删除 `deploy-gtr` job 中的以下步骤（第 203-206 行）：

```yaml
      - name: Deploy Docker cleanup
        working-directory: mihomo/ansible
        run: ansible-playbook -i inventory.ini deploy-docker.yml --limit gtr -v
```

### 变更 6: 移除 `.github/workflows/validate-pr.yml` 中的 Docker syntax-check

**文件:** `.github/workflows/validate-pr.yml`

删除 lint job 中的第 39 行：

```yaml
          ansible-playbook -i inventory.ini deploy-docker.yml --syntax-check
```

---

## 阶段三：重新部署 exitnode monitor（刷新脚本）

> 在阶段二的 repo 变更合并到 main 后执行。CI 的 `deploy-gtr` job 会自动运行 `deploy.yml`，但 monitor 脚本由 `deploy-exitnode.yml` 单独管理。

### 触发方式

**选项 A：手动触发（推荐首次）**
```bash
cd mihomo/ansible
ansible-playbook -i inventory.ini deploy-exitnode.yml --limit gtr -v
```

**验证生成的脚本不含 Docker bridge 代码：**
```bash
ssh root@gtr.tail414c32.ts.net "grep -i docker /usr/local/bin/tailscale-exitnode-monitor.sh"
# 预期：无输出（或仅在注释中出现 'docker' 字样）
```

**选项 B：通过 CI 全量部署**
手动触发 `Deploy Infrastructure` workflow，选择 `target: all`。

---

## 阶段四：验证检查清单

### 4.1 GTR 服务状态

```bash
ssh root@gtr.tail414c32.ts.net
# 所有核心服务应正常运行
for svc in mihomo grafana victoriametrics victorialogs victoriatraces node_exporter tailscale-exitnode-fix; do
    systemctl is-active "$svc" && echo "  $svc: active" || echo "  $svc: FAIL"
done
```

### 4.2 Docker 完全清除

```bash
# docker 命令应已不存在
which docker && echo "FAIL: docker still installed" || echo "OK: docker not found"
# dockerd 进程不应存在
ps aux | grep "[d]ockerd" && echo "FAIL: dockerd running" || echo "OK: no dockerd"
# Docker 数据目录应已删除
ls /var/lib/docker 2>/dev/null && echo "FAIL: /var/lib/docker exists" || echo "OK: cleaned"
# Docker 网桥接口应已删除
ip link show docker0 2>/dev/null && echo "FAIL: docker0 exists" || echo "OK: docker0 removed"
ip link show br-9257ae6e34da 2>/dev/null && echo "FAIL: br-9257ae6e34da exists" || echo "OK: br-9257ae6e34da removed"
```

### 4.3 nftables 清理

```bash
# nftables ruleset 中不应再有 DOCKER 链或引用
sudo nft list ruleset | grep -i docker && echo "FAIL: docker rules remain" || echo "OK: nftables clean"
# POSTROUTING 链应包含 exitnode-fix 注入的 MASQUERADE 规则
sudo nft list chain ip nat POSTROUTING | grep 'oifname.*masquerade'
```

### 4.4 Tailscale exit node 功能

```bash
# ts-postrouting 链应存在（Tailscale 自动创建）
sudo nft list chain ip nat ts-postrouting && echo "OK: ts-postrouting exists" || echo "WARN: missing"
# exitnode-fix monitor 运行正常
sudo journalctl -u tailscale-exitnode-monitor.service --since "5 min ago" | grep -i "fix"
```

### 4.5 CI/CD 验证

- [ ] PR 合并后，`Validate PR` workflow 的 lint job 通过（不再检查 `deploy-docker.yml`）
- [ ] `Deploy Infrastructure` workflow 的 `deploy-gtr` job 通过（不再有 "Deploy Docker cleanup" 步骤）
- [ ] CI 中 `deploy-gtr` 的整体耗时减少（去掉了 Docker cleanup 阶段）

---

## 回滚方案

如果卸载后需要恢复 Docker 环境：

```bash
ssh root@gtr.tail414c32.ts.net

# 重装 Docker
sudo apt install -y docker.io docker-compose-v2 containerd

# 启动 Docker（无需旧 daemon.json，新安装默认无 iptables 冲突）
sudo systemctl enable --now docker

# 验证
docker info | grep "Server Version"
```

如需恢复完整的 docker-cleanup 配置（含 `iptables=false` 和 registry mirrors），从 git 历史恢复 `deploy-docker.yml` 和 `roles/docker-cleanup/`，重新部署即可。

---

## 风险矩阵

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| 有人手动在 GTR 上使用 Docker 开发 | 低 | 中 | 卸载前 `grep` 检查 cron/systemd 中无 docker 引用；提前通知 |
| nftables 清理误删非 Docker 规则 | 低 | 高 | 按 handle 精确删除，仅匹配 `jump DOCKER*` 和明确的 Docker bridge MASQUERADE |
| Tailscale 重启后 exit node 路由异常 | 低 | 中 | `tailscale-exitnode-fix.service` 定时任务 30s 内自动修复 MASQUERADE + 策略路由 |
| 系统 containerd 卸载影响 K3s | **无风险** | — | K3s 使用独立 containerd (`/run/k3s/containerd/`)，不受系统 containerd 影响 |
| CI 中其他 job 隐式依赖 `deploy-docker.yml` | 低 | 中 | 已 grep 全仓确认仅 deploy-infra.yml 和 validate-pr.yml 引用 |

---

## 执行顺序总结

```
阶段一（GTR SSH 现场）
  ├─ Step 1: 停止并禁用 Docker
  ├─ Step 2: 卸载包 (docker.io, docker-compose-v2, containerd)
  ├─ Step 3: purge snap Docker
  ├─ Step 4: 清理数据目录和网桥接口
  ├─ Step 5: 清理 nftables Docker 遗留规则
  ├─ Step 6: 重启 Tailscale
  └─ Step 7: 验证 exit node 功能
       │
       ▼ (验证通过后)
阶段二（repo 代码变更，一次 commit）
  ├─ 变更 1: 删除 deploy-docker.yml
  ├─ 变更 2: 删除 roles/docker-cleanup/
  ├─ 变更 3: 清理 public.yml 中的 Docker 变量
  ├─ 变更 4: 更新 exitnode monitor 模板
  ├─ 变更 5: 移除 deploy-infra.yml 中的 Docker cleanup 步骤
  └─ 变更 6: 移除 validate-pr.yml 中的 syntax-check 行
       │
       ▼ (合并到 main 后)
阶段三（重新部署 monitor 脚本）
  └─ ansible-playbook deploy-exitnode.yml --limit gtr
       │
       ▼
阶段四（最终验证）
  ├─ 4.1 GTR 服务状态
  ├─ 4.2 Docker 完全清除
  ├─ 4.3 nftables 清理
  ├─ 4.4 Tailscale exit node 功能
  └─ 4.5 CI/CD 通过
```
