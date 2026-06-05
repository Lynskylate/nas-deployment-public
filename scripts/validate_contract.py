import yaml
import sys

def load_manifest(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)

def check_subuid_overlap(infra, app):
    conflicts = []
    infra_ranges = infra.get('subuid', []) or []
    app_ranges = app.get('subuid', []) or []
    for a in app_ranges:
        a_start = a['start']
        a_end = a_start + a['size']
        for i in infra_ranges:
            i_start = i['start']
            i_end = i_start + i['size']
            if a_start < i_end and i_start < a_end:
                conflicts.append(
                    "subuid OVERLAP: {} [{}-{}) conflicts with {} [{}-{})".format(
                        a['user'], a_start, a_end, i['user'], i_start, i_end
                    )
                )
    return conflicts

def check_port_conflicts(infra, app):
    conflicts = []
    infra_ports = set()
    for p in (infra.get('ports', []) or []):
        infra_ports.add((p['port'], p.get('protocol', 'tcp')))
    for p in (app.get('ports', []) or []):
        port = p['port']
        proto = p.get('protocol', 'tcp')
        if (port, proto) in infra_ports:
            conflicts.append(
                "port CONFLICT: {}/{} ({}) claimed by both layers".format(
                    proto, port, p.get('service', '?')
                )
            )
    return conflicts

def check_user_conflicts(infra, app):
    conflicts = []
    infra_users = set()
    for u in (infra.get('users', []) or []):
        infra_users.add(u['user'])
    app_users = set()
    for u in (app.get('users', []) or []):
        app_users.add(u['user'])
    for user in infra_users & app_users:
        conflicts.append("user CONFLICT: {} declared in both layers".format(user))
    return conflicts

def check_nftables(infra, app):
    conflicts = []
    app_chains = app.get('nftables_chains', []) or []
    if app_chains:
        conflicts.append("nftables VIOLATION: app declares chains {}".format(app_chains))
    return conflicts

infra = load_manifest(sys.argv[1])
app = load_manifest(sys.argv[2])

all_conflicts = []
all_conflicts.extend(check_subuid_overlap(infra, app))
all_conflicts.extend(check_port_conflicts(infra, app))
all_conflicts.extend(check_user_conflicts(infra, app))
all_conflicts.extend(check_nftables(infra, app))

if all_conflicts:
    print("CONTRACT VALIDATION FAILED")
    for c in all_conflicts:
        print("  x " + c)
    sys.exit(1)
else:
    infra_ports = len(infra.get('ports', []) or [])
    app_ports = len(app.get('ports', []) or [])
    infra_subuid = len(infra.get('subuid', []) or [])
    app_subuid = len(app.get('subuid', []) or [])
    print("CONTRACT VALIDATION PASSED")
    print("  Ports:  {} infra + {} app (no overlap)".format(infra_ports, app_ports))
    print("  Subuid: {} infra + {} app (no overlap)".format(infra_subuid, app_subuid))
    print("  Users:  infra has {} + app has {} (no overlap)".format(
        len(infra.get('users', []) or []),
        len(app.get('users', []) or [])
    ))
    print("  nftables: app declares {} chains (correct)".format(
        len(app.get('nftables_chains', []) or [])
    ))
    sys.exit(0)
