# 09. Upstream & 로드밸런싱

upstream 블록은 프록시 대상 서버 그룹을 정의합니다.
로드밸런싱, health check, 커넥션 풀링을 설정합니다.

---

## 기본 구조

```nginx
upstream backend {
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
    server 192.168.1.12:8080;
}

server {
    location / {
        proxy_pass http://backend;
    }
}
```

---

## 로드밸런싱 알고리즘

### 1. Round Robin (기본값)

순서대로 순환하며 분배합니다.

```nginx
upstream backend {
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
    server 192.168.1.12:8080;
}
```

### 2. Weight (가중치)

서버별 처리 비율을 지정합니다.

```nginx
upstream backend {
    server 192.168.1.10:8080 weight=3;   # 요청의 3/6
    server 192.168.1.11:8080 weight=2;   # 요청의 2/6
    server 192.168.1.12:8080 weight=1;   # 요청의 1/6
}
```

### 3. least_conn (최소 연결)

현재 활성 연결이 가장 적은 서버에 보냅니다.

```nginx
upstream backend {
    least_conn;
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
}
```

처리 시간이 균일하지 않은 서비스에 적합합니다.

### 4. ip_hash (IP 해시)

클라이언트 IP를 해시하여 항상 같은 서버로 보냅니다.
세션 고정(session affinity/sticky session)에 활용합니다.

```nginx
upstream backend {
    ip_hash;
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
    server 192.168.1.12:8080 down;    # 유지보수 중 (ip_hash 계산에서 제외)
}
```

### 5. hash (커스텀 해시, nginx Plus 포함 오픈소스)

임의 키(URI, 헤더 등)를 기준으로 해시합니다.

```nginx
upstream backend {
    hash $request_uri consistent;
    # consistent: Ketama 일관성 해시 (서버 추가/제거 시 재분배 최소화)
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
}

# 쿠키 기반 sticky
upstream backend {
    hash $cookie_SESSIONID;
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
}
```

### 6. random (nginx 1.15.1+)

무작위로 서버를 선택합니다.

```nginx
upstream backend {
    random two least_conn;
    # 무작위로 2개 선택 후 그 중 연결 수 적은 쪽 선택
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
    server 192.168.1.12:8080;
}
```

---

## server 파라미터

```nginx
upstream backend {
    server 192.168.1.10:8080 weight=5;
    # weight=숫자    가중치 (기본 1)

    server 192.168.1.11:8080 max_fails=3 fail_timeout=30s;
    # max_fails=숫자     실패 허용 횟수 (기본 1, 0이면 비활성화)
    # fail_timeout=시간  실패 카운트 시간 및 서버 비활성화 유지 시간 (기본 10s)

    server 192.168.1.12:8080 backup;
    # backup: 주 서버가 모두 다운될 때만 사용하는 백업 서버

    server 192.168.1.13:8080 down;
    # down: 일시적으로 비활성화 (ip_hash에서 유용)

    server unix:/run/app.sock;
    # Unix Domain Socket 사용
}
```

---

## keepalive (upstream 연결 재사용)

upstream 서버와의 연결을 풀링하여 재사용합니다.
매 요청마다 TCP 연결을 맺지 않아 성능이 크게 향상됩니다.

```nginx
upstream backend {
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;

    keepalive 32;          # Worker당 유지할 유휴 연결 수
    keepalive_requests 100;  # 하나의 keepalive 연결로 처리할 최대 요청 수
    keepalive_timeout 60s;   # 유휴 연결 유지 시간
}

# proxy 설정에서 HTTP/1.1 사용 (keepalive 필수)
location / {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";    # Connection: keep-alive 제거 필요
}
```

---

## zone (공유 메모리, nginx Plus or upstream_check)

오픈소스 nginx에서는 기본 health check 기능이 제한적입니다.

```nginx
upstream backend {
    zone backend 64k;    # 모든 Worker가 공유하는 상태 정보

    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
}
```

---

## passive health check (오픈소스 nginx)

실패 감지 기반 자동 제외:

```nginx
upstream backend {
    server 192.168.1.10:8080 max_fails=3 fail_timeout=30s;
    server 192.168.1.11:8080 max_fails=3 fail_timeout=30s;
}
```

동작 방식:
- `fail_timeout` 시간 동안 `max_fails` 횟수 이상 실패 → 서버를 `fail_timeout` 동안 제외
- 제외 기간 후 자동으로 다시 포함

---

## proxy_next_upstream

요청 실패 시 다음 서버로 자동 재시도합니다.

```nginx
location / {
    proxy_pass http://backend;
    proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
    proxy_next_upstream_tries 3;       # 최대 재시도 횟수
    proxy_next_upstream_timeout 10s;   # 재시도 총 제한 시간
}
```

재시도 가능한 조건:
- `error`: 연결 오류
- `timeout`: 타임아웃
- `invalid_header`: 잘못된 응답 헤더
- `http_500`, `http_502`, `http_503`, `http_504`: HTTP 오류 코드
- `non_idempotent`: POST 등 비멱등성 메서드도 재시도 (주의)

---

## resolver (도메인 기반 upstream)

```nginx
resolver 8.8.8.8 8.8.4.4 valid=300s;
resolver_timeout 5s;

upstream backend {
    server api.example.com:8080;    # DNS 조회 필요
}
```

또는 `proxy_pass`에 변수를 사용할 때:

```nginx
server {
    resolver 8.8.8.8;

    location / {
        set $backend "api.example.com";
        proxy_pass http://$backend:8080;
        # 변수 사용 시 nginx가 런타임에 DNS 조회
    }
}
```

---

## 실전 구성 예시: Blue/Green 배포

```nginx
upstream production {
    server 192.168.1.10:8080;    # Blue 환경
}

upstream canary {
    server 192.168.1.20:8080 weight=1;   # 새 버전 10%
    server 192.168.1.10:8080 weight=9;   # 기존 버전 90%
}

map $http_x_canary $upstream_pool {
    "1"     canary;
    default production;
}

server {
    location / {
        proxy_pass http://$upstream_pool;
    }
}
```
