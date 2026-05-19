# 01. Nginx 설치 (Amazon Linux 2023, RPM)

## 왜 dnf로 설치가 안 되는가

AL2023의 기본 패키지 저장소에는 nginx가 포함되어 있지 않습니다.
`amazon-linux-extras`도 AL2023에서는 제거되었습니다.
따라서 nginx 공식 사이트에서 RPM 파일을 직접 받아 설치해야 합니다.

---

## RPM 파일 다운로드

nginx 공식 배포 사이트: http://nginx.org/packages/

AL2023은 RHEL 9 계열이므로 **rhel/9** 디렉토리의 패키지를 사용합니다.

```bash
# 아키텍처 확인 (보통 x86_64 또는 aarch64)
uname -m

# 패키지 목록 확인 후 원하는 버전 선택
# stable 버전: 짝수 마이너 (1.24.x)
# mainline 버전: 홀수 마이너 (1.25.x)

# x86_64 기준 예시 (버전은 최신으로 교체)
curl -O http://nginx.org/packages/rhel/9/x86_64/RPMS/nginx-1.24.0-1.el9.ngx.x86_64.rpm

# aarch64 (ARM) 기준
curl -O http://nginx.org/packages/rhel/9/aarch64/RPMS/nginx-1.24.0-1.el9.ngx.aarch64.rpm
```

### 의존성 패키지 (필요 시 함께 다운로드)

nginx는 다음 라이브러리에 의존합니다. AL2023에는 대부분 기본 설치되어 있습니다.

```bash
# 의존성 확인
rpm -qpR nginx-1.24.0-1.el9.ngx.x86_64.rpm

# 주요 의존 패키지: openssl, pcre2, zlib
# AL2023 기본 포함 여부 확인
rpm -q openssl pcre2 zlib
```

---

## RPM 설치

```bash
# 단순 설치
sudo rpm -ivh nginx-1.24.0-1.el9.ngx.x86_64.rpm

# 이미 설치된 버전이 있을 경우 업그레이드
sudo rpm -Uvh nginx-1.24.0-1.el9.ngx.x86_64.rpm

# 의존성 무시 (비권장, 테스트 목적)
sudo rpm -ivh --nodeps nginx-1.24.0-1.el9.ngx.x86_64.rpm

# 설치 확인
rpm -q nginx
nginx -v          # 버전 출력
nginx -V          # 컴파일 옵션까지 출력
```

---

## 오프라인 환경에서 여러 RPM 동시 설치

네트워크가 없는 서버에 배포할 경우:

```bash
# 로컬에서 모든 RPM 수집 후 SCP로 전송
scp nginx-*.rpm ec2-user@<server-ip>:/tmp/

# 서버에서 한 번에 설치
sudo rpm -ivh /tmp/nginx-*.rpm

# 또는 dnf localinstall 활용 (의존성 자동 해결)
sudo dnf localinstall /tmp/nginx-1.24.0-1.el9.ngx.x86_64.rpm
```

---

## systemd 서비스 등록 및 관리

RPM 설치 시 systemd unit 파일이 자동으로 등록됩니다.

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

# 자동 시작 해제
sudo systemctl disable nginx
```

### systemd unit 파일 위치

```
/usr/lib/systemd/system/nginx.service
```

내용 확인:

```bash
cat /usr/lib/systemd/system/nginx.service
```

```ini
[Unit]
Description=nginx - high performance web server
Documentation=http://nginx.org/en/docs/
After=network-online.target remote-fs.target nss-lookup.target
Wants=network-online.target

[Service]
Type=forking
PIDFile=/var/run/nginx.pid
ExecStartPre=/usr/sbin/nginx -t -q -g 'daemon on; master_process on;'
ExecStart=/usr/sbin/nginx -g 'daemon on; master_process on;'
ExecReload=/bin/kill -s HUP $MAINPID
ExecStop=/bin/kill -s QUIT $MAINPID
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

---

## 설치 후 디렉토리 구조

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

## 방화벽 설정

AL2023은 기본적으로 firewalld가 활성화되어 있습니다.

```bash
# HTTP/HTTPS 포트 열기
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# 특정 포트 열기
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload

# 확인
sudo firewall-cmd --list-all
```

AWS EC2 사용 시 Security Group에서도 인바운드 80/443 허용 필요.

---

## SELinux 고려사항

AL2023은 SELinux가 enforcing 모드로 기본 설정됩니다.

```bash
# SELinux 상태 확인
getenforce
sestatus

# nginx가 네트워크 연결 허용 (reverse proxy 사용 시)
sudo setsebool -P httpd_can_network_connect 1

# nginx가 NFS/CIFS 마운트된 파일 읽기 허용
sudo setsebool -P httpd_use_nfs 1

# 커스텀 포트 사용 시 포트 레이블 추가
sudo semanage port -a -t http_port_t -p tcp 8080

# SELinux 거부 로그 확인
sudo ausearch -m avc -ts recent
sudo tail -f /var/log/audit/audit.log | grep nginx
```

---

## 설치 확인 및 테스트

```bash
# 버전 및 컴파일 옵션 확인
nginx -V

# 설정 파일 문법 검사
sudo nginx -t

# 정상 출력:
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration file /etc/nginx/nginx.conf test is successful

# 서버 응답 테스트
curl -I http://localhost
```
