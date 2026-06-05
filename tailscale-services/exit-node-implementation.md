# Tailscale Exit Node + Mihomo 链式路由实施记录

**日期:** 2026-05-31
**状态:** 未完成（待完成客户端配置修正与端到端验证）

---

## 目标

1. 将 GTR 配置为 Tailscale exit node，使 Tailnet 设备流量通过 GTR 的 Mihomo 代理上网
2. 配置 Mihomo 链式路由（`dialer-proxy`）提高非 AI 流量的容错性
3. AI 流量保持简单直连，不需要链式容错
4. GTR 端保留 RFC1918 与 Tailscale 网段直连，不让 Mihomo TUN 破坏本地网络
5. 客户端在启用 exit node 后仍可按需访问自己的本地 LAN

---

## 当前问题的重新归因

这次实际遇到的是两个独立问题，之前文档把它们混在了一起：

### 问题 A: 客户端未启用本地网络访问

**现象:** 将 `gtr` 设为 exit node 后，客户端无法访问 `192.168.31.59`

**真实原因:** 客户端启用 exit node 时，没有同时启用 `Allow Local Network Access` / `--exit-node-allow-lan-access`。  
当客户端和 GTR 同处 `192.168.31.0/24` 这类本地网段时，客户端对 `192.168.31.59` 的访问也会被送进 exit node，因此失去对 GTR LAN 地址的直连能力。

**修正方式:** 在客户端改用：

```bash
tailscale set --exit-node=gtr --exit-node-allow-lan-access
```

### 问题 B: GTR 端 Mihomo `auto-redirect` 会破坏服务器自身 LAN

**现象:** 早期部署带 TUN 的 Mihomo 配置时，GTR 的 LAN 一度完全不可达

**原因:** `auto-redirect: true` 会通过 iptables REDIRECT 劫持流量，`route-exclude-address` 无法阻止这一层的重定向，因此服务器自身的 LAN 流量可能被错误送入 Mihomo

**当前结论:** GTR 端只保留 `auto-route: true`，不要启用 `auto-redirect: true`

---

## 已完成的变更

### 1. Mihomo 配置模板

文件：`mihomo/ansible/roles/mihomo/templates/config.yaml.j2`

已完成：
- 新增 TUN 配置段，使用 `stack: mixed`
- 保留 `auto-route: true`
- 移除 `auto-redirect: true`
- `route-exclude-address` 排除：
  - `192.168.0.0/16`
  - `10.0.0.0/8`
  - `172.16.0.0/12`
  - `100.64.0.0/10`
- DNS listen 从 `127.0.0.1:5353` 改为 `0.0.0.0:5353`
- 新增 `*.ts.net` fake-ip-filter
- 将已废弃的 `relay` 组改为 `dialer-proxy` 方案
- 新增 `General` fallback 组，自动在三条链、`Auto` 和 `DIRECT` 之间切换
- 默认规则从 `Auto` 改为 `General`

### 2. Tailscale 文档

文件：`tailscale-services/README.md`

已完成：
- 增补 exit node 使用说明
- 明确客户端需使用 `--exit-node-allow-lan-access`
- 修正 grants 示例为当前语法
- 删除“故障时自动回退到原始网络”的强承诺

### 3. GTR 端系统配置

已在 GTR 上生效：

```bash
# /etc/sysctl.d/99-tailscale-forwarding.conf
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
```

### 4. GTR 已启用 exit node 广告

当前使用：

```bash
sudo tailscale up --advertise-exit-node --accept-dns=false
```

后续建议统一改为：

```bash
sudo tailscale set --advertise-exit-node
sudo tailscale set --accept-dns=false
```

---

## 已确认的经验教训

1. **客户端 LAN 访问与 GTR 端 TUN 排除是两回事**
   `--exit-node-allow-lan-access` 只影响客户端是否保留自己的本地网络访问，不会替代 GTR 端的 `route-exclude-address`

2. **`auto-redirect` 不适合这里的网关场景**
   在 GTR 这种要同时承载 Tailscale、LAN 和本地服务的机器上，`auto-redirect` 风险过高，应仅使用 `auto-route`

3. **relay 已废弃**
   Mihomo v1.19.20+ 已移除 `relay`，应改用 `dialer-proxy`

4. **不要把“自动回退”写成既定事实**
   Exit node 或路由设备故障时，客户端可能中断，不应在 runbook 中承诺“必然自动回退到原始网络”

---

## 待完成步骤

### 步骤 1: 重新部署 Mihomo 配置

```bash
cd mihomo/ansible
ansible-playbook -i inventory.ini deploy.yml
```

目标：
- 确认 GTR 上运行的是不含 `auto-redirect` 的配置
- 确认 Mihomo 正常启动

### 步骤 2: 验证 GTR 端 TUN 不破坏服务器自身网络

```bash
ssh gtr "systemctl status mihomo --no-pager"
ssh gtr "ip route show table all | grep -Ei 'mihomo|100\\.64|192\\.168|172\\.16|10\\.'"
ssh gtr "journalctl -u mihomo -n 50 --no-pager"
```

验收标准：
- Mihomo 处于 `active (running)`
- `192.168.0.0/16`、`10.0.0.0/8`、`172.16.0.0/12`、`100.64.0.0/10` 没有被错误导入 TUN
- GTR 自身仍可通过 LAN 正常访问

### 步骤 3: 更新 Tailscale ACL

在 Admin Console 中确认存在 exit node grants：

```json
{
  "grants": [
    {
      "src": ["autogroup:member"],
      "dst": ["autogroup:internet"],
      "ip": ["*"]
    }
  ]
}
```

### 步骤 4: 客户端按正确方式启用 exit node

同 LAN 场景使用：

```bash
tailscale set --exit-node=gtr --exit-node-allow-lan-access
```

如果客户端不需要保留自己的 LAN 访问，可使用：

```bash
tailscale set --exit-node=gtr
```

### 步骤 5: 端到端验证

#### 5.1 同 LAN 客户端

```bash
# 验证出口 IP 走 GTR / Mihomo
curl https://api.ipify.org

# 验证仍可直连 GTR 的 LAN 地址
ping 192.168.31.59
curl http://192.168.31.59:3000
```

验收标准：
- `curl https://api.ipify.org` 显示预期出口 IP
- `192.168.31.59` 可访问

#### 5.2 非同 LAN Tailnet 客户端

```bash
curl https://api.ipify.org
curl https://grafana.tail414c32.ts.net/
```

验收标准：
- 出口 IP 正确
- Tailscale Services 仍可访问

#### 5.3 GTR 端代理验证

```bash
cd mihomo/ansible
ansible-playbook -i inventory.ini verify.yml
```

验收标准：
- Mihomo API 认证成功
- 本地经 Mihomo 代理访问 Google 成功

---

## 故障处理

### 客户端无法访问 `192.168.31.59`

优先检查客户端是否启用了：

```bash
tailscale set --exit-node=gtr --exit-node-allow-lan-access
```

### GTR 端再次出现 Mihomo TUN 破坏本地网络

优先做最小化恢复：

```bash
ssh gtr.tail414c32.ts.net
sudo systemctl stop mihomo
sudo iptables-save
sudo nft list ruleset
```

处理原则：
- 先抓当前规则快照，再清理
- 仅删除 Mihomo 新增的链和规则
- 不要直接将整张 `nat` / `mangle` / `filter` 表 `-F`

如果确认是旧的 `auto-redirect` 残留规则，再按实际链名做定点删除。

### Exit node 故障

不要默认认为客户端会自动回退。应按以下顺序处理：

1. 检查 GTR 上 `tailscaled` 与 `mihomo` 状态
2. 检查客户端是否仍指向 `gtr` 作为 exit node
3. 必要时客户端手动关闭 exit node：

```bash
tailscale up --exit-node=
```

---

## 修改文件清单

| 文件 | 状态 |
|------|------|
| `mihomo/ansible/roles/mihomo/templates/config.yaml.j2` | 已修改，保留 `auto-route` 并移除 `auto-redirect` |
| `tailscale-services/README.md` | 已更新 exit node 使用说明与 grants 语法 |
| `tailscale-services/exit-node-implementation.md` | 已重写，区分客户端问题与 GTR 端 TUN 问题 |
| GTR: `/etc/sysctl.d/99-tailscale-forwarding.conf` | 已创建 |
