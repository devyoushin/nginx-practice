# 01. Nginx 설치 및 업그레이드

Amazon Linux 2023 (AL2023) 환경 기준. RHEL 9 계열 공통 적용 가능.

---

## 설치 방법 비교

| 방법 | 장점 | 단점 | 적합한 경우 |
|------|------|------|------------|
| dnf 저장소 등록 | 업데이트 관리 편리, 의존성 자동 해결 | 인터넷 필요 | 일반적인 운영 서버 |
| RPM 직접 설치 | 오프라인 가능, 버전 고정 쉬움 | 의존성 수동 관리 | 폐쇄망, 특정 버전 고정 |
| 소스 컴파일 | 모듈 자유 선택, 최신 버전 사용 | 빌드 환경 필요, 업데이트 수동 | 커스텀 모듈, 성능 최적화 |

---

## 1. dnf 저장소 등록 설치 (권장)

### nginx 공식 저장소 등록

```bash
# repo 파일 생성
sudo tee /etc/yum.repos.d/nginx.repo << 'EOF'
[nginx-stable]
name=nginx stable repo
baseurl=http://nginx.org/packages/amzn/2023/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true

[nginx-mainline]
name=nginx mainline repo
baseurl=http://nginx.org/packages/mainline/amzn/2023/$basearch/
gpgcheck=1
enabled=0
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
EOF
```

> **stable vs mainline**
> - stable (1.26.x): 안정성 우선, 운영 서버 권장
> - mainline (1.27.x): 최신 기능 포함, 개발/스테이징 환경
> - nginx 공식 권장은 **mainline** (버그 픽스가 mainline에만 반영되는 경우 있음)

### 설치

```bash
# stable 버전 설치
sudo dnf install nginx

# mainline 버전을 쓰려면 (stable 비활성화 + mainline 활성화)
sudo dnf config-manager --disable nginx-stable
sudo dnf config-manager --enable nginx-mainline
sudo dnf install nginx

# 설치 확인
nginx -v
rpm -qi nginx
```

### 사용 가능한 버전 확인

```bash
# 저장소의 nginx 패키지 목록
dnf list available nginx --showduplicates

# 특정 버전 설치
sudo dnf install nginx-1.26.2
```

### RHEL 9 / Rocky / Alma 계열

AL2023 전용 저장소가 없는 경우 RHEL 9 저장소도 호환됩니다.

```bash
# baseurl을 rhel/9로 변경
baseurl=http://nginx.org/packages/rhel/9/$basearch/
```

---

## 2. RPM 직접 설치 (오프라인 / 버전 고정)

### RPM 다운로드

```bash
# 아키텍처 확인
uname -m    # x86_64 또는 aarch64

# nginx 공식 패키지 사이트
# http://nginx.org/packages/rhel/9/x86_64/RPMS/
# http://nginx.org/packages/rhel/9/aarch64/RPMS/

# x86_64 기준 다운로드 (버전은 최신으로 교체)
curl -O http://nginx.org/packages/rhel/9/x86_64/RPMS/nginx-1.26.2-1.el9.ngx.x86_64.rpm

# aarch64 (ARM/Graviton)
curl -O http://nginx.org/packages/rhel/9/aarch64/RPMS/nginx-1.26.2-1.el9.ngx.aarch64.rpm
```

### 의존성 확인

```bash
# RPM 의존성 목록
rpm -qpR nginx-1.26.2-1.el9.ngx.x86_64.rpm

# 주요 의존: openssl, pcre2, zlib (AL2023 기본 포함)
rpm -q openssl pcre2 zlib
```

### 설치

```bash
# 신규 설치
sudo rpm -ivh nginx-1.26.2-1.el9.ngx.x86_64.rpm

# 업그레이드 설치 (기존 버전 → 신규 버전)
sudo rpm -Uvh nginx-1.26.2-1.el9.ngx.x86_64.rpm

# dnf localinstall (의존성 자동 해결, 권장)
sudo dnf localinstall nginx-1.26.2-1.el9.ngx.x86_64.rpm

# 설치 확인
rpm -q nginx
nginx -v
nginx -V    # 컴파일 옵션까지 출력
```

### 오프라인 환경 배포

```bash
# 인터넷이 되는 서버에서 의존성 포함 다운로드
sudo dnf download nginx --resolve --destdir=/tmp/nginx-rpms/

# 또는 repotrack 사용
sudo dnf install dnf-plugins-core
repotrack nginx -p /tmp/nginx-rpms/

# SCP로 전송
scp -r /tmp/nginx-rpms/ ec2-user@<target-ip>:/tmp/

# 대상 서버에서 설치
sudo dnf localinstall /tmp/nginx-rpms/*.rpm
```

---

## 3. 소스 컴파일 설치 (커스텀 빌드)

### 언제 소스 빌드가 필요한가

- 서드파티 모듈 추가 (ModSecurity, Brotli, njs 등)
- 특정 OpenSSL 버전 연동 (TLS 1.3, QUIC)
- 불필요 모듈 제거로 바이너리 최소화
- 최신 mainline 버전 즉시 적용

### 빌드 의존성 설치

```bash
sudo dnf groupinstall "Development Tools"
sudo dnf install pcre2-devel zlib-devel openssl-devel \
                  libxml2-devel libxslt-devel gd-devel \
                  perl-ExtUtils-Embed GeoIP-devel
```

### 소스 다운로드 및 검증

```bash
# 최신 버전 확인: http://nginx.org/en/download.html
NGINX_VERSION=1.26.2

curl -O http://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz
curl -O http://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz.asc

# PGP 서명 검증 (선택)
curl -O https://nginx.org/keys/nginx_signing.key
gpg --import nginx_signing.key
gpg --verify nginx-${NGINX_VERSION}.tar.gz.asc nginx-${NGINX_VERSION}.tar.gz

tar xzf nginx-${NGINX_VERSION}.tar.gz
cd nginx-${NGINX_VERSION}
```

### configure 옵션

```bash
# RPM 패키지와 동일한 경로 구조로 빌드 (운영 호환성)
./configure \
    --prefix=/etc/nginx \
    --sbin-path=/usr/sbin/nginx \
    --modules-path=/usr/lib64/nginx/modules \
    --conf-path=/etc/nginx/nginx.conf \
    --error-log-path=/var/log/nginx/error.log \
    --http-log-path=/var/log/nginx/access.log \
    --pid-path=/var/run/nginx.pid \
    --lock-path=/var/run/nginx.lock \
    --http-client-body-temp-path=/var/cache/nginx/client_temp \
    --http-proxy-temp-path=/var/cache/nginx/proxy_temp \
    --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp \
    --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp \
    --http-scgi-temp-path=/var/cache/nginx/scgi_temp \
    --user=nginx \
    --group=nginx \
    --with-compat \
    --with-file-aio \
    --with-threads \
    --with-http_addition_module \
    --with-http_auth_request_module \
    --with-http_dav_module \
    --with-http_flv_module \
    --with-http_gunzip_module \
    --with-http_gzip_static_module \
    --with-http_mp4_module \
    --with-http_random_index_module \
    --with-http_realip_module \
    --with-http_secure_link_module \
    --with-http_slice_module \
    --with-http_ssl_module \
    --with-http_stub_status_module \
    --with-http_sub_module \
    --with-http_v2_module \
    --with-http_v3_module \
    --with-mail \
    --with-mail_ssl_module \
    --with-stream \
    --with-stream_realip_module \
    --with-stream_ssl_module \
    --with-stream_ssl_preread_module
```

### 주요 configure 옵션 설명

| 옵션 | 설명 |
|------|------|
| `--with-http_ssl_module` | HTTPS 지원 (필수) |
| `--with-http_v2_module` | HTTP/2 지원 |
| `--with-http_v3_module` | HTTP/3 (QUIC) 지원 (1.25.0+) |
| `--with-http_realip_module` | 프록시 뒤 실제 클라이언트 IP 확인 |
| `--with-http_stub_status_module` | 모니터링용 상태 페이지 |
| `--with-stream` | TCP/UDP 프록시 (L4 로드밸런싱) |
| `--with-http_gzip_static_module` | 미리 압축된 .gz 파일 서빙 |
| `--with-compat` | 동적 모듈 호환성 |
| `--with-threads` | 스레드 풀 지원 (aio threads) |
| `--add-module=/path/to/module` | 서드파티 모듈 정적 링크 |
| `--add-dynamic-module=/path` | 서드파티 모듈 동적 로드 |

### 서드파티 모듈 추가 예시

```bash
# Brotli 압축 모듈
git clone https://github.com/google/ngx_brotli.git
cd ngx_brotli && git submodule update --init && cd ..

# njs (JavaScript) 모듈
git clone https://github.com/nginx/njs.git

# configure에 추가
./configure \
    ... \
    --add-dynamic-module=../ngx_brotli \
    --add-dynamic-module=../njs/nginx
```

### 빌드 및 설치

```bash
# 빌드 (CPU 코어 수만큼 병렬)
make -j$(nproc)

# 설치
sudo make install

# nginx 사용자 생성 (없는 경우)
sudo useradd -r -s /sbin/nologin nginx

# 캐시 디렉토리 생성
sudo mkdir -p /var/cache/nginx/{client_temp,proxy_temp,fastcgi_temp,uwsgi_temp,scgi_temp}
sudo chown -R nginx:nginx /var/cache/nginx
```

### systemd unit 파일 직접 생성

소스 빌드 시 systemd 파일이 없으므로 직접 만들어야 합니다.

```bash
sudo tee /usr/lib/systemd/system/nginx.service << 'EOF'
[Unit]
Description=nginx - high performance web server
Documentation=http://nginx.org/en/docs/
After=network-online.target remote-fs.target nss-lookup.target
Wants=network-online.target

[Service]
Type=forking
PIDFile=/var/run/nginx.pid
ExecStartPre=/usr/sbin/nginx -t -q
ExecStart=/usr/sbin/nginx
ExecReload=/bin/kill -s HUP $MAINPID
ExecStop=/bin/kill -s QUIT $MAINPID
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now nginx
```

### 현재 빌드 옵션 확인

```bash
# 설치된 nginx의 configure 인자 확인
nginx -V 2>&1 | tr ' ' '\n' | grep -- '--'
```

---

## 4. 업그레이드

### 4-1. dnf 업그레이드 (저장소 사용 시)

```bash
# 업데이트 가능 버전 확인
dnf check-update nginx

# 업그레이드
sudo dnf update nginx

# 업그레이드 후 설정 검증 및 재시작
sudo nginx -t && sudo systemctl reload nginx
```

### 4-2. RPM 업그레이드

```bash
# 신규 버전 RPM 다운로드 후
sudo rpm -Uvh nginx-1.26.2-1.el9.ngx.x86_64.rpm

# 또는 dnf localinstall (의존성 자동 해결)
sudo dnf localinstall nginx-1.26.2-1.el9.ngx.x86_64.rpm

# 설정 검증 후 재시작
sudo nginx -t && sudo systemctl reload nginx
```

### 4-3. 소스 빌드 업그레이드 (무중단)

nginx는 바이너리 핫 스왑을 지원합니다. 서비스 중단 없이 업그레이드할 수 있습니다.

```bash
# 1) 현재 설정 확인 (동일 옵션으로 빌드해야 함)
nginx -V 2>&1 | grep 'configure arguments'

# 2) 새 버전 소스 빌드
cd nginx-${NEW_VERSION}
./configure <기존과 동일한 옵션>
make -j$(nproc)
# ⚠ make install 하지 않음!

# 3) 기존 바이너리 백업
sudo cp /usr/sbin/nginx /usr/sbin/nginx.old

# 4) 새 바이너리 복사
sudo cp objs/nginx /usr/sbin/nginx

# 5) 새 바이너리로 새 워커 시작 (기존 마스터에 USR2 시그널)
sudo kill -USR2 $(cat /var/run/nginx.pid)
# → 새 마스터 프로세스가 /var/run/nginx.pid.oldbin으로 기존 PID 백업
# → 새 마스터 + 새 워커가 뜸

# 6) 기존 워커를 graceful shutdown
sudo kill -WINCH $(cat /var/run/nginx.pid.oldbin)
# → 기존 워커가 현재 요청 처리 완료 후 종료
# → 새 워커만 요청을 받음

# 7) 새 버전 정상 동작 확인
nginx -v
curl -I http://localhost

# 8-A) 정상이면: 기존 마스터 종료
sudo kill -QUIT $(cat /var/run/nginx.pid.oldbin)

# 8-B) 문제 발생 시: 롤백 (기존 마스터 복원)
sudo kill -HUP $(cat /var/run/nginx.pid.oldbin)   # 기존 마스터 워커 재시작
sudo kill -QUIT $(cat /var/run/nginx.pid)           # 새 마스터 종료
sudo cp /usr/sbin/nginx.old /usr/sbin/nginx         # 바이너리 복원
```

### 업그레이드 시그널 흐름 요약

```
┌─ 기존 Master (PID 1000) ─┐
│  Worker 1                  │
│  Worker 2                  │
└────────────────────────────┘
          │
          │  kill -USR2 1000
          ▼
┌─ 기존 Master (PID 1000) ─┐    ┌─ 새 Master (PID 2000) ─┐
│  Worker 1                  │    │  Worker 3               │
│  Worker 2                  │    │  Worker 4               │
└────────────────────────────┘    └─────────────────────────┘
          │
          │  kill -WINCH 1000
          ▼
┌─ 기존 Master (PID 1000) ─┐    ┌─ 새 Master (PID 2000) ─┐
│  (워커 없음, 대기 중)       │    │  Worker 3               │
│                            │    │  Worker 4               │
└────────────────────────────┘    └─────────────────────────┘
          │
          │  kill -QUIT 1000  (정상) / kill -HUP 1000 (롤백)
          ▼
              ┌─ 새 Master (PID 2000) ─┐
              │  Worker 3               │
              │  Worker 4               │
              └─────────────────────────┘
```

### 4-4. RPM → 소스 빌드 전환 시 주의

```bash
# 기존 RPM 설정 백업
sudo cp -r /etc/nginx /etc/nginx.bak

# RPM 제거 (설정 파일은 보존됨)
sudo rpm -e nginx

# 소스 빌드 후 install
# → /etc/nginx/ 아래 기존 설정 파일을 덮어쓰지 않도록 주의
sudo make install

# 설정 복원 및 검증
sudo nginx -t
```

---

## 5. 버전 관리 전략

### stable vs mainline 선택 기준

```
운영 (Production)     → stable  (1.26.x)
스테이징 / 개발        → mainline (1.27.x)
새 기능 필요 (HTTP/3)  → mainline
보수적 운영 (금융 등)   → stable + 1~2 마이너 버전 뒤
```

### 버전 고정 (dnf)

```bash
# 특정 버전으로 고정 (자동 업데이트 방지)
sudo dnf install dnf-plugin-versionlock
sudo dnf versionlock add nginx-1.26.2

# 고정 해제
sudo dnf versionlock delete nginx

# 고정 목록 확인
dnf versionlock list
```

### 롤백 (dnf)

```bash
# 이전 트랜잭션 확인
dnf history list
dnf history info <transaction-id>

# 특정 트랜잭션으로 롤백
sudo dnf history undo <transaction-id>
```

---

## 6. systemd 서비스 관리

```bash
# 서비스 시작
sudo systemctl start nginx

# 부팅 시 자동 시작 등록
sudo systemctl enable nginx

# 시작 + 자동등록 동시
sudo systemctl enable --now nginx

# 상태 확인
systemctl status nginx

# 설정 재로드 (무중단, 권장)
sudo systemctl reload nginx

# 완전 재시작 (기존 연결 끊김)
sudo systemctl restart nginx

# 중지
sudo systemctl stop nginx
```

### systemd unit 파일 위치

```
/usr/lib/systemd/system/nginx.service    ← 패키지 제공 (수정 비권장)
/etc/systemd/system/nginx.service        ← 사용자 오버라이드
```

```bash
# unit 파일 확인
systemctl cat nginx.service

# 기본값 변경 없이 오버라이드 (권장)
sudo systemctl edit nginx
# → /etc/systemd/system/nginx.service.d/override.conf 생성
```

### 오버라이드 예시: 파일 디스크립터 제한 증가

```ini
# /etc/systemd/system/nginx.service.d/override.conf
[Service]
LimitNOFILE=65536
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx

# 적용 확인
cat /proc/$(cat /var/run/nginx.pid)/limits | grep 'Max open files'
```

---

## 7. 설치 후 디렉토리 구조

```
/etc/nginx/                    ← 설정 파일 루트
├── nginx.conf                 ← 메인 설정 파일
├── conf.d/                    ← 추가 설정 (*.conf 자동 포함)
│   └── default.conf           ← 기본 서버 블록
├── mime.types                 ← MIME 타입 매핑
├── fastcgi_params             ← FastCGI 기본 파라미터
├── fastcgi.conf               ← FastCGI 설정 (SCRIPT_FILENAME 포함)
├── scgi_params                ← SCGI 파라미터
├── uwsgi_params               ← uWSGI 파라미터
└── koi-utf, koi-win, win-utf  ← 문자셋 변환 맵

/usr/sbin/nginx                ← 실행 바이너리
/usr/lib64/nginx/modules/      ← 동적 모듈 (.so 파일)

/var/log/nginx/                ← 로그 디렉토리
├── access.log                 ← 접근 로그
└── error.log                  ← 에러 로그

/var/cache/nginx/              ← 캐시 디렉토리 (proxy_cache 등)

/usr/share/nginx/html/         ← 기본 웹 루트
├── index.html
└── 50x.html

/var/run/nginx.pid             ← Master 프로세스 PID 파일
```

---

## 8. 방화벽 / SELinux

### 방화벽

```bash
# HTTP/HTTPS 포트 열기
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# 커스텀 포트
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload

# 확인
sudo firewall-cmd --list-all
```

AWS EC2 사용 시 Security Group에서도 인바운드 80/443 허용 필요.

### SELinux

AL2023은 SELinux가 enforcing 모드로 기본 설정됩니다.

```bash
# 상태 확인
getenforce
sestatus

# nginx가 네트워크 연결 허용 (reverse proxy 필수)
sudo setsebool -P httpd_can_network_connect 1

# NFS/CIFS 마운트 파일 읽기
sudo setsebool -P httpd_use_nfs 1

# 커스텀 포트 레이블 추가
sudo semanage port -a -t http_port_t -p tcp 8080

# SELinux 거부 로그 확인
sudo ausearch -m avc -ts recent
sudo tail -f /var/log/audit/audit.log | grep nginx
```

---

## 9. 설치 확인 및 테스트

```bash
# 버전 확인
nginx -v

# 컴파일 옵션 + 모듈 확인
nginx -V

# 설정 문법 검사
sudo nginx -t
# 정상: nginx: configuration file /etc/nginx/nginx.conf syntax is ok
#       nginx: configuration file /etc/nginx/nginx.conf test is successful

# 서버 응답 확인
curl -I http://localhost

# 프로세스 확인
ps aux | grep nginx

# 포트 확인
ss -tlnp | grep nginx
```
