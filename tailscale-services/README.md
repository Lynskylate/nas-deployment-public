# Tailscale Services — 服务暴露配置

通过 Tailscale Services 为 GTR 上的本地服务分配独立的 MagicDNS 域名和虚拟 IP（TailVIP），在 Tailnet 内部通过 HTTPS 访问。

## 架构

```
Tailnet 设备 → https://<service>.tail414c32.ts.net/
                        │
                        │ Tailscale 自动路由到 TailVIP
                        │
              GTR (tailscale serve --service)
                        │
            ┌───────────┼───────────┬───────────┬───────────┬───────────┐
            │           │           │           │           │           │
        127.0.0.1:8190 localhost:3000 localhost:9090 localhost:8428 localhost:8429 localhost:9901
        (CFM)       (Grafana)    (Mihomo)    (VM)         (VL)       (Envoy)
```

**TailVIP 与 Envoy 无冲突**：Tailscale Services 使用独立虚拟 IP，Envoy 监听 `0.0.0.0:443` 在主机网络层，两者互不干扰。

## 服务列表

| Service 名称 | MagicDNS | TailVIP (IPv4) | 本地目标 |
|-------------|----------|---------------|---------|
| `svc:corp-finance-monitor` | `corp-finance-monitor.tail414c32.ts.net` | `动态分配` | `127.0.0.1:8190` |
| `svc:grafana` | `grafana.tail414c32.ts.net` | `动态分配` | localhost:3000 |
| `svc:mihomo-api` | `mihomo-api.tail414c32.ts.net` | `动态分配` | 127.0.0.1:9090 |
| `svc:victoriametrics` | `victoriametrics.tail414c32.ts.net` | `动态分配` | localhost:8428 |
| `svc:victorialogs` | `victorialogs.tail414c32.ts.net` | `动态分配` | localhost:8429 |
| `svc:envoy-admin` | `envoy-admin.tail414c32.ts.net` | `动态分配` | 127.0.0.1:9901 |

## 前置条件

- Tailscale >= v1.86.0（当前 GTR: v1.98.4）
- GTR 设备使用 tag 认证（当前: `tag:private`）
- Tailnet 已启用 HTTPS 和 Serve 功能
- 在 Admin Console 已定义对应的 Service

## 配置命令

### 添加 Service Host

```bash
# corp-finance-monitor
sudo tailscale serve --service=svc:corp-finance-monitor --https=443 http://127.0.0.1:8190

# Grafana
sudo tailscale serve --service=svc:grafana --https=443 http://localhost:3000

# Mihomo API
sudo tailscale serve --service=svc:mihomo-api --https=443 http://127.0.0.1:9090

# VictoriaMetrics
sudo tailscale serve --service=svc:victoriametrics --https=443 http://localhost:8428

# VictoriaLogs
sudo tailscale serve --service=svc:victorialogs --https=443 http://localhost:8429

# Envoy Admin
sudo tailscale serve --service=svc:envoy-admin --https=443 http://127.0.0.1:9901
```

### 查看状态

```bash
# 列表形式
tailscale serve status

# JSON 详细信息
tailscale serve status --json

# 查看 Service Host 能力和 TailVIP
tailscale status --json | jq '.Self.CapMap."service-host"'
```

### 移除配置

```bash
# 关闭某个 Service 的 endpoint
sudo tailscale serve --service=svc:grafana --https=443 off

# 清除某个 Service 的所有配置
sudo tailscale serve clear svc:grafana

# 重置所有 Serve 配置
sudo tailscale serve reset
```

### Drain（优雅下线）

```bash
# 停止接受新连接，等待现有连接关闭
sudo tailscale serve drain svc:grafana
```

## ACL 配置示例

在 Tailscale Admin Console 的 Access Controls 中添加 grants：

```json
{
  "grants": [
    {
      "src": ["autogroup:member"],
      "dst": ["svc:grafana"],
      "ip": ["443"]
    },
    {
      "src": ["tag:private"],
      "dst": ["svc:victoriametrics", "svc:victorialogs"],
      "ip": ["443"]
    },
    {
      "src": ["autogroup:admin"],
      "dst": ["svc:mihomo-api", "svc:envoy-admin"],
      "ip": ["443"]
    }
  ]
}
```

## Auto-Approval 策略（可选）

```json
{
  "autoApprovers": {
    "services": {
      "tag:private": ["tag:gtr-service"]
    }
  }
}
```

## 验证

```bash
# 健康检查
curl https://corp-finance-monitor.tail414c32.ts.net/healthz
curl https://grafana.tail414c32.ts.net/
curl https://victoriametrics.tail414c32.ts.net/health
curl https://victorialogs.tail414c32.ts.net/health

# Mihomo（需要 Bearer Token）
curl -H "Authorization: Bearer <token>" https://mihomo-api.tail414c32.ts.net/

# Envoy Admin
curl https://envoy-admin.tail414c32.ts.net/stats
```

## 故障排查

1. **Service 不可达**：检查 Admin Console -> Services 页面，确认 host 状态为 Connected
2. **403 / 无权限**：检查 ACL grants 是否正确配置
3. **502 Bad Gateway**：检查本地服务是否运行：`systemctl status <service>`
4. **证书问题**：HTTPS 证书由 Tailscale 自动管理，无需手动配置
5. **TailVIP 不出现**：检查 `tailscale serve status --json` 确认配置已写入

## Exit Node 配置

GTR 可作为 Tailscale Exit Node，Tailnet 设备可通过 GTR 的 Mihomo 代理上网。

**重要：** 如果客户端和 GTR 在同一个本地网段（例如都在 `192.168.31.0/24`），客户端启用 exit node 时必须同时开启 `Allow Local Network Access`，否则客户端访问 `192.168.31.59` 这样的 LAN 地址也会被送进 exit node，表现为无法直连 GTR 的本地地址。

### 架构

```
Tailnet 设备 (exit-node=gtr)
        │
        │ Tailscale 加密隧道
        │
    GTR Server
        │
        │ Mihomo TUN 模式（处理出口流量，保留本地/Tailscale 直连）
        │
    Mihomo 规则路由
        │
    ┌───┼───────────────────┐
    │   │                   │
    AI  General(容错链)    DIRECT
    (直连) (dialer-proxy 链) (本地/Tailscale)
```

### 启用 Exit Node（GTR 端）

```bash
ssh gtr
sudo tailscale set --advertise-exit-node

# 如需保持 GTR 不接受 Tailnet DNS，可额外设置
sudo tailscale set --accept-dns=false
```

### 客户端使用

```bash
# 启用 exit node 但保留本地 LAN 直连（推荐）
tailscale set --exit-node=gtr --exit-node-allow-lan-access

# 启用 exit node，连本地 LAN 也通过 exit node
tailscale set --exit-node=gtr

# 关闭 exit node（回退到原始网络）
tailscale up --exit-node=
```

### ACL 配置

在 Tailscale Admin Console 的 Access Controls 中添加：

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

### 预期行为

1. **代理链故障**：Mihomo 的 `General` fallback 组会在链式代理、普通 `Auto` 和 `DIRECT` 之间切换，这一层发生在 GTR 本机。
2. **客户端本地 LAN 访问**：默认关闭。客户端若需继续访问本地网关、打印机或与 GTR 同网段的 `192.168.x.x` 地址，必须启用 `--exit-node-allow-lan-access`。
3. **Exit node / 路由设备故障**：不要假设客户端会自动回退到原始网络。Tailscale 对路由设备存在 fail-close 场景，故障时可能直接中断，需要手动关闭 exit node、切换备用 exit node，或等待路由恢复。

### 流量路由策略

| 流量类型 | 代理组 | 策略 |
|---------|--------|------|
| AI 服务（OpenAI/Claude/Gemini 等） | AI (fallback) | 直连，不走链式路由 |
| Google 服务 | AI (fallback) | 同 AI 组（Gemini 需要） |
| GitHub | GitHub (url-test) | 最快节点，速度优先 |
| Streaming | Streaming (url-test) | 最快节点，速度优先 |
| Telegram | General (fallback) | relay 链容错，可靠性优先 |
| Microsoft/Apple/社交/开发工具 | General (fallback) | relay 链容错 |
| 中国服务 | Auto-CN (DIRECT) | 直连 |
| Tailscale/本地网络 | DIRECT | GTR 端直连，不经过代理 |
| 客户端本地 LAN | 本地直连 | 仅在客户端启用 `--exit-node-allow-lan-access` 后保留 |

### 故障排查

```bash
# 检查 exit node 状态
tailscale status

# 检查 Mihomo TUN 接口
ssh gtr "ip addr show | grep tun"

# 检查 Mihomo TUN 路由
ssh gtr "ip route show table all | grep -i mihomo"

# 测试出口 IP
curl https://api.ipify.org   # 应显示代理出口 IP

# 同 LAN 客户端测试本地网络保留
tailscale status | grep -i "exit node"
ping 192.168.31.59            # 需先启用 --exit-node-allow-lan-access

# 关闭 exit node 后恢复原始网络
tailscale up --exit-node=
```

## 注意事项

- VictoriaMetrics / VictoriaLogs 无内置认证，依赖 Tailscale ACL 保护
- Mihomo API 有双重保护：Tailscale ACL + Bearer Token
- 现有边缘节点通过 `gtr.tail414c32.ts.net:8429` 推送数据的连接不受影响
- Service 配置在重启后自动恢复（`--service` 默认后台运行）
- GTR 端 Mihomo TUN 仅应使用 `auto-route`，不要启用 `auto-redirect`
- GTR 端 `192.168/10/172.16` 与 `100.64.0.0/10` 需继续排除在 TUN 之外
- `--exit-node-allow-lan-access` 控制的是客户端本地 LAN 保留，不是 GTR 端的 TUN 排除行为
