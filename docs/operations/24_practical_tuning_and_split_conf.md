# 24. 실전 성능 최적화와 conf 파일 분리

---

## 핵심 요약

Nginx 성능 최적화는 "설정값을 크게 키우는 일"이 아니라, 병목 위치를 확인하고 그 위치에 맞는 설정을 조정하는 일입니다.
Reverse proxy 기준으로는 아래 순서가 가장 실용적입니다.

```text
1. worker와 fd 한계 확인
2. 클라이언트 keepalive와 timeout 정리
3. upstream keepalive로 백엔드 TCP 재연결 비용 감소
4. proxy buffer로 느린 클라이언트와 백엔드 연결 분리
5. 정적 파일, gzip, cache, access log I/O 최적화
6. nginx -t, nginx -T, 부하 테스트로 변경 검증
```

conf 파일 분리는 context 기준으로 해야 합니다.
`worker_processes`, `events`, `http`, `server`, `location`, `upstream`은 들어갈 수 있는 위치가 다르기 때문입니다.

---

## 성능 최적화 기본값 예시

아래 설정은 API gateway 또는 reverse proxy 역할을 하는 서버의 출발점으로 쓸 수 있습니다.
운영에서는 CPU, 메모리, upstream 처리 시간, 연결 수를 보고 값을 조정해야 합니다.

```nginx
# /etc/nginx/nginx.conf
user nginx;
worker_processes auto;
worker_rlimit_nofile 65536;

error_log /var/log/nginx/error.log warn;
pid /run/nginx.pid;

events {
    worker_connections 4096;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'rt=$request_time uct=$upstream_connect_time '
                    'uht=$upstream_header_time urt=$upstream_response_time';

    access_log /var/log/nginx/access.log main buffer=64k flush=5s;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    keepalive_timeout 65s;
    keepalive_requests 10000;

    client_header_timeout 10s;
    client_body_timeout 10s;
    send_timeout 30s;
    reset_timedout_connection on;

    gzip on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_vary on;
    gzip_types
        text/plain
        text/css
        application/json
        application/javascript
        application/xml
        image/svg+xml;

    server_tokens off;

    include /etc/nginx/upstream.d/*.conf;
    include /etc/nginx/conf.d/*.conf;
}
```

### worker와 fd 계산

```text
최대 연결 수 = worker_processes * worker_connections

Reverse proxy 필요 fd 대략값:
worker_processes * worker_connections * 2
```

클라이언트 연결 하나와 upstream 연결 하나를 동시에 잡을 수 있으므로 `* 2`로 계산합니다.

예를 들어 4코어 서버에서 `worker_connections 4096`이면:

```text
4 * 4096 = 16384 연결
16384 * 2 = 32768 fd
```

이 경우 `worker_rlimit_nofile 65536`과 systemd의 `LimitNOFILE=65536` 정도가 출발점으로 적당합니다.

```ini
# /etc/systemd/system/nginx.service.d/override.conf
[Service]
LimitNOFILE=65536
```

적용:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx
cat /proc/$(cat /run/nginx.pid)/limits | grep "open files"
```

---

## Reverse Proxy 성능 최적화

### 1. upstream keepalive

프록시는 백엔드와 TCP 연결을 새로 맺을 수 있기 때문에, 요청마다 연결을 새로 만들면 비용이 커집니다.
`upstream keepalive`는 worker별로 백엔드 유휴 연결을 재사용하게 해 연결 생성 비용을 줄입니다.

```nginx
# /etc/nginx/upstream.d/api.conf
upstream api_backend {
    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;

    keepalive 100;
    keepalive_requests 10000;
    keepalive_timeout 60s;
}
```

```nginx
# location 내부
proxy_pass http://api_backend;
proxy_http_version 1.1;
proxy_set_header Connection "";
```

주의할 점:

- `keepalive 100`은 전체가 아니라 worker당 유휴 upstream 연결 수입니다.
- `worker_processes 4`이면 최대 400개의 유휴 upstream 연결을 유지할 수 있습니다.
- 백엔드의 connection pool, thread pool, fd 한계를 같이 봐야 합니다.

### 2. proxy timeout

timeout은 전체 서버에 크게 잡기보다 API 성격별로 분리하는 편이 좋습니다.

```nginx
location /api/ {
    proxy_connect_timeout 3s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;
}

location /reports/ {
    proxy_connect_timeout 3s;
    proxy_send_timeout 60s;
    proxy_read_timeout 300s;
}
```

권장 방향:

| 요청 유형 | 설정 방향 |
|----------|----------|
| 일반 API | `proxy_connect_timeout 1~3s`, `proxy_read_timeout 10~30s` |
| 파일 업로드 | `client_body_timeout`, `proxy_send_timeout`을 길게 |
| 리포트/배치 API | 별도 location에서 긴 timeout |
| WebSocket/SSE | `proxy_read_timeout`을 길게, buffering off |

### 3. proxy buffer

버퍼링을 켜면 nginx가 백엔드 응답을 먼저 받고 클라이언트에게 천천히 보낼 수 있습니다.
느린 클라이언트 때문에 백엔드 연결이 오래 점유되는 상황을 줄이는 데 유리합니다.

```nginx
location /api/ {
    proxy_pass http://api_backend;

    proxy_buffering on;
    proxy_buffer_size 8k;
    proxy_buffers 16 16k;
    proxy_busy_buffers_size 64k;
}
```

스트리밍 계열은 버퍼링을 끕니다.

```nginx
location /events/ {
    proxy_pass http://api_backend;
    proxy_buffering off;
    proxy_cache off;
}
```

`proxy_buffers 16 16k`는 요청당 최대 256KB 수준의 버퍼를 쓸 수 있습니다.
동시 upstream 응답이 2,000개면 버퍼만 약 512MB까지 커질 수 있으므로 메모리와 함께 계산해야 합니다.

### 4. 정적 파일

```nginx
location /static/ {
    root /var/www/app;

    sendfile on;
    tcp_nopush on;

    expires 1y;
    add_header Cache-Control "public, immutable";

    access_log off;

    open_file_cache max=10000 inactive=30s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;
}
```

정적 파일은 애플리케이션 서버까지 보내지 않는 것이 가장 큰 최적화입니다.

### 5. access log I/O

트래픽이 많으면 access log 쓰기가 병목이 될 수 있습니다.

```nginx
access_log /var/log/nginx/access.log main buffer=64k flush=5s;
```

헬스 체크나 정적 파일 로그는 줄일 수 있습니다.

```nginx
location = /health {
    access_log off;
    return 200 "OK\n";
}
```

---

## conf 파일 분리 원칙

파일을 나눌 때 가장 중요한 기준은 "어떤 context 안에 포함되는가"입니다.

| 파일 종류 | 들어가는 내용 | include 위치 |
|----------|--------------|--------------|
| `nginx.conf` | main, events, http 기본값 | 최상위 |
| `upstream.d/*.conf` | `upstream` 블록 | `http` 내부 |
| `conf.d/*.conf` | `server` 블록 | `http` 내부 |
| `snippets/*.conf` | 반복 지시어 조각 | 필요한 context 내부 |
| `stream.d/*.conf` | TCP/UDP `server` 블록 | `stream` 내부 |

`server` 블록 파일을 `http` 밖에서 include하면 안 됩니다.
반대로 `worker_processes` 같은 main context 지시어를 `conf.d/site.conf`에 넣어도 안 됩니다.

---

## 권장 디렉토리 구조

작거나 중간 규모의 서비스는 아래 구조가 관리하기 좋습니다.

```text
/etc/nginx/
├── nginx.conf
├── upstream.d/
│   ├── api.conf
│   └── web.conf
├── conf.d/
│   ├── 00-default.conf
│   ├── 10-api.example.com.conf
│   └── 10-www.example.com.conf
└── snippets/
    ├── proxy-headers.conf
    ├── proxy-timeouts.conf
    ├── security-headers.conf
    └── ssl-params.conf
```

파일명 앞 숫자는 include 순서를 명시하기 위한 것입니다.
와일드카드 include는 보통 알파벳순으로 로드되므로, default server나 map처럼 순서가 중요한 파일은 숫자를 붙이는 편이 안전합니다.

---

## 파일별 예시

### 1. 메인 설정

```nginx
# /etc/nginx/nginx.conf
user nginx;
worker_processes auto;
worker_rlimit_nofile 65536;

error_log /var/log/nginx/error.log warn;
pid /run/nginx.pid;

events {
    worker_connections 4096;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'rt=$request_time urt=$upstream_response_time';

    access_log /var/log/nginx/access.log main buffer=64k flush=5s;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    keepalive_timeout 65s;
    keepalive_requests 10000;

    gzip on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/json application/javascript application/xml image/svg+xml;

    include /etc/nginx/upstream.d/*.conf;
    include /etc/nginx/conf.d/*.conf;
}
```

### 2. upstream 분리

```nginx
# /etc/nginx/upstream.d/api.conf
upstream api_backend {
    least_conn;

    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;

    keepalive 100;
}
```

```nginx
# /etc/nginx/upstream.d/web.conf
upstream web_backend {
    server 10.0.2.10:3000 max_fails=3 fail_timeout=10s;
    keepalive 50;
}
```

### 3. snippet 분리

```nginx
# /etc/nginx/snippets/proxy-headers.conf
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Request-ID $request_id;
proxy_set_header Connection "";
```

```nginx
# /etc/nginx/snippets/proxy-timeouts.conf
proxy_connect_timeout 3s;
proxy_send_timeout 30s;
proxy_read_timeout 30s;
```

```nginx
# /etc/nginx/snippets/security-headers.conf
add_header X-Frame-Options SAMEORIGIN always;
add_header X-Content-Type-Options nosniff always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
```

주의: `proxy_set_header`와 `add_header`는 하위 context에서 하나라도 다시 선언하면 상위 선언 묶음이 사라질 수 있습니다.
그래서 공통 헤더는 snippet에 모으고, location마다 필요한 snippet을 명시적으로 include하는 편이 안전합니다.

### 4. API server 블록

```nginx
# /etc/nginx/conf.d/10-api.example.com.conf
server {
    listen 80;
    server_name api.example.com;

    include /etc/nginx/snippets/security-headers.conf;

    location = /health {
        access_log off;
        return 200 "OK\n";
    }

    location /api/ {
        include /etc/nginx/snippets/proxy-headers.conf;
        include /etc/nginx/snippets/proxy-timeouts.conf;

        proxy_buffering on;
        proxy_buffer_size 8k;
        proxy_buffers 16 16k;
        proxy_busy_buffers_size 64k;

        proxy_pass http://api_backend;
    }

    location /events/ {
        include /etc/nginx/snippets/proxy-headers.conf;

        proxy_read_timeout 1h;
        proxy_buffering off;
        proxy_cache off;

        proxy_pass http://api_backend;
    }
}
```

### 5. Web server 블록

```nginx
# /etc/nginx/conf.d/10-www.example.com.conf
server {
    listen 80;
    server_name www.example.com example.com;

    root /var/www/app;
    index index.html;

    include /etc/nginx/snippets/security-headers.conf;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /static/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location /api/ {
        include /etc/nginx/snippets/proxy-headers.conf;
        include /etc/nginx/snippets/proxy-timeouts.conf;
        proxy_pass http://api_backend;
    }
}
```

### 6. default server

```nginx
# /etc/nginx/conf.d/00-default.conf
server {
    listen 80 default_server;
    server_name _;

    access_log off;
    return 444;
}
```

---

## 분리할 때 자주 하는 실수

### 1. upstream보다 server가 먼저 로드됨

아래처럼 `server` 블록에서 `api_backend`를 쓰는데 upstream include가 없거나 순서가 뒤면 실패합니다.

```nginx
http {
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/upstream.d/*.conf;
}
```

권장:

```nginx
http {
    include /etc/nginx/upstream.d/*.conf;
    include /etc/nginx/conf.d/*.conf;
}
```

### 2. snippet을 잘못된 context에 넣음

`upstream` 블록 안에서는 `proxy_set_header`를 쓸 수 없습니다.
`proxy_set_header`는 `http`, `server`, `location` context에서 사용합니다.

```nginx
# 잘못된 예
upstream api_backend {
    server 10.0.1.10:8080;
    proxy_set_header Host $host;
}
```

### 3. location별 proxy_pass 슬래시 차이

```nginx
location /api/ {
    proxy_pass http://api_backend;
    # /api/users -> upstream에도 /api/users
}

location /api/ {
    proxy_pass http://api_backend/;
    # /api/users -> upstream에는 /users
}
```

파일 분리 중 `proxy_pass`를 upstream 이름으로 바꿀 때 경로 치환 방식이 바뀌지 않는지 확인해야 합니다.

### 4. 설정 변경 후 nginx -T 확인 생략

`nginx -t`는 문법만 봅니다.
include된 최종 설정이 의도대로 합쳐졌는지는 `nginx -T`로 확인하는 편이 좋습니다.

```bash
sudo nginx -t
sudo nginx -T | less
sudo systemctl reload nginx
```

---

## 실무 운영형 conf.d 분리 패턴

실무에서는 파일을 많이 나누는 것보다 "변경 책임 단위"가 명확한 구조가 더 중요합니다.
보통 아래 기준으로 나눕니다.

| 디렉터리 | 책임 | 변경 주기 | 소유자 |
|----------|------|-----------|--------|
| `nginx.conf` | worker, events, http 전역 기본값 | 낮음 | 플랫폼/인프라 |
| `upstream.d/` | 백엔드 서버 목록, keepalive, 로드밸런싱 | 중간 | 플랫폼/서비스 |
| `conf.d/` | 도메인별 `server` 블록, routing 정책 | 높음 | 서비스 |
| `snippets/` | 공통 header, timeout, TLS, logging 조각 | 낮음 | 플랫폼 |
| `maps.d/` | `map`, canary, routing variable | 중간 | 플랫폼/서비스 |

운영에서 권장하는 형태는 아래와 같습니다.

```text
/etc/nginx/
├── nginx.conf
├── maps.d/
│   ├── 00-release-map.conf
│   └── 10-maintenance-map.conf
├── upstream.d/
│   ├── 10-api-blue.conf
│   ├── 10-api-green.conf
│   └── 20-admin.conf
├── snippets/
│   ├── proxy-common.conf
│   ├── proxy-timeout-api.conf
│   ├── proxy-timeout-long.conf
│   ├── security-headers.conf
│   └── access-log-main.conf
└── conf.d/
    ├── 00-default.conf
    ├── 10-api.example.com.conf
    ├── 20-admin.example.com.conf
    └── 90-internal-health.conf
```

숫자 prefix는 사람이 읽기 위한 규칙이기도 하지만, include 순서를 고정하는 역할도 합니다.
특히 `map`은 `server`보다 먼저 로드되어야 하므로 `maps.d`를 `conf.d`보다 앞에 include합니다.

```nginx
# /etc/nginx/nginx.conf
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    include /etc/nginx/snippets/access-log-main.conf;

    include /etc/nginx/maps.d/*.conf;
    include /etc/nginx/upstream.d/*.conf;
    include /etc/nginx/conf.d/*.conf;
}
```

`conf.d` 안에 `upstream`이나 `map`을 섞어 넣을 수도 있지만, 서비스가 많아지면 변경 영향 범위가 흐려집니다.
운영에서는 `server` 블록은 `conf.d`, upstream은 `upstream.d`, 변수 분기는 `maps.d`로 분리하는 편이 추적하기 쉽습니다.

---

## nginx.conf는 최대한 얇게 유지

`nginx.conf`는 전체 프로세스와 http 전역 기본값만 담당하게 두는 것이 좋습니다.
서비스별 라우팅, upstream 서버, 도메인 정책을 `nginx.conf`에 계속 추가하면 reload 전 검토가 어려워집니다.

```nginx
# /etc/nginx/nginx.conf
user nginx;
worker_processes auto;
worker_rlimit_nofile 65536;

error_log /var/log/nginx/error.log warn;
pid /run/nginx.pid;

events {
    worker_connections 4096;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    server_tokens off;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    keepalive_timeout 65s;
    keepalive_requests 10000;

    client_header_timeout 10s;
    client_body_timeout 10s;
    send_timeout 30s;
    reset_timedout_connection on;

    include /etc/nginx/snippets/access-log-main.conf;
    include /etc/nginx/maps.d/*.conf;
    include /etc/nginx/upstream.d/*.conf;
    include /etc/nginx/conf.d/*.conf;
}
```

`nginx.conf`에 두기 좋은 것:

- `user`, `worker_processes`, `worker_rlimit_nofile`
- `events`
- `log_format`
- `sendfile`, `tcp_nopush`, `tcp_nodelay`
- 공통 timeout의 기본값
- include 순서

`nginx.conf`에 계속 넣지 않는 것이 좋은 것:

- 특정 서비스의 `server_name`
- 특정 API의 `location`
- 특정 upstream 서버 IP
- 임시 canary 비율
- 장애 대응을 위한 임시 차단 정책

---

## 서비스별 conf.d 파일 예시

서비스 하나가 여러 API path를 갖는 경우에도 `server` 블록 하나를 기준으로 파일을 나누는 편이 일반적입니다.
예를 들어 `api.example.com`은 `conf.d/10-api.example.com.conf` 하나가 소유합니다.

```nginx
# /etc/nginx/conf.d/10-api.example.com.conf
server {
    listen 80;
    server_name api.example.com;

    include /etc/nginx/snippets/security-headers.conf;

    location = /health {
        access_log off;
        return 200 "ok\n";
    }

    location /v1/orders/ {
        include /etc/nginx/snippets/proxy-common.conf;
        include /etc/nginx/snippets/proxy-timeout-api.conf;
        proxy_pass http://orders_backend;
    }

    location /v1/payments/ {
        include /etc/nginx/snippets/proxy-common.conf;
        include /etc/nginx/snippets/proxy-timeout-api.conf;

        proxy_next_upstream off;
        proxy_pass http://payments_backend;
    }

    location /v1/reports/ {
        include /etc/nginx/snippets/proxy-common.conf;
        include /etc/nginx/snippets/proxy-timeout-long.conf;
        proxy_pass http://reports_backend;
    }
}
```

이렇게 나누면 `api.example.com`의 변경은 한 파일에서 확인할 수 있고, 백엔드 서버 목록은 `upstream.d`에서 따로 관리할 수 있습니다.

```nginx
# /etc/nginx/upstream.d/10-orders.conf
upstream orders_backend {
    least_conn;
    zone orders_backend 64k;

    server 10.0.10.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.10.12:8080 max_fails=3 fail_timeout=10s;

    keepalive 100;
}
```

```nginx
# /etc/nginx/upstream.d/10-payments.conf
upstream payments_backend {
    zone payments_backend 64k;

    server 10.0.20.11:8080 max_fails=2 fail_timeout=5s;
    server 10.0.20.12:8080 max_fails=2 fail_timeout=5s;

    keepalive 50;
}
```

결제나 주문처럼 중복 요청이 위험한 API는 `proxy_next_upstream off`처럼 서비스 성격에 맞게 location에서 명시합니다.
반대로 조회 API는 timeout, 502, 503 정도에 한해 재시도를 허용할 수 있습니다.

---

## snippet은 공통 설정을 숨기는 곳이 아니다

snippet은 반복을 줄이는 데 유용하지만, 너무 많은 설정을 숨기면 실제 location 동작을 파악하기 어려워집니다.
실무에서는 아래처럼 역할이 명확한 작은 파일로 둡니다.

```nginx
# /etc/nginx/snippets/proxy-common.conf
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Request-ID $request_id;
proxy_set_header Connection "";
```

```nginx
# /etc/nginx/snippets/proxy-timeout-api.conf
proxy_connect_timeout 3s;
proxy_send_timeout 30s;
proxy_read_timeout 30s;
```

```nginx
# /etc/nginx/snippets/proxy-timeout-long.conf
proxy_connect_timeout 3s;
proxy_send_timeout 60s;
proxy_read_timeout 300s;
```

```nginx
# /etc/nginx/snippets/security-headers.conf
add_header X-Frame-Options SAMEORIGIN always;
add_header X-Content-Type-Options nosniff always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
```

주의할 점:

- `include snippets/proxy-common.conf`만 보고도 어떤 헤더가 들어가는지 팀이 알고 있어야 합니다.
- snippet에 `proxy_pass`는 넣지 않는 편이 좋습니다. 실제 라우팅 대상이 숨겨집니다.
- snippet에 `location`이나 `server` 블록을 넣으면 include 위치가 제한되어 실수가 늘어납니다.
- 보안 헤더는 `add_header ... always`를 붙여 4xx/5xx에도 적용되게 합니다.

---

## map으로 환경별/배포별 분기 관리

canary, maintenance, 특정 header 기반 라우팅은 `conf.d` 안에 직접 흩뿌리지 말고 `maps.d`로 분리합니다.

```nginx
# /etc/nginx/maps.d/00-release-map.conf
split_clients "${remote_addr}${http_user_agent}" $release_group {
    5%      green;
    *       blue;
}

map $release_group $api_upstream {
    green   api_green_backend;
    default api_blue_backend;
}
```

```nginx
# /etc/nginx/conf.d/10-api.example.com.conf
server {
    listen 80;
    server_name api.example.com;

    location / {
        include /etc/nginx/snippets/proxy-common.conf;
        include /etc/nginx/snippets/proxy-timeout-api.conf;

        add_header X-Release-Group $release_group always;
        proxy_pass http://$api_upstream;
    }
}
```

이 구조의 장점:

- canary 비율 변경은 `maps.d/00-release-map.conf`만 보면 됩니다.
- 서비스 라우팅 파일에는 `proxy_pass http://$api_upstream`만 남습니다.
- rollback은 `green` 비율을 0%로 낮추고 reload하면 됩니다.

---

## 환경별 설정 관리 방식

운영에서는 보통 `dev`, `stage`, `prod`가 같은 파일 구조를 쓰고 값만 달라집니다.
서버에 직접 편집하는 방식보다 Git에서 환경별 디렉터리를 관리하고 배포 시 `/etc/nginx`에 반영하는 방식이 추적하기 쉽습니다.

```text
nginx-config/
├── common/
│   ├── nginx.conf
│   └── snippets/
├── envs/
│   ├── dev/
│   │   ├── upstream.d/
│   │   └── conf.d/
│   ├── stage/
│   │   ├── upstream.d/
│   │   └── conf.d/
│   └── prod/
│       ├── maps.d/
│       ├── upstream.d/
│       └── conf.d/
└── hosts/
    └── nginx-edge-a/
        └── conf.d/90-local-health.conf
```

배포 시에는 `common -> envs/prod -> hosts/<node>` 순서로 합쳐서 배포합니다.
이 방식은 `ops/bulk-install/config-bundle.sample/`에서 사용하는 overlay 방식과도 맞습니다.

실제 서버에는 최종 결과물만 둡니다.

```text
/etc/nginx/
├── nginx.conf
├── maps.d/
├── upstream.d/
├── snippets/
└── conf.d/
```

서버에 직접 남기지 않는 것이 좋은 것:

- `conf.d/app.conf.bak`
- `conf.d/app.conf.20260101`
- `conf.d/app.conf.disabled`
- 사용하지 않는 오래된 upstream 파일

nginx는 `*.conf`에 걸리는 파일을 모두 읽습니다.
백업 파일이 `.conf`로 끝나면 의도치 않게 설정이 같이 로드될 수 있습니다.

---

## 변경 반영과 롤백 절차

운영에서 설정을 반영할 때는 파일 복사보다 검증 순서가 더 중요합니다.

```bash
# 1. 새 설정을 임시 디렉터리에 구성
sudo rm -rf /tmp/nginx-next
sudo mkdir -p /tmp/nginx-next
sudo cp -a /etc/nginx/. /tmp/nginx-next/

# 2. 변경 파일 반영
sudo cp 10-api.example.com.conf /tmp/nginx-next/conf.d/

# 3. 임시 디렉터리 기준으로 문법 검사
sudo nginx -t -p /tmp/nginx-next/ -c nginx.conf

# 4. 현재 설정 백업
sudo cp -a /etc/nginx "/etc/nginx.backup.$(date +%Y%m%d%H%M%S)"

# 5. 실제 경로 반영
sudo cp -a /tmp/nginx-next/. /etc/nginx/

# 6. 실제 경로에서 다시 검사 후 reload
sudo nginx -t
sudo systemctl reload nginx
```

롤백은 백업 디렉터리를 다시 복사하고 reload합니다.

```bash
sudo rm -rf /etc/nginx
sudo cp -a /etc/nginx.backup.20260615123000 /etc/nginx
sudo nginx -t
sudo systemctl reload nginx
```

reload 후 확인:

```bash
sudo nginx -T | grep -n "server_name api.example.com" -A80
curl -I http://api.example.com/health
tail -f /var/log/nginx/error.log
```

`reload`는 기존 worker를 바로 죽이지 않고 새 worker를 띄운 뒤 기존 연결을 정리합니다.
그래도 설정 오류나 upstream 오타는 서비스 장애로 이어질 수 있으므로 `nginx -t`, `nginx -T`, health check를 항상 묶어서 봅니다.

---

## 검증 절차

운영 반영 전 최소 절차:

```bash
# 문법 검사
sudo nginx -t

# include까지 합쳐진 최종 설정 확인
sudo nginx -T | grep -n "upstream api_backend" -A10
sudo nginx -T | grep -n "server_name api.example.com" -A40

# reload
sudo systemctl reload nginx

# 요청 확인
curl -I http://api.example.com/health
curl -w "total=%{time_total}\n" -o /dev/null -s http://api.example.com/api/users
```

부하 테스트:

```bash
wrk -t4 -c100 -d30s http://api.example.com/api/users
```

같이 봐야 하는 지표:

- nginx worker CPU
- fd 사용량
- 499, 502, 504 비율
- p95/p99 응답 시간
- `$upstream_response_time`
- 백엔드 connection 수
- access log와 proxy temp file로 인한 디스크 I/O

---

## 운영 체크리스트

```text
[ ] worker_processes auto 또는 CPU 코어 수에 맞게 설정
[ ] worker_connections와 LimitNOFILE 계산 완료
[ ] upstream keepalive 설정
[ ] proxy_http_version 1.1, Connection "" 설정
[ ] 일반 API와 장시간 API timeout 분리
[ ] 스트리밍/SSE/WebSocket은 proxy_buffering off 또는 별도 설정
[ ] 정적 파일은 nginx에서 직접 처리
[ ] 헬스 체크와 정적 파일 access log 제외
[ ] nginx.conf, maps.d, upstream.d, conf.d, snippets 책임 분리
[ ] conf.d에는 server 블록 중심으로 구성
[ ] 백업 파일이 *.conf 패턴에 걸리지 않는지 확인
[ ] nginx -t 통과
[ ] nginx -T로 include 결과 확인
[ ] reload 후 4xx/5xx, 응답 시간, fd, CPU 확인
```
