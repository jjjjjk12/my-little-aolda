# 중첩 ARM64 VM 검증

Mac의 Ansible에서 SSH로 Ubuntu 노드를 설정하고, 그 안에서 작은 CirrOS 게스트를 KVM으로 부팅한다. 검증 대상은 Lima의 `aolda-probe` 또는 `mla` 그룹의 세 노드이며, 전체 OpenStack 배포 디렉터리 구조를 확정한 것은 아니다.

## 파일

- `inventory/inventory.ini`: 기존 `probe` 그룹의 Lima SSH 접속 정보.
- `inventory/inventory-lima.ini`: `mla` 그룹의 세 노드 SSH 접속 정보.
- `var/lima-vars.yml`: Lima VM 사양과 이미지, 노드 목록.
- `playbook/create-lima.yml`: 디스크·VM 생성 및 부팅. YAML 출력 위치는 프로젝트의 `lima/vm/`.
- `templates/lima-node.yaml.j2`: VM별 Lima YAML 템플릿.
- `playbook/probe-vars.yml`: 게스트 이미지 URL·SHA256, VM 내부 작업 경로, 펌웨어, CPU·메모리.
- `playbook/prepare-probe.yml`: 사전 조건 검사, 패키지 설치, 이미지 다운로드, 검증 스크립트 배치.
- `playbook/verify-probe.yml`: 실제 부팅 검증 및 결과를 Mac으로 가져오기.
- `files/verify-nested.py`: QMP의 KVM 상태 확인, 시리얼 로그인, 게스트 명령 실행, 정상 종료.
- `artifacts/<inventory 호스트명>/`: 매 실행의 결과와 시리얼 로그. 실행마다 갱신하며 Git 추적에서 제외한다.

## 실행

Mac에서 실행한다. Ansible과 Lima가 설치되어 있어야 한다.

```bash
limactl start aolda-probe
cd /Users/jjjjjk12/Migration/dev/mla/ansible

ansible probe -i inventory/inventory.ini -m ansible.builtin.ping
ansible-playbook -i inventory/inventory.ini playbook/prepare-probe.yml --syntax-check
ansible-playbook -i inventory/inventory.ini playbook/verify-probe.yml --syntax-check
ansible-playbook -i inventory/inventory.ini playbook/prepare-probe.yml
ansible-playbook -i inventory/inventory.ini playbook/verify-probe.yml
```

`mla` 그룹을 사용할 때도 위와 같이 `ansible/` 디렉터리에서 실행한다.

```bash
ansible mla -i inventory/inventory-lima.ini -m ansible.builtin.ping
ansible-playbook -i inventory/inventory-lima.ini playbook/prepare-probe.yml -e target_group=mla
ansible-playbook -i inventory/inventory-lima.ini playbook/verify-probe.yml -e target_group=mla
```

VM 생성 플레이북은 Mac 자체를 대상으로 실행한다.

```bash
ansible-playbook -i localhost, playbook/create-lima.yml --syntax-check
ansible-playbook -i localhost, playbook/create-lima.yml
```

플레이북의 로컬 파일 참조는 플레이북 위치를 기준으로 한다. 검증 결과는 플레이북 폴더 아래가 아닌 `ansible/artifacts/`에 저장한다.

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

중첩 부팅 검증용 플레이북에는 Lima 실행 명령이나 Mac 사용자 경로를 넣지 않았다. VM 생성용 플레이북은 Mac의 Lima를 사용한다. 다른 Ubuntu 24.04 ARM64 KVM 호스트를 검증할 때는 inventory의 SSH 정보와 필요한 환경 변수를 바꾼다. x86 호스트는 사전 검사에서 실패하며, x86용 이미지·QEMU·펌웨어 검증 구성을 별도로 추가해야 한다.

CirrOS 이미지는 체크섬을 고정했다. apt 패키지는 `state: present`이므로 패키지 버전까지 완전히 고정한 재현 환경은 아직 아니다. 이후 배포 버전 조합을 확정할 때 저장소와 패키지 버전 정책을 정한다.

이번 결과는 중첩 KVM 부팅 가능성을 확인한 것이다. libvirt/Nova 통합, OpenStack 컨테이너 이미지 ARM64 지원, 다중 노드 네트워크, Ceph는 아직 검증하지 않았다.

## 근거 문서

- CirrOS 이미지와 체크섬: https://download.cirros-cloud.net/0.6.3/
- QEMU ARM virt 머신: https://www.qemu.org/docs/master/system/arm/virt
- Lima 중첩 가상화 설정: https://github.com/lima-vm/lima/blob/v2.2.0/templates/default.yaml

## Atmosphere ARM64 Ceph 이미지와 배포 진입점

이 랩의 전체 배포는 `playbook/site.yml`로 실행한다. 이 파일은 Ceph 이미지 준비 후
Atmosphere 7.8.1의 site와 같은 순서로 배포한다. Ceph·OpenStack·모니터링 진입점은
로컬 플레이북에서 공식 역할들을 선택해서 사용한다. Kubernetes는 로컬 진입점에서
공식 역할을 사용하고, CSI·공통 인프라는 공식 플레이북을 가져온다.
마지막에 별도의 Skyline 플레이북을 실행한다.

`playbook/kubernetes.yml`은 파일 다운로드의 응답 대기 시간을 120초로 늘리고,
모든 Kubernetes 플레이에 `any_errors_fatal: true`를 적용한다. 노드 일부가 실패한 채
DB 등 다음 단계로 진행하지 않도록 하기 위한 설정이다. 공식 역할의 버전별 SHA256
검증과 재시도는 유지한다. 타임아웃은 파일 전체 다운로드 시간 제한과는 다르다.
설치된 Galaxy 컬렉션은 수정하지 않는다.

```bash
cd /Users/jjjjjk12/Migration/dev/mla
source .venv-atmosphere/bin/activate
export ANSIBLE_COLLECTIONS_PATH="$PWD/.ansible/collections"
ansible-playbook -i ansible/inventory/atmosphere/hosts.ini ansible/playbook/site.yml -b
```

현재 ARM64 CentOS 기반 Ceph 이미지에서는 `ceph-osd --version`도 종료 코드 139로
충돌했다. `TCMALLOC_STACKTRACE_METHOD=generic_fp`를 적용하면 정상 종료한다.
`templates/ceph.Dockerfile.j2`는 원본 이미지를 digest로 고정하고 이 환경변수만 추가한다.
이미지 자체에 환경변수를 넣으므로 ceph-volume의 자식 프로세스와 이후 생성되는
OSD 데몬에도 적용된다. 기존에 실행 중인 MON/MGR를 강제로 재시작하지는 않는다.

`inventory/atmosphere/group_vars/all/ceph.yml`에서 기반 이미지, 로컬 이미지 태그와
Ceph 버전을 관리한다. 실제 생성된 클러스터가 18.2.8이므로 이를 유지한다.
`cephadm_version`은 별도의 관리 도구 버전이며 기존 18.2.7을 유지한다.

`playbook/prepare-ceph-image.yml`은 다음을 수행한다.

1. Docker·cephadm을 준비하고 모든 Ceph 노드에서 같은 Dockerfile로 이미지를 빌드한다.
2. 이미지의 기반 digest·환경변수와 `ceph-osd --version`을 검증한다.
3. 새 클러스터만 로컬 이미지를 이용해 `--skip-pull`로 bootstrap한다.
4. 기존 클러스터는 버전과 cephadm 명령 응답을 확인한다. 설정 변경 시 cephadm 관리 모듈을
   잠시 비활성화해 백그라운드 이미지 조회와 설정 변경이 겹치지 않게 한다.
5. `mgr/cephadm/use_repo_digest=false`를 먼저 적용한 뒤 `container_image`를 지정하고
   모듈을 다시 활성화한다. 로컬 이미지에는 원격 저장소 digest가 없기 때문이다.
6. 기존의 빈 repo digest 오류로 멈춘 모듈도 같은 절차로 복구하고,
   `ceph cephadm get-pub-key`가 성공해야 다음 단계로 넘어간다.

이 복구는 cephadm 관리 모듈만 다시 활성화한다. VM·MON·OSD나 디스크를 초기화하지 않는다.
이미지 선택을 먼저 바꾼 뒤 digest 변환을 끄면 설정 적용 사이에 관리 모듈이 실패할 수 있다.

이미지는 레지스트리에 게시하지 않는다. 새 Ceph 노드를 추가할 때도 이 진입점을
실행해 이미지를 먼저 준비해야 한다. 이미지 준비를 건너뛰거나 일부 노드로 `--limit`하지 않는다.
기반 이미지나 우회 방식을 변경할 때는 로컬 이미지 태그도 새 값으로 변경한다.
새 이미지의 적용은 Ceph 업그레이드·재배포 절차와 별도로 검토해야 한다.

Reef cephadm은 `CEPHADM_IMAGE`를 읽는다. 로컬 `ceph.yml`에서 이 변수를 각 Ceph
플레이에 직접 전달한다. import_playbook에만 지정하면 하위 플레이의 environment에
덮어쓰이므로 Ceph 진입점이 필요하다. 설치된 컬렉션이 전달하는 `CEPH_CONTAINER_IMAGE`만으로는
bootstrap 이미지가 고정되지 않았다. 따라서 공식 site를 직접 호출하지 않는다.

Docker가 이미 설치된 노드에서 **이미지 빌드·실행 검사만** 하려면 다음을 실행한다.
이 명령은 클러스터 설정이나 OSD 디스크를 변경하지 않는다.

```bash
ansible-playbook -i ansible/inventory/atmosphere/hosts.ini \
  ansible/playbook/prepare-ceph-image.yml --tags ceph-image
```

이미지 검사는 OSD 디스크 초기화·운영 성공을 보장하지 않는다. 전체 배포를 재개한 뒤
OSD가 세 개 모두 `up/in`인지 추가 확인한다. 새 클러스터 bootstrap 경로는
기존 클러스터에 대한 검증과 별개다.

관련 ARM64 libunwind/tcmalloc 문제:
https://access.redhat.com/solutions/7143152

## 로컬 랩의 컴포넌트 선택과 Skyline

이번 목표는 VM 생성, Floating IP 접속, 볼륨 연결이다. 선택은 Git으로 관리하는
`playbook/openstack.yml`과 `playbook/monitoring.yml`의 역할 목록에 기록한다.
명령줄에서 매번 `--skip-tags`를 전달할 필요가 없다. Galaxy 컬렉션을 재설치해도
선택이 유지된다. 컬렉션 버전을 올릴 때는 로컬 플레이북과 upstream의 순서를 비교한다.

| 구분 | 이번 구성 |
| --- | --- |
| 기반 | Kubernetes, Ceph, CSI, DB, RabbitMQ, Memcached, 인증서, Ingress, VIP |
| OpenStack | Keystone, Glance, Placement, Nova, Neutron, Cinder |
| 네트워크·컴퓨트 보조 | Open vSwitch, libvirt, CoreDNS 및 공식 호스트 준비 역할 |
| 대시보드 | Skyline 2025.2, Horizon 제외 |
| 관측 | Prometheus, Grafana, Alertmanager, 기본 노드·OpenStack 메트릭 |
| 유지하는 의존성 | Keycloak·Valkey, Ceph/Rook 스토리지 연동 역할 |
| 제외 | Heat, Octavia, Magnum, Manila, Barbican, Staffeln, Loki, Vector, Goldpinger, IPMI/SMART exporter, Pushgateway |

Keycloak은 기본 Keystone 및 Grafana 설정이 사용하므로 유지한다. Barbican을
제외한 상태에서는 암호화 볼륨을 이번 실습 범위에 포함하지 않는다. 제외한 서비스의
기존 endpoint 변수와 Loki 용량 변수는 남아 있지만, 변수만으로 서비스가 설치되지는 않는다.
이미 설치된 서비스를 삭제하는 플레이북은 아니다.

`site.yml`은 핵심 서비스 배포 뒤 `playbook/skyline.yml`을 실행한다. Skyline은
공식 설치 가이드의 API·Console 통합 이미지 `99cloud/skyline:2025.2`를 사용하며,
ARM64 manifest를 확인한 digest로 고정했다. Atmosphere 공식 Skyline 역할이 아니라
이 랩에서 추가한 Kubernetes 배포 구성이다.

- 주소: `https://dashboard.mla.jinkang.dev` (기존 wildcard DNS 사용)
- 파드 1개, SQLite를 저장하는 1Gi PVC. 재시작 시 DB를 유지하며 HA 구성은 아니다.
- 전용 Keystone 서비스 계정을 생성하고 서비스 프로젝트에 admin 역할을 부여한다.
- CA 인증서를 마운트해 API 서버 인증서를 검증한다. 브라우저에도 랩 CA 신뢰 설정이 필요하다.
- 서비스 암호와 서명 키는 Mac의 `.ansible/secrets/`에 생성되고 Kubernetes Secret으로 전달된다.
  이 디렉터리는 Git 제외 대상이다. 클러스터를 유지하며 제어 머신을 옮길 때는 해당 비밀정보도
  안전하게 별도로 옮겨야 한다. Git만 복제해 기존 클러스터에 새 암호를 생성하지 않는다.
- initContainer에서 DB 마이그레이션 후 앱을 시작하고 HTTPS 접속을 검사한다.
  최종 사용자 로그인·VM 관리 동작은 실제 배포 후 추가 검증한다.

핵심 서비스가 준비된 뒤 Skyline 단계만 다시 실행할 때:

```bash
ansible-playbook -i ansible/inventory/atmosphere/hosts.ini ansible/playbook/skyline.yml -b
```

설정 위치: `inventory/atmosphere/group_vars/all/skyline.yml`.
템플릿: `templates/skyline.yaml.j2`, `templates/skyline-kubernetes.yml.j2`.
공식 설치 가이드: https://docs.openstack.org/skyline-apiserver/2025.2/install/docker-install-ubuntu.html

2026-09-30 검증: 전체 site 문법 검사, Skyline 템플릿 렌더링 및 제외 역할 검사 통과.
mla-01의 ARM64 VM에서 고정한 Skyline 이미지와 테스트용 설정으로 SQLite DB 초기화가
종료 코드 0으로 완료됐다. 네트워크가 없는 일회성 컨테이너에서 검사했으며 실제 Keystone
계정이나 OSD 디스크는 사용하지 않았다. 전체 클러스터 배포·사용자 로그인은 아직 검증 전이다.


## Infrastructure 재실행 및 ARM64 Ingress 설정

`playbook/infrastructure.yml`은 Atmosphere 7.8.1의 역할 순서를 유지하면서,
기존 Percona CR의 `status.pxc.version`과 `status.state`가 기록될 때까지
최대 약 15분 기다린 뒤 공식 Percona 역할을 실행한다. 초기화 도중 재실행했을 때
버전 필드가 아직 없어 실패하는 문제를 방지한다. CR이 없으면 공식 역할이 생성한다.
시간 내 상태가 채워지지 않으면 실패하므로 operator/DB 상태를 확인해야 한다.

`lab.yml`의 `ingress_nginx_helm_values.defaultBackend.enabled: false`는
amd64 전용 기본 백엔드 파드를 제거하고 ingress-nginx 내장 404 처리를 사용한다.
등록한 서비스의 Ingress 라우팅은 그대로 사용한다.

2026-09-30: Ingress·Percona 역할만 재실행해 3개 호스트 모두 failed=0 확인.
Percona는 DB 3개 및 HAProxy 3개 ready이며 기존 데이터/PVC를 유지했다.


## Ubuntu 24.04의 배포용 Python 환경

`site.yml`은 첫 단계에서 `playbook/prepare-python.yml`을 실행한다.
이 준비 단계만 `/usr/bin/python3`로 실행하여 Ubuntu 패키지
`python3-venv`, `python3-packaging`, `python3-pymysql`, `python3-openstacksdk`를
설치하고 `/opt/atmosphere/venv`를 생성한다. 이후 Ansible은
`inventory/atmosphere/group_vars/all/python.yml`에 지정한 가상환경 Python을 사용한다.

공식 Kubernetes 역할은 Ubuntu 24.04에서 시스템 패키지를 쓰지만 Keycloak 및
openstacksdk 역할은 pip를 사용한다. 가상환경은 시스템 패키지를 읽을 수 있고
추가 pip 설치는 가상환경에 한정되므로 PEP 668 보호를 해제할 필요가 없다.
Galaxy 컬렉션의 역할 파일은 수정하지 않는다. Mac의 `.venv-atmosphere`와는 별개다.

개별 플레이북을 새 VM에 직접 실행할 때는 `prepare-python.yml`을 먼저 실행한다.
기존 VM에서 공식 Keycloak의 PyMySQL 설치 및 MySQL 연결/DB 생성이 통과했으며,
가상환경 준비는 VM 3대에서 검증했다.

2026-09-30 추가 검증: 공식 Keycloak 역할 전체가 모든 호스트에서 failed=0으로
완료됐고 keycloak-0 파드가 1/1 Ready가 됐다. 전체 site 배포는 별도로 재개했다.


## 관리망 VIP와 Keepalived 의존성

이 랩의 서비스 VIP `192.168.110.121`은 미리 구성한 관리 인터페이스 `lima0`에
할당한다. `inventory/atmosphere/group_vars/all/keepalived.yml`에서
`keepalived_pod_dependency`의 openvswitch/ovn 목록을 비워 Neutron 대기를 제거한다.
공식 역할의 인터페이스 IPv4 대기 검사는 유지한다.

기본 Neutron 의존성을 사용하면 Keepalived가 아직 설치되지 않은 Neutron을 기다리고,
앞선 모니터링 단계는 VIP를 통해 Keycloak에 접속하려고 기다리는 순환 의존성이 생긴다.
나중에 VIP를 Neutron이 생성하는 브리지로 이동한다면 이 설정을 다시 검토해야 한다.

2026-09-30 검증: Keepalived 3개 모두 1/1 Ready, VIP 경유 Keycloak realm URL은
HTTP 200으로 응답했다. 실행 중인 site는 재시작 없이 Keycloak 대기를 통과했다.


## macOS에서 배포 실행

프로젝트 루트에서 `ansible/run-playbook.sh`를 실행하면 고정된 제어 머신 가상환경과
컬렉션 경로로 전체 site를 실행한다. 개별 플레이북 및 옵션도 전달할 수 있다.

```bash
ansible/run-playbook.sh
ansible/run-playbook.sh ansible/playbook/monitoring.yml --tags kube-prometheus-stack
```

macOS에서는 이 프로세스의 `no_proxy`/`NO_PROXY`를 `*`로 설정한다.
Keystone OpenID metadata의 URL lookup이 macOS 시스템 프록시 검색을 호출하면서
fork된 Ansible 작업 프로세스가 충돌하는 경로를 피한다. 시스템이나 사용자 셸의
프록시 설정은 변경하지 않는다. HTTP 프록시가 필수인 환경에서는 이 실행 설정을
재검토해야 한다. Python upstream 설명: https://bugs.python.org/msg293958

`lab.yml`은 pod-tls-sidecar를 ARM64 manifest가 있는 공식 v1.0.2의 digest로 고정한다.
기존 v1.0.0은 ARM64가 없어 인증서 파일을 만들지 못했고 node-exporter 및
Prometheus 보조 컨테이너의 실행을 막았다.

2026-09-30 검증: macOS의 Ansible URL lookup 검사가 3개 호스트에서 통과했다.
이미지 변경 후 node-exporter 3개는 2/2 Ready, Prometheus는 4/4 Ready이며
인증서 발급을 확인했다. 전체 site는 새 실행 스크립트로 재개했다.


## tmux 서버 실행 환경

기존 기본 tmux 서버에서는 controller-side Keycloak URL lookup이 `No route to host`로
실패했지만, 동일 명령의 직접 실행 및 새 tmux 서버 실행은 성공했다. macOS 권한이
원인인지는 확정하지 않았다. 기존 세션은 로그 보존용으로 유지하고 배포는 별도 소켓
`mla-deploy`의 `mla-site` 세션에서 실행한다.

```bash
tmux -L mla-deploy attach -t mla-site
```

이미 Keycloak이 배포된 이 클러스터에서는 재개 전에 같은 tmux 프로세스 환경에서
`ansible/run-playbook.sh ansible/playbook/check-controller-endpoints.yml`을 실행한다.
이 검사는 Keycloak이 없는 최초 설치에는 실행하지 않는다.


## Keystone의 Apache OpenID 모듈

고정된 ARM64 Keystone 2025.2 이미지에는 `libapache2-mod-auth-openidc`가 없어
공식 Apache 설정의 `OIDCClaimPrefix`를 인식하지 못했다.
`prepare-keystone-image.yml`은 공식 digest를 기반으로 Ubuntu 패키지
`2.4.15.1-1ubuntu0.1`을 추가하고 모듈 로드를 확인한 뒤 각 컨트롤러의 containerd에
`docker.io/mla/keystone:2025.2-oidc-v1`을 가져온다. API 이미지에만 override를 적용한다.
Docker 빌드는 DNS 접근을 위해 host 네트워크를 사용하며 서비스 파드 네트워크는 변경하지 않는다.
이미지는 외부 registry에 게시하지 않는다. 노드를 재생성하면 site의 준비 단계가 다시 생성한다.

중단된 최초 Helm 설치는 실행 중인 Helm이 없는 것을 확인한 뒤 release 메타데이터를
VM의 `/var/lib/mla/helm-recovery/`에 0600으로 백업하고 pending-install을 failed로 복구했다.
Secret 백업에는 민감 정보가 있으므로 Git에 넣지 않는다. DB/PVC는 삭제하지 않았다.

Atmosphere 7.8.1의 storage filter가 요구하는 Pydantic v2를 제어 머신 requirements와
lock 파일에 추가했다. 수정 이미지 적용 후 Keystone API 3개가 모두 Ready인 것을 확인했다.


## OpenStack CLI 의존성 순서

Rook의 서비스 프로젝트/역할 생성은 VM의 `openstack` 명령을 사용하므로 로컬
`openstack.yml` 첫 역할에 공식 `openstack_cli`를 추가했다. 공식 컨테이너 CLI를
사용하며 VM 3대에 wrapper를 설치하고 mla-01에서 토큰 발급 성공을 검증했다.
2026-09-30 재개는 완료된 기반 설치를 반복하지 않고 `openstack.yml` 성공 후
`skyline.yml`을 실행한다. 최초 설치의 진입점은 계속 `site.yml`이다.


## ARM64 스토리지 보조 이미지

Glance 스토리지 초기화 이미지의 `/usr/local/bin/kubectl`이 ARM64에서 실행되지 않아
Ceph 풀/사용자 생성 뒤 Kubernetes Secret 반영이 실패했다.
`prepare-arm64-cli-images.yml`은 공식 digest 기반 이미지에 VM의 검증된 ARM64
`/usr/bin/kubectl`을 복사한다. Glance/Cinder storage-init과 ceph-config-helper를
대상으로 이미지 내 CLI 실행을 검사한 뒤 각 컨트롤러의 containerd에 가져온다.
원본 바이너리는 공식 Kubernetes 설치 역할이 준비한다. 소스/템플릿 변경 시 재빌드한다.
기존 Ceph 풀, 사용자 및 DB는 초기화하지 않는다.

2026-09-30 검증: 보조 이미지 3종을 컨트롤러 3대에서 빌드하고 이미지 내부의
ARM64 kubectl 실행 및 containerd 가져오기를 완료했다. 수정 이미지를 사용하는
OpenStack 배포를 재개했으며 Glance storage-init의 완료는 별도 확인한다.

2026-09-30 추가 보완: Cinder backup-storage-init은 별도 이미지 키이므로 검증한
Cinder 보조 이미지로 명시적으로 연결했다. Nova storage-init용 Heat 기반 보조
이미지도 ARM64 kubectl로 준비한다. Glance API 3개가 Ready인 것을 확인했다.

## ARM64 Open vSwitch 실행

고정된 Open vSwitch v3.3.6-6 이미지의 `/tini` 실행이 ARM64 노드에서
`exec format error`로 실패했다. `group_vars/all/openvswitch.yml`에서 공식 차트의
`pod.tini.enabled: false`를 설정하여 시작 스크립트가 `ovsinit`을 직접 실행하도록 한다.
컬렉션과 이미지는 수정하지 않는다. 2026-09-30 적용 후 세 파드 모두 2/2 Ready와
DaemonSet rollout 완료를 확인했다. 진행 중인 Nova 배포와 겹치지 않게 Open vSwitch
릴리스만 동일 옵션으로 갱신했으며 이후 공식 역할 실행에도 이 변수가 적용된다.

## 실습 노드의 Nova/Neutron 워커 수

Atmosphere의 Nova API·metadata·conductor·scheduler 및 Neutron API/RPC 기본 워커
8개를 각 1개로 줄인다. VM당 4코어·12GiB에서 Nova 시작 후 높은 부하와 liveness
시간 초과가 발생했다. 서비스 복제본 3개는 유지하며 Nova 갱신 시 추가 파드를
동시에 늘리지 않도록 `max_surge: 0`, `max_unavailable: 1`을 사용한다.
설정은 `group_vars/all/nova.yml`, `neutron.yml`에 있으며 성능 검증용 구성은 아니다.
`service-workers.yml`은 Glance/Cinder의 기본 워커 8개와 Placement의 프로세스 4개도
각 1개로 줄인다. mla-02의 OOM으로 MySQL이 종료된 것을 확인한 뒤 적용했다.
서비스 복제본 3개는 유지하고 갱신 시 추가 파드를 늘리지 않는다.

## 보조 이미지의 중복 디스크 사용 정리

`cleanup-image-build-cache.yml`은 보조 이미지를 containerd에서 사용할 수 있는지
확인하고 Docker의 빌드용 복사본과 해당 베이스 참조만 제거한다. 실행 중인 Ceph
이미지나 볼륨은 대상으로 삼지 않으며 강제 삭제는 사용하지 않는다. kubelet이
사용하지 않는 보조 이미지를 이미 정리했다면 남아 있는 Docker 복사본에서 먼저
복원한다. 이 절차는 `site.yml`에서 보조 이미지 준비 직후 실행된다.
이후 준비 플레이북을 다시 실행하면 Docker 캐시가 없어 재빌드할 수 있다.
추후 kubelet이 로컬 보조 이미지를 다시 정리했다면 배포 전에 이미지 준비 단계부터
재실행해야 한다. 로컬 이미지가 외부 레지스트리에 게시되어 있지는 않다.

## 중단된 Neutron 초기 마이그레이션 복구

초기 DB 생성이 중단된 뒤 `Unknown column 'quotas.project_id'`로 재시도에 실패하면
`recover-neutron-migration.yml`을 사용한다. 원래 DB sync Job을 일시 중지하고 종료를
확인한 뒤, 기존 Job의 이미지·설정·인증 참조를 사용하는 복구 Job을 만든다.
`quotas.tenant_id`가 있고 `project_id`가 없을 때에만 공식 Neutron revision
`7d9d8eeec6ad`까지 마이그레이션한다. DB 삭제, 버전 강제 stamp, 검사 우회는 하지 않는다.
성공한 경우에만 원래 Job을 재개한다. 복구 실패 시 원래 Job은 중지 상태로 남으므로
복구 로그부터 확인한다. 정상 설치의 `site.yml`에는 이 장애 복구 절차를 넣지 않는다.
중단 시 MySQL이 이미 적용한 `networks.mtu` 삭제를 revision `b67e765a3524`가
재실행하는 경우에는 해당 열의 부재를 확인하여 그 단일 DDL만 재실행하지 않는다.
이 가드는 복구 Job 안에서만 적용되며 나머지 공식 마이그레이션과 revision 기록은
그대로 수행한다. 런타임 이미지나 설치된 컬렉션 파일을 변경하지 않는다.
2026-10-01 복구 Job과 복구 플레이북이 성공했고, 원래 DB sync Job을 재개했다.
Helm 재배포가 진행 중인 마이그레이션 Job을 교체하지 않도록 먼저 기존 Job의
완료를 확인한 후 Neutron 배포를 다시 실행한다.
이후 연결 단절로 `26d1e9f5c766`도 중단되어 주소 그룹 열/외래 키가 이미 존재했다.
복구 스크립트는 해당 테이블이 비어 있음을 확인한 경우에만 기존 BIGINT 열과 동일한
외래 키를 보존하고 나머지 공식 revision을 재실행한다. 기존 행이 있거나 구조가
예상과 다르면 중단한다. 다른 복구 시도는 `-e mla_neutron_recovery_job=...`로
Job 이름을 구분할 수 있다.

실패한 Helm 릴리스의 hook 재실행:
Neutron DB sync 복구 후에도 release가 `failed`이고 사용자/엔드포인트/RabbitMQ
초기화 Job이 없으면 Ansible의 변경 없음 판정만으로는 복구되지 않을 수 있다.
동시에 실행 중인 Helm 작업이 없고 DB sync가 완료됐음을 확인한 후 다음을 실행한다.
기존 release 값을 그대로 사용하며 hook을 생략하지 않는다.

```sh
limactl shell mla-01 -- sudo helm upgrade neutron /usr/local/src/neutron \
  --namespace openstack --kubeconfig /etc/kubernetes/admin.conf \
  --reuse-values --timeout 15m
```

Neutron API에서 `log_config_append`의 null 값이 `<no value>` 경로로 렌더링되어
`LogConfigError`가 발생했다. `group_vars/all/neutron.yml`에서 명시적인 빈 문자열로
설정하고, 갱신 중 메모리 사용을 줄이도록 `max_surge: 0`을 적용했다.
실제 생성된 neutron.conf에서 `log_config_append = `로 반영됨을 확인했다.

## 현재 12GiB 노드용 중앙 서비스 규모

2026-10-01 추가 OOM으로 MySQL이 반복 종료되어 중앙 서비스 복제본을 축소했다.
Keystone/Glance/Cinder/Placement API, Cinder scheduler, Nova API/metadata/conductor/
scheduler/console, Neutron server/RPC는 각각 1개를 사용한다. 이전 절의 3복제본
검증 기록보다 이 설정이 현재 기준이다. Compute와 네트워크 노드 에이전트,
Kubernetes control plane, Ceph 및 DB의 3노드 구성은 유지한다. 중앙 서비스의
고가용성은 제공하지 않는 실습용 구성이다. 용량을 늘린 뒤 복제본을 재조정한다.

libvirt TLS sidecar v1.0.2는 ARM64 manifest가 없어 v1.1.0의 검증된 digest로
`atmosphere_image_overrides.libvirt_tls_sidecar`를 고정했다. 공식 변경 내역:
https://github.com/vexxhost/libvirt-tls-sidecar/releases/tag/v1.1.0
Skyline 설치는 DB 클러스터의 ready 상태를 기다린 뒤 서비스 사용자를 생성하며,
일시적인 API 장애에는 같은 사용자/비밀번호로 재시도한다.
API Deployment의 Available 상태와 별개로 Ingress 교체 중 503이 발생할 수 있어,
Skyline은 기존 endpoint 변수의 Identity HTTPS discovery 응답(200/300)을 먼저
확인하고 catalog 조회도 재시도한다.

이전 ARM64 미지원 TLS 이미지 파드는 libvirt postStart 대기 중 종료가 지연됐다.
종료 요청된 파드만 대상으로, 각 VM에서 qemu-system 프로세스가 없음을 확인한 뒤
그 파드 UID에 속한 실행 컨테이너를 `crictl stop --timeout 10`으로 종료하여 교체를
완료했다. 실행 중인 게스트가 있는 환경에는 이 복구를 자동 적용하지 않는다.

### Skyline ARM 이미지의 콘솔 패키지 보완

검증한 `99cloud/skyline:2025.2` ARM 이미지에는 `skyline_console`이 없어
`skyline-nginx-generator`가 시작되지 않았다. `prepare-skyline-image.yml`은
동일 OpenStack 2025.2 릴리스의 공식 `skyline-console==7.0.0` wheel을 SHA256으로
검증한 뒤 파생 이미지에 설치한다. 콘솔 `index.html`의 존재를 검사하고 세 노드의
containerd에 가져온다. `site.yml`의 Skyline 단계에 포함되어 있다.
독립 실행 시에는 이미지 준비 플레이북, `skyline.yml` 순서로 실행한다.
이미지와 SQLite PVC를 사용하는 단일 Skyline 복제본은 로컬 실습용이다.

### Neutron 2025.2 상태 검사 호환성

공식 차트의 `health-probe.py`는 에이전트의 자식 프로세스를 제외한다.
현재 이미지에서는 실제 RabbitMQ 연결을 `ServiceWrapper worker`가 소유하므로,
에이전트가 UP이고 연결이 ESTABLISHED여도 readiness가 실패했다.
`fix-neutron-health-probe.yml`은 예상 원본 구문을 확인한 후 자식 제외 조건만
제거하고 기존 TCP/RPC 검사를 유지한다. ConfigMap의 해당 키만 수정하며
체크섬으로 에이전트 DaemonSet을 갱신한다. 공식 역할 실행 후 적용하도록
`openstack.yml`에 포함했다. Neutron Helm을 직접 갱신하면 원본이 복원될 수
있으므로 이 플레이북도 다시 실행해야 한다. 차트가 수정되면 이 우회도 재검토한다.

### 기본 동작 검증

`ansible/run-playbook.sh ansible/playbook/smoke-openstack.yml -b`는 SHA256으로
검증한 ARM64 CirrOS 이미지, DHCP 사설망과 public 라우터, 512MiB/1vCPU 게스트,
로컬 provider floating IP, 1GiB Cinder 볼륨을 `mla-smoke-*` 이름으로 만든다.
기존 동일 이름 게스트는 재생성하지 않는다. 콘솔에 user-data 실행 표식이
나오는지 검사하며, 리소스는 확인을 위해 남긴다. 자동 삭제 작업은 없다.
서버 생성에는 Atmosphere의 고정 버전 CLI를 사용한다. Ubuntu openstacksdk 3.0은
현재 `openstack.cloud.server`가 전달하는 `tags` 인자를 지원하지 않는다.
CLI 컨테이너가 작업 디렉토리를 `/opt`로 마운트하므로 user-data도 이 경로로 읽는다.

2026-10-01 Skyline의 콘솔 HTTPS 응답과 실제 로그인 API HTTP 200 및 세션 쿠키
발급을 확인했다. 인증 정보는 VM의 기존 cloud 설정에서 메모리로 읽었으며
로그나 저장소에 출력하지 않았다.

### 실제 uWSGI 프로세스 제한

OpenStack 서비스의 `workers`/`osapi_*_workers`만 줄여서는 현재 이미지의
uWSGI 프로세스 수가 줄지 않았다. 실측으로 Glance와 Cinder 각각 8개 워커가
실행되고 있었고, 테스트 VM 부팅 시 노드 메모리 부족과 API 502가 발생했다.
`conf.glance_api_uwsgi`, `cinder_api_uwsgi`, `nova_api_uwsgi`,
`nova_metadata_uwsgi`, `neutron_api_uwsgi`, `neutron_policy_server_uwsgi`의
`uwsgi.processes`를 각각 1로 명시한다. 이 값은 각 서비스 group_vars에 있다.
Neutron probe 적용은 ConfigMap resourceVersion도 파드 템플릿에 기록하여,
Helm이 원본을 복원한 뒤 같은 수정본을 재적용하는 경우에도 subPath 파일이
새 파드에서 로드되도록 한다.

### 2026-10-01 기본 동작 검증 결과

`smoke-20261001-005243` 실행은 exit-code 0으로 완료됐다. ARM64 CirrOS
`mla-smoke-vm`은 ACTIVE이고, 메타데이터를 통해 전달한 user-data가 콘솔에
`MLA_SMOKE_BOOT_OK`를 기록했다. Floating IP `192.168.120.121`로 맥에서
ICMP 3회 모두 응답했다. `mla-smoke-volume`은 rbd1 타입 1GiB이며 available이다.
Skyline 로그인 API도 HTTP 200과 세션 쿠키 발급을 재확인했다.
검증 리소스는 삭제하지 않고 남겼다. 볼륨 연결·게스트 내부 I/O 및 HA 장애
전환 검증은 이번 기본 검사에 포함하지 않았다. 중앙 API의 단일 복제본과
Skyline SQLite 구성은 실습용이며, Ceph의 모니터 디스크 여유 경고와 과거
mgr 장애 기록은 별도로 남아 있다.

최종 확인에서 Neutron DHCP/L3/metadata/OVS 에이전트 교체가 모두 완료됐다.
probe 수정 플레이북 재실행도 `changed=0`으로 확인하여 반복 실행이 추가
롤아웃을 유발하지 않음을 확인했다. 전체 site 문법 검사와 git diff 공백 검사도
통과했다. 핵심 서비스와 Skyline 기본 검증 완료에 따라 정기 배포 점검을 중지했다.
