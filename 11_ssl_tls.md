# 11. SSL/TLS 설정

---

## 기본 SSL 설정

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    ssl_certificate     /etc/nginx/ssl/example.com.crt;     # 인증서 (체인 포함)
    ssl_certificate_key /etc/nginx/ssl/example.com.key;     # 개인키

    # ...
}
```

---

## 인증서 종류별 파일 준비

### Let's Encrypt (Certbot)

```bash
# 설치
sudo dnf install certbot python3-certbot-nginx

# 인증서 발급 (nginx 자동 설정)
sudo certbot --nginx -d example.com -d www.example.com

# 인증서만 발급 (nginx 설정은 수동)
sudo certbot certonly --standalone -d example.com

# 발급된 파일 위치
# /etc/letsencrypt/live/example.com/fullchain.pem  ← 인증서 + 체인
# /etc/letsencrypt/live/example.com/privkey.pem    ← 개인키

# 자동 갱신 테스트
sudo certbot renew --dry-run

# cron 등록 (보통 자동 등록됨)
# 0 0,12 * * * root certbot renew --quiet
```

nginx.conf에서 사용:

```nginx
ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
```

### 자체 서명 인증서 (Self-Signed, 개발용)

```bash
# 개인키 + 인증서 생성 (10년 유효)
openssl req -x509 -nodes -days 3650 \
    -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/self.key \
    -out /etc/nginx/ssl/self.crt \
    -subj "/C=KR/ST=Seoul/L=Seoul/O=Dev/CN=localhost"

# SAN (Subject Alternative Name) 포함 버전
openssl req -x509 -nodes -days 3650 \
    -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/self.key \
    -out /etc/nginx/ssl/self.crt \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1"
```

---

## 권장 SSL 설정 (Mozilla SSL Configuration Generator 기반)

```nginx
# /etc/nginx/snippets/ssl-params.conf

# 프로토콜 버전 제한 (TLS 1.2 이상만 허용)
ssl_protocols TLSv1.2 TLSv1.3;

# 암호화 알고리즘 (TLS 1.2 호환)
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;    # TLS 1.3에서는 off 권장

# DH 파라미터 (Forward Secrecy)
ssl_dhparam /etc/nginx/ssl/dhparam.pem;

# 세션 캐시 (성능)
ssl_session_cache   shared:SSL:10m;    # 10MB 공유 캐시 (약 40,000 세션)
ssl_session_timeout 1d;               # 세션 재사용 가능 시간

# TLS 1.3 전용 세션 티켓 비활성화 (보안)
ssl_session_tickets off;

# OCSP Stapling (인증서 폐기 확인 성능 향상)
ssl_stapling on;
ssl_stapling_verify on;
resolver 8.8.8.8 8.8.4.4 valid=300s;
resolver_timeout 5s;
```

DH 파라미터 생성:

```bash
openssl dhparam -out /etc/nginx/ssl/dhparam.pem 2048
# 시간이 걸림 (4096은 매우 오래 걸림)
```

---

## HTTPS 보안 헤더

```nginx
server {
    listen 443 ssl;
    include snippets/ssl-params.conf;

    # HSTS (HTTP Strict Transport Security)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # ...
}
```

---

## HTTP → HTTPS 리디렉션

```nginx
# 방법 1: return (권장, 빠름)
server {
    listen 80;
    server_name example.com www.example.com;
    return 301 https://$host$request_uri;
}

# 방법 2: rewrite (비권장)
server {
    listen 80;
    rewrite ^(.*)$ https://$host$1 permanent;
}
```

---

## HTTP/2 설정

```nginx
# nginx 1.25.1 이전
server {
    listen 443 ssl http2;
    # ...
}

# nginx 1.25.1+
server {
    listen 443 ssl;
    http2 on;
    # ...
}
```

HTTP/2 특징:
- 멀티플렉싱: 하나의 TCP 연결로 여러 요청 동시 처리
- 헤더 압축 (HPACK)
- 서버 푸시 (Server Push)
- 바이너리 프로토콜

HTTP/2 Server Push:

```nginx
location = /index.html {
    http2_push /style.css;
    http2_push /app.js;
}
```

---

## HTTP/3 (QUIC) - nginx 1.25+

```nginx
server {
    listen 443 quic reuseport;    # UDP
    listen 443 ssl;

    ssl_certificate     /etc/nginx/ssl/example.com.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.key;

    add_header Alt-Svc 'h3=":443"; ma=86400';    # HTTP/3 광고
}
```

---

## mTLS (Mutual TLS, 클라이언트 인증)

서버뿐 아니라 클라이언트도 인증서로 인증합니다.

```nginx
server {
    listen 443 ssl;

    ssl_certificate     /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # 클라이언트 인증서 검증
    ssl_client_certificate /etc/nginx/ssl/ca.crt;    # 신뢰할 CA
    ssl_verify_client on;                             # 필수 검증
    # ssl_verify_client optional;                    # 선택적 검증
    # ssl_verify_client optional_no_ca;              # CA 검증 없이

    ssl_verify_depth 2;    # 인증서 체인 깊이

    location / {
        # 클라이언트 인증서 정보를 헤더로 전달
        proxy_set_header X-SSL-Client-Cert $ssl_client_cert;
        proxy_set_header X-SSL-Client-DN   $ssl_client_s_dn;
        proxy_pass http://backend;
    }
}
```

클라이언트 인증서 생성:

```bash
# CA 생성
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt -subj "/CN=MyCA"

# 클라이언트 키 + CSR
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr -subj "/CN=client1"

# CA로 서명
openssl x509 -req -days 365 -in client.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out client.crt

# PFX 변환 (브라우저/curl용)
openssl pkcs12 -export -out client.pfx -inkey client.key -in client.crt -certfile ca.crt
```

테스트:

```bash
curl --cert client.crt --key client.key --cacert ca.crt https://example.com
```

---

## SNI (Server Name Indication)

하나의 IP에서 여러 SSL 인증서를 사용합니다.

```nginx
# 인증서가 다른 두 도메인
server {
    listen 443 ssl;
    server_name example.com;
    ssl_certificate     /etc/nginx/ssl/example.com.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.key;
}

server {
    listen 443 ssl;
    server_name another.com;
    ssl_certificate     /etc/nginx/ssl/another.com.crt;
    ssl_certificate_key /etc/nginx/ssl/another.com.key;
}
```

SNI는 TLS handshake 시 클라이언트가 도메인을 먼저 알려주는 방식으로 동작합니다.
모든 현대 브라우저와 클라이언트가 지원합니다.

---

## 인증서 확인 명령

```bash
# 인증서 내용 확인
openssl x509 -in example.com.crt -text -noout

# 만료일 확인
openssl x509 -in example.com.crt -noout -enddate

# 원격 서버 인증서 확인
openssl s_client -connect example.com:443 -servername example.com

# nginx가 사용 중인 인증서 확인
curl -vI https://example.com 2>&1 | grep -A 5 "SSL certificate"
```
