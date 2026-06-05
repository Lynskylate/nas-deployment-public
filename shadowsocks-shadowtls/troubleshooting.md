# Shadowsocks + Shadow-TLS 故障排查指南

## 快速诊断流程

### 1. 检查服务状态

```bash
# 服务器端 (142.171.205.19)
systemctl status shadowsocks-server
systemctl status shadow-tls-server

# 客户端 (GTR)
systemctl status shadow-tls-client
systemctl status shadowsocks-client
systemctl status envoy
```

### 2. 检查端口监听

```bash
# 服务器端
ss -tulnp | grep -E ':(443|8388)'

# 客户端
ss -tulnp | grep -E ':(443|1080|8443)'
```

### 3. 查看日志

```bash
# 实时查看日志
journalctl -u shadow-tls-client -f
journalctl -u shadowsocks-client -f
journalctl -u envoy -f

# 查看最近 50 条
journalctl -u shadow-tls-client -n 50 --no-pager
```

## 常见问题

### 问题 1: TLS 握手失败

**症状**: 客户端无法建立 TLS 连接，日志显示握手错误

**排查步骤**:

```bash
# 1. 测试远程服务器 TLS 端口
openssl s_client -connect 142.171.205.19:443 -servername www.microsoft.com

# 2. 检查 shadow-tls 服务端日志
journalctl -u shadow-tls-server -n 50

# 3. 检查 shadow-tls 客户端日志
journalctl -u shadow-tls-client -n 50

# 4. 验证密码一致性
# 服务器端
grep -r password /etc/systemd/system/shadow-tls*

# 客户端
grep -r password /etc/systemd/system/shadow-tls*
```

**可能原因**:
- 密码不匹配
- SNI 服务器配置错误
- 防火墙阻止 443 端口
- shadow-tls 版本不兼容

**解决方案**:
```bash
# 重新生成密码并更新配置
SS_PASSWORD=$(openssl rand -base64 32)
TLS_PASSWORD=$(openssl rand -base64 32)

# 更新 Ansible vars
vim ansible/group_vars/all/public.yml

# 重新部署
ansible-playbook -i ansible/inventory.ini ansible/server-deploy.yml
ansible-playbook -i ansible/inventory.ini ansible/client-deploy.yml
```

### 问题 2: 连接被拒绝 (Connection Refused)

**症状**: 无法连接到端口，连接被拒绝

**排查步骤**:

```bash
# 1. 检查服务是否运行
systemctl status shadow-tls-client
systemctl status shadowsocks-client

# 2. 检查服务依赖
systemctl list-dependencies envoy.service

# 3. 检查端口占用
ss -tulnp | grep -E ':(443|8443|1080)'

# 4. 检查防火墙
sudo ufw status
# 或
iptables -L -n | grep -E ':443'
```

**可能原因**:
- 服务未启动
- 服务依赖问题
- 端口被占用
- 防火墙规则

**解决方案**:
```bash
# 按正确顺序重启服务
sudo systemctl restart shadowsocks-client
sudo systemctl restart shadow-tls-client
sudo systemctl restart envoy

# 检查服务依赖
sudo systemctl edit envoy.service
# 确保 After= 包含 shadow-tls-client.service
```

### 问题 3: Shadowsocks 认证失败

**症状**: SOCKS5 代理连接成功但流量无法通过

**排查步骤**:

```bash
# 1. 验证密码一致性
# 服务器端
cat /etc/shadowsocks/config.json | grep password

# 客户端
cat /etc/shadowsocks/client.json | grep password

# 2. 检查加密方法
grep method /etc/shadowsocks/*.json

# 3. 查看日志
journalctl -u shadowsocks-client -n 50
journalctl -u shadowsocks-server -n 50
```

**可能原因**:
- 密码不匹配
- 加密方法不一致
- 配置文件格式错误

**解决方案**:
```bash
# 验证 JSON 格式
python3 -m json.tool /etc/shadowsocks/client.json
python3 -m json.tool /etc/shadowsocks/config.json

# 更新密码为一致值
vim /etc/shadowsocks/client.json
vim /etc/shadowsocks/config.json

# 重启服务
sudo systemctl restart shadowsocks-client
sudo systemctl restart shadowsocks-server
```

### 问题 4: Envoy 503 错误

**症状**: Envoy 返回 503 Service Unavailable

**排查步骤**:

```bash
# 1. 检查 cluster 健康状态
curl http://localhost:9901/clusters | jq '.cluster_statuses[] | select(.name=="shadow_tls_client")'

# 2. 检查上游服务
systemctl status shadow-tls-client

# 3. 查看 Envoy 日志
journalctl -u envoy -n 50

# 4. 检查 listener 配置
curl http://localhost:9901/listeners | jq '.[] | select(.name | contains("443"))'
```

**可能原因**:
- 上游服务未启动
- Cluster 配置错误
- 端口配置错误

**解决方案**:
```bash
# 1. 确保 shadow-tls-client 运行
sudo systemctl start shadow-tls-client

# 2. 验证端口配置
# 检查 cds.yaml 中的 port_value 是否为 8443
grep -A 10 "shadow_tls_client" /etc/envoy/dynamic_config/cds.yaml

# 3. 重启 Envoy
sudo systemctl restart envoy

# 4. 检查配置
curl http://localhost:9901/clusters
```

### 问题 5: 代理连接超时

**症状**: 通过 SOCKS5 代理连接超时

**排查步骤**:

```bash
# 1. 测试本地 SOCKS5
curl --socks5 127.0.0.1:1080 https://api.ipify.org

# 2. 测试 shadow-tls 连接
telnet 127.0.0.1 8443

# 3. 测试远程服务器连接
timeout 5 nc -zv 142.171.205.19 443

# 4. 查看连接日志
journalctl -u shadow-tls-client -f
journalctl -u shadowsocks-client -f
```

**可能原因**:
- 网络连接问题
- 远程服务器不可达
- 防火墙阻止

**解决方案**:
```bash
# 1. 检查路由
ping 142.171.205.19

# 2. 测试端口
nc -zv 142.171.205.19 443

# 3. 检查 traceroute
traceroute 142.171.205.19

# 4. 如果是网络问题，检查服务器端防火墙
# 在 142.171.205.19 上
sudo ufw status
```

### 问题 6: SNI 路由不工作

**症状**: Envoy 无法正确路由基于 SNI 的流量

**排查步骤**:

```bash
# 1. 检查 Envoy listener 配置
curl http://localhost:9901/listeners | jq '.[] | select(.name=="listener_443")'

# 2. 验证 filter_chain_match
grep -A 20 "listener_443" /etc/envoy/dynamic_config/lds.yaml

# 3. 检查 tls_inspector 是否启用
grep -A 5 "tls_inspector" /etc/envoy/dynamic_config/lds.yaml
```

**可能原因**:
- TLS Inspector 未配置
- SNI 匹配规则错误
- Listener 配置问题

**解决方案**:
```bash
# 1. 验证 LDS 配置格式
# 确保 listener_filters 包含 tls_inspector

# 2. 验证 server_names 匹配
# 确保 filter_chain_match.server_names 包含正确的 SNI

# 3. 重新加载配置
sudo systemctl reload envoy

# 4. 如果配置文件被破坏，回滚
sudo cp -r /etc/envoy.backup-*/lds.yaml /etc/envoy/dynamic_config/
sudo systemctl restart envoy
```

## 回滚程序

如果部署导致严重问题，执行以下回滚步骤：

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

# 5. 如果需要完全卸载
sudo systemctl disable shadow-tls-client shadowsocks-client
sudo rm -f /etc/systemd/system/shadow*-client.service
sudo systemctl daemon-reload
```

## 性能问题

### 代理速度慢

```bash
# 1. 检查系统资源
htop
iostat -x 1

# 2. 检查网络延迟
ping 142.171.205.19

# 3. 查看连接数
ss -s

# 4. 检查日志级别
# 调整为 warning 或 error 减少日志输出
```

### 连接数过多

```bash
# 1. 查看当前连接
ss -tan | grep :1080 | wc -l

# 2. 查看连接状态分布
ss -tan | grep :1080 | awk '{print $1}' | sort | uniq -c

# 3. 检查是否有异常连接
ss -tanp | grep :1080
```

## 监控建议

### 1. 设置日志监控

```bash
# 创建日志监控脚本
cat > /usr/local/bin/check-ss-status.sh <<'EOF'
#!/bin/bash
# 检查服务状态
systemctl is-active shadow-tls-client || echo "shadow-tls-client is down"
systemctl is-active shadowsocks-client || echo "shadowsocks-client is down"
systemctl is-active envoy || echo "envoy is down"

# 检查端口
ss -tulnp | grep -q ':1080' || echo "SOCKS5 port not listening"
ss -tulnp | grep -q ':8443' || echo "shadow-tls client port not listening"
ss -tulnp | grep -q ':443' || echo "Envoy TLS port not listening"
EOF

chmod +x /usr/local/bin/check-ss-status.sh
```

### 2. 设置定时任务

```bash
# 每 5 分钟检查一次
crontab -e
# 添加: */5 * * * * /usr/local/bin/check-ss-status.sh
```

### 3. 集成到现有监控

如果使用 VictoriaMetrics，可以添加以下监控：

```bash
# 添加到 node_exporter textfile collector
cat > /var/lib/node_exporter/textfile-collector/ss_status.prom <<'EOF'
# HELP shadowsocks_up Shadowsocks service status
# TYPE shadowsocks_up gauge
shadowsocks_up{instance="client"} $(systemctl is-active shadowsocks-client | grep -q active && echo 1 || echo 0)
shadowsocks_up{instance="server"} $(systemctl is-active shadowsocks-server 2>/dev/null | grep -q active && echo 1 || echo 0)

# HELP shadowtls_up Shadow-TLS service status
# TYPE shadowtls_up gauge
shadowtls_up{instance="client"} $(systemctl is-active shadow-tls-client | grep -q active && echo 1 || echo 0)
shadowtls_up{instance="server"} $(systemctl is-active shadow-tls-server 2>/dev/null | grep -q active && echo 1 || echo 0)
EOF
```

## 联系支持

如果以上步骤无法解决问题，请收集以下信息：

```bash
# 收集诊断信息
bash > /tmp/ss-diagnostics.txt <<'EOF'
echo "=== Service Status ==="
systemctl status shadow-tls-client shadowsocks-client envoy --no-pager

echo -e "\n=== Port Listening ==="
ss -tulnp | grep -E ':(443|1080|8443)'

echo -e "\n=== Recent Logs ==="
journalctl -u shadow-tls-client -n 20 --no-pager
journalctl -u shadowsocks-client -n 20 --no-pager
journalctl -u envoy -n 20 --no-pager

echo -e "\n=== Envoy Config ==="
curl -s http://localhost:9901/listeners | jq '.[] | select(.name | contains("443"))'

echo -e "\n=== Network Test ==="
timeout 5 curl --socks5 127.0.0.1:1080 https://api.ipify.org
EOF

cat /tmp/ss-diagnostics.txt
```
