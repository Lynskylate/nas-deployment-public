# Edge 重构部署说明

本目录提供新的 Edge 统一部署入口，目标如下：

- `remote_proxy` 与 `aliyun` 统一使用 edge-proxy 基座（Envoy + Node Exporter + Vector）
- edge-proxy 统一暴露 `80/443`，并统一路由：
  - `/metrics` → Node Exporter
  - `/stats/prometheus` → Envoy Prometheus
- Envoy Admin 仅允许本机 `127.0.0.1:9901`，不经公网 listener 暴露
- `shadow-tls + shadowsocks` 服务端仅部署在 `remote_proxy (66.154.100.187)`
- aliyun 历史代理清理已完成

## 目录

- `ansible/deploy-edge.yml`：统一 edge-proxy 部署（edge 节点）
- `ansible/deploy-edge-tunnel-server.yml`：部署 remote_proxy tunnel server（shadow-tls + shadowsocks）
- `ansible/verify-edge-common.yml`：edge 公共验收
- `ansible/verify-edge-tunnel-server.yml`：remote_proxy tunnel server 验收
- `ansible/verify-gtr-no-regression.yml`：gtr 无回归验收

## 使用

```bash
cd edge/ansible
ansible-playbook -i inventory-edge.ini deploy-edge.yml
ansible-playbook -i inventory-edge.ini deploy-edge-tunnel-server.yml
ansible-playbook -i inventory-edge.ini verify-edge-common.yml
ansible-playbook -i inventory-edge.ini verify-edge-tunnel-server.yml
ansible-playbook -i inventory-edge.ini verify-gtr-no-regression.yml
```

