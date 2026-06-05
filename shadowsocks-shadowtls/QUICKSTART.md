# Shadowsocks + Shadow-TLS 快速开始指南

本指南帮助您快速部署 Shadowsocks + Shadow-TLS 代理方案。

## 前置要求

- Ansible 2.9+ 安装在本地机器
- SSH 访问到:
  - 142.171.205.19 (root 用户)
  - gtr 服务器 (ubuntu 用户)
- 目标服务器: Ubuntu 20.04+ / Debian 10+

## 一键部署

### 1. 安装 Ansible (如果还没有)

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install ansible -y

# macOS
pip install ansible

# 验证安装
ansible --version
```

### 2. 配置 Inventory

编辑 `ansible/inventory.ini`:

```ini
[remote_server]
142.171.205.19 ansible_user=root ansible_port=22

[client_server]
gtr ansible_user=ubuntu
```

如果需要使用 SSH 密钥或自定义端口:

```bash
# 编辑或创建 ansible.cfg
cat > ansible/ansible.cfg <<'EOF'
[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o StrictHostKeyChecking=no
private_key_file = ~/.ssh/your_private_key
EOF
```

### 3. 测试连接

```bash
cd /path/to/gtr-services/shadowsocks-shadowtls

# 测试远程服务器连接
ansible -i ansible/inventory.ini remote_server -m ping

# 测试客户端服务器连接
ansible -i ansible/inventory.ini client_server -m ping
```

### 4. 部署

使用一键部署脚本:

```bash
# 完整部署 (推荐)
./deploy.sh all

# 或分步部署
./deploy.sh server    # 仅部署服务器端
./deploy.sh client    # 仅部署客户端
./deploy.sh verify    # 验证部署
```

### 5. 验证

在 GTR 服务器上手动测试:

```bash
ssh gtr

# 测试 SOCKS5 代理
curl --socks5 127.0.0.1:1080 https://api.ipify.org

# 应该返回: 142.171.205.19
```

## 使用 Ansible Playbook 直接部署

如果不想使用部署脚本:

```bash
# 1. 部署服务器端
ansible-playbook -i ansible/inventory.ini ansible/server-deploy.yml

# 2. 部署客户端
ansible-playbook -i ansible/inventory.ini ansible/client-deploy.yml

# 3. 验证
ansible-playbook -i ansible/inventory.ini ansible/verify.yml
```

## 配置说明

### 修改密码

编辑 `ansible/group_vars/all/public.yml`，并通过 private vault 渲染 `ansible/group_vars/all/secret.runtime.yml`:

```yaml
# 生成新密码
shadowsocks_password: "your_new_password_here"
shadowtls_password: "your_new_password_here"
```

生成强随机密码:

```bash
SS_PASSWORD=$(openssl rand -base64 32)
TLS_PASSWORD=$(openssl rand -base64 32)
echo "Shadowsocks: $SS_PASSWORD"
echo "Shadow-TLS: $TLS_PASSWORD"
```

### 修改 SNI 伪装服务器

编辑 `ansible/group_vars/all/public.yml`:

```yaml
shadowtls_sni_server: "www.microsoft.com"  # 或其他网站
```

### 修改版本

编辑 `ansible/group_vars/all/public.yml`:

```yaml
shadowsocks_version: "v1.18.2"
shadowtls_version: "v0.2.25"
```

## 部署后使用

### 使用 SOCKS5 代理

在 GTR 服务器上:

```bash
# 方法 1: 使用 curl
curl --socks5 127.0.0.1:1080 https://www.google.com

# 方法 2: 使用环境变量
export ALL_PROXY=socks5://127.0.0.1:1080
curl https://www.google.com

# 方法 3: 使用 proxychains
echo "socks5 127.0.0.1 1080" >> /etc/proxychains.conf
proxychains curl https://www.google.com
```

### 从远程机器使用代理

通过 SSH 隧道:

```bash
# 在本地机器上建立 SSH 隧道
ssh -L 1080:localhost:1080 gtr

# 然后在本地使用
curl --socks5 127.0.0.1:1080 https://www.google.com
```

### 配置系统代理

```bash
# 临时设置
export http_proxy=socks5://127.0.0.1:1080
export https_proxy=socks5://127.0.0.1:1080

# 或使用 HTTP 代理转换工具 (如 privoxy)
# 安装 privoxy: sudo apt install privoxy
# 配置: echo "forward-socks5 / 127.0.0.1:1080 ." >> /etc/privoxy/config
# 使用: export http_proxy=http://127.0.0.1:8118
```

## 服务管理

### 检查服务状态

```bash
# 服务器端
ansible -i ansible/inventory.ini remote_server -m shell \
  -a "systemctl status shadowsocks-server shadow-tls-server"

# 客户端
ansible -i ansible/inventory.ini client_server -m shell \
  -a "systemctl status shadow-tls-client shadowsocks-client envoy"
```

### 查看日志

```bash
# 实时查看日志
ansible -i ansible/inventory.ini client_server -m shell \
  -a "journalctl -u shadow-tls-client -f"
```

### 重启服务

```bash
# 客户端服务
ansible -i ansible/inventory.ini client_server -m shell \
  -a "systemctl restart shadowsocks-client shadow-tls-client envoy"
```

## 常见问题

### 连接失败

1. 检查服务状态: `./deploy.sh verify`
2. 查看日志: `journalctl -u shadow-tls-client -n 50`
3. 检查端口: `ss -tulnp | grep -E ':(1080|8443|443)'`

### Ansible 连接失败

1. 检查 SSH 配置: `ansible -i ansible/inventory.ini all -m ping`
2. 检查 SSH 密钥权限: `chmod 600 ~/.ssh/your_key`
3. 测试手动 SSH: `ssh root@142.171.205.19`

### 代理速度慢

1. 检查网络延迟: `ping 142.171.205.19`
2. 检查系统资源: `htop`
3. 考虑更换 SNI 服务器

## 下一步

- 阅读完整文档: [README.md](README.md)
- 查看故障排查: [troubleshooting.md](troubleshooting.md)
- 了解服务器部署: [server/server-deployment.md](server/server-deployment.md)
- 了解客户端部署: [client/client-deployment.md](client/client-deployment.md)

## 安全建议

1. **定期更换密码**: 每月更换 Shadowsocks 和 Shadow-TLS 密码
2. **监控日志**: 定期检查异常连接
3. **限制访问**: 确保 Envoy admin 端口不暴露
4. **备份配置**: 保持配置文件的备份
5. **更新软件**: 定期更新到最新版本

## 架构图

```
外部访问 → Envoy (443) → Shadow-TLS Client → Shadowsocks Client → SOCKS5 (1080)
                                    ↓
                            远程服务器 (142.171.205.19:443)
                            Shadow-TLS Server → Shadowsocks Server
```

## 支持

如有问题，请查看:
1. [troubleshooting.md](troubleshooting.md) - 故障排查指南
2. [ansible/README.md](ansible/README.md) - Ansible 部署详细说明
3. 项目 GitHub Issues

---

**部署完成后，请立即测试代理连接并妥善保管密码！**
