# 010 — aliyun 重装后 Tailscale 直连诊断

**日期**: 2026-06-07
**触发**: GitHub Actions [run 27085847002](https://github.com/Lynskylate/nas-deployment-public/actions/runs/27085847002) 失败
**状态**: 已修复（CI 走公网 IP），直连不可用（运营商层面）

---

## 背景

aliyun ECS（47.120.46.128 / Tailscale 100.100.99.70）操作系统重装后，CI `deploy-infra.yml` 全部失败。报错为 Ansible SSH 连接超时。

## 诊断过程

### 初始死锁

```
重装 → Tailscale 重新认证（缺 tag） → CGNAT iptables 未应用 →
所有 Tailscale 入站被 DROP → CI 无法 SSH → Ansible 无法部署修复
```

通过阿里云控制台 VNC 介入后，手动执行了 `tailscale set --netfilter-mode=nodivert`。

### 修复步骤

| 步骤 | 操作 | 结果 |
|------|------|------|
| 1 | Tailscale 标签从 `lynskylate@` 改为 `tag:public` | ✅ 手动在 admin console 完成 |
| 2 | 添加 `ci@gtr` SSH 公钥到 `/home/ci/.ssh/authorized_keys` | ✅ SSH 恢复 |
| 3 | 阿里云安全组放行入方向 UDP 41641 | ✅ |
| 4 | 验证 K3s 集群状态 | ✅ 三节点 Ready |

### 核心发现：Tailscale 直连不可用

**诊断现象**：

```bash
$ tailscale ping 100.100.99.70
pong from vmaliyun via DERP(sfo) in 315ms   # 永远走 DERP 中继
direct connection not established            # 从未建立直连
```

**双向 tcpdump 抓包证实**：

| 方向 | 结果 |
|------|------|
| gtr → aliyun:41641 (WireGuard) | ✅ aliyun 收到 |
| aliyun → gtr:41641 (WireGuard) | ❌ gtr 收不到 |
| tencent → aliyun:41641 (WireGuard) | ✅ aliyun 收到 |
| aliyun → tencent (IPv6) | ✅ 走 IPv6 |
| DERP relay (TCP/443) | ✅ 始终双向通 |

**aliyun tcpdump（eth0 发出但 gtr 收不到）**：
```
172.23.245.47:41641 > 114.84.3.22:41641  WireGuard
172.23.245.47:41641 > 114.84.3.22:20251  WireGuard
172.23.245.47:41641 > 192.168.31.59:41641 WireGuard
```

**gtr tcpdump（0 个来自 aliyun 的包）**：
```
$ tcpdump src host 47.120.46.128
0 packets captured
```

### 根因分析

Not a Tailscale or iptables issue — **阿里云出口到中国电信之间的 UDP WireGuard 包被丢弃**。

```
aliyun tailscaled → eth0 ✅ → 阿里云 NAT(改源端口) → 中国电信网络 → ❌ gtr 收不到
```

对比：
- tencent↔gtr 直连正常（腾讯云出口不丢包）
- tencent→aliyun 直连正常（入站能到）
- aliyun→tencent IPv6 正常（IPv6 路径不丢）
- 唯独 aliyun IPv4 UDP → gtr（中国电信）丢包

可能是：阿里云与中国电信之间的 UDP 过滤、PMTU black hole、或运营商级别的 DPI。

### `--netfilter-mode=nodivert` 持久性

已验证：`tailscale set --netfilter-mode=nodivert` **是持久的**，`systemctl restart tailscaled` 后不丢失。Ansible `k3s-prereq` 角色在每次 `deploy-gtr-k3s-server.yml` 时会自动检查并确保该设置生效。

**唯一失效场景**：OS 重装（Tailscale 状态文件随系统盘消失），但重装后重新执行 Ansible 即可恢复。

### IPv6 尝试

阿里云 VPC 已分配 IPv6 段 `2408:4008:1053:3400::/64`，但：
- VPC 路由表缺少 `::/0` 默认路由（需要 IPv6 互联网网关，额外付费）
- 即使配了地址，`tailscale netcheck` 显示 `IPv6: no`
- IPv6 直连理论上可以解决（无 NAT，端口不变），但需付费启用

## 当前方案

### inventory 调整（已提交）

```ini
# 之前：走 Tailscale DERP，CI 中 SSH 偶超时
# aliyun ansible_host=100.100.99.70

# 现在：CI 部署走公网 IP，K3s 内部通信仍走 Tailscale
aliyun ansible_host=47.120.46.128 ansible_user=ci ansible_port=22
```

### 配置状态

| 配置项 | 文件 | 值 |
|--------|------|-----|
| Ansible SSH | `inventory-edge.ini` | `47.120.46.128`（公网） |
| K3s API URL | `group_vars/all/public.yml` | `https://100.100.99.70:6443`（Tailscale） |
| nodivert | `host_vars/aliyun/public.yml` | `k3s_prereq_tailscale_nodivert: true` |
| ci 用户 | aliyun ECS | uid=1002, NOPASSWD sudo ✅ |
| SSH 公钥 | aliyun `/home/ci/.ssh/authorized_keys` | `lynskylate@tele` + `lynskylate@gtr` + `ci@gtr` |

### 待办

- [ ] 确认 CI deploy key（来自 vault `bootstrap/github-actions/prod.sops.yml`）的公钥也在 aliyun ci 用户中
- [ ] 如启用 IPv6 网关，更新 `tailscale-cgnat-conflict-fix-plan.md` 增加 IPv6 直连方案
- [ ] 监控 DERP relay 延迟，如超过 1s 持续影响部署，考虑自建 DERP 节点

## 经验总结

1. **重装后破局**：必须通过云控制台 VNC 或救援模式介入，手动执行 `tailscale set --netfilter-mode=nodivert`
2. **SSH 多层 key**：CI runner 的 deploy key ≠ gtr 的 ci key ≠ 个人 key，需确保所有必要公钥都在目标机器上
3. **Tailscale 直连不总是可行**：云平台 NAT 行为（端口随机化）+ 运营商 UDP 过滤可能导致永久回退 DERP，但 DERP 对管理流量够用
4. **VPC 路由 `100.64.0.0/10`** 不影响 Tailscale，因为 Tailscale 使用独立的 kernel 路由表（table 52）
5. **`nodivert` 持久性**：系统重启后保留，只需在 OS 重装后重新执行 Ansible 恢复
