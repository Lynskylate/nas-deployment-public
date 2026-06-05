# Shadowsocks + Shadow-TLS 部署完成总结

## 概述

本文档总结了 Shadowsocks + Shadow-TLS 代理方案的完整 Ansible 部署基础设施。所有部署文件已准备就绪，可以立即用于生产环境部署。

## 部署架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        远程服务器 (142.171.205.19)                      │
│                                                                         │
│  shadowsocks-rust server (127.0.0.1:8388)                              │
│           ↓                                                             │
│  shadow-tls server (0.0.0.0:443) - SNI: www.microsoft.com              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ TLS 伪装连接
                                    │
┌───────────────────────────────────▼─────────────────────────────────────┐
│                           GTR 客户端服务器                                │
│                                                                         │
│  Envoy (0.0.0.0:443) - SNI 透传                                         │
│           ↓                                                             │
│  shadow-tls client (127.0.0.1:8443)                                    │
│           ↓                                                             │
│  shadowsocks-rust client (127.0.0.1:1080) - SOCKS5 代理                │
└─────────────────────────────────────────────────────────────────────────┘
```

## 文件结构

```
shadowsocks-shadowtls/
├── README.md                           # 主要运行手册
├── QUICKSTART.md                       # 快速开始指南
├── troubleshooting.md                  # 故障排查指南
├── deploy.sh                           # 一键部署脚本
│
├── ansible/                            # Ansible 部署文件
│   ├── README.md                       # Ansible 使用说明
│   ├── inventory.ini                   # 服务器清单
│   ├── group_vars/
│   │   └── all.yml                     # 全局配置变量
│   ├── server-deploy.yml               # 服务器端部署 playbook
│   ├── client-deploy.yml               # 客户端部署 playbook
│   ├── verify.yml                      # 验证 playbook
│   └── roles/                          # Ansible 角色
│       ├── shadowsocks-server/         # Shadowsocks 服务器角色
│       ├── shadowsocks-client/         # Shadowsocks 客户端角色
│       ├── shadowtls-server/           # Shadow-TLS 服务器角色
│       ├── shadowtls-client/           # Shadow-TLS 客户端角色
│       └── envoy-sni-config/           # Envoy SNI 配置角色
│
├── server/
│   └── server-deployment.md            # 服务器端部署指南
│
└── client/
    └── client-deployment.md            # 客户端部署指南
```

## 生成的密码

部署时使用的安全密码（已自动生成）：

```bash
# Shadowsocks 密码（用于 SS 认证）
SHADOWSOCKS_PASSWORD=<render-from-private-vault>

# Shadow-TLS 密码（用于 TLS 握手）
SHADOW_TLS_PASSWORD=<render-from-private-vault>
```

## 软件版本

- **shadowsocks-rust**: v1.18.2
- **shadow-tls**: v0.2.25
- **加密方法**: aes-256-gcm
- **Shadow-TLS 协议**: v3

## 部署步骤

### 方式一：使用一键部署脚本（推荐）

```bash
cd /path/to/gtr-services/shadowsocks-shadowtls

# 完整部署
./deploy.sh all

# 或分步部署
./deploy.sh server    # 仅部署服务器端
./deploy.sh client    # 仅部署客户端
./deploy.sh verify    # 验证部署
```

### 方式二：使用 Ansible Playbook

```bash
# 1. 配置 inventory
vim ansible/inventory.ini

# 2. 测试连接
ansible -i ansible/inventory.ini all -m ping

# 3. 部署服务器端
ansible-playbook -i ansible/inventory.ini ansible/server-deploy.yml

# 4. 部署客户端
ansible-playbook -i ansible/inventory.ini ansible/client-deploy.yml

# 5. 验证
ansible-playbook -i ansible/inventory.ini ansible/verify.yml
```

## 配置参数

### 服务器端 (142.171.205.19)

| 服务 | 监听地址 | 端口 | 用途 |
|------|----------|------|------|
| shadowsocks-rust | 127.0.0.1 | 8388 | Shadowsocks 协议 |
| shadow-tls | 0.0.0.0 | 443 | TLS 伪装入口 |

### 客户端 (GTR)

| 服务 | 监听地址 | 端口 | 用途 |
|------|----------|------|------|
| Envoy | 0.0.0.0 | 443 | SNI 透传 |
| shadow-tls client | 127.0.0.1 | 8443 | 连接远程 |
| shadowsocks client | 127.0.0.1 | 1080 | SOCKS5 代理 |

## 关键特性

### 1. Envoy SNI 透传

- 基于 SNI 的智能路由
- 支持多个 HTTPS 服务共用 443 端口
- 保留 shadow-tls 的 TLS 伪装能力

### 2. 安全加固

- 所有服务使用专用系统用户运行
- systemd 安全限制（NoNewPrivileges, PrivateTmp 等）
- 仅 localhost 监听（除必要端口）
- 强随机密码

### 3. 高可用性

- systemd 自动重启
- 服务依赖管理
- 配置自动备份
- 滚动更新支持

### 4. 可维护性

- Ansible 自动化部署
- 完整的文档
- 故障排查指南
- 监控集成点

## 使用方式

### 在 GTR 服务器上使用

```bash
# 使用 SOCKS5 代理
curl --socks5 127.0.0.1:1080 https://api.ipify.org

# 设置环境变量
export ALL_PROXY=socks5://127.0.0.1:1080
curl https://www.google.com
```

### 从远程机器通过 SSH 隧道

```bash
# 建立隧道
ssh -L 1080:localhost:1080 gtr

# 在本地使用
curl --socks5 127.0.0.1:1080 https://www.google.com
```

## 服务管理命令

```bash
# 检查状态
systemctl status shadow-tls-client shadowsocks-client envoy

# 查看日志
journalctl -u shadow-tls-client -f
journalctl -u shadowsocks-client -f

# 重启服务
systemctl restart shadowsocks-client
systemctl restart shadow-tls-client
systemctl restart envoy
```

## 监控集成

### Node Exporter 指标

```bash
# 创建指标收集脚本
cat > /usr/local/bin/update-ss-metrics.sh <<'EOF'
#!/bin/bash
cat > /var/lib/node_exporter/textfile-collector/ss_proxy.prom <<'PROM'
shadowsocks_up{instance="client"} $(systemctl is-active shadowsocks-client | grep -q active && echo 1 || echo 0)
shadowtls_up{instance="client"} $(systemctl is-active shadow-tls-client | grep -q active && echo 1 || echo 0)
socks5_connections $(ss -tn | grep :1080 | wc -l)
PROM
EOF

chmod +x /usr/local/bin/update-ss-metrics.sh

# 添加定时任务
crontab -e
# */1 * * * * /usr/local/bin/update-ss-metrics.sh
```

## 故障排查

### 快速诊断

```bash
# 检查服务
ansible-playbook -i ansible/inventory.ini ansible/verify.yml

# 检查端口
ss -tulnp | grep -E ':(443|1080|8443)'

# 检查 Envoy
curl http://localhost:9901/listeners
curl http://localhost:9901/clusters

# 测试代理
curl --socks5 127.0.0.1:1080 https://api.ipify.org
```

### 常见问题

详见 [troubleshooting.md](troubleshooting.md)，包括：
- TLS 握手失败
- 连接被拒绝
- Shadowsocks 认证失败
- Envoy 503 错误
- 代理连接超时

## 回滚计划

如果部署出现问题：

```bash
# 停止新服务
sudo systemctl stop shadow-tls-client shadowsocks-client

# 恢复 Envoy 配置
LATEST_BACKUP=$(ls -t /etc/envoy.backup-* | head -1)
sudo cp -r $LATEST_BACKUP/* /etc/envoy/

# 重启 Envoy
sudo systemctl restart envoy

# 验证
curl http://localhost:9901/listeners
```

## 安全建议

1. **密码管理**
   - 妥善保管生成的密码
   - 定期更换密码（建议每月）
   - 不要在版本控制中存储明文密码

2. **网络安全**
   - 确保 shadowsocks 和 shadow-tls 只监听 localhost
   - 确保 Envoy admin 端口不暴露到公网
   - 定期检查连接日志

3. **更新维护**
   - 定期更新软件版本
   - 关注安全公告
   - 测试后再部署到生产环境

4. **监控告警**
   - 集成到现有监控系统
   - 设置服务状态告警
   - 监控连接数和流量

## 后续优化

### 短期优化

1. 添加监控仪表板（Grafana）
2. 配置日志聚合
3. 添加连接限流
4. 优化性能参数

### 长期优化

1. 实现多用户支持
2. 添加流量统计
3. 实现负载均衡
4. 添加故障转移

## 参考资源

- [shadowsocks-rust GitHub](https://github.com/shadowsocks/shadowsocks-rust)
- [shadow-tls GitHub](https://github.com/ihciah/shadow-tls)
- [Envoy 文档](https://www.envoyproxy.io/docs/)
- [Ansible 文档](https://docs.ansible.com/)

## 部署检查清单

部署前检查：
- [ ] Ansible 已安装
- [ ] SSH 密钥已配置
- [ ] Inventory 文件已更新
- [ ] 防火墙规则已确认

部署后验证：
- [ ] 服务器端服务运行正常
- [ ] 客户端服务运行正常
- [ ] 端口监听正确
- [ ] Envoy 配置生效
- [ ] 代理连接测试通过
- [ ] 日志无错误

## 联系支持

如有问题，请：
1. 查看 [troubleshooting.md](troubleshooting.md)
2. 检查日志: `journalctl -u <service> -n 50`
3. 运行验证: `./deploy.sh verify`

---

**部署完成后，请立即测试代理连接并妥善保管密码！**

部署日期: 2025-01-XX
部署人员: [Your Name]
版本: 1.0
