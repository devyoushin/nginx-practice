# 16. Rate Limiting (요청 속도/연결 제한)

---

## limit_req (요청 속도 제한)

### 존 정의 (http 블록)

```nginx
http {
    # 클라이언트 IP 기준
    limit_req_zone $binary_remote_addr zone=req_ip:10m rate=10r/s;
    # zone 이름, 메모리 크기, 초당 요청 수

    # 분당 요청 수
    limit_req_zone $binary_remote_addr zone=req_login:10m rate=5r/m;

    # 서버 전체 기준
    limit_req_zone $server_name zone=per_server:10m rate=1000r/s;

    # 사용자별 (로그인 토큰 기반)
    limit_req_zone $http_authorization zone=per_user:10m rate=30r/m;
}
```

`$binary_remote_addr` vs `$remote_addr`:
- `$binary_remote_addr`: 4바이트(IPv4)/16바이트(IPv6) → 메모리 효율적
- `$remote_addr`: 문자열 → 메모리 더 사용

### location에서 적용

```nginx
location /api/ {
    limit_req zone=req_ip burst=20 nodelay;
    # zone: 사용할 zone 이름
    # burst: 순간 초과 허용 요청 수 (큐 크기)
    # nodelay: burst 초과 요청을 지연 없이 즉시 처리 (후 차단)
    #          없으면 burst 내 요청도 지연시킴

    proxy_pass http://backend;
}

location /login {
    limit_req zone=req_login burst=3 nodelay;
    # 분당 5개 + 순간 3개까지 허용
}
```

### burst와 nodelay 동작 차이

```
rate=10r/s, burst=20 으로 설정 시:

burst 없음:
  초당 10개 초과 시 → 즉시 503

burst=20 (nodelay 없음):
  11~30번째 요청 → 큐에 넣고 100ms씩 지연하여 처리
  31번째 이후 → 503

burst=20 nodelay:
  1~30개 → 즉시 처리 (지연 없음)
  31번째 이후 → 503
  이후 큐가 소진될 때까지 새 요청 차단
```

---

## limit_conn (동시 연결 수 제한)

```nginx
http {
    limit_conn_zone $binary_remote_addr zone=conn_ip:10m;
    limit_conn_zone $server_name zone=conn_server:10m;
}

server {
    limit_conn conn_ip 10;         # IP당 최대 10개 동시 연결
    limit_conn conn_server 1000;   # 서버 전체 최대 1000개 연결

    # 큰 파일 다운로드 속도 제한
    location /downloads/ {
        limit_conn conn_ip 2;       # IP당 동시 2개 다운로드
        limit_rate 500k;            # 연결당 500KB/s
        limit_rate_after 1m;        # 1MB 이후부터 속도 제한 적용
    }
}
```

---

## 응답 속도 제한 (limit_rate)

```nginx
location /download/ {
    limit_rate 1m;            # 1MB/s 제한
    limit_rate_after 10m;     # 처음 10MB는 제한 없이, 이후 제한
}
```

변수로 동적 속도 제한:

```nginx
# 인증된 사용자는 빠르게, 아니면 느리게
map $http_authorization $rate {
    ""      512k;   # 미인증: 512KB/s
    default 0;      # 인증: 무제한
}

location /files/ {
    limit_rate $rate;
}
```

---

## 에러 응답 커스터마이징

```nginx
http {
    limit_req_zone $binary_remote_addr zone=req_ip:10m rate=10r/s;
    limit_req_status 429;          # 기본 503 대신 429 Too Many Requests
    limit_conn_status 429;

    server {
        error_page 429 /rate-limit.json;

        location = /rate-limit.json {
            internal;
            return 429 '{"error":"Too Many Requests","message":"Rate limit exceeded"}';
            add_header Content-Type application/json;
        }
    }
}
```

---

## 로그 레벨 조정

rate limiting 로그는 기본적으로 error 레벨로 기록됩니다.

```nginx
limit_req_log_level warn;    # error(기본), warn, notice, info
limit_conn_log_level warn;
```

---

## 화이트리스트 (특정 IP 제외)

```nginx
http {
    geo $limit {
        default          1;
        127.0.0.1        0;
        10.0.0.0/8       0;    # 내부 네트워크 제외
        192.168.0.0/16   0;
    }

    map $limit $limit_key {
        0 "";                           # 화이트리스트: 빈 키 → zone 적용 안 됨
        1 $binary_remote_addr;          # 그 외: IP 기준 제한
    }

    limit_req_zone $limit_key zone=req_ip:10m rate=10r/s;
}

server {
    location / {
        limit_req zone=req_ip burst=20 nodelay;
    }
}
```

---

## 실전: API 서버 rate limiting 전략

```nginx
http {
    # 로그인 엔드포인트 (엄격)
    limit_req_zone $binary_remote_addr zone=login:10m     rate=5r/m;
    # 일반 API (여유)
    limit_req_zone $binary_remote_addr zone=api:10m       rate=30r/s;
    # 검색 API (중간)
    limit_req_zone $binary_remote_addr zone=search:10m    rate=10r/s;
    # 연결 수
    limit_conn_zone $binary_remote_addr zone=conn:10m;

    limit_req_status 429;
    limit_conn_status 429;
}

server {
    listen 443 ssl;
    server_name api.example.com;

    limit_conn conn 50;    # IP당 최대 50개 동시 연결

    location /auth/login {
        limit_req zone=login burst=3 nodelay;
        proxy_pass http://auth-backend;
    }

    location /search {
        limit_req zone=search burst=5 nodelay;
        proxy_pass http://search-backend;
    }

    location /api/ {
        limit_req zone=api burst=50 nodelay;
        proxy_pass http://api-backend;
    }
}
```
