"""Local tests only: no VM, sudo, deployment, or external network changes."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('support', ROOT / 'scripts/install_support.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mla installer test ')
        self.root = Path(self.temp.name)
        shutil.copy(ROOT / 'install.sh', self.root / 'install.sh')
        for d in ('ansible', '.venv-atmosphere/bin', 'fake-bin', '.ansible/install/inventory'):
            (self.root / d).mkdir(parents=True)
        (self.root / '.ansible/install/inventory/hosts.ini').write_text('[controllers]\ntest\n')
        self.executable('.venv-atmosphere/bin/ansible-playbook', 'exit 0')
        self.executable('fake-bin/uname', '[ "$1" = -s ] && echo Darwin || echo arm64')
        self.executable('fake-bin/pgrep', 'exit 1')
        self.executable('fake-bin/caffeinate', 'exit 0')
        self.executable('ansible/run-playbook.sh',
                        'printf "%s\\n" "$*" >> calls\ncase "$1" in *site.yml) exit "${FAIL_DEPLOY:-0}";; esac')
        self.env = dict(os.environ, PATH=str(self.root / 'fake-bin') + ':' + os.environ['PATH'])

    def tearDown(self):
        self.temp.cleanup()

    def executable(self, path, body):
        p = self.root / path
        p.write_text('#!/bin/bash\n' + body + '\n')
        p.chmod(0o700)

    def run_install(self, *args, **env):
        return subprocess.run(['bash', str(self.root / 'install.sh'), *args],
                              env=dict(self.env, **env), capture_output=True, text=True)

    def test_plan_makes_no_run_directory(self):
        r = self.run_install('--plan', '--from', 'guest-network', '--skip-probe')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ['guest-network', 'access', 'secrets', 'dns', 'deploy', 'verify'])
        self.assertFalse((self.root / '.ansible/runs').exists())

    def test_invalid_range(self):
        self.assertEqual(self.run_install('--from', 'verify', '--until', 'deps').returncode, 2)

    def test_order_and_no_smoke(self):
        r = self.run_install('--from', 'deploy', '--skip-smoke')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.root / 'calls').read_text().splitlines(),
                         ['ansible/playbook/site.yml -b', 'ansible/playbook/verify-install.yml -b'])
        run = next((self.root / '.ansible/runs').iterdir())
        self.assertEqual((run / 'exit-code').read_text().strip(), '0')
        self.assertFalse((self.root / '.ansible/install/lock').exists())

    def test_failure_stops_before_verification_and_records_stage(self):
        r = self.run_install('--from', 'deploy', '--skip-smoke', FAIL_DEPLOY='23')
        self.assertEqual(r.returncode, 23, r.stderr)
        self.assertEqual((self.root / 'calls').read_text().strip(), 'ansible/playbook/site.yml -b')
        run = next((self.root / '.ansible/runs').iterdir())
        self.assertEqual((run / 'last-stage').read_text().strip(), 'deploy')
        self.assertEqual((run / 'exit-code').read_text().strip(), '23')
        self.assertFalse((self.root / '.ansible/install/lock').exists())

    def test_lock_and_missing_inventory(self):
        lock = self.root / '.ansible/install/lock'
        lock.mkdir()
        self.assertNotEqual(self.run_install('--from', 'deploy').returncode, 0)
        lock.rmdir()
        (self.root / '.ansible/install/inventory/hosts.ini').unlink()
        self.assertNotEqual(self.run_install('--from', 'verify', '--skip-smoke').returncode, 0)
        self.assertFalse((self.root / 'calls').exists())


class HelperTests(unittest.TestCase):
    def test_generated_inventories_handle_spaces_and_preserve_group_vars(self):
        with tempfile.TemporaryDirectory(prefix='mla helper spaces ') as t:
            root = Path(t)
            state, lima, groups = root / 'state', root / 'lima', root / 'group_vars'
            (lima / 'mla-01').mkdir(parents=True)
            (lima / 'mla-01/ssh.config').write_text('Host lima-mla-01\n')
            (lima / '_config').mkdir()
            (lima / '_config/user').write_text('dummy test key')
            (groups / 'all').mkdir(parents=True)
            (groups / 'all/test.yml').write_text('test_group_variable: preserved\n')
            with patch.object(support, 'STATE', state), patch.object(support, 'LIMA', lima), \
                 patch.object(support, 'GROUPS', groups), patch.object(support, 'nodes', return_value=[('mla-01', '192.168.110.111')]), \
                 patch.object(support, 'lima_shell', side_effect=['portable.guest', 'ssh-ed25519 AAAA test']), contextlib.redirect_stdout(io.StringIO()):
                support.bootstrap()
                support.access()
            inv = ROOT / '.venv-atmosphere/bin/ansible-inventory'
            r = subprocess.run([str(inv), '-i', str(state / 'inventory/hosts.ini'), '--list'], capture_output=True, text=True, check=True)
            host = json.loads(r.stdout)['_meta']['hostvars']['mla-01']
            self.assertEqual(host['ansible_user'], 'portable.guest')
            self.assertEqual(host['test_group_variable'], 'preserved')
            self.assertEqual(host['ansible_ssh_private_key_file'], str(lima / '_config/user'))
            self.assertIn('StrictHostKeyChecking=yes', host['ansible_ssh_common_args'])
            r = subprocess.run([str(inv), '-i', str(state / 'lima.ini'), '--list'], capture_output=True, text=True, check=True)
            self.assertIn(str(lima / 'mla-01/ssh.config'), json.loads(r.stdout)['_meta']['hostvars']['mla-01']['ansible_ssh_common_args'])

    def test_missing_secrets_on_deployed_node_are_not_regenerated(self):
        with tempfile.TemporaryDirectory() as t, patch.object(support, 'GROUPS', Path(t)), \
             patch.object(support, 'nodes', return_value=[('mla-01', '192.168.110.111')]), \
             patch.object(support, 'lima_shell', return_value='deployed'):
            with self.assertRaisesRegex(ValueError, 'restore'):
                support.prepare_secrets()

    def test_existing_secrets_remain_identical(self):
        with tempfile.TemporaryDirectory() as t, patch.object(support, 'GROUPS', Path(t)), contextlib.redirect_stdout(io.StringIO()):
            p = Path(t) / 'all/secrets.yml'
            p.parent.mkdir(); p.write_text('example: keep-original\n')
            self.assertEqual(support.prepare_secrets(), 10)
            self.assertEqual(p.read_text(), 'example: keep-original\n')


if __name__ == '__main__':
    unittest.main()
