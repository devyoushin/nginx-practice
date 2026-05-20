# 05. Events 모듈

events 블록은 Worker 프로세스의 연결 처리 방식을 제어합니다.

```nginx
events {
    worker_connections  1024;
    use epoll;
    multi_accept on;
    accept_mutex off;
}
```

---

## worker_connections

Worker 프로세스 하나가 동시에 처리할 수 있는 최대 연결 수입니다.

```nginx
worker_connections 1024;    # 기본값
worker_connections 4096;    # 고트래픽 서버
worker_connections 65535;   # 최대치 (worker_rlimit_nofile과 맞춰야 함)
```

### 최대 동시 연결 수 계산

```
전체 최대 동시 연결 = worker_processes x worker_connections

예: worker_processes=4, worker_connections=4096
--> 최대 16,384 동시 연결
```

**주의**: reverse proxy 사용 시 하나의 클라이언트 요청이 백엔드 연결도 필요하므로
실제 최대 클라이언트 수 = (worker_processes x worker_connections) / 2

### 정적 파일 서빙 vs 프록시의 연결 계산 차이

```
[정적 파일 서빙]
클라이언트 ──→ Nginx
  연결 1개 = fd 1개

최대 클라이언트 수 = worker_processes x worker_connections
예: 4 x 4096 = 16,384 클라이언트

[리버스 프록시]
클라이언트 ──→ Nginx ──→ 백엔드
  연결 1개 = fd 2개 (클라이언트 소켓 + 백엔드 소켓)

최대 클라이언트 수 = (worker_processes x worker_connections) / 2
예: 4 x 4096 / 2 = 8,192 클라이언트

[프록시 + keepalive]
클라이언트 ──→ Nginx ──→ 백엔드 (keepalive 연결 유지)
  활성 요청 = fd 2개
  유휴 keepalive = fd 1개 (백엔드) + fd 1개 (클라이언트)

keepalive가 많으면 실제 처리 가능한 새 요청 수가 줄어듦
upstream 설정에서 keepalive 연결 수를 적절히 제한해야 함
```

```nginx
# 프록시 서버에서의 권장 설정
upstream backend {
    server 10.0.1.100:8080;
    server 10.0.1.101:8080;
    keepalive 32;    # 백엔드 keepalive 연결 풀 크기 제한
}
```

### 실전 worker_connections 계산 예시

```
시나리오: 일 평균 100만 페이지뷰, 피크 시간 3배
- 일 평균 요청: 1,000,000
- 피크 시간 요청: 3,000,000 / 24h = 초당 약 35 요청
- 평균 연결 유지 시간: 5초 (keepalive)
- 동시 연결 추정: 35 x 5 = 175
- 안전 마진 (10배): 1,750
- 프록시 계수 (x2): 3,500
- worker_processes: 4

worker_connections = 3,500 / 4 = 875
--> worker_connections 1024로 충분

시나리오: 고트래픽 API 서버 (초당 10,000 요청)
- 초당 요청: 10,000
- 평균 연결 유지: 2초
- 동시 연결 추정: 20,000
- 프록시 계수 (x2): 40,000
- 안전 마진 (x2): 80,000
- worker_processes: 8

worker_connections = 80,000 / 8 = 10,000
--> worker_connections 16384 권장
```

---

## use

I/O 이벤트 감지 방식을 지정합니다.

```nginx
use epoll;      # Linux (권장, 기본)
use kqueue;     # BSD/macOS
use select;     # 범용 (비효율적, 폴백용)
use poll;       # select보다 약간 나음
use /dev/poll;  # Solaris
use eventport;  # Solaris 10+
```

nginx는 빌드 환경에서 최적의 방법을 자동 선택하므로 대부분 생략 가능합니다.
Linux에서는 항상 `epoll`이 선택됩니다.

### epoll vs kqueue vs select/poll 상세 비교

| 항목 | select | poll | epoll (Linux) | kqueue (BSD/macOS) |
|------|--------|------|---------------|-------------------|
| 시간 복잡도 | O(N) | O(N) | O(1) | O(1) |
| 최대 fd 수 | FD_SETSIZE (1024) | 제한 없음 | 제한 없음 | 제한 없음 |
| fd 전달 방식 | 매 호출마다 전체 집합 복사 | 매 호출마다 전체 배열 복사 | fd 등록/해제만 | fd 등록/해제만 |
| 이벤트 통지 | 레벨 트리거만 | 레벨 트리거만 | LT + ET 지원 | LT + ET 지원 |
| 메모리 사용 | fd 집합 크기에 비례 | fd 배열 크기에 비례 | 커널 내부 레드블랙 트리 | 커널 내부 큐 |
| 1만 연결 시 성능 | 매우 느림 | 느림 | 빠름 | 빠름 |
| 지원 OS | 모든 OS | 대부분 OS | Linux 2.6+ | FreeBSD, macOS |
| 배치 이벤트 등록 | 불가 | 불가 | 불가 | 가능 (changelist) |

### 왜 epoll/kqueue가 빠른가 (상세 설명)

```
select/poll의 문제점:
──────────────────────────────────────────────
1. 매번 전체 fd 목록을 커널에 전달 (유저→커널 복사)
2. 커널이 모든 fd를 순회하며 이벤트 확인
3. 결과를 다시 유저 공간으로 복사
4. 유저 프로그램이 결과를 순회하며 활성 fd 찾기

10,000 fd가 있고 10개만 활성인 경우:
  - select: 10,000개 검사 → 10개 반환 → 10,000번 순회 → 10개 처리
  - 불필요한 작업이 9,990번 발생

epoll의 해결:
──────────────────────────────────────────────
1. epoll_create()로 인스턴스 생성 (1회)
2. epoll_ctl()로 fd 등록/해제 (변경 시에만)
3. epoll_wait()는 활성 fd만 반환

10,000 fd가 있고 10개만 활성인 경우:
  - epoll: 10개만 반환 → 10개 처리
  - 커널이 내부 레드블랙 트리로 fd 관리
  - 콜백 기반으로 활성 fd를 별도 리스트에 유지
```

---

## multi_accept

Worker가 한 번의 이벤트 루프 반복에서 여러 연결을 수락할지 여부입니다.

```nginx
multi_accept on;    # 가능한 많은 연결을 한 번에 수락
multi_accept off;   # 한 번에 하나씩 수락 (기본값)
```

- `on`: 새 연결이 폭발적으로 들어올 때 처리 효율 향상
- `use epoll`과 함께 사용 시 효과적
- 단, 특정 Worker에 연결이 집중될 수 있음

### multi_accept 동작 차이

```
multi_accept off:
──────────────────────────────────
이벤트 루프 반복 1:
  epoll_wait() → 3개 연결 대기 중 감지
  accept() → 연결 1개만 수락
  → 나머지 2개는 다음 반복에서 처리

이벤트 루프 반복 2:
  epoll_wait() → 2개 연결 대기 중 감지
  accept() → 연결 1개만 수락

multi_accept on:
──────────────────────────────────
이벤트 루프 반복 1:
  epoll_wait() → 3개 연결 대기 중 감지
  accept() → 연결 3개 모두 수락
  → 한 번의 반복으로 모두 처리 완료
```

---

## accept_mutex

Worker 프로세스들이 새 연결을 받기 위해 경쟁할 때 뮤텍스를 사용할지 여부입니다.

```nginx
accept_mutex on;      # 기본값 (1.11.3 이전)
accept_mutex off;     # 권장 (epoll 사용 시, 1.11.3 이후 기본)
```

- `on`: 한 번에 하나의 Worker만 accept() 호출 -- thundering herd 방지
- `off`: 모든 Worker가 동시에 accept() 대기 -- epoll에서는 불필요

현대 Linux + epoll 환경에서는 `off`가 성능상 유리합니다.

### Thundering Herd 문제 설명

```
Thundering Herd (놀란 무리) 문제:

새 연결 도착 시 (accept_mutex 없이):
──────────────────────────────────────────────

                  새 연결 도착!
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │Worker 0 │   │Worker 1 │   │Worker 2 │
    │ "깨어남"│   │ "깨어남"│   │ "깨어남"│
    │ accept()│   │ accept()│   │ accept()│
    │ 성공!   │   │ 실패    │   │ 실패    │
    └─────────┘   └─────────┘   └─────────┘
         │              │             │
         │         불필요하게      불필요하게
         │         깨어남          깨어남
         ▼
    연결 처리

모든 Worker가 깨어났지만 1개만 성공 → 나머지는 CPU 낭비

accept_mutex on:
──────────────────────────────────────────────

    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │Worker 0 │   │Worker 1 │   │Worker 2 │
    │ 뮤텍스  │   │ 대기    │   │ 대기    │
    │ 획득!   │   │         │   │         │
    │ accept()│   │         │   │         │
    │ 성공    │   │         │   │         │
    └─────────┘   └─────────┘   └─────────┘

한 번에 하나의 Worker만 accept() → 불필요한 깨어남 없음
하지만 뮤텍스 경합 오버헤드 발생
```

### 현대 Linux에서 accept_mutex가 불필요한 이유

Linux 커널 4.5 이상에서는 `EPOLLEXCLUSIVE` 플래그를 지원합니다. 이 플래그가 설정되면 커널이 자체적으로 하나의 프로세스만 깨우므로 thundering herd 문제가 커널 수준에서 해결됩니다.

```
Linux 4.5+ 커널 + epoll + accept_mutex off:
- 커널이 EPOLLEXCLUSIVE로 1개 Worker만 깨움
- 유저 공간 뮤텍스 오버헤드 없음
- 최적의 성능

Linux 4.5 미만 커널:
- accept_mutex on 고려
- 또는 reuseport 사용 (아래 참조)
```

---

## accept_mutex_delay

`accept_mutex on` 상태에서, 뮤텍스 획득 재시도 간격입니다.

```nginx
accept_mutex_delay 500ms;    # 기본값
accept_mutex_delay 100ms;    # 빠른 재시도
```

뮤텍스를 획득하지 못한 Worker는 이 시간만큼 대기 후 다시 시도합니다.

---

## reuseport (SO_REUSEPORT)

커널 수준에서 각 Worker에 별도의 listen 소켓을 할당합니다.

```nginx
server {
    listen 80 reuseport;    # 각 Worker가 독립 소켓으로 accept
    server_name example.com;
}
```

### reuseport의 동작 원리

```
reuseport 미사용 (기본):
──────────────────────────────────────────

    listen 소켓 1개 (공유)
         │
    ┌────┼────┐
    ▼    ▼    ▼
  W0   W1   W2    ← 모든 Worker가 같은 소켓에서 accept() 경쟁

reuseport 사용:
──────────────────────────────────────────

  소켓0  소켓1  소켓2    ← Worker별 독립 소켓
    │      │      │
    ▼      ▼      ▼
   W0     W1     W2      ← 각 Worker가 자기 소켓에서만 accept()

커널이 새 연결을 소켓들에 분배 (해시 기반)
→ 잠금 경합 완전 제거
→ 연결 수락 처리량 2~3배 향상 가능
```

### reuseport 사용 시기

```
reuseport가 효과적인 경우:
- 초당 수만 건 이상의 새 연결이 발생하는 서버
- 짧은 연결(HTTP/1.0, 비 keepalive)이 많은 환경
- Worker 간 불균등한 부하 분배 문제가 있을 때

reuseport가 불필요한 경우:
- keepalive 연결이 대부분인 환경 (연결 수립이 드물면 효과 미미)
- Worker 수가 적은 서버 (2~4개)
- 트래픽이 적은 서버

주의사항:
- Linux 3.9 이상 필요
- reload 시 일시적 연결 끊김 가능 (소켓 재생성)
- Worker별 연결 분배가 해시 기반이므로 완벽히 균등하지 않을 수 있음
```

---

## worker_aio_requests

`aio` 사용 시 Worker당 최대 비동기 I/O 요청 수입니다.

```nginx
worker_aio_requests 32;    # 기본값
worker_aio_requests 256;   # 디스크 I/O 집약 서버
```

---

## debug_connection

특정 클라이언트 IP에 대해서만 디버그 수준 로그를 기록합니다.

```nginx
events {
    debug_connection 192.168.1.100;
    debug_connection 10.0.0.0/24;
    worker_connections 1024;
}
```

운영 환경에서 전체 debug 로그를 켜면 성능에 큰 영향을 줍니다. `debug_connection`을 사용하면 특정 클라이언트의 요청만 상세하게 추적할 수 있습니다.

```bash
# 사전 조건: --with-debug 컴파일 옵션 필요
nginx -V 2>&1 | grep -- '--with-debug'

# error_log에 debug 레벨 설정도 필요
# error_log /var/log/nginx/error.log debug;
```

디버그 로그에서 확인할 수 있는 정보:
- 연결 수립/종료 과정
- 요청 헤더 파싱 과정
- location 매칭 과정
- upstream 연결 과정
- 응답 생성 과정

---

## 연결 수명 주기 (Connection Lifecycle)

```
1. 연결 수립
   ─────────────────────────────────────
   클라이언트 → TCP SYN
   Nginx     → TCP SYN-ACK
   클라이언트 → TCP ACK
   Worker    → accept() 호출, fd 할당
   Worker    → epoll_ctl(ADD) 로 fd 등록

2. 요청 수신
   ─────────────────────────────────────
   epoll_wait() → 읽기 이벤트 감지
   Worker → read() 로 HTTP 요청 헤더 읽기
   Worker → 요청 파싱 (method, URI, headers)
   Worker → server/location 매칭

3. 요청 처리
   ─────────────────────────────────────
   [정적 파일]
     Worker → open() + read() 또는 sendfile()
   [프록시]
     Worker → 백엔드 connect() + write() + read()
     Worker → epoll_ctl(ADD) 백엔드 fd도 등록

4. 응답 전송
   ─────────────────────────────────────
   Worker → write() 로 HTTP 응답 전송
   (큰 응답은 여러 이벤트 루프 반복에 걸쳐 전송)

5. 연결 유지 또는 종료
   ─────────────────────────────────────
   [keepalive]
     Worker → 타이머 설정 (keepalive_timeout)
     Worker → 다음 요청 대기 (2번으로 돌아감)
   [종료]
     Worker → close() 또는 shutdown()
     Worker → epoll_ctl(DEL) 로 fd 해제
     Worker → fd 반환

6. 타임아웃
   ─────────────────────────────────────
   keepalive_timeout 만료 → Worker가 연결 종료
   client_body_timeout 만료 → 408 Request Timeout
   proxy_read_timeout 만료 → 504 Gateway Timeout
```

---

## 실전 용량 계획 (Capacity Planning)

### 1단계: 현재 트래픽 파악

```bash
# 현재 동시 연결 수 확인 (stub_status 모듈 필요)
curl http://localhost/nginx_status
# Active connections: 291
# server accepts handled requests
#  16630948 16630948 31070465
# Reading: 6 Writing: 179 Waiting: 106

# Reading: 요청 헤더 읽는 중인 연결
# Writing: 응답 전송 중인 연결
# Waiting: keepalive 유휴 연결

# 실시간 모니터링
watch -n 1 'curl -s http://localhost/nginx_status'
```

### 2단계: OS 수준 확인

```bash
# 1. CPU 코어 수 확인
nproc

# 2. 현재 파일 디스크립터 한계
ulimit -n

# 3. OS 파일 디스크립터 최대값
cat /proc/sys/fs/file-max

# 4. 현재 열린 파일 수
cat /proc/sys/fs/file-nr
# (사용 중 fd  /  할당되었지만 미사용  /  최대값)

# 5. TIME_WAIT 소켓 수 확인
ss -s | grep TIME-WAIT

# 6. 네트워크 버퍼 크기
sysctl net.core.somaxconn
sysctl net.core.netdev_max_backlog

# 7. 포트 범위 (프록시 시 중요)
sysctl net.ipv4.ip_local_port_range
# 기본: 32768 60999 (약 28,000개 포트)
```

### 3단계: 설정 계산

```
입력값:
  - 예상 최대 동시 연결: 20,000
  - 서버 역할: 리버스 프록시
  - CPU 코어 수: 8

계산:

1. worker_processes = 8 (코어 수)

2. worker_connections 계산:
   필요 연결 수 = 20,000 x 2 (프록시) = 40,000
   worker당 = 40,000 / 8 = 5,000
   안전 마진 = 5,000 x 1.5 = 7,500
   → worker_connections 8192;

3. worker_rlimit_nofile 계산:
   = worker_connections x 2 + 여유분
   = 8192 x 2 + 256
   → worker_rlimit_nofile 16384; (또는 넉넉하게 65535)

4. OS 설정:
   somaxconn = 65535 (listen backlog)
   file-max = worker_rlimit_nofile x worker_processes x 2
            = 65535 x 8 x 2 = 1,048,560
   ip_local_port_range = "1024 65535" (약 64,000 포트)
```

### 4단계: OS 커널 파라미터 튜닝

```bash
# /etc/sysctl.conf 또는 /etc/sysctl.d/nginx.conf

# listen 소켓 백로그 크기
net.core.somaxconn = 65535

# 네트워크 수신 큐 크기
net.core.netdev_max_backlog = 65535

# TIME_WAIT 소켓 재사용
net.ipv4.tcp_tw_reuse = 1

# 로컬 포트 범위 확장 (프록시 시 중요)
net.ipv4.ip_local_port_range = 1024 65535

# TCP keepalive 설정
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# SYN 백로그
net.ipv4.tcp_max_syn_backlog = 65535

# 최대 파일 디스크립터
fs.file-max = 1048576

# 적용
sysctl -p
```

---

## 실운영 권장 events 설정

```nginx
events {
    worker_connections 4096;
    use epoll;              # Linux에서 자동이지만 명시 가능
    multi_accept on;
    accept_mutex off;
}
```

### 서버 역할별 권장 설정

| 설정 | 정적 파일 서버 | 리버스 프록시 | WebSocket 서버 | API Gateway |
|------|--------------|-------------|---------------|-------------|
| worker_connections | 4096 | 8192 | 16384 | 8192 |
| multi_accept | on | on | on | on |
| accept_mutex | off | off | off | off |
| reuseport | 불필요 | 고트래픽 시 | 불필요 | 고트래픽 시 |
| worker_aio_requests | 256 | 32 | 32 | 32 |

### 전체 동시 연결 수 튜닝 체크리스트

```bash
# 1. CPU 코어 수 확인
nproc

# 2. 현재 파일 디스크립터 한계
ulimit -n

# 3. OS 파일 디스크립터 최대값
cat /proc/sys/fs/file-max

# 4. 현재 nginx 연결 수 확인 (stub_status 모듈 필요)
curl http://localhost/nginx_status

# 5. TIME_WAIT 소켓 수 확인
ss -s | grep TIME-WAIT

# 6. somaxconn 확인
sysctl net.core.somaxconn

# 7. 부하 테스트
wrk -t4 -c1000 -d30s http://localhost/
```
