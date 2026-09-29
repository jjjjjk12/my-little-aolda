# 중첩 ARM64 VM 검증

Mac의 Ansible에서 SSH로 Ubuntu 노드를 설정하고, 그 안에서 작은 CirrOS 게스트를 KVM으로 부팅한다. 현재 검증 대상은 Lima의 `aolda-probe`이며, 전체 OpenStack 배포 디렉터리 구조를 확정한 것은 아니다.

## 파일

- `inventory.ini`: 사용자가 작성한 Lima SSH 접속 정보.
- `probe-vars.yml`: 게스트 이미지 URL·SHA256, VM 내부 작업 경로, 펌웨어, CPU·메모리.
- `prepare-probe.yml`: 사전 조건 검사, 패키지 설치, 이미지 다운로드, 검증 스크립트 배치.
- `verify-probe.yml`: 실제 부팅 검증 및 결과를 Mac으로 가져오기.
- `files/verify-nested.py`: QMP의 KVM 상태 확인, 시리얼 로그인, 게스트 명령 실행, 정상 종료.
- `artifacts/<inventory 호스트명>/`: 매 실행의 결과와 시리얼 로그. 실행마다 갱신하며 Git 추적에서 제외한다.

## 실행

Mac에서 실행한다. Ansible과 Lima가 설치되어 있어야 한다.

```bash
limactl start aolda-probe
cd /Users/jjjjjk12/Migration/dev/mla/ansible

ansible probe -i inventory.ini -m ansible.builtin.ping
ansible-playbook -i inventory.ini prepare-probe.yml --syntax-check
ansible-playbook -i inventory.ini verify-probe.yml --syntax-check
ansible-playbook -i inventory.ini prepare-probe.yml
ansible-playbook -i inventory.ini verify-probe.yml
```

설치 단계는 반복 적용할 수 있다. 설치 직후 다시 실행하면 변경이 없어야 한다. apt 캐시 유효기간(1시간)이 지나면 캐시 갱신이 변경으로 보고될 수 있다. 검증 단계는 실행할 때마다 내부 VM을 새로 부팅한다. `--check`는 실제 부팅을 하지 않으므로 검증 성공의 근거로 사용하지 않는다.

## 성공 조건

1. QEMU를 `-accel kvm -cpu host`로 실행한다. 소프트웨어 에뮬레이션으로 대체하지 않는다.
2. QMP `query-kvm`에서 `present: true`, `enabled: true`를 확인한다.
3. CirrOS 콘솔에 로그인한다.
4. 내부 게스트의 `uname -m` 결과 `aarch64`, `id -un` 결과 `cirros`를 확인한다.
5. 내부 게스트에서 `sudo poweroff` 후 QEMU 종료 코드 0을 확인한다.

내부 VM은 1 vCPU·512MiB RAM을 사용한다. QEMU `-snapshot`으로 임시 디스크 쓰기를 사용하므로 원본 이미지에 게스트 변경을 저장하지 않는다. 네트워크는 QEMU user-mode NAT이며 외부로 로그인 포트를 열지 않는다. CirrOS의 공개 테스트 계정 `cirros` / `gocubsgo`는 이 일회성 실습에만 사용한다.

검증이 끝나면 내부 VM은 종료되고, 바깥쪽 Lima VM과 설치 도구·원본 이미지는 남는다. 오류 발생 시에도 스크립트는 자신이 실행한 QEMU를 종료하도록 구성했다. 결과는 바깥 VM의 `/var/lib/aolda-nested-probe/`와 Mac의 `artifacts/`에 남는다.

## 2026-09-29 검증 결과

- 환경: M5 Pro → Lima 2.2.0 VZ → Ubuntu 24.04 ARM64 → CirrOS 0.6.3 ARM64.
- QEMU: 8.2.2, Ubuntu 패키지 `1:8.2.2+ds-0ubuntu1.18`.
- KVM 활성, 게스트 로그인·명령 실행·정상 종료 확인. 부팅부터 종료까지 약 67.52초(성능 벤치마크 아님).
- 준비 플레이북: 첫 실행 `ok=8 changed=4 failed=0`, 두 번째 실행 `ok=8 changed=0 failed=0`.
- 검증 플레이북: `failed=0`. 결과 파일을 가져오는 작업은 변경으로 표시된다.
- CirrOS의 메타데이터 서버 재시도는 이 독립 실습에 메타데이터 서버가 없어서 발생하며, 이후 로그인까지 진행됨을 확인했다.

## 이식성과 남은 검증

플레이북에는 Lima 실행 명령이나 Mac 사용자 경로를 넣지 않았다. 다른 Ubuntu 24.04 ARM64 KVM 호스트를 검증할 때는 inventory의 SSH 정보와 필요한 환경 변수를 바꾼다. x86 호스트는 사전 검사에서 실패하며, x86용 이미지·QEMU·펌웨어 검증 구성을 별도로 추가해야 한다.

CirrOS 이미지는 체크섬을 고정했다. apt 패키지는 `state: present`이므로 패키지 버전까지 완전히 고정한 재현 환경은 아직 아니다. 이후 배포 버전 조합을 확정할 때 저장소와 패키지 버전 정책을 정한다.

이번 결과는 중첩 KVM 부팅 가능성을 확인한 것이다. libvirt/Nova 통합, OpenStack 컨테이너 이미지 ARM64 지원, 다중 노드 네트워크, Ceph는 아직 검증하지 않았다.

## 근거 문서

- CirrOS 이미지와 체크섬: https://download.cirros-cloud.net/0.6.3/
- QEMU ARM virt 머신: https://www.qemu.org/docs/master/system/arm/virt
- Lima 중첩 가상화 설정: https://github.com/lima-vm/lima/blob/v2.2.0/templates/default.yaml
