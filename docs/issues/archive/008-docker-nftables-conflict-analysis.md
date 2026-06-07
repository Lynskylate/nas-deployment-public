# [Analysis] Docker nftables 路由冲突与 docker-cleanup 清理方案

## Overview

分析 GTR 上 Docker 的 nftables 规则与 Tailscale/Mihomo 路由的冲突根因，评估现有 `docker-cleanup` playbook 的有效性，提出清理方案。

**作者:** pi agent (2026-06-06)
**状态:** 已 review（2026-06-06 SSH 验证通过，修订卸载方案）

---

## 1. 背景

### 1.1 现有问题

2026-05-31 发现 GTR 作为 Tailscale exit node 时，客户端无法访问国际站点。根因是两问题叠加：
1. **Tailscale 的 `ts-postrouting` 链未被引用** → 缺少 MASQUERADE → 源 IP 未转换
2. **Exit node 流量绕过了 Mihomo TUN** → 未经代理直连 → 被 GFW 阻断

### 1.2 缓解措施

创建了两个 Ansible playbook 作为 workaround：
- `mihomo/ansible/deploy-exitnode.yml` — 手动注入 nftables MASQUERADE 规则 + 策略路由
- `mihomo/ansible/deploy-docker.yml` — 设置 Docker `iptables=false` 防止冲突

### 1.3 本文档目的

分析 Docker 与 Tailscale 的 nftables 冲突机制，评估 `docker-cleanup` 是否仍必要，以及能否从根本上卸载 Docker。

---

## 2. 冲突机制分析

### 2.1 现状快照（2026-06-06 SSH 到 GTR 采集）

| 项目 | 值 |
|------|-----|
| Docker 版本 | 29.1.3 (Ubuntu `docker.io` 包，非 docker-ce) |
| Docker 容器数 | 0 |
| Docker 网桥 | `docker0` (172.17.0.0/16), `br-9257ae6e34da` (172.18.0.0/16) |
| 网桥状态 | 两者均为 `DOWN` (NO-CARRIER) |
| Docker daemon.json | `{ "iptables": false, "registry-mirrors": [...] }` |
| iptables 模式 | `iptables-legacy`（非 nftables） |
| Docker Firewall Backend | `iptables` |
| 安装来源 | Ubuntu `docker.io` + `docker-compose-v2`（apt）|
| Snap Docker | 已 disabled（snap 29.3.1），但未 purge |
| 系统 containerd | `/run/containerd/containerd.sock` — 仅被 Docker 使用 |
| K3s containerd | `/run/k3s/containerd/containerd.sock` — 独立，不受影响 |
| Docker 数据目录 | `/var/lib/docker` 仅 272K |
| dockerd 内存占用 | 78 MB RSS |

### 2.2 关键证据：nftables 中存在 Docker 遗留规则

```bash
# 证据 A：nftables nat 表 POSTROUTING 链
$ sudo nft list table ip nat
table ip nat {
    chain POSTROUTING {
        type nat hook postrouting priority srcnat; policy accept;
        ip saddr 172.18.0.0/16 oifname != "br-9257ae6e34da" ... masquerade    # ← Docker 遗留
        oifname != "docker0" ip saddr 172.17.0.0/16 ... masquerade            # ← Docker 遗留  
        oifname "wlp4s0" masquerade                                            # ← exitnode-fix 注入
        jump FLANNEL-POSTRTG                                                   # ← Flannel
    }
    chain ts-postrouting { }  # ← Tailscale 创建但从未被引用！
}
```

```bash
# 证据 B：nftables filter 表存在 6 个 Docker 链
$ sudo nft list table ip filter | grep "chain DOCKER"
chain DOCKER { ... }
chain DOCKER-USER { }
chain DOCKER-FORWARD { ... }
chain DOCKER-CT { ... }
chain DOCKER-BRIDGE { ... }
chain DOCKER-INTERNAL { }
```

```bash
# 证据 C：FORWARD 链中 DOCKER 规则仍被跳转
# 注意：虽然网桥 DOWN，但 DOCKER-FORWARD 仍处理所有 FORWARD 流量
# 每个转发包额外经历 3 次 jump（DOCKER-CT → DOCKER-INTERNAL → DOCKER-BRIDGE），造成不必要的开销
chain FORWARD {
    jump KUBE-ROUTER-FORWARD
    mark & 0x20000 == 0x20000 accept
    jump DOCKER-USER       ← 空链，counter 453K packets
    jump DOCKER-FORWARD     ← counter 453K packets（持续增长）
    jump FLANNEL-FWD
}
```

```bash
# 证据 D：iptables-legacy 中没有 Docker 规则（证明 iptables=false 生效了）
$ sudo iptables-legacy -L FORWARD -n
Chain FORWARD (policy ACCEPT)
    KUBE-ROUTER-FORWARD
    KUBE-PROXY-FIREWALL
    KUBE-FORWARD
    KUBE-SERVICES
    KUBE-EXTERNAL-SERVICES
    ACCEPT (mark 0x20000)
    FLANNEL-FWD
    # ← 没有 DOCKER 规则
```

```bash
# 证据 E：Docker 的 daemon.json 确认 iptables=false
$ sudo cat /etc/docker/daemon.json
{
  "registry-mirrors": ["https://docker.m.daocloud.io", ...],
  "iptables": false
}
```

### 2.3 冲突发生的完整链条

```
┌────────────────────────────────────────────────────────────────────┐
│ 阶段 1：Docker 安装（默认 iptables=true）                           │
│                                                                    │
│  Docker 启动时在 nftables 中创建了 DOCKER 链族                      │
│  (DOCKER, DOCKER-USER, DOCKER-FORWARD, DOCKER-CT,                 │
│   DOCKER-BRIDGE, DOCKER-INTERNAL)                                  │
│  并在主链中插入 jump 引用                                           │
│    FORWARD → jump DOCKER-USER                                      │
│    FORWARD → jump DOCKER-FORWARD                                   │
│    PREROUTING → jump DOCKER                                        │
│    POSTROUTING → 插入 bridge MASQUERADE                            │
└────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 阶段 2：Tailscale exit node 启用                                    │
│                                                                    │
│  Tailscale 尝试管理自己的 nftables 规则：                            │
│  - 创建 ts-postrouting 链                                          │
│  - 期望在主 POSTROUTING 链中插入 "jump ts-postrouting"              │
│                                                                    │
│  【冲突点】Docker 的规则已存在于链中，                               │
│  Tailscale 的链管理逻辑被干扰，只追加了链定义而没有                  │
│  在主链中插入 jump 引用                                            │
└────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 阶段 3：后果                                                       │
│                                                                    │
│  POSTROUTING 链中：                                                │
│    Docker MASQUERADE (网桥 DOWN，无流量)                            │
│    FLANNEL-POSTRTG (Flannel 集群流量)                              │
│    ⛔ 没有 jump ts-postrouting                                     │
│                                                                    │
│  ts-postrouting 链：                                               │
│    存在但为空，且从未被调用                                          │
│                                                                    │
│  → Exit node 流量经过 POSTROUTING 时，                             │
│    跳过 ts-postrouting，没有被 MASQUERADE，                        │
│    带着 Tailscale 私有 IP (100.x.x.x) 发出                        │
│    → 上游路由器丢弃 → 客户端无法访问                                │
└────────────────────────────────────────────────────────────────────┘
```

### 2.4 `iptables=false` 的局限性

**解决的问题：** 阻止 Docker 继续写入新的 nftables 规则。

**未解决的问题：**
1. ❌ **不清理已有规则** — DOCKER 链和 jump 引用仍残留在 nftables 中
2. ❌ **`ts-postrouting` 仍需靠 `deploy-exitnode.yml` 手动修复**（注入 `oifname wlp4s0 masquerade` + 策略路由）
3. ❌ **Docker 进程本身仍在运行**（占 78MB RSS 内存，docker0/br-* 接口存在）
4. ❌ **DOCKER-FORWARD 链仍在处理所有 FORWARD 流量**（counter 453K+ packets），每个包额外 3 次 jump 开销

---

## 3. docker-cleanup playbook 评估

### 3.1 文件位置

```
mihomo/ansible/
├── deploy-docker.yml              # Playbook
├── group_vars/all/public.yml      # docker_bridges, docker_registry_mirrors 等变量
└── roles/docker-cleanup/
    ├── tasks/main.yml             # 4 个阶段
    ├── handlers/main.yml          # restart docker
    └── templates/daemon.json.j2   # {"iptables": false, "registry-mirrors": [...]}
```

### 3.2 核心行为

| 阶段 | 作用 | 当前是否仍有价值 |
|------|------|----------------|
| 阶段 1: 禁用 snap Docker | 停止/禁用 snap 版 Docker | ❌ snap Docker 早已被禁用，不再需要 |
| 阶段 2: 配置 system Docker | 设置 `iptables=false` + 镜像加速 | ❌ 已配置生效，一次性的 |
| 阶段 3: 手动管理 bridge NAT | 注入 bridge MASQUERADE 规则 | ❌ 两个网桥都是 DOWN，无流量经过 |
| 阶段 4: 验证 | 显示状态 | 信息性 |

### 3.3 结论：该 playbook 已基本完成其历史使命

`docker-cleanup` 在 2026-05-31 时是一个合理的工作区——保留 Docker 的同时避免冲突。但现在：

- **GTR 上没有任何 workload 需要 Docker**（0 容器）
- K3s (containerd) 覆盖了容器编排需求
- Podman 覆盖了 rootless 容器需求
- 遗留的 nftables Docker 链仍然存在，但 `iptables=false` + 网桥 DOWN 使其无害

**根本方案是卸载 Docker，而非继续维护这个 workaround。**

---

## 4. 卸载 Docker 的方案

### 4.1 前提条件确认

| 检查项 | 状态 | 证据 |
|--------|------|------|
| GTR 上是否有 Docker 容器在运行？ | 无 | `docker ps -a` 输出为空 |
| 是否有任何 systemd 服务依赖 docker.service？ | 否 | K3s 用独立 containerd，Podman 独立 |
| 系统 containerd 是否被 Docker 以外的进程使用？ | 否 | `lsof /run/containerd/containerd.sock` 仅 dockerd |
| `docker-compose-v2` 是否可随 Docker 一起移除？ | 是 | `apt-cache rdepends docker.io` 显示反向依赖 |
| Snap Docker 是否需要 purge？ | 是 | snap docker 29.3.1 disabled 但未清除 |
| 是否有脚本/工具硬编码了 docker 命令？ | 需确认 | 建议 grep 整个 repo |
| 是否有用户在 GTR 上手动用 docker 跑开发环境？ | 需确认 | 手动确认 |

### 4.2 卸载步骤

```bash
# Step 1: 停止 Docker
sudo systemctl stop docker docker.socket
sudo systemctl disable docker docker.socket

# Step 2: 卸载包（注意：GTR 用的是 Ubuntu docker.io，不是 docker-ce）
sudo apt purge -y docker.io docker-compose-v2
# 系统 containerd 仅被 Docker 使用，K3s 有独立的 containerd（/run/k3s/containerd/）
sudo apt purge -y containerd
sudo apt autoremove -y

# Step 3: 彻底清除 snap Docker 残留
sudo snap remove --purge docker

# Step 4: 清理数据目录和接口
sudo rm -rf /var/lib/docker /etc/docker /run/docker.sock
# 删除残留的 Docker 网桥接口（已无容器使用）
sudo ip link delete docker0 2>/dev/null; true
sudo ip link delete br-9257ae6e34da 2>/dev/null; true

# Step 5: 清理 nftables 中 Docker 遗留规则
# 重要：必须先从主链中删除 jump DOCKER* 引用，再删除 DOCKER 子链
# 否则子链可能因被引用而删除失败或留下悬空引用

# Step 5a: 删除主链中所有 jump DOCKER* 规则（基于 rule handle）
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
# 这两条规则匹配 172.17/18 网段的 MASQUERADE，网桥删除后变成死规则
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

# Step 6: 重启 Tailscale 以让其重建 ts-postrouting
sudo systemctl restart tailscaled

# Step 7: 验证 ts-postrouting 是否被正确引用
sleep 5
sudo nft list chain ip nat ts-postrouting
sudo nft list chain ip nat POSTROUTING | grep ts-postrouting
# 如果 ts-postrouting 仍未被引用，tailscale-exitnode-fix.service 会自动注入
# （deploy-exitnode.yml 部署的定时任务会检测并修复）

# Step 8: 验证 exit node 功能正常
# 从客户端测试：curl --proxy ... https://github.com
```

### 4.3 Repo 清理

```bash
# 标记 mihomo/ansible/deploy-docker.yml 为废弃
# 删除 mihomo/ansible/roles/docker-cleanup/ 目录
# 删除 mihomo/ansible/group_vars/all/public.yml 中 docker_* 变量
```

### 4.4 风险与回滚

| 风险 | 可能性 | 缓解措施 |
|------|--------|---------|
| 有人正在用 Docker 跑开发环境 | 低 | 提前沟通确认 |
| 未来要跑 Docker 镜像需重装 | 低 | `apt install docker.io` 即可恢复 |
| nftables 清理误删其他规则 | 低 | 先删引用再删链，只处理明确命名为 DOCKER* 的链和规则 |
| Tailscale 重建后路由异常 | 低 | 有 deploy-exitnode.yml 可回退 |
| 系统 containerd 卸载影响 K3s | 无 | K3s 使用独立 containerd (`/run/k3s/containerd/`)，不受影响 |

---

### 4.5 回滚方案

如果卸载后需要恢复 Docker 环境：

```bash
# 重装 Docker
sudo apt install -y docker.io docker-compose-v2 containerd

# 恢复 daemon.json（从 git 恢复）
sudo cp /path/to/repo/mihomo/ansible/roles/docker-cleanup/templates/daemon.json.j2 /etc/docker/daemon.json
# 注意：需要将 Jinja2 模板变量替换为实际值

# 启动 Docker
sudo systemctl enable --now docker

# 如果需要恢复 iptables=true 模式（Docker 自动管理 nftables）
# 编辑 /etc/docker/daemon.json 删除 "iptables": false 行
sudo systemctl restart docker
```

### 4.6 deploy-exitnode.yml 的长期定位

卸载 Docker 后，`tailscale-exitnode-fix.service`（由 `deploy-exitnode.yml` 部署）**仍需保留**。原因：

1. **MASQUERADE 注入**：即使 Docker 被移除，Tailscale 在干净环境下能否自行正确管理 `ts-postrouting` 链引用尚不确定。`tailscale-exitnode-fix.service` 作为保险机制，确保 POSTROUTING 中始终存在 MASQUERADE 规则。
2. **策略路由**：`ip rule from 100.64.0.0/10 lookup 2022` 将 Tailscale 流量导向 Mihomo TUN，这是独立于 Docker 的需求。

**优化建议**：在卸载 Docker + 重启 tailscaled 后，先验证 `ts-postrouting` 是否被自动正确引用。如果 Tailscale 能自行管理好链引用，则 `tailscale-exitnode-fix.service` 可以简化为仅做策略路由注入，移除 MASQUERADE 注入部分。

---

## 5. Reference 索引

| Ref | 文件 | 说明 |
|-----|------|------|
| R1 | `docs/issues/008-docker-nftables-conflict-analysis.md` | 本文档 |
| R2 | `tailscale-services/exit-node-troubleshooting-2026-05-31.md` | 原始 exit node 故障排查报告 |
| R3 | `mihomo/ansible/deploy-docker.yml` | docker-cleanup playbook |
| R4 | `mihomo/ansible/roles/docker-cleanup/tasks/main.yml` | docker-cleanup 任务定义 |
| R5 | `mihomo/ansible/roles/docker-cleanup/templates/daemon.json.j2` | `{"iptables": false}` 模板 |
| R6 | `mihomo/ansible/group_vars/all/public.yml` | docker_bridges 等变量定义 |
| R7 | `mihomo/ansible/deploy-exitnode.yml` | exit node 修复 playbook（仍需保留） |

## 6. 现场采集数据（raw evidence）

```bash
# 采集时间: 2026-06-06
# 命令: SSH gtr 执行以下命令

# E1: Docker daemon.json → iptables=false 已生效
cat /etc/docker/daemon.json
→ {"registry-mirrors":[...], "iptables": false}

# E2: Docker 容器数 → 0
docker ps -a
→ (空)

# E3: Docker 网桥状态 → DOWN
ip link show docker0 br-9257ae6e34da
→ docker0: <NO-CARRIER,BROADCAST,MULTICAST,UP> state DOWN
→ br-9257ae6e34da: <NO-CARRIER,BROADCAST,MULTICAST,UP> state DOWN

# E4: nftables nat 表 → Docker bridge MASQUERADE 残留 + ts-postrouting 空链
sudo nft list table ip nat
→ 见 2.2 证据 A

# E5: nftables filter 表 → 6 个 Docker 链残留
sudo nft list table ip filter | grep "chain DOCKER"
→ 见 2.2 证据 B

# E6: iptables-legacy 无 Docker 规则 → iptables=false 有效
sudo iptables-legacy -L FORWARD -n
→ 无 DOCKER 规则（对比 nftables 有）

# E7: Docker info → Firewall Backend: iptables
sudo docker info | grep -i "iptables\|firewall"
→ Firewall Backend: iptables

# E8: dockerd 命令行
ps aux | grep dockerd
→ /usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock

# E9: Docker 安装包来源 → Ubuntu docker.io（非 docker-ce）
dpkg -l | grep -i docker
→ docker.io  29.1.3-0ubuntu3~22.04.2
→ docker-compose-v2  2.40.3+ds1-0ubuntu1~22.04.1

# E10: 系统 containerd 与 K3s containerd 是独立的
sudo lsof /run/containerd/containerd.sock | grep -v containerd$
→ 仅 dockerd 使用系统 containerd
ls /run/k3s/containerd/containerd.sock
→ K3s 有独立的 containerd socket

# E11: Snap Docker 状态 → disabled 但未 purge
snap list docker
→ docker 29.3.1 3505 latest/stable canonical** disabled

# E12: Docker 数据目录大小
sudo du -sh /var/lib/docker
→ 272K（几乎为空）

# E13: containerd 反向依赖
apt-cache rdepends --installed containerd
→ containerd 仅被 docker.io 依赖

# E14: DOCKER-FORWARD 性能开销
sudo nft list chain ip filter DOCKER-FORWARD
→ counter packets 453737 bytes 250029454 jump DOCKER-CT
→ 每个转发包额外 3 次 jump（DOCKER-CT → DOCKER-INTERNAL → DOCKER-BRIDGE）
```
