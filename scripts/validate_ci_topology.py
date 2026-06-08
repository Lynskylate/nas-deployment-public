#!/usr/bin/env python3
"""校验当前 K3s/Tailscale/CI 拓扑契约，防止稳定路径被误改回不可靠方案。"""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parent.parent
INVENTORY_PATH = ROOT / "edge/ansible/inventory-edge.ini"
GLOBAL_VARS_PATH = ROOT / "edge/ansible/group_vars/all/public.yml"
TENCENT_VARS_PATH = ROOT / "edge/ansible/host_vars/tencent.yml"
REMOTE_PROXY_VARS_PATH = ROOT / "edge/ansible/host_vars/remote_proxy.yml"

TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def find_inventory_host_vars(path: Path, hostname: str) -> dict[str, str]:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "[")):
            continue
        if not stripped.startswith(f"{hostname} "):
            continue

        parts = stripped.split()
        return {
            key: value
            for key, value in (part.split("=", 1) for part in parts[1:] if "=" in part)
        }
    raise KeyError(hostname)


def parse_url_host(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"非法 URL: {url}")
    return parsed.hostname


def is_cgnat_ip(value: str) -> bool:
    return ipaddress.ip_address(value) in TAILSCALE_CGNAT


def main() -> int:
    global_vars = load_yaml(GLOBAL_VARS_PATH)
    tencent_vars = load_yaml(TENCENT_VARS_PATH)
    remote_proxy_vars = load_yaml(REMOTE_PROXY_VARS_PATH)

    errors: list[str] = []
    notes: list[str] = []

    # 1. remote_proxy management SSH must use public IP, not Tailscale CGNAT
    try:
        remote_proxy_inventory_vars = find_inventory_host_vars(INVENTORY_PATH, "remote_proxy")
    except KeyError as exc:
        errors.append(f"inventory 缺少 remote_proxy 主机定义: {exc}")
        remote_proxy_inventory_vars = {}

    remote_proxy_ansible_host = remote_proxy_inventory_vars.get("ansible_host", "")
    if not remote_proxy_ansible_host:
        errors.append("`inventory-edge.ini` 中 remote_proxy 缺少 `ansible_host`。")
    else:
        try:
            if is_cgnat_ip(remote_proxy_ansible_host):
                errors.append(
                    f"remote_proxy 的 `ansible_host={remote_proxy_ansible_host}` 落在 Tailscale CGNAT 段。"
                    "CI 管理面必须走公网 IP，避免美国 runner 为了部署美国节点先接入 tailnet。"
                )
        except ValueError as exc:
            errors.append(f"remote_proxy 的 `ansible_host` 不是合法 IP: {exc}")

    # 2. aliyun management SSH must use public IP (not Tailscale)
    try:
        aliyun_inventory_vars = find_inventory_host_vars(INVENTORY_PATH, "aliyun")
    except KeyError as exc:
        errors.append(f"inventory 缺少 aliyun 主机定义: {exc}")
        aliyun_inventory_vars = {}

    aliyun_ansible_host = aliyun_inventory_vars.get("ansible_host", "")
    if not aliyun_ansible_host:
        errors.append("`inventory-edge.ini` 中 aliyun 缺少 `ansible_host`。")
    else:
        try:
            if is_cgnat_ip(aliyun_ansible_host):
                errors.append(
                    f"aliyun 的 `ansible_host={aliyun_ansible_host}` 落在 Tailscale CGNAT 段。"
                    "CI 管理面必须走公网 IP。"
                )
        except ValueError as exc:
            errors.append(f"aliyun 的 `ansible_host` 不是合法 IP: {exc}")

    # 2.1 remote_proxy must use an RFC1123-safe Kubernetes node name
    remote_proxy_node_name = remote_proxy_vars.get("k3s_node_name", "")
    if remote_proxy_node_name != "remote-proxy":
        errors.append(
            "remote_proxy 必须显式设置 `k3s_node_name: remote-proxy`，"
            "避免把 inventory alias 里的下划线写入 Kubernetes Node 名。"
        )

    # 3. K3s server (tencent) Tailscale IP must be in CGNAT range
    k3s_server_tailscale_ip = tencent_vars.get("k3s_server_tailscale_ip", "")
    if not k3s_server_tailscale_ip:
        errors.append("`host_vars/tencent.yml` 缺少 `k3s_server_tailscale_ip`。")
    else:
        try:
            if not is_cgnat_ip(k3s_server_tailscale_ip):
                errors.append(
                    f"`k3s_server_tailscale_ip={k3s_server_tailscale_ip}` 不在 Tailscale CGNAT 段。"
                )
        except ValueError as exc:
            errors.append(f"`k3s_server_tailscale_ip` 不是合法 IP: {exc}")

    # 4. k3s_server_url must point to tencent's Tailscale IP
    k3s_server_url = global_vars.get("k3s_server_url", "")
    try:
        k3s_server_url_host = parse_url_host(k3s_server_url)
    except ValueError as exc:
        errors.append(str(exc))
        k3s_server_url_host = ""
    if k3s_server_url_host and k3s_server_tailscale_ip and k3s_server_url_host != k3s_server_tailscale_ip:
        errors.append(
            "`group_vars/all/public.yml` 中 `k3s_server_url` 必须指向 "
            f"`k3s_server_tailscale_ip`。当前为 {k3s_server_url_host} != {k3s_server_tailscale_ip}。"
        )

    # 5. TLS SANs must include tencent's Tailscale IP and public management IP
    tls_sans = tencent_vars.get("k3s_server_tls_sans", []) or []
    tencent_ansible_host = (find_inventory_host_vars(INVENTORY_PATH, "tencent")
                            .get("ansible_host", ""))
    if k3s_server_tailscale_ip and k3s_server_tailscale_ip not in tls_sans:
        errors.append("`k3s_server_tls_sans` 必须包含 tencent 的 Tailscale IP。")
    if tencent_ansible_host and tencent_ansible_host not in tls_sans:
        errors.append("`k3s_server_tls_sans` 必须包含 tencent 的公网管理 IP。")

    # 6. tencent must have nodivert to avoid cloud provider 100.x conflicts
    if tencent_vars.get("k3s_prereq_tailscale_nodivert") is not True:
        errors.append(
            "tencent 必须保持 `k3s_prereq_tailscale_nodivert: true`，"
            "否则云厂商 100.x 网段冲突会再次导致 SSH/控制面失联。"
        )

    # 7. aliyun agent must follow the current cluster API contract
    aliyun_vars_path = ROOT / "edge/ansible/host_vars/aliyun/public.yml"
    aliyun_vars = load_yaml(aliyun_vars_path)
    aliyun_agent_url = aliyun_vars.get("k3s_agent_server_url", "")
    try:
        aliyun_agent_host = parse_url_host(aliyun_agent_url)
    except ValueError as exc:
        errors.append(str(exc))
        aliyun_agent_host = ""
    if aliyun_agent_host and k3s_server_tailscale_ip and aliyun_agent_host != k3s_server_tailscale_ip:
        errors.append(
            "aliyun 的 `k3s_agent_server_url` 必须指向当前 K3s API 地址"
            f"（tencent Tailscale IP），当前为 {aliyun_agent_host} != {k3s_server_tailscale_ip}。"
        )

    notes.append(f"remote_proxy SSH 管理面: {remote_proxy_ansible_host or 'missing'}")
    notes.append(f"remote_proxy K8s 节点名: {remote_proxy_node_name or 'missing'}")
    notes.append(f"aliyun SSH 管理面: {aliyun_ansible_host or 'missing'}")
    notes.append(f"cluster API: {k3s_server_url or 'missing'}")
    notes.append(f"tencent (server) Tailscale IP: {k3s_server_tailscale_ip or 'missing'}")
    notes.append(f"aliyun agent API override: {aliyun_agent_url or 'missing'}")

    if errors:
        print("CI TOPOLOGY VALIDATION FAILED")
        for item in notes:
            print(f"  - {item}")
        print()
        for item in errors:
            print(f"  x {item}")
        return 1

    print("CI TOPOLOGY VALIDATION PASSED")
    for item in notes:
        print(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
