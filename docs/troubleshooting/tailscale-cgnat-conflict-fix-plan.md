# Tailscale CGNAT (100.x.y.z) 与云服务内网冲突修复方案

## 参考
- [Tailscale CGNAT Conflicts Resolution](https://avilpage.com/2024/09/tailscale-cgnat-conflicts-resolution.html)
- [Tailscale 100.x addresses](https://tailscale.com/kb/1015/100.x-addresses)
- [Tailscale IP Pool](https://tailscale.com/kb/1304/ip-pool)
- [Tailscale `--netfilter-mode` docs](https://tailscale.com/kb/1315/netfilter-mode)
- [Tailscale `--accept-dns` docs](https://tailscale.com/kb/1248/dns)

---

## 问题描述

### Tailscale CGNAT 范围

Tailscale 默认使用 `100.64.0.0/10`（即 100.64.0.0 ~ 100.127.255.255）作为 CGNAT 地址池，为每个节点分配唯一 IP。

### 冲突场景

**阿里云 ECS** 的 VPC 内网服务（如 DNS、元数据服务等）也使用 `100.x.x.x` 地址段。当 Tailscale 在阿里云节点上运行时：

1. Tailscale 分配一个 `100.x.x.x` IP 给该节点（如 `100.100.99.70`）
2. Tailscale 的 iptables 规则会 **DROP 所有源地址为 `100.64.0.0/10` 且不来自 `tailscale0` 接口的入站流量**
3. 阿里云内网服务（如 `100.100.100.100` DNS）的 IP 源地址命中此规则 → **被 DROP**
4. 结果：节点 DNS 解析、元数据 API 等内网服务全部不可用，甚至导致 SSH 无法连接

### 相同风险节点

| 节点 | 云厂商 | 是否有 100.x 冲突风险 |
|------|-------|---------------------|
| aliyun | 阿里云 | ✅ 高（VPC DNS: 100.100.2.136, 元数据: 100.100.100.200） |
| tencent | 腾讯云 | ⚠️ 可能（腾讯云也使用 100.x 段） |
| gtr | 自建 | ❌ 否（家庭网络无 100.x 冲突） |
| remote_proxy | 海外 VPS | ❌ 否 |
| yiling | 海外 VPS | ❌ 否 |

---

## 解决方案

### Step 1：缩小 Tailscale IP 池（已完成）

在 Tailscale ACL 配置（`tailscale admin console → Access Controls`）中设置 `ipPool`，限制 Tailscale 只使用池外地址：

```json
{
    "nodeAttrs": [
        {
            "target": ["autogroup:member"],
            "ipPool": ["100.100.96.0/20"]
        }
    ]
}
```

- `100.100.96.0/20` = 100.100.96.1 ~ 100.100.111.254（4094 个可用地址）
- 新加入的节点将从此池中分配 IP，不再随机使用整个 `100.64.0.0/10`

**注意：** 此配置不影响已分配的 IP。已分配 IP 的节点需要重新认证（`tailscale up`）才能获取新池中的 IP。

### Step 2：设置 `--netfilter-mode=nodivert`（核心步骤）

**替代了之前复杂的 iptables 手动修复 + systemd 持久化。一行命令即可。**

```bash
sudo tailscale set --netfilter-mode=nodivert
```

**原理：** `nodivert` 让 Tailscale **停止向 iptables 注入** ts-input 链的 DROP 规则。Tailscale 不再拦截任何 100.x 流量，由内核标准路由处理。

ipPool 缩小后（Step 1），Tailscale 实际只使用 `100.100.96.0/20`；而 `nodivert` 确保阿里云自身的 100.x 内网服务（DNS、元数据等）不被误杀。

> ⚠️ `nodivert` 后需要**手动管理 iptables 安全规则**。在纯 Tailscale 组网场景下（所有节点通过 Tailscale 互联），默认内核路由已足够安全。

**验证：**

```bash
sudo tailscale debug prefs | grep NetfilterMode
# → "NetfilterMode": 1  （1 = nodivert, 2 = on）

sudo iptables -L ts-input -n
# → ts-input 链显示 (0 references)，不再接入 INPUT
```

### Step 2b（可选）：`--accept-dns=false` 防止 MagicDNS 覆盖内网 DNS

阿里云内网 DNS 地址为 `100.100.2.136` / `100.100.2.138`。Tailscale 默认用 MagicDNS（`100.100.100.100`）覆盖 `/etc/resolv.conf`。

在云节点上，建议禁用 MagicDNS，保留云厂商内网 DNS 作为主解析器：

```bash
sudo tailscale set --accept-dns=false
```

**效果：**
- `/etc/resolv.conf` 由 systemd-resolved 或云厂商管理，不再被 Tailscale 覆盖
- 仍可通过 Tailscale IP 直接访问其他节点（我们的 Ansible 配置已全量使用 IP）
- MagicDNS 的 `gtr.tail414c32.ts.net` 解析失效，但 `100.121.0.67` 不受影响

### Step 3：更新 host_vars 配置

当节点重置/重新认证后，Tailscale IP 会变化。需要更新 Ansible 配置：

```yaml
# edge/ansible/host_vars/aliyun/public.yml
k3s_server_tailscale_ip: 100.100.99.70       # 重置后的新 IP
k3s_server_tls_sans:
- aliyun
- 100.100.99.70
```

```ini
# edge/ansible/inventory-edge.ini
aliyun ansible_host=100.100.99.70 ansible_user=ci ansible_port=22
```

```yaml
# edge/ansible/group_vars/all/public.yml
k3s_server_url: https://100.100.99.70:6443   # 与 Tailscale IP 同步
```

---

## 部署检查清单

### 阿里云重置后的完整恢复步骤

```bash
# 1. 通过云控制台 VNC 访问重置后的 VM
# 2. 安装 Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# 3. 认证（使用预授权密钥，带标签）
sudo tailscale up \
  --auth-key=tskey-auth-XXXXX \
  --hostname=vmaliyun \
  --accept-routes

# 4. 验证 IP
tailscale ip -4
# 预期：100.100.99.x（在 ipPool 范围内）

# 5. 应用 iptables 修复（Step 2b）
sudo mkdir -p /etc/systemd/system/tailscaled.service.d
# ...（复制上面的 systemd drop-in）

# 6. 创建 ci 用户和 SSH 授权
sudo useradd -m -u 1002 -s /bin/bash ci
sudo usermod -aG sudo ci
sudo mkdir -p /home/ci/.ssh
# 从 gtr 复制 authorized_keys
sudo chmod 600 /home/ci/.ssh/authorized_keys
sudo chown -R ci:ci /home/ci/.ssh
echo "ci ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/ci-nopasswd
sudo chmod 440 /etc/sudoers.d/ci-nopasswd

# 7. 更新 Ansible 配置
# - host_vars/aliyun/public.yml: 更新 k3s_server_tailscale_ip
# - inventory-edge.ini: 更新 ansible_host
# - group_vars/all/public.yml: 更新 k3s_server_url

# 8. 部署 K3s server
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-server.yml

# 9. 部署 K3s agents
ansible-playbook -i inventory-edge.ini deploy-gtr-k3s-agent.yml

# 10. 验证
k3s kubectl get nodes -o wide
```

---

## 已知问题与排查

### 问题：tencent→aliyun TCP 不通

**现象：** tencent (100.99.48.76) 通过 Tailscale 可以 ping 通 aliyun (100.100.99.70)，但 TCP 连接（端口 22、6443）超时。

**排查发现：**
- `tailscale ping` 正常（UDP/ICMP 可达）
- GTR→aliyun TCP 正常（GTR 通过 DERP relay 连接）
- tencent→GTR TCP 正常
- aliyun→tencent TCP 正常（反向连接正常）
- 降低 MTU、MSS clamping 无效
- 移除 aliyun 上所有 iptables DROP 规则无效
- tcpdump 在 aliyun 上未捕获到 tencent 发来的 TCP SYN 包

**根因推测：** 可能为以下之一：
1. 腾讯云安全组/防火墙对特定端口的出站连接做 DPI 拦截
2. 腾讯云与阿里云之间的跨境直连 WireGuard UDP 隧道存在运营商层面的 TCP 干扰
3. Tailscale 的某些版本在 direct connection 模式下存在 bug

**临时绕过方法：**

```bash
# 在 tencent 上强制使用 DERP relay（绕过 direct connection）
# 注意：会影响性能（延迟增加）
sudo tailscale set --exit-node=  # 确保未设置 exit node
sudo tailscale set --accept-routes

# 或者直接通过 aliyun 公网 IP 访问 K3s API：
# 修改 tencent 的 /etc/rancher/k3s/config.yaml 中 server 为公网 IP
# （需要配置 TLS SANs 含公网 IP + 安全组放行 6443）
```

**永久修复方向：**
1. 升级所有节点 Tailscale 到最新版本
2. 在 tencent 上应用 Step 2 的 iptables 修复（防止 tencent 自身的 100.x 服务被阻断）
3. 如持续失败，考虑将 tencent 的 K3s agent 走 DERP relay 路径

---

## 更新 Ansible 以自动应用 iptables 修复

建议将 iptables 修复步骤自动化，作为 `k3s-prereq` 角色的一部分。

### 新增模板文件

`roles/k3s-prereq/templates/tailscale-cgnat-fix.conf.j2`：

```
[Service]
ExecStartPost=/bin/sh -c 'sleep 2 && iptables -C ts-input -s 100.64.0.0/10 ! -i tailscale0 -j DROP 2>/dev/null && { iptables -D ts-input -s 100.64.0.0/10 ! -i tailscale0 -j DROP; iptables -I ts-input 5 -s 100.100.96.0/20 ! -i tailscale0 -j DROP; echo "tailscale CGNAT iptables fix applied" | systemd-cat -t tailscale-fix; } || echo "iptables rule already fixed" | systemd-cat -t tailscale-fix'
```

### 新增 Task

在 `roles/k3s-prereq/tasks/main.yml` 中添加：

```yaml
- name: Apply Tailscale CGNAT iptables fix
  ansible.builtin.template:
    src: tailscale-cgnat-fix.conf.j2
    dest: /etc/systemd/system/tailscaled.service.d/fix-cgnat-iptables.conf
    owner: root
    group: root
    mode: "0644"
  when: tailscale_cgnat_fix_enabled | default(false) | bool
  notify: reload tailscaled systemd
```

### 新增 Handler（可选）

```yaml
- name: reload tailscaled systemd
  ansible.builtin.systemd:
    name: tailscaled
    daemon_reload: true
    state: restarted
```

### 控制变量

在 `group_vars/all/public.yml` 中添加：

```yaml
# 是否启用 Tailscale CGNAT iptables 修复（阿里云、腾讯云等节点需要）
tailscale_cgnat_fix_enabled: false
```

在 `host_vars/aliyun/public.yml` 中覆盖：

```yaml
tailscale_cgnat_fix_enabled: true
```

---

## 版本历史

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| v1 | 2026-06-07 | — | 初始方案文档 |
