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
전체 최대 동시 연결 = worker_processes × worker_connections

예: worker_processes=4, worker_connections=4096
→ 최대 16,384 동시 연결
```

**주의**: reverse proxy 사용 시 하나의 클라이언트 요청이 백엔드 연결도 필요하므로
실제 최대 클라이언트 수 = (worker_processes × worker_connections) / 2

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

### epoll이 select보다 빠른 이유

```
select/poll:
- O(N): N개의 fd를 매번 전부 검사
- fd 최대 수 제한 (FD_SETSIZE=1024)

epoll:
- O(1): 이벤트 발생한 fd만 반환
- fd 수 제한 없음
- 레벨 트리거(LT) 및 엣지 트리거(ET) 지원
```

---

## multi_accept

Worker가 한 번의 accept() 호출로 여러 연결을 수락할지 여부입니다.

```nginx
multi_accept on;    # 가능한 많은 연결을 한 번에 수락
multi_accept off;   # 한 번에 하나씩 수락 (기본값)
```

- `on`: 새 연결이 폭발적으로 들어올 때 처리 효율 향상
- `use epoll`과 함께 사용 시 효과적
- 단, 첫 연결 처리 지연이 있을 수 있음

---

## accept_mutex

Worker 프로세스들이 새 연결을 받기 위해 경쟁할 때 뮤텍스를 사용할지 여부입니다.

```nginx
accept_mutex on;      # 기본값 (1.11.3 이전)
accept_mutex off;     # 권장 (epoll 사용 시, 1.11.3 이후 기본)
```

- `on`: 한 번에 하나의 Worker만 accept() 호출 → thundering herd 방지
- `off`: 모든 Worker가 동시에 accept() 대기 → epoll에서는 불필요

현대 Linux + epoll 환경에서는 `off`가 성능상 유리합니다.

---

## accept_mutex_delay

`accept_mutex on` 상태에서, 뮤텍스 획득 재시도 간격입니다.

```nginx
accept_mutex_delay 500ms;    # 기본값
accept_mutex_delay 100ms;    # 빠른 재시도
```

---

## worker_aio_requests

`aio` 사용 시 Worker당 최대 비동기 I/O 요청 수입니다.

```nginx
worker_aio_requests 32;    # 기본값
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
```
