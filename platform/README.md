# Platform 组件

`platform/` 目录存储 K3s 集群内平台组件的声明式配置，由 Argo CD App-of-Apps 自动同步管理。

## 目录结构

```
platform/
├── README.md                        ← 本文档
├── applications/                    ← Argo CD Application CRDs（App-of-Apps）
│   ├── sealed-secrets.yaml          ← Sealed Secrets Application
│   └── tailscale-operator.yaml      ← Tailscale Operator Application
└── helm-values/
    └── tailscale-operator/
        └── values.yaml              ← Operator Helm values override
```

## 管理策略

- **Argo CD** 通过 Ansible 引导安装，之后自我管理
- **Sealed Secrets** 完全由 Argo CD 管理（Helm chart），私钥从 vault 恢复（bootstrap playbook）
- **Tailscale Operator** 完全通过 Argo CD Application 管理（GitOps）

## 使用说明

### 添加新平台组件

1. 在 `platform/applications/` 中创建 Argo CD Application CRD
2. 如有 Helm values，放在 `platform/helm-values/<component>/values.yaml`

> App-of-Apps 使用 `directory: { recurse: true }` 自动发现 `applications/` 目录下所有 `.yaml` 文件，无需维护索引文件。

### 查看同步状态

```bash
# 通过 Argo CD CLI
argocd app list
argocd app sync <app-name>
argocd app get <app-name>

# 通过 kubectl
k3s kubectl -n argocd get applications
k3s kubectl -n argocd get application <app-name> -o yaml
```
