# Mihomo 部署 - Aliyun 服务器

本文档记录 Aliyun 服务器 (47.120.46.128) 上的 Mihomo 代理服务部署和运维操作。

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Aliyun 服务器 (47.120.46.128)                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Internet ──▶ 0.0.0.0:80 ───▶ Envoy                                     │
│                          │                                               │
│         ┌────────────────┼────────────────┐                              │
│         │                │                │                              │
│         ▼                ▼                ▼                              │
│    /node_exporter/  /mihomo/*      /stats/prometheus                     │
│         │                │                │                              │
│         ▼                ▼                ▼                              │
│    node_exporter    Mihomo API       Envoy Admin                         │
│      (9100)        (127.0.0.1:9090)   (127.0.0.1:8001)                   │
│                                                                          │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │  Mihomo Proxy                                                   │    │
│   │  - 127.0.0.1:7890 (本地, 无鉴权)                                │    │
│   │  - 0.0.0.0:8888  (公网, HTTP Basic Auth)                       │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## 部署信息

| 项目 | 值 |
|------|-----|
| 服务器 IP | 47.120.46.128 |
| SSH 用户 | yiling (需要 NOPASSWD sudo) |
| Mihomo 版本 | v1.19.20 |
| Envoy 版本 | 1.32.2 |
| 操作系统 | Ubuntu 22.04.3 LTS |

## 服务端口

| 服务 | 端口 | 访问方式 | 鉴权 |
|------|------|----------|------|
| Envoy HTTP | 80 | 公网 | 无 |
| Mihomo API | 127.0.0.1:9090 | 通过 Envoy /mihomo/ | Bearer Token |
| Mihomo Proxy (本地) | 127.0.0.1:7890 | 本地 | 无 |
| Mihomo Proxy (公网) | 0.0.0.0:8888 | 公网 | HTTP Basic Auth |
| Node Exporter | 127.0.0.1:9100 | 通过 Envoy /node_exporter/ | 无 |
| Envoy Admin | 127.0.0.1:8001 | 通过 Envoy /stats/prometheus | 无 |

## 访问凭证

### Mihomo API (Bearer Token)
```
Token: <mihomo-secret-from-private-vault>
```

### Mihomo Proxy (HTTP Basic Auth)
```
用户名: mihomo
密码: <proxy-auth-password-from-private-vault>
```

### ShadowTLS 出站代理
```
服务器: 142.171.205.19:443
SNI: www.microsoft.com
Shadowsocks 密码: <shadowsocks-password-from-private-vault>
ShadowTLS 密码: <shadowtls-password-from-private-vault>
加密: aes-256-gcm
```

## 部署方式

### 一键部署

```bash
cd /path/to/gtr-services/mihomo/ansible
ansible-playbook -i inventory-aliyun.ini deploy-aliyun.yml
```

### 验证部署

```bash
ansible-playbook -i inventory-aliyun.ini verify-aliyun.yml
```

### 重复部署 (幂等性)

```bash
# Playbook 支持多次执行，自动跳过已完成的任务
ansible-playbook -i inventory-aliyun.ini deploy-aliyun.yml
```

## 使用示例

### Mihomo API

```bash
# 获取 Mihomo 状态
curl -H "Authorization: Bearer <mihomo-secret-from-private-vault>" \
  http://47.120.46.128/mihomo/

# 获取流量统计
curl -H "Authorization: Bearer <mihomo-secret-from-private-vault>" \
  http://47.120.46.128/mihomo/traffic

# 获取代理列表
curl -H "Authorization: Bearer <mihomo-secret-from-private-vault>" \
  http://47.120.46.128/mihomo/proxies
```

### Mihomo Proxy

```bash
# 通过公网代理访问 (需要鉴权)
PROXY_PASSWORD="<proxy-auth-password-from-private-vault>"
curl -u "mihomo:${PROXY_PASSWORD}" \
  -x http://47.120.46.128:8888 \
  https://api.ipify.org

# 设置环境变量使用代理
export http_proxy=http://47.120.46.128:8888
export https_proxy=http://47.120.46.128:8888
export PROXY_USER="mihomo"
export PROXY_PASSWORD="<proxy-auth-password-from-private-vault>"
curl https://www.google.com
```

### Node Exporter

```bash
# 通过 Envoy 访问
curl http://47.120.46.128/node_exporter/metrics
```

### Prometheus 指标

```bash
# 通过 Envoy 访问
curl http://47.120.46.128/stats/prometheus
```

## 服务管理

```bash
# SSH 到服务器
ssh aliyun

# 检查服务状态
systemctl status mihomo
systemctl status envoy
systemctl status node_exporter

# 重启服务
sudo systemctl restart mihomo
sudo systemctl restart envoy

# 查看日志
journalctl -u mihomo -f
journalctl -u envoy -f

# 检查端口
ss -tulnp | grep -E ':(80|8888|9090|9100)'
```

## 文件路径

| 文件/目录 | 路径 |
|-----------|------|
| Mihomo 配置 | /etc/mihomo/config.yaml |
| Mihomo 二进制 | /usr/local/bin/mihomo |
| Mihomo 数据目录 | /var/lib/mihomo |
| Mihomo 日志目录 | /var/log/mihomo |
| Mihomo Systemd 服务 | /etc/systemd/system/mihomo.service |
| Envoy 配置 | /etc/envoy/envoy.yaml |
| Envoy 配置备份 | /etc/envoy/backup/ |

## 部署文件结构

```
mihomo/
├── ansible/
│   ├── inventory-aliyun.ini          # Aliyun 服务器清单
│   ├── deploy-aliyun.yml             # 部署 playbook
│   ├── verify-aliyun.yml             # 验证 playbook
│   ├── group_vars/
│   │   └── aliyun.yml                # Aliyun 配置变量
│   └── roles/mihomo/templates/
│       ├── config-aliyun.yaml.j2     # Mihomo 配置模板
│       ├── mihomo.service.j2         # Systemd 服务模板
│       └── htpasswd.j2               # HTTP Basic Auth 密码
├── envoy/
│   ├── envoy-aliyun.yaml.j2          # Envoy 配置模板
│   └── mihomo-integration.yaml       # Envoy 集成参考
└── README-aliyun.md                  # 本文档
```

## 配置修改

### 修改 Mihomo 配置

```bash
# 1. 修改配置变量
vim mihomo/ansible/group_vars/aliyun/public.yml

# 2. 重新部署
cd mihomo/ansible
ansible-playbook -i inventory-aliyun.ini deploy-aliyun.yml
```

### 修改 Envoy 配置

```bash
# 1. 修改配置模板
vim mihomo/envoy/envoy-aliyun.yaml.j2

# 2. 重新部署
cd mihomo/ansible
ansible-playbook -i inventory-aliyun.ini deploy-aliyun.yml
```

### 添加新的代理订阅

编辑 `mihomo/ansible/group_vars/aliyun/public.yml`:

```yaml
# 取消注释并配置
proxy_provider_url: "https://your-subscription-url"
proxy_provider_interval: 3600
```

## 故障排查

### 服务无法启动

```bash
# 检查日志
journalctl -u mihomo -n 100

# 检查配置语法
/usr/local/bin/mihomo -t -d /etc/mihomo

# 检查端口占用
ss -tulnp | grep -E ':(7890|8888|9090)'
```

### Envoy 配置错误

```bash
# 验证配置语法
envoy -c /etc/envoy/envoy.yaml --mode validate

# 恢复备份配置
ls -lt /etc/envoy/backup/
sudo cp /etc/envoy/backup/envoy.yaml.backup-TIMESTAMP /etc/envoy/envoy.yaml
sudo systemctl restart envoy
```

### 代理连接失败

```bash
# 检查 Mihomo 日志
journalctl -u mihomo -f

# 测试本地代理
ssh aliyun "curl -x http://127.0.0.1:7890 https://api.ipify.org"

# 检查代理组状态
curl -H "Authorization: Bearer <mihomo-secret-from-private-vault>" \
  http://127.0.0.1:9090/proxies
```

### 鉴权失败

```bash
# 检查密码文件
ssh aliyun "cat /etc/envoy/htpasswd"

# 测试 Basic Auth
curl -v -u "mihomo:${PROXY_PASSWORD}" http://47.120.46.128:8888/
```

## 安全注意事项

1. **NOPASSWD sudo**: 确保 yiling 用户配置了 `NOPASSWD:ALL`
2. **密码保管**: 妥善保管 API Token 和代理密码
3. **端口访问**: 8888 端口公网可访问，建议配置防火墙白名单
4. **日志审计**: 定期检查 `journalctl -u mihomo` 日志

## 回滚操作

```bash
# 1. 停止 Mihomo 服务
sudo systemctl stop mihomo

# 2. 恢复 Envoy 配置
sudo cp /etc/envoy/backup/envoy.yaml.backup-LATEST /etc/envoy/envoy.yaml
sudo systemctl restart envoy

# 3. 禁用 Mihomo 开机启动
sudo systemctl disable mihomo
```

## 相关文档

- [Mihomo 官方文档](https://wiki.metacubex.one/)
- [Mihomo GitHub](https://github.com/MetaCubeX/mihomo)
- [Envoy 文档](https://www.envoyproxy.io/docs/)
- [项目主 README](../README.md)

---

部署日期: 2026-02-11
版本: 1.0
