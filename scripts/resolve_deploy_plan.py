#!/usr/bin/env python3
"""按触发来源与变更路径生成 infra deploy plan。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ZERO_SHA = "0000000000000000000000000000000000000000"
ALL_EDGE_TARGETS = {"remote_proxy", "aliyun", "tencent"}


@dataclass
class DeployPlan:
    target: str
    run_gtr: bool = False
    run_edge: bool = False
    run_k3s_server: bool = False
    run_k3s_agent: bool = False
    run_k3s_platform: bool = False
    run_validate_contract: bool = False
    edge_targets: set[str] = field(default_factory=set)
    run_gtr_mihomo: bool = False
    run_gtr_resource_manifest: bool = False
    run_gtr_ai_tools: bool = False
    run_platform_argocd: bool = False
    run_platform_sealed_secrets: bool = False
    run_platform_tailscale_operator: bool = False
    runner_needs_tailscale: bool = False

    def enable_all(self) -> None:
        self.run_gtr = True
        self.run_edge = True
        self.run_k3s_server = True
        self.run_k3s_agent = True
        self.run_k3s_platform = True
        self.run_validate_contract = True
        self.edge_targets |= ALL_EDGE_TARGETS
        self.run_gtr_mihomo = True
        self.run_gtr_resource_manifest = True
        self.run_gtr_ai_tools = True
        self.run_platform_argocd = True
        self.run_platform_sealed_secrets = True
        self.run_platform_tailscale_operator = True

    def finalize(self) -> None:
        self.run_edge = bool(self.edge_targets)

        if self.run_gtr and not any(
            [self.run_gtr_mihomo, self.run_gtr_resource_manifest, self.run_gtr_ai_tools]
        ):
            self.run_gtr_mihomo = True
            self.run_gtr_resource_manifest = True
            self.run_gtr_ai_tools = True

        if self.run_k3s_platform and not any(
            [
                self.run_platform_argocd,
                self.run_platform_sealed_secrets,
                self.run_platform_tailscale_operator,
            ]
        ):
            self.run_platform_argocd = True
            self.run_platform_sealed_secrets = True
            self.run_platform_tailscale_operator = True

        # 仅当 runner 必须直连 tailnet 里的私网节点时才初始化 Tailscale。
        # aliyun / remote_proxy 都有公网 SSH 管理入口，validate-contract 也只读本地文件。
        self.runner_needs_tailscale = any(
            [
                self.run_gtr,
                self.run_k3s_agent,
                "tencent" in self.edge_targets,
            ]
        )

    def to_github_output(self) -> str:
        payload = {
            "target": self.target,
            "run_gtr": _bool(self.run_gtr),
            "run_edge": _bool(self.run_edge),
            "run_k3s_server": _bool(self.run_k3s_server),
            "run_k3s_agent": _bool(self.run_k3s_agent),
            "run_k3s_platform": _bool(self.run_k3s_platform),
            "run_validate_contract": _bool(self.run_validate_contract),
            "edge_targets": json.dumps(sorted(self.edge_targets)),
            "run_gtr_mihomo": _bool(self.run_gtr_mihomo),
            "run_gtr_resource_manifest": _bool(self.run_gtr_resource_manifest),
            "run_gtr_ai_tools": _bool(self.run_gtr_ai_tools),
            "run_platform_argocd": _bool(self.run_platform_argocd),
            "run_platform_sealed_secrets": _bool(self.run_platform_sealed_secrets),
            "run_platform_tailscale_operator": _bool(self.run_platform_tailscale_operator),
            "runner_needs_tailscale": _bool(self.runner_needs_tailscale),
        }
        return "\n".join(f"{key}={value}" for key, value in payload.items())


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def changed_files_for_push(before: str, after: str) -> list[str]:
    if before and before != ZERO_SHA:
        try:
            output = _git("diff", "--name-only", "--diff-filter=ACMRTUXB", before, after)
            return [line for line in output.splitlines() if line]
        except subprocess.CalledProcessError:
            pass

    output = _git("show", "--pretty=", "--name-only", after)
    return [line for line in output.splitlines() if line]


def manual_plan(target: str) -> DeployPlan:
    plan = DeployPlan(target=target)

    match target:
        case "all":
            plan.enable_all()
        case "gtr_core":
            plan.run_gtr = True
            plan.run_validate_contract = True
            plan.run_gtr_mihomo = True
            plan.run_gtr_resource_manifest = True
            plan.run_gtr_ai_tools = True
        case "gtr_k3s_platform":
            plan.run_gtr = True
            plan.run_k3s_server = True
            plan.run_k3s_agent = True
            plan.run_k3s_platform = True
            plan.edge_targets |= {"aliyun", "tencent"}
            plan.run_gtr_mihomo = True
            plan.run_gtr_resource_manifest = True
            plan.run_platform_argocd = True
            plan.run_platform_sealed_secrets = True
            plan.run_platform_tailscale_operator = True
        case "edge_remote_proxy":
            plan.edge_targets.add("remote_proxy")
        case "edge_aliyun":
            plan.edge_targets.add("aliyun")
        case "edge_tencent":
            plan.edge_targets.add("tencent")
        case _:
            raise ValueError(f"Unsupported target: {target}")

    plan.finalize()
    return plan


def path_plan(changed_files: list[str]) -> DeployPlan:
    plan = DeployPlan(target="push-paths")

    for path in changed_files:
        classify_path(path, plan)

    plan.finalize()
    return plan


def classify_path(path: str, plan: DeployPlan) -> None:
    if path == ".github/workflows/deploy-infra.yml" or path.startswith(".github/actions/bootstrap-deploy-env/") or path.startswith(".github/scripts/"):
        plan.enable_all()
        return

    if path.startswith("mihomo/ansible/"):
        plan.run_gtr = True
        plan.run_gtr_mihomo = True
        return

    if path == ".resource-manifest.yml" or path == "edge/ansible/deploy-resource-manifest.yml":
        plan.run_gtr = True
        plan.run_gtr_resource_manifest = True
        plan.run_validate_contract = True
        return

    if path.startswith("edge/ansible/group_vars/all/") or path == "edge/ansible/inventory-edge.ini":
        plan.edge_targets |= ALL_EDGE_TARGETS
        plan.run_k3s_server = True
        plan.run_k3s_agent = True
        plan.run_k3s_platform = True
        plan.run_validate_contract = True
        plan.run_platform_argocd = True
        plan.run_platform_sealed_secrets = True
        plan.run_platform_tailscale_operator = True
        return

    if path.startswith("edge/ansible/host_vars/remote_proxy"):
        plan.edge_targets.add("remote_proxy")
        return

    if path.startswith("edge/ansible/host_vars/aliyun/"):
        plan.edge_targets.add("aliyun")
        plan.run_k3s_agent = True
        return

    if path == "edge/ansible/host_vars/tencent.yml":
        plan.edge_targets.add("tencent")
        plan.run_k3s_server = True
        plan.run_k3s_platform = True
        plan.run_validate_contract = True
        plan.run_platform_argocd = True
        plan.run_platform_sealed_secrets = True
        plan.run_platform_tailscale_operator = True
        return

    if path.startswith("edge/ansible/host_vars/gtr/"):
        plan.run_k3s_agent = True
        return

    if path.startswith("edge/ansible/roles/gtr-ai-tools/") or path in {
        "edge/ansible/deploy-gtr-ai-tools.yml",
        "edge/ansible/verify-gtr-ai-tools.yml",
    }:
        plan.run_gtr = True
        plan.run_gtr_ai_tools = True
        return

    if path in {"edge/ansible/deploy-edge.yml", "edge/ansible/verify-edge-common.yml"} or path.startswith(
        (
            "edge/ansible/roles/edge-envoy/",
            "edge/ansible/roles/edge-vector/",
            "edge/ansible/roles/node-exporter/",
            "edge/ansible/roles/edge-tailscale/",
            "edge/ansible/roles/tailscale-p2p-heal/",
        )
    ):
        plan.edge_targets |= ALL_EDGE_TARGETS
        return

    if path in {"edge/ansible/deploy-gtr-k3s-server.yml", "edge/ansible/verify-gtr-k3s-server.yml"} or path.startswith(
        "edge/ansible/roles/k3s-server/"
    ):
        plan.run_k3s_server = True
        return

    if path in {"edge/ansible/deploy-gtr-k3s-agent.yml", "edge/ansible/verify-gtr-k3s-agent.yml"} or path.startswith(
        ("edge/ansible/roles/k3s-agent/", "edge/ansible/roles/k3s-prereq/")
    ):
        plan.run_k3s_agent = True
        return

    if path in {"edge/ansible/deploy-platform-argocd.yml", "edge/ansible/verify-platform-argocd.yml"} or path.startswith(
        "edge/ansible/roles/argocd/"
    ):
        plan.run_k3s_platform = True
        plan.run_platform_argocd = True
        return

    if path in {
        "edge/ansible/bootstrap-platform-sealed-secrets-key.yml",
        "edge/ansible/verify-platform-sealed-secrets.yml",
    }:
        plan.run_k3s_platform = True
        plan.run_platform_sealed_secrets = True
        return

    if path == "platform/applications/sealed-secrets.yaml":
        plan.run_k3s_platform = True
        plan.run_platform_sealed_secrets = True
        return

    if path in {"edge/ansible/deploy-platform-tailscale-operator.yml", "edge/ansible/verify-platform-tailscale-operator.yml"}:
        plan.run_k3s_platform = True
        plan.run_platform_tailscale_operator = True
        return


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if not event_name:
        raise RuntimeError("GITHUB_EVENT_NAME is required")

    if event_name == "workflow_dispatch":
        target = os.environ.get("INPUT_TARGET", "all")
        plan = manual_plan(target)
    else:
        before = os.environ.get("GITHUB_EVENT_BEFORE", "")
        after = os.environ.get("GITHUB_SHA", "HEAD")
        changed_files = changed_files_for_push(before, after)
        plan = path_plan(changed_files)

    print(plan.to_github_output())
    return 0


if __name__ == "__main__":
    sys.exit(main())
