# 15. 보안

---

## 보안 헤더

```nginx
server {
    # Clickjacking 방지
    add_header X-Frame-Options "SAMEORIGIN" always;

    # MIME 타입 스니핑 방지
    add_header X-Content-Type-Options "nosniff" always;

    # XSS 필터 (구형 브라우저용)
    add_header X-XSS-Protection "1; mode=block" always;

    # HTTPS 강제 (HSTS)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Referrer 정책
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Content Security Policy (CSP)
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:;" always;

    # Permissions Policy (기능 접근 제한)
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    # nginx 버전 숨기기
    server_tokens off;
}
```

**주의**: `add_header`는 하위 블록에서 재정의하면 상위 헤더가 사라집니다.
공통 보안 헤더는 스니펫 파일로 분리하고 모든 server 블록에 include 하세요.

---

## IP 접근 제어

```nginx
# 특정 IP 허용/차단
location /admin/ {
    allow 10.0.0.0/8;
    allow 192.168.1.0/24;
    allow 203.0.113.5;         # 특정 IP
    deny all;
}

# 특정 IP 차단
location / {
    deny 192.168.1.100;
    deny 10.0.0.0/8;
    allow all;
}
```

### geo 모듈로 국가별 차단

```nginx
http {
    geo $block_country {
        default 0;
        # MaxMind GeoIP 데이터 필요 (ngx_http_geoip2_module)
    }

    # 간단한 IP 범위 기반
    geo $limited_access {
        default         1;      # 기본: 차단
        127.0.0.1       0;
        10.0.0.0/8      0;      # 내부 네트워크: 허용
        203.0.113.0/24  0;      # 특정 외부: 허용
    }
}

server {
    location /internal/ {
        if ($limited_access) {
            return 403;
        }
    }
}
```

---

## Basic Auth

```bash
# htpasswd 파일 생성
sudo dnf install httpd-tools    # htpasswd 명령 포함

# 새 파일 생성 + 사용자 추가
htpasswd -c /etc/nginx/.htpasswd admin
# 기존 파일에 사용자 추가
htpasswd /etc/nginx/.htpasswd user2

# 파일 보안
chmod 640 /etc/nginx/.htpasswd
chown root:nginx /etc/nginx/.htpasswd
```

```nginx
location /protected/ {
    auth_basic "Restricted Area";
    auth_basic_user_file /etc/nginx/.htpasswd;
}

# 특정 IP는 인증 없이 통과
location /protected/ {
    satisfy any;    # allow 조건이나 auth 중 하나만 통과하면 됨
    allow 10.0.0.0/8;
    deny all;
    auth_basic "Restricted Area";
    auth_basic_user_file /etc/nginx/.htpasswd;
}
```

---

## 요청 크기/속도 제한

```nginx
# 요청 크기 제한
client_max_body_size 10m;

# 요청 수 제한 (rate limiting 문서 참조)
limit_req_zone $binary_remote_addr zone=req_limit:10m rate=10r/s;
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;
```

---

## SSL/TLS 보안 (요약, 상세는 11_ssl_tls.md 참조)

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_session_tickets off;
```

---

## 악성 요청 차단

```nginx
server {
    # 빈 User-Agent 차단
    if ($http_user_agent = "") {
        return 444;
    }

    # 알려진 악성 봇 차단
    if ($http_user_agent ~* (masscan|nmap|nikto|sqlmap|zgrab)) {
        return 444;
    }

    # HTTP 메서드 제한
    if ($request_method !~ ^(GET|HEAD|POST|PUT|DELETE|OPTIONS|PATCH)$) {
        return 405;
    }

    # 잘못된 프로토콜 차단
    if ($server_protocol = "HTTP/1.0") {
        return 444;
    }
}
```

---

## 숨김 파일/디렉토리 차단

```nginx
# .git, .env, .htaccess, .htpasswd 등 접근 차단
location ~ /\. {
    deny all;
    access_log off;
    log_not_found off;
    return 404;
}

# 특정 확장자 차단
location ~* \.(git|env|sql|bak|conf|ini|log|sh|py|rb)$ {
    deny all;
    return 404;
}
```

---

## Buffer Overflow 방어

```nginx
client_body_buffer_size    128k;
client_header_buffer_size  1k;
client_max_body_size       10m;
large_client_header_buffers 4 4k;
```

---

## Slowloris 공격 대응

느린 HTTP 연결로 서버 연결을 고갈시키는 공격입니다.

```nginx
client_header_timeout  10s;    # 헤더 수신 타임아웃 줄이기
client_body_timeout    10s;    # 바디 수신 타임아웃 줄이기
keepalive_timeout      30s;    # keepalive 타임아웃 줄이기
reset_timedout_connection on;  # 타임아웃 연결 즉시 초기화
```

---

## CORS 설정

```nginx
location /api/ {
    # 허용할 출처 (Origin)
    if ($http_origin ~* "^https://(www\.)?example\.com$") {
        add_header Access-Control-Allow-Origin "$http_origin" always;
    }
    add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type, X-Requested-With" always;
    add_header Access-Control-Allow-Credentials "true" always;
    add_header Access-Control-Max-Age "3600" always;

    # Preflight 요청 처리
    if ($request_method = OPTIONS) {
        add_header Access-Control-Allow-Origin "$http_origin" always;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
        return 204;
    }

    proxy_pass http://backend;
}
```

---

## 모의 해킹 방어 (WAF 없이)

```nginx
# SQL Injection 기본 차단
location / {
    if ($query_string ~* "union.*select.*\(") { return 444; }
    if ($query_string ~* "concat.*\(")        { return 444; }
    if ($query_string ~* "information_schema"){ return 444; }
}

# XSS 기본 차단
location / {
    if ($query_string ~* "<script>")    { return 444; }
    if ($args ~* "(<|%3C)script")       { return 444; }
}
```

**주의**: `if` 지시어는 nginx에서 주의해서 사용해야 합니다. (`if is evil` 참조)
실제 WAF가 필요하다면 ModSecurity(ngx_http_modsecurity_module)를 사용하세요.

---

## ModSecurity 연동 (고급)

```bash
# ModSecurity 동적 모듈 설치 (빌드 필요)
# libmodsecurity3 + nginx connector
```

```nginx
load_module modules/ngx_http_modsecurity_module.so;

http {
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsecurity/modsecurity.conf;
}
```
