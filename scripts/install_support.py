#!/usr/bin/env python3
"""Local installer helpers. Never print credentials or private key material."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.ansible/install'
LIMA = Path(os.environ.get('LIMA_HOME', str(Path.home() / '.lima'))).expanduser().resolve()
GROUPS = ROOT / 'ansible/inventory/atmosphere/group_vars'


def read_yaml(path):
    return yaml.safe_load(path.read_text()) or {}


def nodes():
    configs = read_yaml(ROOT / 'ansible/var/lima-vars.yml')['lima_nodes']
    addresses = read_yaml(ROOT / 'ansible/var/network-vars.yml')['mla_management_addresses']
    result = []
    for item in configs:
        name = item['name']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Invalid Lima node name')
        result.append((name, str(ipaddress.IPv4Address(addresses[name]))))
    if not result or len({n for n, _ in result}) != len(result) or len({a for _, a in result}) != len(result):
        raise ValueError('Node names and addresses must be nonempty and unique')
    return result


def write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'w', encoding='utf-8') as stream:
        os.chmod(temp, 0o600)
        stream.write(text)
    temp.replace(path)


def lima_shell(name, *args):
    return subprocess.run(['limactl', 'shell', name, '--', *args], check=True,
                          capture_output=True, text=True, timeout=90).stdout.strip()


def bootstrap():
    lines = ['[mla]']
    for name, _ in nodes():
        config = LIMA / name / 'ssh.config'
        if not config.is_file():
            raise ValueError(f'Missing {config}; run the vms stage first')
        args = shlex.join(['-F', str(config)])
        lines.append(f'{name} ansible_host=lima-{name} ansible_ssh_common_args={json.dumps(args)}')
    lines += ['', '[mla:vars]', 'ansible_connection=ssh', 'ansible_python_interpreter=/usr/bin/python3']
    write_private(STATE / 'lima.ini', '\n'.join(lines) + '\n')
    print('Prepared Lima bootstrap inventory.')


def access():
    known = []
    lines = ['[controllers]']
    for name, address in nodes():
        user = lima_shell(name, 'id', '-un')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', user):
            raise ValueError('Unexpected guest username')
        key = lima_shell(name, 'sudo', 'cat', '/etc/ssh/ssh_host_ed25519_key.pub').split()
        if len(key) < 2 or key[0] != 'ssh-ed25519':
            raise ValueError('Unexpected guest host key')
        # Trust the key read through Lima, not an unauthenticated network keyscan.
        known.append(f'{address},{name} {key[0]} {key[1]}')
        lines.append(f'{name} ansible_host={address} ansible_user={user}')
    key_path = LIMA / '_config/user'
    if not key_path.is_file():
        raise ValueError('Lima SSH private key is missing')
    write_private(STATE / 'known_hosts', '\n'.join(known) + '\n')
    lines += ['', '[computes:children]', 'controllers', '', '[cephs:children]', 'controllers',
              '', '[all:vars]', 'ansible_connection=ssh',
              "ansible_ssh_private_key_file=" + str(key_path),
              'ansible_ssh_common_args=' + shlex.join([
                  '-o', 'StrictHostKeyChecking=yes', '-o', 'GlobalKnownHostsFile=/dev/null',
                  '-o', 'UserKnownHostsFile=' + str(STATE / 'known_hosts')])]
    inventory = STATE / 'inventory'
    inventory.mkdir(parents=True, exist_ok=True)
    link = inventory / 'group_vars'
    if link.is_symlink() and link.resolve() != GROUPS.resolve():
        link.unlink()
    if not link.exists():
        link.symlink_to(GROUPS, target_is_directory=True)
    elif link.resolve() != GROUPS.resolve():
        raise ValueError('Generated inventory group_vars conflicts with an existing directory')
    write_private(inventory / 'hosts.ini', '\n'.join(lines) + '\n')
    print('Prepared verified SSH host keys and deployment inventory; existing inventories preserved.')


def prepare_secrets():
    destination = GROUPS / 'all/secrets.yml'
    if destination.exists():
        if not destination.read_text().strip():
            raise ValueError('Existing secrets.yml is empty; restore it rather than rotating credentials')
        os.chmod(destination, 0o600)
        print('Preserving existing secrets.yml.')
        return 10
    for name, _ in nodes():
        result = lima_shell(name, 'sudo', 'sh', '-c',
                            'if test -e /etc/kubernetes/admin.conf; then echo deployed; else echo fresh; fi')
        if result != 'fresh':
            raise ValueError('Existing deployment detected without secrets.yml; restore the original secrets backup')
    # Reuse the pinned upstream generator rather than maintaining a second list of passwords.
    collection = ROOT / '.ansible/collections/ansible_collections/vexxhost/atmosphere'
    plays = read_yaml(collection / 'playbooks/generate_workspace.yml')
    matches = [p for p in plays if p['name'] == 'Generate secrets for workspace']
    if len(matches) != 1:
        raise ValueError('Upstream secret generation changed; review the installer')
    play = matches[0]
    play.update(connection='local', no_log=True)
    play['vars'].update(secrets_path=str(destination), ansible_python_interpreter=sys.executable)
    roles = shlex.quote(str(collection / 'roles'))
    for task in play['tasks']:
        if 'with_lines' in task:
            task['with_lines'] = task['with_lines'].replace('{{ playbook_dir }}/../roles', roles)
        for module in ('ansible.builtin.file', 'ansible.builtin.copy'):
            if task.get(module, {}).get('dest', task.get(module, {}).get('path')) == '{{ secrets_path }}':
                task[module]['mode'] = '0600'
    write_private(STATE / 'generate-secrets.yml', yaml.safe_dump([play], sort_keys=False))
    print('Prepared the upstream secret-generation play (all output censored).')
    return 0


def dns():
    values = read_yaml(GROUPS / 'all/endpoints.yml')
    values.update(read_yaml(GROUPS / 'all/skyline.yml'))
    expected = read_yaml(GROUPS / 'all/keepalived.yml')['keepalived_vip']
    hosts = sorted({str(v) for k, v in values.items() if k.endswith('_host')})
    errors = []
    for host in hosts:
        try:
            ips = {r[4][0] for r in socket.getaddrinfo(host, None, socket.AF_INET)}
            if ips != {expected}:
                errors.append(host)
        except socket.gaierror:
            errors.append(host)
    if errors:
        raise ValueError(f'DNS must resolve service names to {expected}: ' + ', '.join(errors))
    print(f'DNS: {len(hosts)} service names resolve to {expected}.')


def ping():
    # Read only the test address; never emit clouds.yaml or a token.
    code = """import openstack
c = openstack.connect(cloud='atmosphere')
s = c.compute.find_server('mla-smoke-vm', ignore_missing=False)
ports = {p.id for p in c.network.ports(device_id=s.id)}
ips = [i.floating_ip_address for i in c.network.ips() if i.port_id in ports]
assert len(ips) == 1
print(ips[0])
"""
    address = lima_shell(nodes()[0][0], 'sudo', '/opt/atmosphere/venv/bin/python3', '-c', code)
    address = str(ipaddress.IPv4Address(address))
    subprocess.run(['ping', '-c', '3', '-W', '1000', address], check=True, timeout=15)


def main():
    actions = {'bootstrap': bootstrap, 'access': access, 'secrets': prepare_secrets, 'dns': dns, 'ping': ping}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise ValueError('Expected: bootstrap | access | secrets | dns | ping')
    return actions[sys.argv[1]]() or 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        # Subprocess stderr can contain sensitive diagnostics; do not print captured output.
        message = str(error) if isinstance(error, (ValueError, KeyError)) else type(error).__name__
        print('Installer preflight failed: ' + message, file=sys.stderr)
        sys.exit(1)
