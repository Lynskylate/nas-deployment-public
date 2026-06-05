# Shadowsocks + Shadow-TLS Ansible 部署指南

本目录包含使用 Ansible 自动部署 Shadowsocks + Shadow-TLS 代理方案的所有配置和脚本。

## 目录结构

```
ansible/
├── inventory.ini              # Ansible inventory 文件
├── group_vars/
│   └── all.yml               # 全局配置变量
├── server-deploy.yml         # 服务器端部署 playbook
├── client-deploy.yml         # 客户端部署 playbook
├── verify.yml                # 验证 playbook
└── roles/
    ├── shadowsocks-server/   # Shadowsocks 服务器角色
    ├── shadowsocks-client/   # Shadowsocks 客户端角色
    ├── shadowtls-server/     # Shadow-TLS 服务器角色
    ├── shadowtls-client/     # Shadow-TLS 客户端角色
    └── envoy-sni-config/     # Envoy SNI 配置角色
```

## 快速开始

### 前置要求

1. **本地机器**（运行 Ansible）:
   - Ansible 2.9+
   - SSH 访问到目标服务器

2. **目标服务器**:
   - Ubuntu 20.04+ / Debian 10+
   - Python 3
   - sudo 权限

3. **网络要求**:
   - 能够 SSH 连接到 `142.171.205.19`（root 用户）
   - 能够 SSH 连接到 `gtr` 服务器（ubuntu 用户）

### 配置 Inventory

编辑 `inventory.ini`，设置正确的服务器地址和用户：

```ini
[remote_server]
142.171.205.19 ansible_user=root

[client_server]
gtr ansible_user=ubuntu
```

如果需要使用 SSH 密钥：

```bash
# 创建 Ansible 配置
cat > ansible.cfg <<'EOF'
[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s
private_key_file = ~/.ssh/your_key
EOF
```

### 配置变量

编辑 `group_vars/all/public.yml`，根据需要调整公开配置；secret 通过 `group_vars/all/secret.runtime.yml` 注入：

```yaml
# 版本配置
shadowsocks_version: "v1.18.2"
shadowtls_version: "v0.2.25"

# 安全凭证（建议使用新生成的密码）
shadowsocks_password: "your_password_here"
shadowtls_password: "your_password_here"

# 网络配置
remote_server_ip: "142.171.205.19"
shadowtls_sni_server: "www.microsoft.com"
```

生成新密码：

```bash
SS_PASSWORD=$(openssl rand -base64 32)
TLS_PASSWORD=$(openssl rand -base64 32)
echo "Shadowsocks Password: $SS_PASSWORD"
echo "Shadow-TLS Password: $TLS_PASSWORD"
```

## 部署步骤

### 1. 部署服务器端

首先在远程服务器 (142.171.205.19) 上部署 Shadowsocks 和 Shadow-TLS 服务：

```bash
cd /path/to/gtr-services/shadowsocks-shadowtls

# 检查配置
ansible -i ansible/inventory.ini remote_server -m ping

# 执行部署
ansible-playbook -i ansible/inventory.ini ansible/server-deploy.yml
```

预期输出：
- ✓ 安装 shadowsocks-rust server
- ✓ 安装 shadow-tls server
- ✓ 配置 systemd 服务
- ✓ 配置防火墙规则
- ✓ 启动服务

### 2. 部署客户端

在 GTR 服务器上部署客户端和 Envoy 配置：

```bash
# 检查配置
ansible -i ansible/inventory.ini client_server -m ping

# 执行部署
ansible-playbook -i ansible/inventory.ini ansible/client-deploy.yml
```

预期输出：
- ✓ 安装 shadowsocks-rust client
- ✓ 安装 shadow-tls client
- ✓ 配置 Envoy SNI 透传
- ✓ 更新 Envoy 依赖
- ✓ 启动所有服务

### 3. 验证部署

运行验证测试确保一切正常：

```bash
ansible-playbook -i ansible/inventory.ini ansible/verify.yml
```

验证内容包括：
- 服务状态检查
- 端口监听检查
- 日志检查
- 代理连接测试

### 4. 手动测试

在 GTR 服务器上手动测试代理：

```bash
# 测试 SOCKS5 代理
curl --socks5 127.0.0.1:1080 https://api.ipify.org

# 应该返回远程服务器的 IP (142.171.205.19)

# 测试访问网站
curl --socks5 127.0.0.1:1080 https://www.google.com
```

## Playbook 详细说明

### server-deploy.yml

部署远程服务器组件：

**角色**:
- `shadowsocks-server`: 安装和配置 Shadowsocks 服务器
- `shadowtls-server`: 安装和配置 Shadow-TLS 服务器

**安装路径**:
- Binary: `/usr/local/shadowsocks-server/ssserver`
- Config: `/etc/shadowsocks/config.json`
- Service: `/etc/systemd/system/shadowsocks-server.service`

**防火墙**:
- 自动开放 443 端口 (TCP/UDP)

### client-deploy.yml

部署客户端组件：

**角色**:
- `shadowsocks-client`: 安装和配置 Shadowsocks 客户端
- `shadowtls-client`: 安装和配置 Shadow-TLS 客户端
- `envoy-sni-config`: 配置 Envoy SNI 透传

**安装路径**:
- sslocal: `/usr/local/shadowsocks-client/sslocal`
- shadow-tls: `/usr/local/shadow-tls-client/shadow-tls`
- Configs: `/etc/shadowsocks/client.json`

**Envoy 配置**:
- Listener: `/etc/envoy/dynamic_config/lds.yaml`
- Cluster: `/etc/envoy/dynamic_config/cds.yaml`
- 自动备份现有配置

### verify.yml

验证部署状态：

- 检查所有服务运行状态
- 验证端口监听
- 检查日志
- 测试代理连接

## 角色说明

### shadowsocks-server / shadowsocks-client

**任务**:
1. 创建 shadowsocks 系统用户
2. 下载并安装 shadowsocks-rust
3. 创建配置文件
4. 部署 systemd 服务
5. 启动和启用服务

**配置参数**:
- 加密方法: aes-256-gcm
- 超时: 300 秒
- Fast Open: 启用

### shadowtls-server / shadowtls-client

**任务**:
1. 创建 shadowtls 系统用户
2. 下载并安装 shadow-tls
3. 部署 systemd 服务
4. 配置防火墙 (仅服务器端)
5. 启动和启用服务

**特性**:
- Shadow-TLS v3 协议
- SNI 伪装: www.microsoft.com
- TLS 透传模式

### envoy-sni-config

**任务**:
1. 备份现有 Envoy 配置
2. 更新 LDS 配置 (添加 443 listener)
3. 更新 CDS 配置 (添加 shadow_tls_client cluster)
4. 更新 systemd 依赖
5. 重启 Envoy

**SNI 路由规则**:
- 匹配 `www.microsoft.com` 和 `*.microsoft.com`
- 透传到 shadow-tls client (127.0.0.1:8443)

## 常用命令

### 检查服务状态

```bash
# 服务器端
ansible -i ansible/inventory.ini remote_server -m shell -a "systemctl status shadowsocks-server shadow-tls-server"

# 客户端
ansible -i ansible/inventory.ini client_server -m shell -a "systemctl status shadow-tls-client shadowsocks-client envoy"
```

### 查看日志

```bash
# 实时查看日志
ansible -i ansible/inventory.ini client_server -m shell -a "journalctl -u shadow-tls-client -f"
```

### 重启服务

```bash
# 重启客户端服务
ansible -i ansible/inventory.ini client_server -m shell -a "systemctl restart shadowsocks-client shadow-tls-client envoy"
```

### 更新配置

如果需要更新配置（如更改密码）：

```bash
# 1. 更新 group_vars/all/public.yml
vim ansible/group_vars/all/public.yml

# 2. 重新部署
ansible-playbook -i ansible/inventory.ini ansible/server-deploy.yml
ansible-playbook -i ansible/inventory.ini ansible/client-deploy.yml
```

## 故障排查

### 连接问题

1. 检查服务状态：
   ```bash
   ansible-playbook -i ansible/inventory.ini ansible/verify.yml
   ```

2. 查看日志：
   ```bash
   ansible -i ansible/inventory.ini client_server -m shell -a "journalctl -u shadow-tls-client -n 50"
   ```

### Envoy 配置问题

1. 检查配置：
   ```bash
   ansible -i ansible/inventory.ini client_server -m shell -a "curl http://localhost:9901/listeners"
   ```

2. 回滚配置：
   ```bash
   ansible -i ansible/inventory.ini client_server -m shell -a "ls -t /etc/envoy.backup-*"
   # 选择最新的备份进行恢复
   ```

详细故障排查步骤请参考 [troubleshooting.md](../troubleshooting.md)。

## 安全建议

1. **密码管理**:
   - 使用强随机密码
   - 定期更换密码
   - 不要在版本控制中存储密码

2. **网络安全**:
   - 确保 shadowsocks 和 shadow-tls 只监听 localhost
   - 确保 Envoy admin 端口不暴露到公网
   - 定期检查连接日志

3. **更新维护**:
   - 定期更新软件版本
   - 关注安全公告
   - 测试后再部署到生产环境

## 维护操作

### 更新软件版本

1. 修改 `group_vars/all/public.yml` 中的版本号
2. 重新运行部署 playbook

### 更换密码

1. 生成新密码
2. 更新 `group_vars/all/public.yml`
3. 重新部署

### 完全卸载

```bash
# 服务器端
ansible -i ansible/inventory.ini remote_server -m shell -a "systemctl stop shadowsocks-server shadow-tls-server"
ansible -i ansible/inventory.ini remote_server -m shell -a "systemctl disable shadowsocks-server shadow-tls-server"

# 客户端
ansible -i ansible/inventory.ini client_server -m shell -a "systemctl stop shadow-tls-client shadowsocks-client"
ansible -i ansible/inventory.ini client_server -m shell -a "systemctl disable shadow-tls-client shadowsocks-client"

# 手动清理文件（如果需要）
```

## 参考资源

- [shadowsocks-rust GitHub](https://github.com/shadowsocks/shadowsocks-rust)
- [shadow-tls GitHub](https://github.com/ihciah/shadow-tls)
- [Envoy TLS Inspector](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/listener/tls_inspector/v3/tls_inspector.proto)
- [Ansible Documentation](https://docs.ansible.com/)
