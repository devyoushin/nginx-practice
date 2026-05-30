# 02. Nginx 아키텍처

## Master / Worker 프로세스 모델

Nginx는 Apache의 prefork/thread 모델과 달리 **이벤트 기반 비동기 I/O** 아키텍처를 사용합니다.

```
┌─────────────────────────────────────────┐
│            Master Process               │
│  - 설정 파일 읽기 및 검증               │
│  - Worker 프로세스 생성/관리            │
│  - 시그널 처리 (HUP, QUIT 등)          │
│  - PID 파일 관리                        │
│  - 로그 파일 열기 (권한 필요)           │
└────────────────┬────────────────────────┘
                 │ fork()
     ┌───────────┼───────────┐
     ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│Worker 0 │ │Worker 1 │ │Worker N │
│         │ │         │ │         │
│ 이벤트  │ │ 이벤트  │ │ 이벤트  │
│  루프   │ │  루프   │ │  루프   │
└─────────┘ └─────────┘ └─────────┘
     │
     │  각 Worker는 수천 개의 연결을 단일 스레드로 처리
     ▼
┌─────────────────────────────┐
│  epoll (Linux) / kqueue     │
│  비동기 I/O 이벤트 감지     │
└─────────────────────────────┘
```

### Master 프로세스의 역할

1. **설정 관리**: `nginx.conf` 파싱, 검증
2. **Worker 생성**: `fork()`로 Worker 프로세스 복제
3. **시그널 수신**: HUP(재로드), QUIT(정상 종료), TERM(강제 종료)
4. **소켓 바인딩**: 1024 미만 포트는 root 권한 필요 -- Master가 바인딩 후 Worker에 전달
5. **무중단 업그레이드**: 새 Master 실행 -- 기존 Master와 공존 -- 기존 Worker 점진적 종료

### Worker 프로세스의 역할

1. 실제 요청 처리
2. 이벤트 루프로 수천 개 연결 동시 처리
3. 설정에서 지정한 user 권한으로 실행 (root 아님)
4. 각 Worker는 독립적 -- 한 Worker 크래시가 전체에 영향 없음

```bash
# 실행 중인 프로세스 확인
ps aux | grep nginx

# 결과 예시:
# root      1234  nginx: master process /usr/sbin/nginx
# nginx     1235  nginx: worker process
# nginx     1236  nginx: worker process
# nginx     1237  nginx: worker process
# nginx     1238  nginx: worker process
```

---

## Apache vs Nginx 상세 비교

### 아키텍처 비교

| 항목 | Apache (prefork) | Apache (worker/event) | Nginx |
|------|------------------|-----------------------|-------|
| 처리 모델 | 프로세스 기반 | 스레드 기반 | 이벤트 기반 |
| 연결당 자원 | 프로세스 1개 (수 MB) | 스레드 1개 (수백 KB) | 이벤트 핸들러 (수 KB) |
| 동시 연결 10,000개 | 메모리 약 10GB | 메모리 약 1GB | 메모리 약 100MB |
| C10K 문제 | 해결 불가 | 부분 해결 | 완전 해결 |
| 컨텍스트 스위칭 | 매우 빈번 | 빈번 | 최소 |
| 정적 파일 처리 | 느림 | 보통 | 매우 빠름 |
| 동적 콘텐츠 | mod_php 내장 가능 | mod_php 불가 | 외부 프로세스(FastCGI) |
| 설정 유연성 | .htaccess 지원 | .htaccess 지원 | .htaccess 미지원 |

### 메모리 사용량 비교 (동시 연결 수 기준)

```
동시 연결 수    Apache prefork     Apache event      Nginx
──────────────────────────────────────────────────────────
100              ~250 MB            ~50 MB            ~5 MB
1,000            ~2.5 GB            ~200 MB           ~15 MB
5,000            ~12 GB             ~800 MB           ~30 MB
10,000           ~25 GB (불가능)    ~1.5 GB           ~50 MB
50,000           불가능             ~7 GB (한계)      ~150 MB
100,000          불가능             불가능            ~300 MB
```

위 수치는 정적 파일 서빙 기준의 근사치입니다. 실제 환경에서는 모듈, 설정, 요청 크기에 따라 달라집니다.

### 부하 수준별 연결 처리 다이어그램

```
[저부하: 동시 100 연결]
Apache:  프로세스 100개 ──→ 각각 대기 중에도 메모리 점유
Nginx:   Worker 4개 ──→ 각 Worker가 25개 연결을 이벤트로 처리

[중부하: 동시 5,000 연결]
Apache:  프로세스 5,000개 ──→ 컨텍스트 스위칭 폭증, 응답 지연 급증
Nginx:   Worker 4개 ──→ 각 Worker가 1,250개 연결을 이벤트로 처리, CPU 여유

[고부하: 동시 50,000 연결]
Apache:  사실상 처리 불가, 연결 거부 발생
Nginx:   Worker 8개 ──→ 각 Worker가 6,250개 연결 처리, 메모리 약 150MB
```

---

## 이벤트 기반 아키텍처

### 전통적 방식 (Apache prefork) vs Nginx

```
Apache prefork:                    Nginx:
─────────────────────              ─────────────────────────────────
요청 1 → 프로세스 1                Worker 1 이벤트 루프:
요청 2 → 프로세스 2                  ├─ 요청 1 (소켓 읽기 대기)
요청 3 → 프로세스 3                  ├─ 요청 2 (백엔드 응답 대기)
...                                  ├─ 요청 3 (파일 읽기 대기)
요청 N → 프로세스 N                  └─ 요청 4 (클라이언트에 전송 중)

→ 프로세스마다 메모리 수 MB 사용     → 연결당 수 KB의 메모리
→ 컨텍스트 스위칭 오버헤드 큼        → 컨텍스트 스위칭 최소
```

### 이벤트 루프 상세 동작

```
Worker 프로세스 이벤트 루프 상세:

  ┌──────────────────────────────────────────────┐
  │              epoll_wait() 호출               │
  │         (이벤트 발생까지 블로킹)             │
  └──────────────────┬───────────────────────────┘
                     │ 이벤트 발생
                     ▼
  ┌──────────────────────────────────────────────┐
  │         이벤트 큐에서 활성 fd 목록 수신       │
  │         (예: fd=5 읽기 가능, fd=8 쓰기 가능)  │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────┐
  │         각 fd에 대해 비차단 I/O 수행          │
  │         - 새 연결 accept                     │
  │         - 요청 데이터 읽기                   │
  │         - 응답 데이터 쓰기                   │
  │         - 백엔드 연결/응답 처리              │
  │         (각 작업은 즉시 완료 또는 EAGAIN)     │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────┐
  │         타이머 이벤트 처리                    │
  │         - keepalive 타임아웃 검사             │
  │         - proxy 타임아웃 검사                 │
  └──────────────────┬───────────────────────────┘
                     │
                     └──→ 다시 epoll_wait()로 돌아감
```

### epoll (Linux) 동작 원리

```
1. Worker가 epoll_create()로 epoll 인스턴스 생성
2. 새 연결 수신 시 epoll_ctl()로 소켓 fd를 관심 목록에 등록
3. epoll_wait()로 이벤트 발생 대기 (블로킹 없음)
4. 이벤트 발생(데이터 수신/전송 가능) 시 해당 연결만 처리
5. 처리 완료 후 다시 epoll_wait()
```

### epoll의 레벨 트리거(LT) vs 엣지 트리거(ET)

Nginx는 기본적으로 **엣지 트리거(ET)** 모드로 epoll을 사용합니다.

```
레벨 트리거(LT):
  - 데이터가 버퍼에 남아있는 동안 계속 이벤트 발생
  - 읽을 데이터가 남으면 매번 epoll_wait에서 반환
  - 단순하지만, 불필요한 이벤트 반복 가능

엣지 트리거(ET):
  - 상태가 변경될 때만 이벤트 발생 (새 데이터 도착 시 1회)
  - 한 번 통지 후 남은 데이터를 모두 읽어야 함 (EAGAIN까지)
  - 더 효율적이지만, 구현이 복잡
  - Nginx가 ET를 사용하는 이유: 시스템 콜 횟수 감소
```

---

## 요청 처리 흐름

```
클라이언트                      Nginx                           백엔드
    │                             │                               │
    │──── TCP SYN ───────────────▶│                               │
    │◀─── TCP SYN-ACK ────────────│                               │
    │──── TCP ACK ───────────────▶│                               │
    │                             │                               │
    │──── HTTP Request ──────────▶│                               │
    │                             │ 1. 설정 매칭 (server_name)    │
    │                             │ 2. location 매칭              │
    │                             │ 3. 요청 처리                  │
    │                             │    - 정적 파일: 직접 응답     │
    │                             │    - 프록시: 백엔드 연결 ────▶│
    │                             │◀─────────────────────────────│
    │◀──── HTTP Response ─────────│                               │
```

### 내부 처리 단계 (Phase)

Nginx는 요청을 여러 **phase**로 나눠 처리합니다:

| Phase | 설명 | 관련 모듈/지시어 |
|-------|------|-----------------|
| `NGX_HTTP_POST_READ_PHASE` | 요청 헤더 읽기 완료 후 | realip |
| `NGX_HTTP_SERVER_REWRITE_PHASE` | server 블록의 rewrite 처리 | rewrite |
| `NGX_HTTP_FIND_CONFIG_PHASE` | location 매칭 | (내부) |
| `NGX_HTTP_REWRITE_PHASE` | location 블록의 rewrite 처리 | rewrite |
| `NGX_HTTP_POST_REWRITE_PHASE` | rewrite 완료 후 | (내부) |
| `NGX_HTTP_PREACCESS_PHASE` | 접근 제한 전처리 | limit_req, limit_conn |
| `NGX_HTTP_ACCESS_PHASE` | 접근 제어 | allow/deny, auth_basic |
| `NGX_HTTP_POST_ACCESS_PHASE` | 접근 제어 후처리 | (내부) |
| `NGX_HTTP_TRY_FILES_PHASE` | try_files 처리 | try_files |
| `NGX_HTTP_CONTENT_PHASE` | 실제 응답 생성 | proxy_pass, fastcgi, static |
| `NGX_HTTP_LOG_PHASE` | 로그 기록 | access_log |

각 phase는 순서대로 실행되며, 중간에 요청 처리가 완료되면 이후 phase는 건너뛸 수 있습니다. 예를 들어 ACCESS_PHASE에서 403을 반환하면 CONTENT_PHASE에 도달하지 않습니다.

---

## 무중단 설정 재로드 (HUP 시그널)

```
1. systemctl reload nginx
   또는 kill -HUP <master_pid>

2. Master가 새 설정 파일 검증
   └─ 오류 시: 기존 설정 유지, 에러 로그 기록

3. 검증 성공 시:
   a. 새 listen 소켓이 필요하면 생성
   b. 새 설정으로 새 Worker 프로세스 생성
   c. 기존 Worker에 QUIT 시그널 전송
   d. 기존 Worker는 현재 진행 중인 요청 완료 후 종료
   e. 완전히 새 Worker만 남아 새 설정으로 동작

→ 요청 단절 없음, 연결 유지
```

### 재로드 시 주의사항

```
# 기존 Worker가 오래된 요청을 처리 중이면 한동안 공존할 수 있음
# worker_shutdown_timeout 설정으로 기존 Worker의 최대 대기 시간을 제한 가능

worker_shutdown_timeout 30s;   # 30초 후 기존 Worker 강제 종료
```

기존 Worker가 종료되지 않는 경우 확인:
```bash
# 기존 Worker와 새 Worker 공존 확인
ps aux | grep "nginx: worker"

# 오래된 Worker가 처리 중인 연결 수 확인
# /proc/<pid>/fd 디렉토리의 소켓 fd 개수 확인
ls -la /proc/<pid>/fd | wc -l
```

---

## 무중단 바이너리 업그레이드

nginx 바이너리 자체를 무중단으로 교체할 수 있습니다.

```bash
# 1. 기존 Master PID 확인
cat /var/run/nginx.pid
# 예: 1234

# 2. 새 바이너리로 교체 (이미 파일을 교체했다고 가정)

# 3. 기존 Master에 USR2 시그널 → 새 Master 실행
kill -USR2 1234

# 4. 새/기존 Master 동시 실행 상태 확인
ps aux | grep nginx
# 새 Master (pid 5678)와 기존 Master (pid 1234) 공존

# 5. 기존 Worker 점진적 종료
kill -WINCH 1234

# 6. 이상 없으면 기존 Master 종료
kill -QUIT 1234

# 롤백이 필요한 경우: 기존 Master에 HUP
kill -HUP 1234
```

### 바이너리 업그레이드 시 PID 파일 변화

```
업그레이드 과정에서 PID 파일 변화:

단계 1 (USR2 전):
  /var/run/nginx.pid = 1234 (기존 Master)

단계 2 (USR2 후):
  /var/run/nginx.pid = 5678 (새 Master)
  /var/run/nginx.pid.oldbin = 1234 (기존 Master)

단계 3 (QUIT 후):
  /var/run/nginx.pid = 5678 (새 Master만 남음)
  /var/run/nginx.pid.oldbin 삭제됨
```

---

## 시그널 요약 표

| 시그널 | 명령어 | 동작 | nginx -s 옵션 |
|--------|--------|------|---------------|
| TERM, INT | `kill -TERM <pid>` | 즉시 종료 | `nginx -s stop` |
| QUIT | `kill -QUIT <pid>` | 정상(graceful) 종료 | `nginx -s quit` |
| HUP | `kill -HUP <pid>` | 설정 재로드 | `nginx -s reload` |
| USR1 | `kill -USR1 <pid>` | 로그 파일 재오픈 | `nginx -s reopen` |
| USR2 | `kill -USR2 <pid>` | 바이너리 업그레이드 시작 | 없음 |
| WINCH | `kill -WINCH <pid>` | Worker 점진적 종료 | 없음 |

Worker 프로세스에 직접 보내는 시그널:

| 시그널 | 동작 |
|--------|------|
| TERM | Worker 즉시 종료 |
| QUIT | Worker 정상 종료 (현재 요청 완료 후) |

---

## Cache Manager / Cache Loader 프로세스

proxy_cache 또는 fastcgi_cache 설정 시 추가 프로세스가 생성됩니다.

```bash
ps aux | grep nginx
# nginx: cache manager process  ← 캐시 만료/삭제 담당
# nginx: cache loader process   ← 서버 시작 시 캐시 디스크 → 메모리 로드
```

### Cache Manager 상세

Cache Manager는 주기적으로 캐시 디렉토리를 순회하며 다음 작업을 수행합니다:

- **만료된 캐시 항목 삭제**: `proxy_cache_valid`에 설정된 유효 시간이 지난 항목
- **캐시 크기 관리**: `max_size`를 초과하면 LRU(Least Recently Used) 방식으로 오래된 항목 삭제
- **디스크 공간 관리**: 캐시가 차지하는 디스크 공간을 설정 범위 내로 유지

```nginx
proxy_cache_path /var/cache/nginx levels=1:2
    keys_zone=my_cache:10m     # 캐시 키를 저장하는 공유 메모리 크기
    max_size=10g               # 캐시 최대 크기 (Cache Manager가 이를 초과하면 삭제)
    inactive=60m               # 60분간 접근 없으면 삭제
    manager_files=100          # Cache Manager가 한 번에 처리하는 파일 수
    manager_sleep=50ms         # 반복 간 대기 시간
    manager_threshold=200ms;   # 한 번의 반복에서 소요할 최대 시간
```

### Cache Loader 상세

Cache Loader는 Nginx 시작 시(또는 재시작 시) 한 번만 실행됩니다:

- 디스크에 저장된 캐시 파일을 읽어 공유 메모리(keys_zone)에 메타데이터 로드
- 서버 시작 직후부터 캐시가 동작하도록 보장
- 대량의 캐시 파일이 있을 경우 점진적으로 로드하여 시작 시 과부하 방지

```nginx
proxy_cache_path /var/cache/nginx levels=1:2
    keys_zone=my_cache:10m
    loader_files=100           # 한 번에 로드하는 파일 수
    loader_sleep=50ms          # 반복 간 대기 시간
    loader_threshold=200ms;    # 한 번의 반복에서 소요할 최대 시간
```

---

## Thread Pool 설명

Nginx의 이벤트 모델에서 블로킹 작업(디스크 I/O 등)은 이벤트 루프를 차단할 수 있습니다. Thread Pool은 이 문제를 해결합니다.

```
이벤트 루프 기반 처리 (Thread Pool 없이):
──────────────────────────────────────────
Worker 이벤트 루프:
  → 요청 A 처리 (네트워크 I/O, 비차단) ← 빠름
  → 요청 B 처리 (디스크 읽기, 차단!)   ← 느림, 이벤트 루프 멈춤
  → 요청 C 처리 (대기 중...)           ← B가 끝날 때까지 대기

Thread Pool 사용 시:
──────────────────────────────────────────
Worker 이벤트 루프:
  → 요청 A 처리 (네트워크 I/O, 비차단) ← 빠름
  → 요청 B의 디스크 읽기를 Thread Pool에 위임
  → 요청 C 처리 (즉시 가능!)           ← 대기 없음
  → Thread Pool에서 B의 읽기 완료 통지 → 요청 B 이어서 처리
```

### Thread Pool 설정 예시

```nginx
# main context에서 스레드 풀 정의
thread_pool disk_io threads=16 max_queue=65536;
thread_pool heavy_io threads=32 max_queue=32768;

http {
    server {
        # 대용량 정적 파일 제공 시
        location /videos/ {
            aio threads=disk_io;
            sendfile on;
            directio 8m;        # 8MB 이상 파일은 direct I/O 사용
        }

        # 고부하 파일 I/O 경로
        location /downloads/ {
            aio threads=heavy_io;
            sendfile on;
        }
    }
}
```

Thread Pool 사용 시 주의사항:
- 컴파일 시 `--with-threads` 옵션이 필요합니다
- 모든 운영체제에서 지원되지는 않습니다 (Linux 권장)
- 스레드 수를 너무 많이 설정하면 오히려 컨텍스트 스위칭 오버헤드가 발생합니다
- `max_queue`가 가득 차면 에러가 발생하므로 적절한 크기로 설정해야 합니다

---

## 실전 트러블슈팅

### Worker 크래시 진단

Worker 프로세스가 비정상 종료되면 Master가 자동으로 새 Worker를 생성합니다. 하지만 반복적인 크래시는 조사가 필요합니다.

```bash
# 1. error_log에서 크래시 관련 로그 확인
grep -i "signal\|segfault\|abort\|worker process" /var/log/nginx/error.log

# 대표적인 크래시 로그 패턴:
# worker process <pid> exited on signal 11 (SIGSEGV)  ← 세그폴트
# worker process <pid> exited on signal 6 (SIGABRT)   ← 어보트

# 2. 코어 덤프 활성화 (root 권한)
# /etc/nginx/nginx.conf에 추가:
# worker_rlimit_core 500m;
# working_directory /var/crash/nginx;

# 디렉토리 생성 및 권한 설정
mkdir -p /var/crash/nginx
chown nginx:nginx /var/crash/nginx
chmod 700 /var/crash/nginx

# 코어 덤프 시스템 설정
echo '/var/crash/nginx/core.%e.%p' > /proc/sys/kernel/core_pattern
ulimit -c unlimited

# 3. 코어 덤프 분석 (gdb 사용)
gdb /usr/sbin/nginx /var/crash/nginx/core.nginx.12345
# (gdb) bt     ← 백트레이스 확인
```

흔한 Worker 크래시 원인:
- 서드파티 모듈의 버그 (특히 Lua, njs 모듈)
- 잘못된 정규표현식으로 인한 스택 오버플로우
- 메모리 부족 (OOM Killer에 의한 종료)
- Nginx 버전 자체의 버그 (업그레이드로 해결)

### 높은 CPU 사용률 진단

```bash
# 1. 어떤 Worker가 CPU를 많이 사용하는지 확인
top -p $(pgrep -d',' nginx)

# 또는 ps로 확인
ps -eo pid,ppid,%cpu,%mem,cmd | grep nginx

# 2. Worker의 CPU 사용 내역 확인 (strace)
strace -c -p <worker_pid> -e trace=network,file
# 시스템 콜별 소요 시간 통계 출력

# 3. perf로 상세 프로파일링
perf top -p <worker_pid>
# 어떤 함수에서 시간을 소비하는지 확인

# 4. Nginx 상태 확인 (stub_status 모듈)
curl http://localhost/nginx_status
# Active connections: 291
# server accepts handled requests
#  16630948 16630948 31070465
# Reading: 6 Writing: 179 Waiting: 106
```

높은 CPU의 일반적인 원인과 해결책:

| 원인 | 진단 방법 | 해결책 |
|------|----------|--------|
| 과도한 정규표현식 매칭 | strace에서 regex 관련 호출 다수 | 정규표현식 단순화, pcre_jit 활성화 |
| SSL/TLS 핸드셰이크 | openssl 관련 함수 상위 | SSL session cache 설정, ECDSA 인증서 사용 |
| gzip 압축 | gzip 관련 함수 상위 | gzip_comp_level 낮추기 (1-3 권장) |
| 로그 기록 과다 | write() 시스템 콜 다수 | access_log 버퍼링, 불필요한 로그 비활성화 |
| Worker 수 부족 | 모든 Worker CPU 100% | worker_processes 증가 |

### 메모리 사용량 진단

```bash
# Worker별 메모리 사용량 확인
ps -eo pid,rss,vsz,cmd | grep "nginx: worker"
# RSS: 실제 물리 메모리 사용량 (KB)
# VSZ: 가상 메모리 크기 (KB)

# 공유 메모리 사용 확인 (캐시, SSL session 등)
# nginx -T 출력에서 shared memory zone 확인
nginx -T 2>/dev/null | grep -E "zone=|keys_zone="

# 전체 Nginx 메모리 사용량 합계
ps -eo rss,cmd | grep nginx | awk '{sum+=$1} END {print sum/1024 " MB"}'
```

메모리 사용량이 비정상적으로 높을 때:
- `proxy_buffers`, `proxy_buffer_size` 설정이 과도하게 큰 경우
- 대량의 캐시 keys_zone 설정
- 서드파티 모듈의 메모리 누수
- 클라이언트가 대용량 본문을 업로드하는 경우 (`client_body_buffer_size`)

---

## Nginx 프로세스 전체 구조 요약

```
┌─────────────────────────────────────────────────────────┐
│                    Master Process                       │
│                    (root 권한)                           │
│  역할: 설정 관리, Worker 관리, 시그널 처리, 소켓 바인딩  │
└───┬───────┬───────┬───────────┬───────────┬─────────────┘
    │       │       │           │           │
    ▼       ▼       ▼           ▼           ▼
 Worker  Worker  Worker   Cache Mgr   Cache Loader
   0       1      ...    (캐시 관리)  (시작 시 로드)
   │       │       │
   │       │       │    각 Worker 내부:
   │       │       │    ┌────────────────────────┐
   │       │       │    │ 이벤트 루프 (epoll)    │
   │       │       │    │ + Thread Pool (선택)   │
   │       │       │    │ + 연결 풀              │
   │       │       │    │ + 메모리 풀            │
   │       │       │    └────────────────────────┘
   ▼       ▼       ▼
  수천 개의 동시 연결 처리
```
