# Nginx Bulk Install

여러 대의 서버에 Nginx를 같은 방식으로 설치할 때 사용하는 운영 보조 자료입니다. 서버 목록은 `inventory.sample` 형식을 복사해 환경에 맞게 작성하고, `ssh-fanout.sh`로 각 서버에 설치 스크립트를 전송해 실행합니다.

## 파일 구성

| 파일 | 용도 |
|------|------|
| `inventory.sample` | 설치 대상 서버 목록 예시 |
| `install-nginx-al2023.sh` | Amazon Linux 2023 기준 Nginx 설치 스크립트 |
| `ssh-fanout.sh` | inventory를 읽어 여러 서버에 설치 스크립트를 실행하는 도구 |

## 사용 순서

1. 서버 목록을 준비합니다.

```bash
cp ops/bulk-install/inventory.sample ops/bulk-install/inventory.prod
vi ops/bulk-install/inventory.prod
```

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
- 서버별 설정 배포와 reload는 별도 배포 절차로 관리합니다.
