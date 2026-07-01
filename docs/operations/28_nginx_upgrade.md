# 28. Nginx 업그레이드 절차

Nginx 업그레이드는 단순히 패키지를 올리는 작업이 아니라, **설정 호환성 확인 → 모듈 호환성 확인 → 노드 단위 배포 → reload/restart 영향 확인 → 롤백 경로 확보**까지 포함하는 운영 작업이다.

이 문서는 Amazon Linux 2023 환경을 기본으로 하고, Ubuntu/Debian 계열 명령과 Nginx 공식 signal 기반 무중단 binary upgrade 절차도 함께 정리한다.

---

## 1. 업그레이드 방식 선택

| 방식 | 사용 상황 | 장점 | 주의점 |
|---|---|---|---|
| 패키지 업그레이드 + reload/restart | 대부분의 운영 서버 | 단순하고 표준적 | restart 시 연결 영향 가능 |
| 로드밸런서 뒤 롤링 업그레이드 | Nginx가 여러 대인 운영 환경 | 서비스 영향 최소화 | drain/health check 절차 필요 |
| signal 기반 binary upgrade | 단일 서버에서 연결 유지가 중요 | old/new worker 공존 가능 | 절차 복잡, systemd/패키지 환경에서 신중히 사용 |
| 새 AMI/새 서버 교체 | immutable 운영 | 롤백 명확, 재현성 높음 | 이미지 빌드/트래픽 전환 필요 |

운영 Best Practice는 **로드밸런서 뒤에서 한 대씩 빼고 패키지 업그레이드 후 검증한 뒤 다시 붙이는 방식**이다. 단일 서버에서 연결 유지가 핵심이면 `USR2`, `WINCH`, `QUIT` signal을 이용한 binary upgrade를 검토한다.

---

## 2. 사전 점검

### 2.1 현재 버전과 빌드 옵션 확인

```bash
nginx -v
nginx -V 2>&1
```

모듈과 경로만 보기:

```bash
nginx -V 2>&1 | tr ' ' '\n' | grep -E '^--with-|^--add-|^--modules-path|^--prefix|^--conf-path|^--pid-path'
```

확인할 항목:

| 항목 | 이유 |
|---|---|
| 현재 nginx version | 업그레이드 전후 비교 |
| `--conf-path` | 실제 설정 파일 위치 확인 |
| `--pid-path` | signal 전송 대상 PID 파일 확인 |
| `--modules-path` | dynamic module 위치 확인 |
| `--with-*` | SSL, HTTP/2, stream 등 필수 모듈 포함 여부 확인 |
| `--add-module` | third-party module 호환성 확인 |

### 2.2 설정 백업

```bash
sudo mkdir -p /var/backups/nginx

sudo tar czf /var/backups/nginx/nginx-config-$(date +%Y%m%d%H%M%S).tar.gz \
  /etc/nginx \
  /etc/systemd/system/nginx.service.d \
  2>/dev/null || true
```

현재 실행 중인 전체 설정을 하나의 파일로 저장한다.

```bash
sudo nginx -T > /var/backups/nginx/nginx-effective-config-$(date +%Y%m%d%H%M%S).conf
```

### 2.3 패키지 후보 버전 확인

Amazon Linux 2023:

```bash
sudo dnf list nginx --showduplicates
sudo dnf info nginx
```

Ubuntu/Debian:

```bash
apt-cache policy nginx
apt-cache madison nginx
```

### 2.4 설정 문법 검증

```bash
sudo nginx -t
```

업그레이드 전에 `nginx -t`가 실패하면 업그레이드를 진행하지 않는다. 기존 설정이 이미 깨진 상태에서는 패키지 변경과 설정 문제를 분리하기 어렵다.

---

## 3. Amazon Linux 2023 패키지 업그레이드

### 3.1 nginx.org repository 확인

공식 nginx repository를 사용한다면 `/etc/yum.repos.d/nginx.repo`에 Amazon Linux 2023용 repo가 있어야 한다.

```bash
sudo sed -n '1,120p' /etc/yum.repos.d/nginx.repo
```

Amazon Linux 2023 stable repo 예시:

```ini
[nginx-stable]
name=nginx stable repo
baseurl=https://nginx.org/packages/amzn/2023/$basearch/
gpgcheck=1
enabled=1
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
priority=9

[nginx-mainline]
name=nginx mainline repo
baseurl=https://nginx.org/packages/mainline/amzn/2023/$basearch/
gpgcheck=1
enabled=0
gpgkey=https://nginx.org/keys/nginx_signing.key
module_hotfixes=true
priority=9
```

stable과 mainline을 운영 중 섞지 않는다. mainline으로 전환해야 하면 staging에서 먼저 모듈·설정 호환성을 검증한다.

### 3.2 업그레이드 실행

```bash
sudo dnf makecache
sudo dnf upgrade nginx
```

특정 버전으로 고정 업그레이드:

```bash
sudo dnf list nginx --showduplicates
sudo dnf install nginx-<VERSION>
```

예시:

```bash
sudo dnf install nginx-1.26.3
```

패키지 설치 후 버전 확인:

```bash
nginx -v
nginx -V 2>&1 | tr ' ' '\n' | grep -E '^--with-|^--add-|^--modules-path|^--conf-path|^--pid-path'
```

### 3.3 설정 검증 후 reload

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl status nginx --no-pager
```

`reload`는 master process에 `HUP` signal을 보내 새 설정을 읽고 새 worker를 시작한다. 설정 적용에 실패하면 기존 설정으로 계속 동작한다. 단, binary 자체를 교체한 뒤라면 패키지 post script나 systemd 동작에 따라 restart가 필요할 수 있으므로 프로세스 버전을 확인한다.

실행 중인 master/worker 확인:

```bash
ps -eo pid,ppid,user,etime,cmd | grep '[n]ginx'
```

---

## 4. Ubuntu/Debian 패키지 업그레이드

### 4.1 repository와 후보 버전 확인

```bash
apt-cache policy nginx
apt-cache madison nginx
```

### 4.2 업그레이드 실행

```bash
sudo apt update
sudo apt install --only-upgrade nginx
```

특정 버전 설치:

```bash
sudo apt install nginx=<VERSION>
```

패키지 hold:

```bash
sudo apt-mark hold nginx
```

hold 해제:

```bash
sudo apt-mark unhold nginx
```

### 4.3 검증

```bash
nginx -v
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl status nginx --no-pager
```

---

## 5. 로드밸런서 뒤 롤링 업그레이드

Nginx가 여러 대이고 ALB/NLB 뒤에 있다면 한 번에 전체 서버를 올리지 않는다. 한 대씩 target에서 제외하고 업그레이드한다.

### 5.1 절차

| 단계 | 작업 | 확인 |
|---|---|---|
| 1 | 대상 서버를 LB target에서 drain | 신규 요청 유입 중지 |
| 2 | active connection 감소 대기 | access log, connection metric |
| 3 | 패키지 업그레이드 | `dnf upgrade nginx` |
| 4 | 설정 검증 | `nginx -t` |
| 5 | reload/restart | `systemctl reload nginx` |
| 6 | 로컬 헬스체크 | `curl -fsS http://127.0.0.1/health` |
| 7 | LB target 복귀 | target healthy 확인 |
| 8 | 다음 서버 진행 | 한 대씩 반복 |

### 5.2 AWS ALB/NLB target 제외 예시

```bash
aws elbv2 deregister-targets \
  --target-group-arn <TARGET_GROUP_ARN> \
  --targets Id=<INSTANCE_ID> \
  --region ap-northeast-2 \
  --output json
```

target health 확인:

```bash
aws elbv2 describe-target-health \
  --target-group-arn <TARGET_GROUP_ARN> \
  --targets Id=<INSTANCE_ID> \
  --region ap-northeast-2 \
  --output json
```

업그레이드 후 다시 등록:

```bash
aws elbv2 register-targets \
  --target-group-arn <TARGET_GROUP_ARN> \
  --targets Id=<INSTANCE_ID> \
  --region ap-northeast-2 \
  --output json
```

---

## 6. signal 기반 binary upgrade

Nginx 공식 절차는 `USR2`, `WINCH`, `QUIT` signal로 old master와 new master를 동시에 띄워 binary를 교체한다.

이 방식은 단일 서버에서 연결 손실을 줄이는 데 유용하지만, systemd 패키지 운영에서는 절차가 복잡하다. 일반 운영에서는 로드밸런서 롤링 업그레이드를 우선 사용한다.

### 6.1 signal 의미

| Signal | 대상 | 의미 |
|---|---|---|
| `HUP` | master | 설정 reload, 새 worker 시작, old worker graceful shutdown |
| `USR1` | master | log file reopen |
| `USR2` | master | 새 nginx executable로 new master 시작 |
| `WINCH` | master | worker graceful shutdown |
| `QUIT` | master | graceful shutdown |
| `TERM`, `INT` | master | fast shutdown |

### 6.2 on-the-fly upgrade 절차

현재 master PID 확인:

```bash
cat /run/nginx.pid
ps -eo pid,ppid,user,etime,cmd | grep '[n]ginx'
```

새 패키지 또는 새 binary를 설치한 뒤, 기존 master에 `USR2`를 보낸다.

```bash
sudo kill -USR2 $(cat /run/nginx.pid)
```

새 master와 새 worker가 올라왔는지 확인한다. 이때 `/run/nginx.pid.oldbin`이 생긴다.

```bash
ls -l /run/nginx.pid*
ps -eo pid,ppid,user,etime,cmd | grep '[n]ginx'
```

old worker를 graceful shutdown한다.

```bash
sudo kill -WINCH $(cat /run/nginx.pid.oldbin)
```

트래픽과 로그를 검증한다.

```bash
curl -fsS http://127.0.0.1/health || true
tail -n 100 /var/log/nginx/error.log
```

문제가 없으면 old master를 종료한다.

```bash
sudo kill -QUIT $(cat /run/nginx.pid.oldbin)
```

### 6.3 on-the-fly rollback

새 binary가 문제가 있으면 old master를 다시 살린 뒤 new master를 종료한다.

old master에 `HUP` 전송:

```bash
sudo kill -HUP $(cat /run/nginx.pid.oldbin)
```

new master 종료:

```bash
sudo kill -QUIT $(cat /run/nginx.pid)
```

프로세스 확인:

```bash
ps -eo pid,ppid,user,etime,cmd | grep '[n]ginx'
```

주의: PID path가 `/run/nginx.pid`가 아닌 패키지도 있다. 반드시 `nginx -V`의 `--pid-path` 또는 설정의 `pid` directive를 확인한다.

---

## 7. 롤백 전략

### 7.1 패키지 롤백

Amazon Linux 2023:

```bash
sudo dnf history list nginx
sudo dnf history info <TRANSACTION_ID>
sudo dnf history undo <TRANSACTION_ID>
```

특정 이전 버전 설치:

```bash
sudo dnf list nginx --showduplicates
sudo dnf downgrade nginx-<PREVIOUS_VERSION>
```

Ubuntu/Debian:

```bash
apt-cache madison nginx
sudo apt install nginx=<PREVIOUS_VERSION>
```

### 7.2 설정 롤백

```bash
sudo tar xzf /var/backups/nginx/nginx-config-<YYYYMMDDHHMMSS>.tar.gz -C /
sudo nginx -t
sudo systemctl reload nginx
```

### 7.3 AMI 또는 서버 교체

운영 환경에서 가장 명확한 롤백은 이전 AMI 또는 이전 Launch Template version으로 되돌리는 방식이다. Nginx 서버가 Auto Scaling Group 뒤에 있다면 새 AMI로 canary 1대를 먼저 올리고, 문제가 있으면 이전 Launch Template version으로 교체한다.

---

## 8. 업그레이드 체크리스트

### 8.1 사전 체크

| 항목 | 명령 |
|---|---|
| 현재 버전 확인 | `nginx -v` |
| 빌드 옵션 확인 | `nginx -V` |
| 설정 전체 백업 | `nginx -T > backup.conf` |
| 설정 문법 확인 | `nginx -t` |
| 패키지 후보 확인 | `dnf list nginx --showduplicates` |
| 동적 모듈 확인 | `ls -l /usr/lib64/nginx/modules` |
| 로그 에러 확인 | `tail -n 100 /var/log/nginx/error.log` |

### 8.2 업그레이드 후 체크

| 항목 | 명령 |
|---|---|
| 버전 변경 확인 | `nginx -v` |
| 설정 문법 확인 | `nginx -t` |
| 서비스 상태 확인 | `systemctl status nginx --no-pager` |
| 프로세스 확인 | `ps -eo pid,ppid,user,etime,cmd \| grep '[n]ginx'` |
| 로컬 헬스체크 | `curl -fsS http://127.0.0.1/health` |
| 에러 로그 확인 | `tail -n 100 /var/log/nginx/error.log` |
| access log 확인 | `tail -f /var/log/nginx/access.log` |

---

## 9. 트러블슈팅

### unknown directive 발생

증상:

```text
nginx: [emerg] unknown directive "ssl_preread"
```

원인:

- 업그레이드 후 모듈 패키지가 누락됨
- 동적 모듈 `.so` 경로가 변경됨
- 기존에는 소스 빌드 모듈을 사용했지만 패키지 빌드에는 포함되지 않음

해결:

```bash
nginx -V 2>&1 | tr ' ' '\n' | grep -E 'stream|ssl_preread|modules-path'
ls -l /usr/lib64/nginx/modules
sudo nginx -T | sed -n '1,80p'
```

동적 모듈이면 `load_module` 경로를 확인한다.

```nginx
load_module modules/ngx_stream_module.so;
```

### reload 실패

증상:

```text
nginx: configuration file /etc/nginx/nginx.conf test failed
```

원인:

- 신규 버전에서 directive 문법이 맞지 않음
- include 파일 경로가 없음
- 인증서/key 파일 권한 또는 경로 문제

해결:

```bash
sudo nginx -t
sudo nginx -T > /tmp/nginx-debug.conf
sudo tail -n 100 /var/log/nginx/error.log
```

`nginx -t`가 실패하면 reload/restart를 진행하지 않는다. 설정을 이전 백업으로 되돌린 뒤 다시 검증한다.

### systemctl reload는 성공했지만 worker가 예전 binary로 남음

증상:

- `nginx -v`는 새 버전인데 기존 worker가 오래 살아 있음

원인:

- reload는 설정 재적용 중심이다. binary 교체 후 완전한 프로세스 교체가 필요한 상황에서는 restart 또는 공식 binary upgrade 절차가 필요함

해결:

```bash
ps -eo pid,ppid,user,etime,cmd | grep '[n]ginx'
sudo systemctl restart nginx
```

운영 연결 영향이 우려되면 로드밸런서에서 대상 서버를 먼저 drain한 뒤 restart한다.

### 업그레이드 후 502/504 증가

원인:

- upstream keepalive 설정 변경
- proxy timeout 기본값/설정 누락
- backend 연결 실패
- SELinux, 방화벽, systemd override 차이

확인:

```bash
sudo tail -n 200 /var/log/nginx/error.log
sudo grep -E ' 502 | 504 ' /var/log/nginx/access.log | tail -n 50
sudo nginx -T | grep -E 'proxy_pass|proxy_read_timeout|upstream|keepalive'
```

롤링 업그레이드 중이면 해당 서버를 LB에서 다시 제외하고 원인 분석 후 진행한다.

---

## 10. 운영 팁

- 운영 서버는 stable repository를 기본으로 사용한다. mainline은 기능 검증 목적이 아니면 staging에서 먼저 검증한다.
- dynamic module을 사용하는 서버는 `nginx -V` 출력과 `/usr/lib64/nginx/modules` 목록을 업그레이드 전후로 비교한다.
- `nginx -t`만으로 애플리케이션 정상성을 보장하지 않는다. `/health`, TLS handshake, proxy upstream, WebSocket, cache hit, gzip 응답까지 필요한 경로를 확인한다.
- 단일 서버 restart는 연결 끊김을 만들 수 있다. 운영은 LB drain 후 한 대씩 업그레이드한다.
- 설정 변경과 binary upgrade를 한 작업에 섞지 않는다. 먼저 binary만 올리고 정상 확인 후 설정 변경을 별도 배포한다.
- 패키지 업그레이드 전 AMI 또는 EBS snapshot을 남겨두면 롤백 시간이 줄어든다.
- 관련 문서:
  - [01. 설치](../install/01_installation.md)
  - [23. Monitoring](./23_monitoring.md)
  - [24. 설정 분리와 운영 튜닝](./24_practical_tuning_and_split_conf.md)
  - [26. 무중단 배포와 빠른 롤백 운영](./26_zero_downtime_release.md)
  - [27. 자주 쓰는 Nginx 모듈 정리](../config/27_common_modules.md)
  - [Nginx 공식 문서 - Controlling nginx](https://nginx.org/en/docs/control.html)
  - [Nginx 공식 문서 - Linux packages](https://nginx.org/en/linux_packages.html)
