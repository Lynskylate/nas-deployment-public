# Edge 重构部署说明

本目录提供新的 Edge 统一部署入口，目标如下：

- `remote_proxy` 与 `aliyun` 统一使用 edge-proxy 基座（Envoy + Node Exporter + Vector）
- edge-proxy 统一暴露 `80/443`，并统一路由：
  - `/metrics` → Node Exporter
  - `/stats/prometheus` → Envoy Prometheus
- Envoy Admin 仅允许本机 `127.0.0.1:9901`，不经公网 listener 暴露
- `shadow-tls + shadowsocks` 服务端仅部署在 `remote_proxy (142.171.205.19)`
- `shadow-tls-client + shadowsocks-client` 仅部署在 `gtr`
- `aliyun` 执行历史代理清理（remove/purge mihomo 与 7890/8888 能力）
- 支持 OpenSSL Root CA 签发与系统信任下发

## 目录

- `ansible/deploy-edge.yml`：统一 edge-proxy 部署（edge 节点）
- `ansible/deploy-edge-tunnel-server.yml`：部署 remote_proxy tunnel server（shadow-tls + shadowsocks）
- `ansible/deploy-gtr-tunnel-client.yml`：部署 gtr tunnel client（shadow-tls-client + shadowsocks-client）
- `ansible/verify-edge-common.yml`：edge 公共验收
- `ansible/verify-edge-tunnel-server.yml`：remote_proxy tunnel server 验收
- `ansible/verify-gtr-tunnel-client.yml`：gtr tunnel client 验收
- `ansible/verify-aliyun-cleanup.yml`：aliyun 清理验收
- `ansible/verify-gtr-no-regression.yml`：gtr 无回归验收
- `ansible/verify-ca-trust.yml`：CA 信任验收

## 使用

```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-edge.yml
ansible-playbook -i inventory-edge.ini deploy-edge-tunnel-server.yml
ansible-playbook -i inventory-edge.ini deploy-gtr-tunnel-client.yml
ansible-playbook -i inventory-edge.ini verify-edge-common.yml
ansible-playbook -i inventory-edge.ini verify-edge-tunnel-server.yml
ansible-playbook -i inventory-edge.ini verify-gtr-tunnel-client.yml
ansible-playbook -i inventory-edge.ini verify-aliyun-cleanup.yml
ansible-playbook -i inventory-edge.ini verify-gtr-no-regression.yml
```

## CA 前置

1. 先生成 Root CA（见 `../scripts/bootstrap-root-ca.sh`）
2. 在 `ansible/group_vars/all/public.yml` 中启用：
   - `edge_ca_issue_enabled: true`
   - `edge_ca_trust_enabled: true`
3. 配置 `envoy_tls_certificates` 与 `envoy_domain_routes` 中的 `tls_terminate_http` 路由
