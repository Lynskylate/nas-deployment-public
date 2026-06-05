# 客户端部署指南

本文档描述如何在 GTR 服务器上部署 Shadowsocks + Shadow-TLS 客户端及 Envoy SNI 透传配置。

## 服务器信息

- **服务器**: gtr
- **SSH 用户**: ubuntu
- **操作系统**: Ubuntu 22.04 LTS
- **现有服务**: Grafana, VictoriaMetrics, VictoriaLogs, Vector, Envoy

## 部署步骤

### 方法 1: 使用 Ansible（推荐）

```bash
cd /path/to/gtr-services/shadowsocks-shadowtls

# 测试连接
ansible -i ansible/inventory.ini client_server -m ping

# 部署
./deploy.sh client
```

### 方法 2: 手动部署

#### 1. 安装 Shadowsocks-Rust Client

```bash
# SSH 登录 GTR
ssh gtr

# 下载并安装
wget https://github.com/shadowsocks/shadowsocks-rust/releases/download/v1.18.2/shadowsocks-v1.18.2.x86_64-unknown-linux-gnu.tar.xz
tar xf shadowsocks-v1.18.2.x86_64-unknown-linux-gnu.tar.xz
sudo mkdir -p /usr/local/shadowsocks-client
sudo mv sslocal /usr/local/shadowsocks-client/
sudo chmod +x /usr/local/shadowsocks-client/sslocal

# 创建用户
sudo useradd --system --shell /usr/sbin/nologin shadowsocks
sudo mkdir -p /var/lib/shadowsocks
sudo chown shadowsocks:shadowsocks /var/lib/shadowsocks
```

**创建配置文件** `/etc/shadowsocks/client.json`:
```json
{
    "server": "127.0.0.1",
    "server_port": 8443,
    "password": "<render-from-private-vault>",
    "timeout": 300,
    "method": "aes-256-gcm",
    "local_address": "127.0.0.1",
    "local_port": 1080,
    "fast_open": true
}
```

**创建 systemd 服务** `/etc/systemd/system/shadowsocks-client.service`:
```ini
[Unit]
Description=Shadowsocks-Rust Client
After=network-online.target shadow-tls-client.service
Wants=network-online.target
Requires=shadow-tls-client.service

[Service]
Type=simple
User=shadowsocks
Group=shadowsocks
ExecStart=/usr/local/shadowsocks-client/sslocal -c /etc/shadowsocks/client.json
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/shadowsocks

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable shadowsocks-client
# 注意: 不要启动，需要等待 shadow-tls-client 先启动
```

#### 2. 安装 Shadow-TLS Client

```bash
# 下载并安装
wget https://github.com/ihciah/shadow-tls/releases/download/v0.2.25/shadow-tls-x86_64-unknown-linux-gnu.tar.xz
tar xf shadow-tls-x86_64-unknown-linux-gnu.tar.xz
sudo mkdir -p /usr/local/shadow-tls-client
sudo mv shadow-tls /usr/local/shadow-tls-client/
sudo chmod +x /usr/local/shadow-tls-client/shadow-tls

# 创建用户
sudo useradd --system --shell /usr/sbin/nologin shadowtls
```

**创建 systemd 服务** `/etc/systemd/system/shadow-tls-client.service`:
```ini
[Unit]
Description=Shadow-TLS Client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=shadowtls
Group=shadowtls
ExecStart=/usr/local/shadow-tls-client/shadow-tls \
    client \
    --listen 127.0.0.1:8443 \
    --server 142.171.205.19:443 \
    --tls www.microsoft.com:443 \
    --password <render-from-private-vault> \
    --v3
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable shadow-tls-client
sudo systemctl start shadow-tls-client
sudo systemctl start shadowsocks-client

# 验证
sudo systemctl status shadow-tls-client shadowsocks-client
ss -tulnp | grep -E ':(1080|8443)'
```

#### 3. 配置 Envoy SNI 透传

**备份现有配置**:
```bash
sudo cp -r /etc/envoy /etc/envoy.backup-$(date +%s)
```

**更新 Listener 配置** `/etc/envoy/dynamic_config/lds.yaml`:

在 `resources` 数组中添加新的 listener:

```yaml
resources:
  # ... 现有的 listener_0 (端口 80) ...

  - "@type": type.googleapis.com/envoy.config.listener.v3.Listener
    name: listener_443
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 443
    listener_filters:
      - name: envoy.filters.listener.tls_inspector
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.listener.tls_inspector.v3.TlsInspector
    filter_chains:
      - filter_chain_match:
          server_names: ["www.microsoft.com", "*.microsoft.com"]
        filters:
          - name: envoy.filters.network.tcp_proxy
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.tcp_proxy.v3.TcpProxy
              stat_prefix: shadow_tls_passthrough
              cluster: shadow_tls_client
      # 未来可添加其他 filter_chain 用于其他 SNI
```

**更新 Cluster 配置** `/etc/envoy/dynamic_config/cds.yaml`:

在 `resources` 数组中添加新的 cluster:

```yaml
resources:
  # ... 现有的 clusters ...

  - "@type": type.googleapis.com/envoy.config.cluster.v3.Cluster
    name: shadow_tls_client
    connect_timeout: 5s
    type: STATIC
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: shadow_tls_client
      endpoints:
        - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: 127.0.0.1
                    port_value: 8443
    upstream_connection_options:
      tcp_keepalive: {}
```

#### 4. 更新 Envoy systemd 服务

编辑 `/etc/systemd/system/envoy.service`:

在 `[Unit]` 部分的 `After=` 行添加依赖:

```ini
[Unit]
Description=Envoy Proxy
After=network-online.target shadow-tls-client.service shadowsocks-client.service
Wants=network-online.target
Requires=shadow-tls-client.service
```

```bash
# 重新加载 systemd 并重启 Envoy
sudo systemctl daemon-reload
sudo systemctl restart envoy

# 验证
sudo systemctl status envoy
curl http://localhost:9901/listeners | jq '.[] | select(.name | contains("443"))'
```

## 验证部署

### 检查服务状态

```bash
systemctl status shadow-tls-client
systemctl status shadowsocks-client
systemctl status envoy
```

### 检查端口监听

```bash
ss -tulnp | grep -E ':(1080|8443|443)'
```

预期输出：
```
tcp   LISTEN 0    4096    127.0.0.1:1080       0.0.0.0:*       users:(("sslocal",pid=xxx,fd=...))
tcp   LISTEN 0    4096    127.0.0.1:8443       0.0.0.0:*       users:(("shadow-tls",pid=xxx,fd=...))
tcp   LISTEN 0    4096    0.0.0.0:443          0.0.0.0:*       users:(("envoy",pid=xxx,fd=...))
```

### 检查 Envoy 配置

```bash
# 检查 listeners
curl http://localhost:9901/listeners | jq

# 检查 cluster
curl http://localhost:9901/clusters | jq '.cluster_statuses[] | select(.name=="shadow_tls_client")'
```

### 测试代理连接

```bash
# 测试 SOCKS5 代理
curl --socks5 127.0.0.1:1080 https://api.ipify.org

# 应该返回远程服务器的 IP (142.171.205.19)

# 测试访问网站
curl --socks5 127.0.0.1:1080 https://www.google.com
```

### 查看日志

```bash
# 实时查看日志
journalctl -u shadow-tls-client -f
journalctl -u shadowsocks-client -f
journalctl -u envoy -f
```

## 维护操作

### 重启服务

```bash
# 按依赖顺序重启
sudo systemctl restart shadowsocks-client
sudo systemctl restart shadow-tls-client
sudo systemctl restart envoy
```

### 查看连接状态

```bash
# SOCKS5 连接数
ss -tn | grep :1080 | wc -l

# Shadow-TLS 连接数
ss -tn | grep :8443 | wc -l

# Envoy 443 端口连接数
ss -tn | grep :443 | wc -l
```

### 测试代理性能

```bash
# 测试延迟
time curl --socks5 127.0.0.1:1080 https://www.google.com

# 测试带宽
curl --socks5 127.0.0.1:1080 -o /dev/null http://speedtest.tele2.net/10MB.zip
```

## 集成现有监控

### 添加到 VictoriaMetrics

创建文本收集器:

```bash
sudo mkdir -p /var/lib/node_exporter/textfile-collector

cat > /var/lib/node_exporter/textfile-collector/ss_proxy.prom <<'EOF'
# HELP shadowsocks_up Shadowsocks service status
# TYPE shadowsocks_up gauge
shadowsocks_up{instance="client"} $(systemctl is-active shadowsocks-client | grep -q active && echo 1 || echo 0)

# HELP shadowtls_up Shadow-TLS service status
# TYPE shadowtls_up gauge
shadowtls_up{instance="client"} $(systemctl is-active shadow-tls-client | grep -q active && echo 1 || echo 0)

# HELP socks5_connections Current SOCKS5 connections
# TYPE socks5_connections gauge
socks5_connections $(ss -tn | grep :1080 | wc -l)
EOF

sudo chmod +x /var/lib/node_exporter/textfile-collector/ss_proxy.prom
```

添加定时任务更新指标:

```bash
sudo crontab -e
# 添加: */1 * * * * /usr/local/bin/update-ss-metrics.sh
```

## 故障排查

### 服务无法启动

```bash
# 检查依赖
systemctl list-dependencies envoy.service

# 检查端口占用
sudo lsof -i :443
sudo lsof -i :8443
sudo lsof -i :1080

# 检查日志
journalctl -u shadow-tls-client -n 50
journalctl -u shadowsocks-client -n 50
```

### Envoy 503 错误

```bash
# 检查 cluster 健康
curl http://localhost:9901/clusters

# 检查上游服务
systemctl status shadow-tls-client

# 测试上游连接
nc -zv 127.0.0.1 8443
```

### SNI 路由不工作

```bash
# 检查 listener 配置
curl http://localhost:9901/listeners | jq '.[] | select(.name=="listener_443")'

# 验证 TLS Inspector
grep -A 5 "tls_inspector" /etc/envoy/dynamic_config/lds.yaml

# 测试 SNI 路由
openssl s_client -connect localhost:443 -servername www.microsoft.com
```

更多故障排查步骤请参考 [troubleshooting.md](../troubleshooting.md)。

## 回滚计划

如果部署导致问题：

```bash
# 1. 停止新服务
sudo systemctl stop shadow-tls-client shadowsocks-client

# 2. 恢复 Envoy 配置
LATEST_BACKUP=$(ls -t /etc/envoy.backup-* | head -1)
sudo cp -r $LATEST_BACKUP/* /etc/envoy/

# 3. 重启 Envoy
sudo systemctl restart envoy

# 4. 验证
curl http://localhost:9901/listeners
ss -tulnp | grep 443
```

## 卸载

```bash
# 停止服务
sudo systemctl stop shadow-tls-client shadowsocks-client
sudo systemctl disable shadow-tls-client shadowsocks-client

# 删除服务文件
sudo rm /etc/systemd/system/shadowsocks-client.service
sudo rm /etc/systemd/system/shadow-tls-client.service

# 删除二进制文件
sudo rm -rf /usr/local/shadowsocks-client
sudo rm -rf /usr/local/shadow-tls-client

# 删除配置
sudo rm -rf /etc/shadowsocks

# 删除用户
sudo userdel shadowsocks
sudo userdel shadowtls

# 恢复 Envoy 配置（移除 443 listener）
sudo vim /etc/envoy/dynamic_config/lds.yaml
sudo vim /etc/envoy/dynamic_config/cds.yaml

# 重载 systemd
sudo systemctl daemon-reload
sudo systemctl restart envoy
```
