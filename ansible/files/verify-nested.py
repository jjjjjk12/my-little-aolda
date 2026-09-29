#!/usr/bin/env python3
"""Boot a disposable ARM64 guest. Require QMP KVM confirmation and guest login."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone

import pexpect


def qmp_command(stream, command):
    stream.write((json.dumps({'execute': command}) + '\n').encode())
    stream.flush()
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError('QMP connection closed')
        response = json.loads(line)
        if 'error' in response:
            raise RuntimeError(str(response['error']))
        if 'return' in response:
            return response['return']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--firmware', required=True)
    parser.add_argument('--memory', default='512')
    parser.add_argument('--cpus', default='1')
    args = parser.parse_args()
    directory = Path(args.directory)
    # Do not let concurrent runs replace one another's evidence.
    lock = (directory / 'verify.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    result = {'passed': False, 'started_at': datetime.now(timezone.utc).isoformat()}
    child = None
    started = time.monotonic()
    try:
        result['qemu_version'] = subprocess.check_output(
            ['qemu-system-aarch64', '--version'], text=True).splitlines()[0]
        with tempfile.TemporaryDirectory(prefix='aolda-kvm-') as runtime, \
                (directory / 'serial.log').open('w', buffering=1) as log:
            qmp_path = os.path.join(runtime, 'qmp.sock')
            argv = [
                '-machine', 'virt', '-accel', 'kvm', '-cpu', 'host',
                '-smp', args.cpus, '-m', args.memory,
                '-bios', args.firmware,
                '-drive', f'file={directory}/cirros-aarch64.img,format=qcow2,if=virtio',
                '-snapshot', '-netdev', 'user,id=net0',
                '-device', 'virtio-net-pci,netdev=net0',
                '-nographic', '-monitor', 'none',
                '-qmp', f'unix:{qmp_path},server=on,wait=off',
            ]
            result['qemu_argv'] = argv
            child = pexpect.spawn('qemu-system-aarch64', argv,
                                  encoding='utf-8', codec_errors='replace', timeout=360)
            child.logfile_read = log
            deadline = time.monotonic() + 20
            while not os.path.exists(qmp_path):
                if not child.isalive() or time.monotonic() > deadline:
                    raise RuntimeError('QEMU did not expose its QMP socket')
                time.sleep(0.1)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(15)
                sock.connect(qmp_path)
                with sock.makefile('rwb') as stream:
                    greeting = json.loads(stream.readline())
                    if 'QMP' not in greeting:
                        raise RuntimeError('Invalid QMP greeting')
                    qmp_command(stream, 'qmp_capabilities')
                    result['kvm'] = qmp_command(stream, 'query-kvm')
                    if result['kvm'] != {'enabled': True, 'present': True}:
                        raise RuntimeError('KVM is not active')
            child.expect(r'login:')
            child.sendline('cirros')
            child.expect(r'Password:', timeout=30)
            # Public test-image credential, not a private infrastructure secret.
            child.sendline('gocubsgo')
            child.expect(r'\$ ', timeout=30)
            # Anchored output checks avoid treating echoed input as success.
            child.sendline("printf 'AOLDA_ARCH='; uname -m; printf 'AOLDA_USER='; id -un")
            child.expect(r'(?m)^AOLDA_ARCH=aarch64\r?$', timeout=30)
            child.expect(r'(?m)^AOLDA_USER=cirros\r?$', timeout=30)
            child.expect(r'\$ ', timeout=30)
            result['guest_architecture'] = 'aarch64'
            result['guest_login'] = 'cirros'
            child.sendline('sudo poweroff')
            child.expect(pexpect.EOF, timeout=60)
            child.close()
            result['qemu_exit_status'] = child.exitstatus
            if child.exitstatus != 0:
                raise RuntimeError('QEMU did not exit cleanly')
            result['clean_shutdown'] = True
            result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if child is not None and child.isalive():
            child.terminate(force=True)
        result['elapsed_seconds'] = round(time.monotonic() - started, 2)
        (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
        lock.close()
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
