# 27. 자주 쓰는 Nginx 모듈 정리

Nginx는 기능이 모듈 단위로 나뉜다. 같은 `nginx.conf`를 쓰더라도 빌드 시 포함된 모듈, 동적 모듈 로드 여부, 패키지 배포판에 따라 사용할 수 있는 directive가 달라진다.

이 문서는 실무에서 자주 쓰는 모듈을 목적별로 정리하고, 설정 파일을 읽을 때 “이 directive가 어느 모듈의 기능인지” 빠르게 판단하기 위한 기준을 제공한다.

---

## 1. 모듈 확인 방법

현재 설치된 Nginx가 어떤 모듈을 포함하는지 먼저 확인한다.

```bash
nginx -V 2>&1
```

보기 쉽게 옵션만 줄 단위로 확인한다.

```bash
nginx -V 2>&1 | tr ' ' '\n' | grep -E '^--with-|^--add-|^--modules-path|^--prefix|^--conf-path'
```

예시 출력:

```text
--with-http_ssl_module
--with-http_v2_module
--with-http_gzip_static_module
--with-http_stub_status_module
--with-stream
--with-stream_ssl_module
--with-stream_ssl_preread_module
--modules-path=/usr/lib64/nginx/modules
```

해석 기준:

| 표시 | 의미 |
|---|---|
| `--with-http_ssl_module` | 빌드 시 정적 또는 내장 모듈로 포함 |
| `--with-stream=dynamic` | 동적 모듈로 빌드됨. `load_module` 필요 |
| `--add-module=...` | 서드파티 모듈을 소스 빌드에 추가 |
| `--modules-path=...` | 동적 모듈 `.so` 파일 위치 |

동적 모듈은 `nginx.conf` 최상단 main context에서 로드한다.

```nginx
load_module modules/ngx_stream_module.so;

user nginx;
worker_processes auto;
```

`load_module`은 `events`, `http`, `server` 안에 둘 수 없다. 반드시 최상단에 둔다.

---

## 2. 핵심 모듈 분류

### 2.1 Core / Event 계열

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| Core functionality | `worker_processes`, `error_log`, `include`, `load_module`, `worker_rlimit_nofile` | 프로세스, 로그, include, 동적 모듈 로드 |
| Events | `events`, `worker_connections`, `use`, `multi_accept` | connection accept와 event loop 설정 |

기본 골격:

```nginx
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /run/nginx.pid;

events {
    worker_connections 4096;
    multi_accept off;
}
```

운영에서 가장 자주 보는 값은 `worker_processes`와 `worker_connections`다. 이론상 최대 동시 연결 수는 대략 `worker_processes × worker_connections`지만, 실제 한계는 file descriptor, upstream 연결, keepalive, OS 커널 파라미터 영향을 함께 받는다.

### 2.2 HTTP 기본 처리 모듈

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_http_core_module` | `http`, `server`, `location`, `root`, `alias`, `try_files`, `client_max_body_size` | HTTP 요청 처리의 기본 구조 |
| `ngx_http_log_module` | `log_format`, `access_log` | access log 포맷과 출력 |
| `ngx_http_index_module` | `index` | 디렉토리 요청 시 기본 파일 선택 |
| `ngx_http_autoindex_module` | `autoindex` | 디렉토리 목록 출력 |
| `ngx_http_headers_module` | `add_header`, `expires`, `add_trailer` | 응답 헤더와 cache header 제어 |
| `ngx_http_map_module` | `map` | 변수 기반 조건 분기 |

기본 server 예시:

```nginx
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$request_time"';

    access_log /var/log/nginx/access.log main;

    server {
        listen 80;
        server_name example.com;

        root /usr/share/nginx/html;
        index index.html;

        location / {
            try_files $uri $uri/ =404;
        }
    }
}
```

`map`은 `if` 남용을 줄이는 데 자주 사용한다.

```nginx
http {
    map $http_upgrade $connection_upgrade {
        default upgrade;
        ""      close;
    }

    map $request_uri $skip_cache {
        default 0;
        ~*^/admin 1;
        ~*preview=true 1;
    }
}
```

### 2.3 Reverse Proxy / Upstream 계열

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_http_proxy_module` | `proxy_pass`, `proxy_set_header`, `proxy_read_timeout`, `proxy_buffering` | HTTP reverse proxy |
| `ngx_http_upstream_module` | `upstream`, `server`, `keepalive`, `least_conn`, `ip_hash` | backend pool과 load balancing |
| `ngx_http_fastcgi_module` | `fastcgi_pass`, `fastcgi_param` | PHP-FPM 등 FastCGI 연동 |
| `ngx_http_grpc_module` | `grpc_pass` | gRPC proxy |
| `ngx_http_uwsgi_module` | `uwsgi_pass` | uWSGI 연동 |

가장 흔한 reverse proxy 구성:

```nginx
upstream app_backend {
    least_conn;
    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.2.10:8080 max_fails=3 fail_timeout=10s;
    keepalive 64;
}

server {
    listen 80;
    server_name app.example.com;

    location / {
        proxy_pass http://app_backend;

        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

WebSocket은 proxy 모듈과 map 조합을 사용한다.

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ""      close;
}

server {
    listen 80;
    server_name ws.example.com;

    location /ws/ {
        proxy_pass http://app_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }
}
```

### 2.4 TLS / HTTP/2 / HTTP/3 계열

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_http_ssl_module` | `ssl_certificate`, `ssl_certificate_key`, `ssl_protocols`, `ssl_ciphers` | HTTPS/TLS 종료 |
| `ngx_http_v2_module` | `http2` | HTTP/2 처리 |
| `ngx_http_v3_module` | `http3`, `quic_retry` | HTTP/3/QUIC 처리 |

기본 TLS server:

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/pki/nginx/example.com.crt;
    ssl_certificate_key /etc/pki/nginx/private/example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    location / {
        root /usr/share/nginx/html;
        index index.html;
    }
}
```

TLS 관련 세부 설정은 [11. SSL/TLS 설정](../security/11_ssl_tls.md)을 기준으로 관리한다.

### 2.5 압축 / 캐시 계열

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_http_gzip_module` | `gzip`, `gzip_types`, `gzip_comp_level` | 응답 gzip 압축 |
| `ngx_http_gzip_static_module` | `gzip_static` | 미리 압축된 `.gz` 파일 제공 |
| `ngx_http_gunzip_module` | `gunzip` | gzip 미지원 client에 압축 해제 응답 |
| `ngx_http_proxy_module` | `proxy_cache`, `proxy_cache_path`, `proxy_cache_valid` | reverse proxy cache |
| `ngx_http_slice_module` | `slice` | 큰 파일을 조각 단위로 cache |
| `ngx_http_headers_module` | `expires`, `Cache-Control` | client/browser cache 제어 |

gzip 기본:

```nginx
http {
    gzip on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_types
        text/plain
        text/css
        application/json
        application/javascript
        application/xml
        image/svg+xml;
}
```

proxy cache 기본:

```nginx
http {
    proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=app_cache:100m inactive=60m max_size=10g;

    server {
        listen 80;
        server_name cache.example.com;

        location / {
            proxy_pass http://app_backend;
            proxy_cache app_cache;
            proxy_cache_valid 200 302 10m;
            proxy_cache_valid 404 1m;
            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

캐시 세부 패턴은 [12. 캐싱](../performance/12_caching.md), gzip 세부 설정은 [14. gzip 압축](../performance/14_gzip.md)을 참고한다.

### 2.6 보안 / 접근 제어 계열

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_http_access_module` | `allow`, `deny` | IP 기반 접근 제어 |
| `ngx_http_auth_basic_module` | `auth_basic`, `auth_basic_user_file` | Basic Auth |
| `ngx_http_auth_request_module` | `auth_request` | 외부 인증 서버 연동 |
| `ngx_http_limit_req_module` | `limit_req_zone`, `limit_req` | 요청 속도 제한 |
| `ngx_http_limit_conn_module` | `limit_conn_zone`, `limit_conn` | 동시 연결 수 제한 |
| `ngx_http_realip_module` | `set_real_ip_from`, `real_ip_header` | L4/L7 프록시 뒤 실제 client IP 복원 |
| `ngx_http_referer_module` | `valid_referers` | Referer 기반 hotlink 방지 |
| `ngx_http_secure_link_module` | `secure_link` | 서명 URL 처리 |

rate limit 예시:

```nginx
http {
    limit_req_zone $binary_remote_addr zone=api_rate:10m rate=10r/s;
    limit_conn_zone $binary_remote_addr zone=addr_conn:10m;

    server {
        listen 80;
        server_name api.example.com;

        location /api/ {
            limit_req zone=api_rate burst=20 nodelay;
            limit_conn addr_conn 20;
            proxy_pass http://app_backend;
        }
    }
}
```

real IP 예시:

```nginx
http {
    set_real_ip_from 10.0.0.0/8;
    set_real_ip_from 172.16.0.0/12;
    set_real_ip_from 192.168.0.0/16;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
}
```

주의: `set_real_ip_from 0.0.0.0/0`는 임의 client가 `X-Forwarded-For`를 조작할 수 있어 위험하다. 신뢰 가능한 ALB/NLB/프록시 CIDR만 지정한다.

### 2.7 Rewrite / Routing 계열

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_http_rewrite_module` | `rewrite`, `return`, `if`, `set` | URI rewrite, redirect, 조건 처리 |
| `ngx_http_try_files` 기능 | `try_files` | 파일 존재 여부 기반 fallback |
| `ngx_http_map_module` | `map` | 변수 변환과 라우팅 조건 |
| `ngx_http_split_clients_module` | `split_clients` | 비율 기반 A/B 분기 |

redirect는 가능하면 `rewrite`보다 `return`을 우선 사용한다.

```nginx
server {
    listen 80;
    server_name old.example.com;

    return 301 https://new.example.com$request_uri;
}
```

SPA fallback:

```nginx
server {
    listen 80;
    server_name app.example.com;
    root /usr/share/nginx/html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### 2.8 관측 / 운영 계열

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_http_log_module` | `access_log`, `log_format` | 요청 로그 |
| `ngx_http_stub_status_module` | `stub_status` | 기본 connection 상태 노출 |
| `ngx_http_status_module` | `status` | NGINX Plus 상태 API |
| Core functionality | `error_log` | 에러 로그 |

stub_status 예시:

```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /nginx_status {
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
```

확인:

```bash
curl -s http://127.0.0.1:8080/nginx_status
```

로그와 모니터링은 [13. Logging](../operations/13_logging.md), [23. Monitoring](../operations/23_monitoring.md)을 같이 본다.

### 2.9 Stream 계열

HTTP가 아닌 TCP/UDP 프록시가 필요하면 stream 모듈을 사용한다.

| 모듈 | 대표 directive | 용도 |
|---|---|---|
| `ngx_stream_core_module` | `stream`, `server`, `listen` | TCP/UDP proxy context |
| `ngx_stream_proxy_module` | `proxy_pass`, `proxy_timeout` | TCP/UDP upstream 전달 |
| `ngx_stream_upstream_module` | `upstream`, `server` | stream backend pool |
| `ngx_stream_ssl_module` | `ssl_certificate`, `ssl_preread`와 별도 TLS 종료 | TCP TLS 종료 |
| `ngx_stream_ssl_preread_module` | `ssl_preread`, `$ssl_preread_server_name` | TLS SNI 기반 라우팅 |
| `ngx_stream_log_module` | `access_log`, `log_format` | stream access log |

SNI 기반 TCP 라우팅 예시:

```nginx
stream {
    map $ssl_preread_server_name $stream_backend {
        db.example.com      db_backend;
        redis.example.com   redis_backend;
        default             default_backend;
    }

    upstream db_backend {
        server 10.0.1.10:5432;
    }

    upstream redis_backend {
        server 10.0.2.10:6379;
    }

    upstream default_backend {
        server 10.0.3.10:443;
    }

    server {
        listen 443;
        ssl_preread on;
        proxy_pass $stream_backend;
    }
}
```

stream 구성은 [20. Stream 모듈](../proxy/20_stream_module.md)을 기준으로 확장한다.

---

## 3. 자주 쓰는 모듈 빠른 선택표

| 목적 | 우선 확인할 모듈 | 대표 directive |
|---|---|---|
| 정적 파일 서빙 | `ngx_http_core_module`, `ngx_http_index_module` | `root`, `alias`, `index`, `try_files` |
| Reverse proxy | `ngx_http_proxy_module`, `ngx_http_upstream_module` | `proxy_pass`, `upstream`, `keepalive` |
| PHP-FPM 연동 | `ngx_http_fastcgi_module` | `fastcgi_pass`, `fastcgi_param` |
| HTTPS | `ngx_http_ssl_module` | `ssl_certificate`, `ssl_protocols` |
| HTTP/2 | `ngx_http_v2_module` | `listen ... http2` |
| 압축 | `ngx_http_gzip_module`, `ngx_http_gzip_static_module` | `gzip`, `gzip_static` |
| 캐싱 | `ngx_http_proxy_module`, `ngx_http_headers_module` | `proxy_cache`, `expires` |
| Rate limit | `ngx_http_limit_req_module`, `ngx_http_limit_conn_module` | `limit_req`, `limit_conn` |
| 실제 client IP 복원 | `ngx_http_realip_module` | `set_real_ip_from`, `real_ip_header` |
| 인증 연동 | `ngx_http_auth_basic_module`, `ngx_http_auth_request_module` | `auth_basic`, `auth_request` |
| redirect/rewrite | `ngx_http_rewrite_module` | `return`, `rewrite`, `set` |
| 조건 분기 | `ngx_http_map_module`, `ngx_http_split_clients_module` | `map`, `split_clients` |
| 상태 확인 | `ngx_http_stub_status_module` | `stub_status` |
| TCP/UDP 프록시 | `ngx_stream_core_module`, `ngx_stream_proxy_module` | `stream`, `proxy_pass` |
| SNI 기반 TCP 라우팅 | `ngx_stream_ssl_preread_module` | `ssl_preread` |

---

## 4. 트러블슈팅

### unknown directive 오류

증상:

```text
nginx: [emerg] unknown directive "stub_status" in /etc/nginx/conf.d/status.conf:6
```

원인:

- 해당 directive를 제공하는 모듈이 빌드에 포함되지 않음
- 동적 모듈인데 `load_module`이 누락됨
- directive를 잘못된 context에 작성함

확인:

```bash
nginx -V 2>&1 | tr ' ' '\n' | grep stub_status
nginx -T 2>&1 | sed -n '1,80p'
```

해결:

```nginx
load_module modules/ngx_http_stub_status_module.so;
```

패키지에 해당 `.so`가 없으면 모듈 포함 패키지를 설치하거나, 모듈을 포함해 다시 빌드한다.

### directive is not allowed here 오류

증상:

```text
nginx: [emerg] "upstream" directive is not allowed here
```

원인:

- `upstream`을 `server` 또는 `location` 안에 작성함
- `load_module`을 `http` 안에 작성함
- `stream` directive를 `http` 내부에 작성함

확인:

```bash
nginx -t
nginx -T | less
```

해결 기준:

| directive | 올바른 context |
|---|---|
| `load_module` | main 최상단 |
| `events` | main |
| `http` | main |
| `stream` | main |
| `upstream` | `http` 또는 `stream` |
| `server` | `http` 또는 `stream` |
| `location` | `server` inside `http` |

### real IP가 전부 프록시 IP로 찍힘

증상:

- access log의 `$remote_addr`가 ALB, NLB, reverse proxy IP로만 표시됨

원인:

- `ngx_http_realip_module` 미사용
- `set_real_ip_from`에 신뢰 가능한 proxy CIDR 누락
- `real_ip_header` 값이 실제 헤더와 맞지 않음

해결:

```nginx
http {
    set_real_ip_from 10.0.0.0/8;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
}
```

검증:

```bash
nginx -t
systemctl reload nginx
tail -f /var/log/nginx/access.log
```

### stream 설정이 동작하지 않음

증상:

```text
nginx: [emerg] unknown directive "stream"
```

원인:

- `ngx_stream_module`이 빌드에 포함되지 않거나 동적 모듈 로드 누락

확인:

```bash
nginx -V 2>&1 | tr ' ' '\n' | grep stream
ls -l /usr/lib64/nginx/modules | grep stream
```

해결:

```nginx
load_module modules/ngx_stream_module.so;
```

배포판 패키지에서 stream 모듈이 별도 패키지로 분리된 경우 해당 패키지를 설치한다.

---

## 5. 운영 팁

- 설정을 읽을 때 directive 이름만 보지 말고 “어느 module/context의 directive인지” 먼저 확인한다.
- `nginx -V` 결과를 운영 서버별로 보관한다. 같은 설정이 한 서버에서만 실패하면 빌드 옵션 차이일 가능성이 높다.
- 동적 모듈은 `load_module` 순서와 경로를 표준화한다. `/etc/nginx/modules-enabled/*.conf` 같은 include 구조를 쓰면 운영이 편하다.
- third-party 모듈은 성능·보안·업그레이드 리스크를 만든다. 가능하면 공식 모듈과 배포판 패키지 모듈을 우선 사용한다.
- `if`는 rewrite 모듈 기능이지만 location 안에서 복잡한 제어 흐름을 만들면 예측이 어려워진다. 단순 redirect는 `return`, 조건 분기는 `map`을 우선 사용한다.
- rate limit, realip, auth_request는 보안 영향이 크다. 적용 후 `nginx -t`, `nginx -T`, access log, error log를 함께 확인한다.

---

## 6. 참고 문서

- [Nginx 공식 문서 - Modules reference](https://nginx.org/en/docs/)
- [Nginx 공식 문서 - Core functionality](https://nginx.org/en/docs/ngx_core_module.html)
- [Nginx 공식 문서 - ngx_http_core_module](https://nginx.org/en/docs/http/ngx_http_core_module.html)
- [Nginx 공식 문서 - ngx_http_proxy_module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
- [Nginx 공식 문서 - ngx_http_upstream_module](https://nginx.org/en/docs/http/ngx_http_upstream_module.html)
- [Nginx 공식 문서 - ngx_stream_core_module](https://nginx.org/en/docs/stream/ngx_stream_core_module.html)
