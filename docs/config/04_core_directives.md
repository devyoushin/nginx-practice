# 04. Core 지시어 (main context)

main context는 nginx.conf 최상위에 위치하며, 전체 nginx 프로세스에 영향을 줍니다.

---

## user

Worker 프로세스가 실행될 OS 사용자/그룹을 지정합니다.

```nginx
user nginx;
user nginx nginx;    # user group 형식
```

- Master 프로세스는 root로 실행됨 (1024 미만 포트 바인딩 위해)
- Worker 프로세스는 이 user로 실행 -- 파일 접근 권한이 이 user 기준
- 웹 루트의 파일이 nginx 유저로 읽힐 수 있어야 함

```bash
# nginx 유저 확인
id nginx

# 웹 루트 권한 확인
ls -la /usr/share/nginx/html/
```

### user 설정 관련 흔한 문제

```bash
# 문제: 403 Forbidden 에러
# 원인: nginx 유저가 웹 루트 파일을 읽을 수 없음

# 확인 방법
sudo -u nginx test -r /var/www/html/index.html && echo "읽기 가능" || echo "읽기 불가"

# 해결: 파일 소유자/권한 변경
chown -R nginx:nginx /var/www/html/
chmod -R 644 /var/www/html/
chmod 755 /var/www/html/    # 디렉토리는 실행 권한 필요
```

```bash
# 문제: upstream 소켓 연결 실패 (Permission denied)
# 원인: nginx 유저가 Unix 소켓 파일에 접근 불가

# PHP-FPM 소켓 예시
ls -la /run/php-fpm/www.sock
# srw-rw---- 1 php-fpm php-fpm ... /run/php-fpm/www.sock

# 해결: nginx 유저를 php-fpm 그룹에 추가
usermod -aG php-fpm nginx
```

---

## worker_processes

Worker 프로세스 수를 지정합니다.

```nginx
worker_processes 1;       # 단일 Worker
worker_processes 4;       # 4개 Worker
worker_processes auto;    # CPU 코어 수에 맞게 자동 (권장)
```

- `auto`: `/proc/cpuinfo`에서 CPU 코어 수를 읽어 설정
- 일반적으로 CPU 코어 수 = Worker 수로 설정
- I/O 바운드 작업이 많다면 코어 수 x 2도 고려

```bash
# CPU 코어 수 확인
nproc
grep -c processor /proc/cpuinfo
```

### 워크로드별 worker_processes 튜닝 가이드

#### CPU 바운드 워크로드

SSL/TLS 종료, gzip 압축, 이미지 처리 등 CPU 집약적인 작업이 많은 경우:

```nginx
# CPU 코어 수와 동일하게 설정 (권장)
worker_processes auto;    # 또는 코어 수 직접 지정

# 이유:
# - CPU 바운드 작업은 코어를 100% 활용
# - Worker 수 > 코어 수이면 컨텍스트 스위칭 오버헤드만 증가
# - Worker 수 < 코어 수이면 코어가 유휴 상태
```

```bash
# CPU 바운드인지 확인하는 방법
top -p $(pgrep -d',' -x nginx)
# %CPU가 높고 %IO(wa)가 낮으면 CPU 바운드

# 또는 pidstat으로 확인
pidstat -p $(pgrep -d',' -x nginx) 1
```

#### I/O 바운드 워크로드

디스크에서 대용량 파일을 읽거나, 느린 백엔드에 프록시하는 경우:

```nginx
# 코어 수의 1.5~2배 설정 고려
worker_processes 8;    # 4코어 서버에서

# 이유:
# - Worker가 I/O 대기 중일 때 다른 Worker가 CPU 사용 가능
# - 하지만 너무 많으면 메모리 사용량 증가 및 컨텍스트 스위칭 오버헤드

# 더 나은 대안: Thread Pool 사용
thread_pool default threads=32 max_queue=65536;
```

#### 혼합 워크로드 (가장 일반적)

```nginx
# auto가 가장 안전한 선택
worker_processes auto;

# 성능 테스트를 통해 최적값 확인
# 부하 테스트 도구 (wrk, ab, k6 등)로 다양한 Worker 수를 테스트
```

```bash
# wrk로 Worker 수별 성능 비교 예시
# worker_processes 값을 변경하며 테스트
for workers in 1 2 4 8; do
    echo "Testing with $workers workers..."
    # nginx.conf 수정 후 reload
    wrk -t4 -c100 -d30s http://localhost/
done
```

#### 컨테이너 환경 (Docker/Kubernetes)

```nginx
# 컨테이너에 할당된 CPU만큼만 사용
# auto는 호스트의 전체 CPU 코어를 감지하므로 주의

# cgroup v2 환경에서는 auto가 올바르게 동작 (Nginx 1.25+)
worker_processes auto;

# 구버전 Nginx이거나 cgroup v1인 경우 명시적 지정
worker_processes 2;    # 컨테이너에 2 CPU 할당 시
```

---

## worker_cpu_affinity

각 Worker 프로세스를 특정 CPU 코어에 바인딩합니다.

```nginx
worker_processes 4;

# 각 Worker를 개별 코어에 바인딩 (4코어)
worker_cpu_affinity 0001 0010 0100 1000;

# auto: nginx가 자동으로 배분
worker_cpu_affinity auto;

# 모든 Worker가 모든 코어 사용 (기본)
worker_cpu_affinity auto 1111;
```

CPU 캐시 히트율 향상 및 NUMA 아키텍처 최적화에 유용합니다.

### NUMA 아키텍처에서의 CPU 어피니티

NUMA(Non-Uniform Memory Access) 서버에서는 Worker를 같은 NUMA 노드의 CPU에 바인딩하면 메모리 접근 지연을 줄일 수 있습니다.

```
NUMA 서버 구조 예시 (2소켓 서버):

Node 0: CPU 0,1,2,3  + 로컬 메모리 32GB
Node 1: CPU 4,5,6,7  + 로컬 메모리 32GB

Worker가 Node 0의 CPU에서 실행되면서 Node 1의 메모리에 접근하면
로컬 메모리 대비 1.5~2배 느림 (원격 메모리 접근)
```

```nginx
# 8코어 2 NUMA 노드 서버 설정 예시
worker_processes 8;

# 모든 코어에 순서대로 바인딩
worker_cpu_affinity 00000001 00000010 00000100 00001000
                    00010000 00100000 01000000 10000000;

# 또는 NUMA 노드별로 Worker 분리
# Node 0 (CPU 0-3)에서만 Worker 실행
worker_processes 4;
worker_cpu_affinity 0001 0010 0100 1000;
```

```bash
# NUMA 구조 확인
numactl --hardware
# available: 2 nodes (0-1)
# node 0 cpus: 0 1 2 3
# node 1 cpus: 4 5 6 7

# Worker의 CPU 어피니티 확인
taskset -cp <worker_pid>
# pid <worker_pid>'s current affinity list: 0

# NUMA 노드별 메모리 사용량 확인
numastat -p $(pgrep -d',' -x nginx)
```

---

## worker_rlimit_nofile

Worker 프로세스가 열 수 있는 최대 파일 디스크립터 수입니다.

```nginx
worker_rlimit_nofile 65535;
```

`worker_connections`와 관련: 각 연결은 최소 1개의 fd를 사용하므로
`worker_rlimit_nofile` >= `worker_connections`이어야 합니다.

```bash
# OS 전체 파일 디스크립터 한계 확인
ulimit -n
cat /proc/sys/fs/file-max

# OS 레벨 한계 올리기 (/etc/security/limits.conf)
# nginx soft nofile 65535
# nginx hard nofile 65535
```

### worker_rlimit_nofile과 systemd LimitNOFILE 관계

systemd로 Nginx를 관리하는 경우, 파일 디스크립터 한계는 3개 계층에서 제어됩니다:

```
우선순위 (높은 것이 적용):
1. nginx.conf의 worker_rlimit_nofile  ← Nginx가 자체적으로 setrlimit() 호출
2. systemd 서비스 파일의 LimitNOFILE  ← systemd가 프로세스 시작 시 설정
3. /etc/security/limits.conf          ← PAM 모듈이 적용 (systemd에서는 무시됨)
```

중요: systemd 환경에서는 `/etc/security/limits.conf`가 적용되지 않습니다. systemd가 자체적으로 제한값을 설정하기 때문입니다.

```bash
# systemd 서비스 파일 확인
systemctl cat nginx.service

# LimitNOFILE 확인
systemctl show nginx.service | grep LimitNOFILE
```

```ini
# /etc/systemd/system/nginx.service.d/override.conf
# systemd의 파일 디스크립터 한계 변경
[Service]
LimitNOFILE=65535
```

```bash
# override 적용
sudo systemctl daemon-reload
sudo systemctl restart nginx

# 실제 적용 확인
cat /proc/$(pgrep -x nginx | head -1)/limits | grep "Max open files"
# Max open files            65535                65535                files
```

### 세 계층의 상호작용

```
시나리오 1: systemd LimitNOFILE=1024, nginx worker_rlimit_nofile=65535
  → Nginx가 65535로 올리려 하지만 systemd 한계(1024)를 넘을 수 없음
  → 실제 적용값: 1024 (에러 로그에 경고 발생)

시나리오 2: systemd LimitNOFILE=65535, nginx worker_rlimit_nofile 미설정
  → systemd가 65535로 설정
  → 실제 적용값: 65535

시나리오 3: systemd LimitNOFILE=65535, nginx worker_rlimit_nofile=8192
  → Nginx가 스스로 8192로 내려서 설정
  → 실제 적용값: 8192

권장: 양쪽 모두 같은 값으로 설정
  systemd LimitNOFILE=65535
  nginx worker_rlimit_nofile 65535;
```

### 적정 worker_rlimit_nofile 계산

```
worker_rlimit_nofile 계산 공식:

필요한 fd 수 = worker_connections x 2 (프록시 시 클라이언트 + 백엔드)
              + 로그 파일 fd (보통 2~10개)
              + 캐시 파일 fd
              + 여유분

예시: worker_connections=4096인 프록시 서버
  = 4096 x 2 + 10 + 100 + 여유
  = 약 8,300
  → worker_rlimit_nofile 16384; (넉넉하게 설정)
```

---

## error_log

에러 로그 파일 경로와 로그 레벨을 설정합니다.

```nginx
error_log /var/log/nginx/error.log;             # 기본 (warn 레벨)
error_log /var/log/nginx/error.log notice;
error_log /var/log/nginx/error.log info;
error_log /var/log/nginx/error.log debug;       # 상세 (개발 시)
error_log /dev/null;                             # 로그 비활성화
```

### 로그 레벨 (낮을수록 상세)

| 레벨 | 설명 | 운영 사용 |
|------|------|----------|
| `debug` | 모든 디버그 정보 (매우 상세, 고부하) | 개발/디버깅 전용 |
| `info` | 정보성 메시지 | 상세 모니터링 시 |
| `notice` | 중요 이벤트 | 일반 운영 |
| `warn` | 경고 | 권장 (운영 기본) |
| `error` | 처리 오류 | 최소 로깅 |
| `crit` | 심각한 오류 | 최소 로깅 |
| `alert` | 즉각 조치 필요 | 최소 로깅 |
| `emerg` | 시스템 사용 불가 | 최소 로깅 |

지정한 레벨 이상의 로그만 기록됩니다. `warn`을 지정하면 warn/error/crit/alert/emerg만 기록.

### debug_connection: 특정 클라이언트만 디버그 로깅

운영 환경에서 전체 debug 로그를 켜면 부하가 매우 큽니다. `debug_connection`을 사용하면 특정 IP에서 오는 요청에 대해서만 debug 로그를 기록할 수 있습니다.

```nginx
# error_log에 debug 레벨 설정 필요
error_log /var/log/nginx/error.log debug;

events {
    # 특정 IP에서의 연결만 디버그 로그 기록
    debug_connection 192.168.1.100;
    debug_connection 10.0.0.0/24;      # CIDR 표기 가능

    # 다른 연결은 error_log에 설정된 레벨이 적용되지만,
    # debug_connection에 해당하는 연결만 debug 수준으로 기록됨

    worker_connections 1024;
}
```

주의사항:
- Nginx가 `--with-debug` 옵션으로 컴파일되어야 합니다
- `nginx -V`로 컴파일 옵션 확인 가능

```bash
nginx -V 2>&1 | grep -- '--with-debug'
# --with-debug가 포함되어 있으면 debug_connection 사용 가능
```

### error_log를 여러 파일에 동시 기록

```nginx
# 일반 로그와 디버그 로그를 분리
error_log /var/log/nginx/error.log warn;         # 운영 로그
error_log /var/log/nginx/error-debug.log debug;  # 디버그 로그 (별도 파일)

# syslog로 전송 (원격 로그 수집)
error_log syslog:server=192.168.1.200:514,facility=local7 warn;
error_log /var/log/nginx/error.log warn;
```

---

## pid

Master 프로세스의 PID 파일 경로입니다.

```nginx
pid /var/run/nginx.pid;
```

systemd와 logrotate가 이 파일을 참조합니다.

---

## daemon

백그라운드 데몬으로 실행할지 여부입니다.

```nginx
daemon on;   # 기본값, 백그라운드 실행
daemon off;  # 포그라운드 실행 (Docker 컨테이너에서 사용)
```

Docker에서 nginx를 직접 실행할 때 `daemon off`를 사용하거나
CMD에서 `nginx -g 'daemon off;'`를 씁니다.

```dockerfile
# Dockerfile 예시
FROM nginx:1.25
COPY nginx.conf /etc/nginx/nginx.conf
# 방법 1: nginx.conf에 daemon off; 포함
CMD ["nginx"]

# 방법 2: 명령줄에서 전역 지시어 전달
CMD ["nginx", "-g", "daemon off;"]
```

---

## master_process

Master/Worker 모델 사용 여부입니다.

```nginx
master_process on;   # 기본값
master_process off;  # 개발/디버깅 시 단일 프로세스로 실행
```

---

## load_module

동적 모듈을 로드합니다.

```nginx
load_module modules/ngx_http_image_filter_module.so;
load_module modules/ngx_stream_module.so;
```

```bash
# 사용 가능한 모듈 확인
ls /usr/lib64/nginx/modules/

# 컴파일된 모듈 목록
nginx -V 2>&1 | grep -o -- '--with-[a-z_]*'
```

---

## env

환경 변수를 Worker 프로세스에 전달합니다.

```nginx
env MALLOC_OPTIONS;         # 기존 환경변수 전달
env PERL5LIB=/data/site/modules;  # 값 설정하여 전달
env OPENSSL_ALLOW_PROXY_CERTS=1;
```

기본적으로 Nginx는 Master 프로세스에서 Worker로 환경 변수를 전달하지 않습니다. 필요한 환경 변수는 `env` 지시어로 명시적으로 전달해야 합니다.

```nginx
# Lua 모듈에서 환경변수 사용 시
env API_KEY;
env DATABASE_URL;

# njs 모듈에서 환경변수 접근
env MY_APP_CONFIG;
```

---

## thread_pool

비동기 파일 I/O를 위한 스레드 풀 설정입니다.
(컴파일 시 `--with-threads` 필요)

```nginx
thread_pool default threads=32 max_queue=65536;

# location에서 사용
location /video/ {
    aio threads=default;
    sendfile on;
}
```

### thread_pool 튜닝

```nginx
# 용도별 스레드 풀 분리
thread_pool static_files threads=16 max_queue=65536;
thread_pool large_files threads=8 max_queue=32768;

http {
    server {
        # 일반 정적 파일
        location /assets/ {
            aio threads=static_files;
            sendfile on;
        }

        # 대용량 파일 다운로드
        location /downloads/ {
            aio threads=large_files;
            sendfile on;
            directio 4m;    # 4MB 이상은 direct I/O
        }
    }
}
```

---

## pcre_jit

PCRE 라이브러리의 JIT(Just-In-Time) 컴파일을 활성화합니다.

```nginx
pcre_jit on;
```

정규표현식을 많이 사용하는 설정에서 성능을 크게 향상시킵니다.

```
효과:
- location ~ 정규표현식 매칭 속도 향상
- rewrite 지시어의 정규표현식 처리 속도 향상
- map 지시어에서 정규표현식 사용 시 성능 향상

전제 조건:
- PCRE 라이브러리가 JIT 지원으로 컴파일되어 있어야 함
- Nginx 1.1.12 이상
```

```bash
# PCRE JIT 지원 확인
pcretest -C | grep JIT
# JIT support

# Nginx에서 PCRE 사용 여부 확인
nginx -V 2>&1 | grep pcre
```

---

## worker_shutdown_timeout

기존 Worker 프로세스가 종료될 때까지 기다리는 최대 시간입니다.

```nginx
worker_shutdown_timeout 30s;    # 30초 후 강제 종료
worker_shutdown_timeout 120s;   # 긴 요청을 처리하는 서버
```

설정을 reload할 때 기존 Worker가 처리 중인 요청을 완료하기를 기다리는 시간입니다. 이 시간이 지나면 기존 Worker의 연결을 강제로 닫습니다.

```
사용 사례:
- WebSocket 연결이 많은 서버: 길게 설정 (60s~300s)
- 짧은 API 요청만 처리하는 서버: 짧게 설정 (10s~30s)
- 파일 다운로드 서버: 길게 설정 (300s~600s)
- 미설정 시: Worker가 모든 연결이 끝날 때까지 무한 대기
```

```bash
# reload 후 기존 Worker가 아직 살아있는지 확인
ps aux | grep "nginx: worker" | wc -l
# Worker 수가 worker_processes보다 많으면 기존 Worker가 아직 종료 안 된 것

# 기존 Worker가 종료 안 되는 원인 진단
# 해당 Worker의 fd 수 확인
ls /proc/<old_worker_pid>/fd | wc -l
```

---

## timer_resolution

Nginx 내부 타이머의 해상도를 설정합니다.

```nginx
timer_resolution 100ms;    # 100밀리초 단위로 시간 갱신
```

기본적으로 Nginx는 `gettimeofday()` 시스템 콜을 통해 시간을 갱신합니다. `timer_resolution`을 설정하면 지정된 간격으로만 시간을 갱신하여 시스템 콜 횟수를 줄입니다.

```
효과:
- gettimeofday() 호출 횟수 감소 → 약간의 성능 향상
- 로그 타임스탬프의 정밀도가 설정값에 맞춰 낮아짐

일반적으로 설정하지 않아도 성능 차이가 미미합니다.
매우 높은 트래픽(초당 수만 요청) 환경에서만 의미가 있습니다.
```

---

## worker_priority

Worker 프로세스의 nice 값(실행 우선순위)을 설정합니다.

```nginx
worker_priority -5;    # 높은 우선순위 (-20 ~ 19, 낮을수록 높은 우선순위)
worker_priority 0;     # 기본값 (일반 우선순위)
```

다른 프로세스와 CPU 경합이 있을 때 Nginx Worker에 더 높은 우선순위를 부여합니다.

---

## worker_rlimit_core

Worker 크래시 시 생성되는 코어 덤프 파일의 최대 크기입니다.

```nginx
worker_rlimit_core 500m;
working_directory /var/crash/nginx;    # 코어 덤프 저장 위치
```

```bash
# 코어 덤프 디렉토리 준비
mkdir -p /var/crash/nginx
chown nginx:nginx /var/crash/nginx
chmod 700 /var/crash/nginx
```

---

## 실전 트러블슈팅

### 증상별 진단 가이드

| 증상 | 확인 사항 | 관련 지시어 |
|------|----------|------------|
| "Too many open files" 에러 | fd 한계 확인 | worker_rlimit_nofile |
| Worker 빈번한 재시작 | error_log에서 시그널 확인 | worker_rlimit_core |
| 503 에러 급증 | Worker 연결 포화 | worker_connections |
| reload 후 메모리 증가 | 기존 Worker 미종료 | worker_shutdown_timeout |
| CPU 사용률 높음 | Worker 수/어피니티 확인 | worker_processes, worker_cpu_affinity |
| 권한 거부 에러 | 파일/소켓 접근 권한 | user |

### "Too many open files" 해결 절차

```bash
# 1. 현재 한계 확인
cat /proc/$(cat /var/run/nginx.pid)/limits | grep "Max open files"

# 2. 현재 사용 중인 fd 수 확인
ls /proc/$(pgrep -o "nginx: worker")/fd | wc -l

# 3. nginx.conf 설정
# worker_rlimit_nofile 65535;

# 4. systemd override 설정
sudo systemctl edit nginx
# [Service]
# LimitNOFILE=65535

# 5. 적용 및 확인
sudo systemctl daemon-reload
sudo systemctl restart nginx
cat /proc/$(pgrep -o "nginx: worker")/limits | grep "Max open files"
```

### 설정 변경 시 검증 체크리스트

```bash
# 1. 문법 검사
sudo nginx -t

# 2. 현재 설정과 새 설정 비교
sudo nginx -T > /tmp/before.conf
# (설정 변경 후)
sudo nginx -t -c /path/to/new/nginx.conf
# 오류 없으면 적용

# 3. reload
sudo systemctl reload nginx

# 4. 프로세스 상태 확인
ps aux | grep nginx

# 5. 로그 확인
tail -20 /var/log/nginx/error.log

# 6. 서비스 정상 동작 확인
curl -I http://localhost/
```

---

## 정리: 실운영 권장 main context 설정

```nginx
user nginx;
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 65535;
worker_shutdown_timeout 30s;
pcre_jit on;

error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

load_module modules/ngx_http_geoip2_module.so;  # 필요 시
```

### 환경별 권장 설정 비교

| 설정 | 개발 환경 | 스테이징 | 운영 환경 |
|------|----------|---------|----------|
| worker_processes | 1 | auto | auto |
| worker_rlimit_nofile | 1024 | 65535 | 65535 |
| error_log 레벨 | debug | notice | warn |
| worker_shutdown_timeout | 5s | 30s | 30s~120s |
| pcre_jit | off | on | on |
| daemon | off (Docker) | on | on |
