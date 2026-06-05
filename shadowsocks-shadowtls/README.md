# Shadowsocks + Shadow-TLS 代理服务运行手册

本文档记录了 GTR 服务器上部署的 Shadowsocks-Rust + Shadow-TLS 代理方案的运维操作。

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        远程服务器 (142.171.205.19)                      │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  shadowsocks-rust server (127.0.0.1:8388)                         │ │
│  │  - 加密: aes-256-gcm                                               │ │
│  └────────────────────────────┬───────────────────────────────────────┘ │
│                               │                                          │
│  ┌────────────────────────────▼───────────────────────────────────────┐ │
│  │  shadow-tls server (0.0.0.0:443)                                  │ │
│  │  - SNI 伪装: www.microsoft.com:443                                │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Internet (TLS 伪装)
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│                           GTR 客户端服务器                                │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │  Envoy Proxy (0.0.0.0:443) - SNI 透传                             │ │
│  └────────────────────────────┬───────────────────────────────────────┘ │
│                               │                                          │
│  ┌────────────────────────────▼───────────────────────────────────────┐ │
│  │  shadow-tls client (127.0.0.1:8443)                               │ │
│  └────────────────────────────┬───────────────────────────────────────┘ │
│                               │                                          │
│  ┌────────────────────────────▼───────────────────────────────────────┐ │
│  │  shadowsocks-rust client (127.0.0.1:1080)                         │ │
│  │  - SOCKS5 代理端点                                                 │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

## 服务组件

### 服务器端 (142.171.205.19)

| 服务 | 监听地址 | 端口 | 用途 |
|------|----------|------|------|
| shadowsocks-rust server | 127.0.0.1 | 8388 | Shadowsocks 协议 |
| shadow-tls server | 0.0.0.0 | 443 | TLS 伪装入口 |

### 客户端 (GTR)

| 服务 | 监听地址 | 端口 | 用途 |
|------|----------|------|------|
| Envoy (TLS 透传) | 0.0.0.0 | 443 | SNI 路由 |
| shadow-tls client | 127.0.0.1 | 8443 | 连接远程服务器 |
| shadowsocks-rust client | 127.0.0.1 | 1080 | SOCKS5 代理 |

## 快速操作

### 查看服务状态

```bash
# 客户端 (GTR)
systemctl status shadow-tls-client shadowsocks-client envoy

# 服务器端 (142.171.205.19)
systemctl status shadow-tls-server shadowsocks-server
```

### 查看端口监听

```bash
# GTR 客户端
ss -tulnp | grep -E ':(443|1080|8443)'

# 服务器端
ss -tulnp | grep -E ':(443|8388)'
```

### 重启服务

```bash
# GTR 客户端 - 按依赖顺序重启
sudo systemctl restart shadowsocks-client
sudo systemctl restart shadow-tls-client
sudo systemctl restart envoy

# 服务器端 - 按依赖顺序重启
sudo systemctl restart shadowsocks-server
sudo systemctl restart shadow-tls-server
```

### 查看日志

```bash
# 实时查看日志
journalctl -u shadow-tls-client -f
journalctl -u shadowsocks-client -f
journalctl -u envoy -f

# 查看最近 50 条
journalctl -u shadow-tls-client -n 50
journalctl -u shadowsocks-client -n 50
```

### 测试代理连接

```bash
# 测试 SOCKS5 代理
curl --socks5 127.0.0.1:1080 https://api.ipify.org

# 测试访问网站
curl --socks5 127.0.0.1:1080 https://www.google.com
```

## 配置文件路径

### 服务器端 (142.171.205.19)

| 文件 | 路径 |
|------|------|
| Shadowsocks 配置 | `/etc/shadowsocks/config.json` |
| Shadowsocks 服务 | `/etc/systemd/system/shadowsocks-server.service` |
| Shadow-TLS 服务 | `/etc/systemd/system/shadow-tls-server.service` |

### 客户端 (GTR)

| 文件 | 路径 |
|------|------|
| Shadowsocks 配置 | `/etc/shadowsocks/client.json` |
| Shadowsocks 服务 | `/etc/systemd/system/shadowsocks-client.service` |
| Shadow-TLS 服务 | `/etc/systemd/system/shadow-tls-client.service` |
| Envoy Listener 配置 | `/etc/envoy/dynamic_config/lds.yaml` |
| Envoy Cluster 配置 | `/etc/envoy/dynamic_config/cds.yaml` |
| Envoy 服务 | `/etc/systemd/system/envoy.service` |

## 环境变量

部署时使用的密码（存储在服务器上，请妥善保管）：

```bash
# Shadowsocks 密码
SHADOWSOCKS_PASSWORD=<render-from-private-vault>

# Shadow-TLS 密码
SHADOW_TLS_PASSWORD=<render-from-private-vault>
```

## 安全注意事项

1. **端口保护**: Shadowsocks 和 Shadow-TLS 仅监听 localhost，除 Envoy 外无对外暴露
2. **密码安全**: 使用强随机密码，定期更换
3. **日志监控**: 定期检查连接日志，发现异常活动
4. **SNI 伪装**: 使用 www.microsoft.com 进行流量伪装
5. **Admin 保护**: Envoy admin 端口 9901 不暴露到公网

## 故障排查

详见 [troubleshooting.md](./troubleshooting.md)

## 回滚计划

如果服务出现问题，参考 [troubleshooting.md](./troubleshooting.md) 中的回滚步骤。

## 部署历史

- **2025-01-XX**: 初始部署
  - shadowsocks-rust v1.18.2
  - shadow-tls v0.2.25
  - Envoy SNI passthrough 配置
