# Nginx Bulk Install

여러 대의 서버에 Nginx를 같은 방식으로 설치할 때 사용하는 운영 보조 자료입니다. 서버 목록은 `inventory.sample` 형식을 복사해 환경에 맞게 작성하고, `ssh-fanout.sh`로 각 서버에 설치 스크립트를 전송해 실행합니다.

## 파일 구성

| 파일 | 용도 |
|------|------|
| `inventory.sample` | 설치 대상 서버 목록 예시 |
| `install-nginx-al2023.sh` | Amazon Linux 2023 기준 Nginx 설치 스크립트 |
| `ssh-fanout.sh` | inventory를 읽어 여러 서버에 설치 스크립트를 실행하는 도구 |
| `deploy-nginx-config.sh` | 서버별 Nginx 설정 bundle을 배포하고 검증 후 reload하는 도구 |
| `config-bundle.sample/` | 공통/그룹/서버별 설정 overlay 예시 |

## 사용 순서

1. 서버 목록을 준비합니다.

```bash
cp ops/bulk-install/inventory.sample ops/bulk-install/inventory.prod
vi ops/bulk-install/inventory.prod
```

inventory는 아래 형식을 사용합니다.

```text
<host> <group> <node_id>
```

- `host`: SSH 접속 대상 IP 또는 DNS 이름
- `group`: 같은 설정을 공유하는 서버 그룹
- `node_id`: 특정 서버만 덮어쓸 설정을 찾는 ID

설치 스크립트는 첫 번째 컬럼인 `host`만 사용하고, 설정 배포 스크립트는 `group`, `node_id`까지 사용합니다.

2. 단일 서버에서 먼저 설치 스크립트를 검증합니다.

```bash
scp ops/bulk-install/install-nginx-al2023.sh ec2-user@10.0.1.10:/tmp/
ssh ec2-user@10.0.1.10 'sudo bash /tmp/install-nginx-al2023.sh'
```

3. 전체 서버에 실행합니다.

```bash
ops/bulk-install/ssh-fanout.sh \
  --inventory ops/bulk-install/inventory.prod \
  --user ec2-user \
  --script ops/bulk-install/install-nginx-al2023.sh
```

## 서버별 설정 배포

설치는 모든 서버에 거의 동일하게 적용하지만, 운영 설정은 서버 역할에 따라 달라집니다. 이 repo에서는 설정을 아래 순서로 합칩니다.

```text
config-bundle/
├── common/             # 모든 서버 공통 설정
├── groups/<group>/     # 같은 역할의 서버 설정
└── hosts/<node_id>/    # 특정 서버만 덮어쓰는 설정
```

적용 순서는 `common -> groups/<group> -> hosts/<node_id>`입니다. 뒤에 있는 파일이 같은 경로의 앞 파일을 덮어씁니다.

예를 들어 inventory가 아래와 같다면:

```text
10.0.1.10 edge nginx-edge-a
```

배포 시 아래 디렉터리를 순서대로 합쳐 `/etc/nginx`에 반영합니다.

```text
config-bundle/common/
config-bundle/groups/edge/
config-bundle/hosts/nginx-edge-a/
```

샘플을 복사해서 실제 환경용 bundle을 만듭니다.

```bash
cp -R ops/bulk-install/config-bundle.sample ops/bulk-install/config-bundle.prod
vi ops/bulk-install/config-bundle.prod/groups/edge/conf.d/app.conf
```

한 대에 먼저 설정을 배포합니다.

```bash
ops/bulk-install/deploy-nginx-config.sh \
  --inventory <(printf '10.0.1.10 edge nginx-edge-a\n') \
  --user ec2-user \
  --config-root ops/bulk-install/config-bundle.prod
```

검증 후 전체 서버에 배포합니다.

```bash
ops/bulk-install/deploy-nginx-config.sh \
  --inventory ops/bulk-install/inventory.prod \
  --user ec2-user \
  --config-root ops/bulk-install/config-bundle.prod
```

배포 스크립트는 원격 서버에서 다음 순서로 동작합니다.

1. `/tmp/nginx-config-next`에 새 설정 압축 해제
2. `nginx -t -p /tmp/nginx-config-next/ -c nginx.conf`로 사전 검증
3. 기존 `/etc/nginx`를 `/etc/nginx.backup.<timestamp>`로 백업
4. 새 설정을 `/etc/nginx`에 복사
5. `nginx -t` 재검증
6. `systemctl reload-or-restart nginx`

## Nginx 설치 방식

기본값은 `repo`입니다. nginx.org 공식 저장소를 등록하고 stable 패키지를 설치합니다.

```bash
# 기본: nginx.org stable repo
sudo bash install-nginx-al2023.sh

# mainline 저장소 사용
sudo NGINX_CHANNEL=mainline bash install-nginx-al2023.sh

# 오프라인 RPM 디렉터리에서 설치
sudo NGINX_INSTALL_METHOD=local-rpm \
  NGINX_RPM_DIR=/tmp/nginx-rpms \
  bash install-nginx-al2023.sh
```

## 운영 원칙

- 전체 실행 전 한 대의 서버에서 반드시 검증합니다.
- 설치 스크립트는 `/etc/nginx/conf.d/default.conf`가 없을 때만 기본 설정을 생성합니다.
- 기존 설정 파일은 덮어쓰지 않습니다.
- 설정 배포는 설치와 분리하고, validate 성공 후에만 reload합니다.
- 서버별 차이는 스크립트 내부 분기보다 inventory의 `group`, `node_id`와 config overlay로 관리합니다.
