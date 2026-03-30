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
4. **소켓 바인딩**: 1024 미만 포트는 root 권한 필요 → Master가 바인딩 후 Worker에 전달
5. **무중단 업그레이드**: 새 Master 실행 → 기존 Master와 공존 → 기존 Worker 점진적 종료

### Worker 프로세스의 역할

1. 실제 요청 처리
2. 이벤트 루프로 수천 개 연결 동시 처리
3. 설정에서 지정한 user 권한으로 실행 (root 아님)
4. 각 Worker는 독립적 → 한 Worker 크래시가 전체에 영향 없음

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

### epoll (Linux) 동작 원리

```
1. Worker가 epoll_create()로 epoll 인스턴스 생성
2. 새 연결 수신 시 epoll_ctl()로 소켓 fd를 관심 목록에 등록
3. epoll_wait()로 이벤트 발생 대기 (블로킹 없음)
4. 이벤트 발생(데이터 수신/전송 가능) 시 해당 연결만 처리
5. 처리 완료 후 다시 epoll_wait()
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

| Phase | 설명 |
|-------|------|
| `NGX_HTTP_POST_READ_PHASE` | 요청 헤더 읽기 완료 후 |
| `NGX_HTTP_SERVER_REWRITE_PHASE` | server 블록의 rewrite 처리 |
| `NGX_HTTP_FIND_CONFIG_PHASE` | location 매칭 |
| `NGX_HTTP_REWRITE_PHASE` | location 블록의 rewrite 처리 |
| `NGX_HTTP_POST_REWRITE_PHASE` | rewrite 완료 후 |
| `NGX_HTTP_PREACCESS_PHASE` | 접근 제한 전처리 (limit_req 등) |
| `NGX_HTTP_ACCESS_PHASE` | 접근 제어 (allow/deny, auth) |
| `NGX_HTTP_POST_ACCESS_PHASE` | 접근 제어 후처리 |
| `NGX_HTTP_TRY_FILES_PHASE` | try_files 처리 |
| `NGX_HTTP_CONTENT_PHASE` | 실제 응답 생성 |
| `NGX_HTTP_LOG_PHASE` | 로그 기록 |

---

## 무중단 설정 재로드 (HUP 시그널)

```
1. systemctl reload nginx
   또는 kill -HUP <master_pid>

2. Master가 새 설정 파일 검증
   └─ 오류 시: 기존 설정 유지, 에러 로그 기록

3. 검증 성공 시:
   a. 새 설정으로 새 Worker 프로세스 생성
   b. 기존 Worker에 QUIT 시그널 전송
   c. 기존 Worker는 현재 진행 중인 요청 완료 후 종료
   d. 완전히 새 Worker만 남아 새 설정으로 동작

→ 요청 단절 없음, 연결 유지
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

---

## Cache Manager / Cache Loader 프로세스

proxy_cache 또는 fastcgi_cache 설정 시 추가 프로세스가 생성됩니다.

```bash
ps aux | grep nginx
# nginx: cache manager process  ← 캐시 만료/삭제 담당
# nginx: cache loader process   ← 서버 시작 시 캐시 디스크 → 메모리 로드
```
