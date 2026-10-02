# MLA 로컬 OpenStack 설치

- 대상 환경: Apple Silicon Mac
- VM 구성: Lima VM 3개
- VM별 사양: 4 vCPU · 12GiB RAM · OS 디스크 40GiB · Ceph 디스크 40GiB
- 배포 도구: Ansible · Atmosphere
- 대시보드: Skyline
- 기본 검증 범위: 중첩 KVM 부팅 · OpenStack 테스트 인스턴스 · 볼륨 생성

## 사전 준비

- 사전 설치 필요: Xcode Command Line Tools · Homebrew
- 사전 설치로 분리한 이유: GUI 또는 초기 사용자 설정이 필요할 수 있음
- 자동 설치 대상: Lima · Python 3.12 · tmux · Ansible 및 Python 의존성 · Atmosphere 컬렉션
- socket_vmnet 미설치 시: 체크섬 고정 설치 스크립트 실행
- 실행 계정: 일반 사용자
- 실행 금지 방식: `sudo ./install.sh`
- 관리자 비밀번호 입력: 관리자 권한이 필요한 네트워크 준비 단계
- 버전 고정 범위: Python 의존성 · Ansible 컬렉션
- 버전 고정 제외: 호스트 도구 전체

## 실행

- 실행 위치: 프로젝트를 clone한 디렉터리
- 내부 경로 기준: 설치 스크립트가 위치한 프로젝트 디렉터리
- 다른 경로에 clone한 경우: 아래 `cd` 경로만 변경
- 실행 순서 확인: `./install.sh --plan` — 실제 변경 없음
- 준비 단계만 실행: `./install.sh --until deps`
- 전체 설치 및 기본 동작 검증: `./install.sh`

```bash
cd /Users/jjjjjk12/Migration/dev/mla
./install.sh --plan       # 실행 순서만 확인. 변경 없음.
./install.sh              # 전체 설치 및 기본 동작 검증
```

### tmux에서 실행

- 목적: 오래 걸리는 설치를 터미널과 분리
- tmux 미설치 시: `./install.sh --until deps` 먼저 실행

```bash
# tmux가 없는 새 맥에서는 먼저 ./install.sh --until deps 실행
tmux -L mla-deploy new-session -s mla-install './install.sh'
```

- 세션 분리: `Ctrl-b`를 누른 뒤 `d`
- 세션 재접속: `tmux -L mla-deploy attach -t mla-install`
- 설치 중 동작: Mac의 유휴 잠자기 억제
- 제한사항: 덮개 닫기·재부팅 후 프로세스 유지 보장 없음

## 실행 순서

| 단계 | 작업 |
| --- | --- |
| `deps` | 호스트 도구, Python venv, 잠금 파일에 지정된 Python 의존성·Ansible 컬렉션 설치 |
| `network` | socket_vmnet, management/provider 네트워크, 검증된 sudoers 설정 |
| `vms` | 기존 디스크·VM 확인, 없는 것만 생성, 정지된 VM 시작 |
| `guest-network` | Lima SSH로 고정 IP·인터페이스·호스트명·노드 이름 해석 설정 |
| `access` | 실제 VM 사용자명 확인, Lima에서 읽은 공개 호스트키 등록, SSH 검증 |
| `secrets` | 기존 비밀번호 보존; 새 환경에서만 공식 생성 로직으로 생성 |
| `dns` | Mac과 각 VM에서 서비스 이름이 서비스 VIP로 해석되는지 확인 |
| `probe` | 작은 ARM 게스트를 중첩 KVM으로 부팅·검증·정상 종료 |
| `deploy` | 기존 `site.yml`: Ceph → Kubernetes/CSI → 인프라 → OpenStack → Skyline |
| `verify` | 노드·파드·Ceph·Skyline 로그인, 테스트 VM·볼륨·Floating IP 통신 확인 |

- 실패 시 동작: 해당 단계에서 즉시 중단
- 실패 후 자동 실행: 이후 단계·별도 복구 명령 실행 없음
- 중복 실행 감지: 다른 설치 스크립트 또는 Ansible 배포 프로세스 감지 시 중단
- 로그·종료 코드: 정상 종료와 실패 모두 `.ansible/runs/install-*/`에 저장
- 최신 실행 경로: `.ansible/install/latest-run`
- 로그 관리: Git 추적 제외

## 중간 단계부터 실행

```bash
./install.sh --until access           # VM/네트워크/SSH까지만
./install.sh --from secrets           # 기존 VM 준비가 끝난 경우
./install.sh --from deploy            # 배포부터 재시도
./install.sh --from verify            # 서비스와 기본 동작 재검증
./install.sh --skip-probe             # 중첩 KVM 사전 부팅 검사 생략
./install.sh --from verify --skip-smoke # 테스트 리소스 생성 없이 서비스 검사만
```

- `--from` 사용 조건: 지정 단계 이전의 준비 완료
- 단계 자동 생략: 실패 단계·기존 설치 여부를 추측한 자동 생략 없음
- 첫 실행 기본 명령: `./install.sh`
- 강제 종료 후 lock 잔존 시: `.ansible/install/lock/pid`의 프로세스 종료 여부 먼저 확인

## 설정과 외부 준비

### 설정 파일

- VM 사양·이미지: `ansible/var/lima-vars.yml`
- management/provider 대역·노드 IP: `ansible/var/network-vars.yml`
- 클러스터 VIP·Ceph·서비스·도메인: `ansible/inventory/atmosphere/group_vars/`

### DNS

- 현재 레코드: `*.mla.jinkang.dev`
- 레코드 유형·주소: A · `192.168.110.121`
- 프록시 설정: 비활성화
- 도메인 변경 시: `endpoints.yml`과 `skyline.yml`의 이름 함께 수정
- 외부 DNS 사업자 레코드 등록: 사용자 설정 필요
- Mac DNS·hosts: 자동 덮어쓰기 없음

### 네트워크·VM

- 기본 네트워크 전제: `/24` 실습망
- 대역 변경 시 함께 수정할 항목: Ceph 네트워크 · Kubernetes/서비스 VIP · Neutron public 서브넷 · smoke 보안그룹
- 기존 VM 하드웨어·NIC: 자동 변경 없음
- 기존 VM 재생성: 자동 실행 없음
- 같은 이름의 VM 사양 불일치 시: 생성 플레이북 중단

### 접속 인벤토리

- VM 사용자명·로컬 경로: 새 맥에 맞춘 하드코딩 불필요
- 생성 위치: `.ansible/install/inventory/hosts.ini`
- 생성 인벤토리의 `group_vars`: 저장소의 기존 설정 연결
- 원래 인벤토리: 덮어쓰기 없이 보존
- `LIMA_HOME` 지정 시: 해당 Lima 디렉터리 사용
- 생성 인벤토리로 개별 플레이북 실행:

```bash
MLA_INVENTORY="$PWD/.ansible/install/inventory/hosts.ini" \
  ansible/run-playbook.sh ansible/playbook/site.yml -b
```

### 비밀번호·키 관리

- 별도 백업 대상: `ansible/inventory/atmosphere/group_vars/all/secrets.yml` · `.ansible/secrets/`
- 백업 목적: 기존 환경 복구
- 원격 Git 저장소 업로드: 제외
- 기존 Kubernetes가 있으나 `secrets.yml`이 없는 경우: 새 암호 생성 없이 중단
- Vault 암호화 파일: 기존 `ANSIBLE_VAULT_PASSWORD_FILE` 설정 사용 가능

## 포함한 수정과 제외한 복구 명령

- 적용 위치: 현재 `site.yml`과 변수 파일
- 포함한 수정: ARM 이미지 보완 · uWSGI 프로세스 수 제한 · Ceph 이미지 우회 · Neutron 상태 검사 수정
- 의존성 설치 기준: 검증 당시 Python 잠금 파일 · `requirements-atmosphere.lock.yml`의 컬렉션 버전
- 상시 설치에서 제외한 명령: DB 마이그레이션 수리 · 컨테이너 강제 종료 · Helm 강제 재실행
- 제외 이유: 특정 실패 상태를 전제로 한 일회성 복구 명령
- 복구 필요 시: 해당 로그 확인 후 별도 판단
- 실행하지 않는 작업: VM/디스크 삭제 · OSD 초기화

## 검증 범위와 제한사항

- 검증 리소스: `mla-smoke-*` 이름으로 생성 후 확인용으로 유지
- 검증 제외 범위: 볼륨 연결 · 게스트 I/O · HA 장애 전환
- 인증서: 자체 서명 인증서
- 실습 환경 제한: 중앙 API 단일 복제본 · 작은 메모리/디스크 여유
- Ceph `HEALTH_ERR`: 실패 처리
- Ceph `HEALTH_WARN`: 경고 보고

## 스크립트 검증

```bash
bash -n install.sh ansible/run-playbook.sh lima/script/bootstrap-socket-vmnet.sh
.venv-atmosphere/bin/python -m unittest discover -s tests -v
```

- 테스트 방식: 임시 디렉터리 · 가짜 실행기 사용
- 테스트 영향: VM·실제 배포 상태 변경 없음
- 설치 스크립트 작성 시: 전체 재설치 미실행
- 상세 구성·장애 수정 기록: [Ansible 문서](ansible/README.md)
