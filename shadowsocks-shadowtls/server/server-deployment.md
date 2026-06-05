# 服务器端部署指南

本文档描述如何在远程服务器 (142.171.205.19) 上部署 Shadowsocks + Shadow-TLS 服务。

## 服务器信息

- **IP 地址**: 142.171.205.19
- **SSH 用户**: root
- **操作系统**: Ubuntu 22.04 LTS

## 部署步骤

### 方法 1: 使用 Ansible（推荐）

```bash
cd /path/to/gtr-services/shadowsocks-shadowtls

# 配置 inventory
cat > ansible/inventory.ini <<'EOF'
[remote_server]
142.171.205.19 ansible_user=root ansible_port=22

[client_server]
gtr ansible_user=ubuntu
EOF

# 测试连接
ansible -i ansible/inventory.ini remote_server -m ping

# 部署
./deploy.sh server
```

### 方法 2: 手动部署

#### 1. 安装 Shadowsocks-Rust Server

```bash
# SSH 登录
ssh root@142.171.205.19

# 下载并安装
wget https://github.com/shadowsocks/shadowsocks-rust/releases/download/v1.18.2/shadowsocks-v1.18.2.x86_64-unknown-linux-gnu.tar.xz
tar xf shadowsocks-v1.18.2.x86_64-unknown-linux-gnu.tar.xz
sudo mkdir -p /usr/local/shadowsocks-server
sudo mv ssserver /usr/local/shadowsocks-server/
sudo chmod +x /usr/local/shadowsocks-server/ssserver

# 创建用户
sudo useradd --system --shell /usr/sbin/nologin shadowsocks
sudo mkdir -p /var/lib/shadowsocks
sudo chown shadowsocks:shadowsocks /var/lib/shadowsocks
```

**创建配置文件** `/etc/shadowsocks/config.json`:
```json
{
    "server": "127.0.0.1",
    "server_port": 8388,
    "password": "<render-from-private-vault>",
    "timeout": 300,
    "method": "aes-256-gcm",
    "fast_open": true,
    "nameserver": "8.8.8.8",
    "mode": "tcp_and_udp"
}
```

**创建 systemd 服务** `/etc/systemd/system/shadowsocks-server.service`:
```ini
[Unit]
Description=Shadowsocks-Rust Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=shadowsocks
Group=shadowsocks
ExecStart=/usr/local/shadowsocks-server/ssserver -c /etc/shadowsocks/config.json
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
sudo systemctl enable shadowsocks-server
sudo systemctl start shadowsocks-server
sudo systemctl status shadowsocks-server
```

#### 2. 安装 Shadow-TLS Server

```bash
# 下载并安装
wget https://github.com/ihciah/shadow-tls/releases/download/v0.2.25/shadow-tls-x86_64-unknown-linux-gnu.tar.xz
tar xf shadow-tls-x86_64-unknown-linux-gnu.tar.xz
sudo mkdir -p /usr/local/shadow-tls-server
sudo mv shadow-tls /usr/local/shadow-tls-server/
sudo chmod +x /usr/local/shadow-tls-server/shadow-tls

# 创建用户
sudo useradd --system --shell /usr/sbin/nologin shadowtls
```

**创建 systemd 服务** `/etc/systemd/system/shadow-tls-server.service`:
```ini
[Unit]
Description=Shadow-TLS Server
After=network-online.target shadowsocks-server.service
Wants=network-online.target
Requires=shadowsocks-server.service

[Service]
Type=simple
User=shadowtls
Group=shadowtls
ExecStart=/usr/local/shadow-tls-server/shadow-tls \
    server \
    --listen 0.0.0.0:443 \
    --server 127.0.0.1:8388 \
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
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable shadow-tls-server
sudo systemctl start shadow-tls-server
sudo systemctl status shadow-tls-server
```

#### 3. 防火墙配置

```bash
# 开放 443 端口
sudo ufw allow 443/tcp
sudo ufw allow 443/udp

# 验证
sudo ufw status
ss -tulnp | grep -E ':(443|8388)'
```

## 验证部署

### 检查服务状态

```bash
systemctl status shadowsocks-server
systemctl status shadow-tls-server
```

### 检查端口监听

```bash
ss -tulnp | grep -E ':(443|8388)'
```

预期输出：
```
tcp   LISTEN 0    4096         127.0.0.1:8388       0.0.0.0:*       users:(("ssserver",pid=xxx,fd=...))
tcp   LISTEN 0    4096         0.0.0.0:443          0.0.0.0:*       users:(("shadow-tls",pid=xxx,fd=...))
```

### 查看日志

```bash
journalctl -u shadowsocks-server -f
journalctl -u shadow-tls-server -f
```

### 测试 TLS 连接

```bash
openssl s_client -connect 142.171.205.19:443 -servername www.microsoft.com
```

## 维护操作

### 重启服务

```bash
# 按依赖顺序重启
sudo systemctl restart shadowsocks-server
sudo systemctl restart shadow-tls-server
```

### 更新配置

```bash
# 编辑配置文件
vim /etc/shadowsocks/config.json

# 重启服务
sudo systemctl restart shadowsocks-server
```

### 查看统计信息

```bash
# 连接数
ss -tn | grep :443 | wc -l

# 流量统计（如果启用）
# TODO: 集成 VictoriaMetrics 监控
```

## 安全检查

### 1. 验证端口绑定

```bash
# 确保 Shadowsocks 只监听 localhost
ss -tulnp | grep 8388
# 应该显示: 127.0.0.1:8388

# 确保 Shadow-TLS 监听所有接口
ss -tulnp | grep ':443'
# 应该显示: 0.0.0.0:443
```

### 2. 验证防火墙

```bash
sudo ufw status verbose
```

### 3. 检查日志异常

```bash
journalctl -u shadow-tls-server -n 100 --no-pager | grep -i error
journalctl -u shadowsocks-server -n 100 --no-pager | grep -i error
```

## 故障排查

### 服务无法启动

```bash
# 检查日志
journalctl -u shadowsocks-server -n 50
journalctl -u shadow-tls-server -n 50

# 检查配置文件
python3 -m json.tool /etc/shadowsocks/config.json

# 检查端口占用
sudo lsof -i :8388
sudo lsof -i :443
```

### 连接问题

```bash
# 检查服务是否运行
systemctl status shadowsocks-server shadow-tls-server

# 检查防火墙
sudo ufw status

# 测试端口
nc -zv 142.171.205.19 443
```

更多故障排查步骤请参考 [troubleshooting.md](../troubleshooting.md)。

## 卸载

```bash
# 停止服务
sudo systemctl stop shadow-tls-server shadowsocks-server
sudo systemctl disable shadow-tls-server shadowsocks-server

# 删除服务文件
sudo rm /etc/systemd/system/shadowsocks-server.service
sudo rm /etc/systemd/system/shadow-tls-server.service

# 删除二进制文件
sudo rm -rf /usr/local/shadowsocks-server
sudo rm -rf /usr/local/shadow-tls-server

# 删除配置
sudo rm -rf /etc/shadowsocks

# 删除用户
sudo userdel shadowsocks
sudo userdel shadowtls

# 重载 systemd
sudo systemctl daemon-reload
```
