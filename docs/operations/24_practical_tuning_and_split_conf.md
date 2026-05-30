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
[ ] nginx -t 통과
[ ] nginx -T로 include 결과 확인
[ ] reload 후 4xx/5xx, 응답 시간, fd, CPU 확인
```
