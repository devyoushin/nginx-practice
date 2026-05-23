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

## TLS termination 위치

nginx는 SSL/TLS 인증서를 직접 적용할 수 있습니다.
하지만 실무에서는 nginx 앞단의 WAF, CDN, API Gateway, Load Balancer에서 TLS를 먼저 종료하고 nginx로 넘기는 구조도 매우 흔합니다.

대표 구조:

```text
# nginx가 직접 TLS 종료
Client --HTTPS--> Nginx --HTTP--> App

# 앞단에서 TLS 종료
Client --HTTPS--> WAF / CDN / API Gateway / Load Balancer --HTTP--> Nginx --HTTP--> App

# 앞단에서 TLS 종료 후 내부 구간 재암호화
Client --HTTPS--> WAF / CDN / API Gateway / Load Balancer --HTTPS--> Nginx --HTTP--> App
```

용어:

| 용어 | 의미 |
|------|------|
| TLS termination | HTTPS 연결을 복호화하고 HTTP 요청으로 처리하는 지점 |
| Edge termination | 사용자와 가장 가까운 WAF/CDN/LB/API Gateway에서 TLS 종료 |
| Re-encryption | 앞단에서 TLS를 종료한 뒤, 내부 nginx로 다시 HTTPS 연결 |
| End-to-end TLS | Client부터 App 근처까지 구간별로 계속 TLS 사용 |

앞단에서 TLS termination을 하는 이유:

- WAF가 HTTP 요청 내용을 확인해야 공격 패턴을 검사할 수 있습니다.
- API Gateway가 인증, 인가, rate limit, 라우팅, JWT 검증 등을 처리할 수 있습니다.
- 인증서 발급/갱신/교체를 한 곳에서 관리하기 쉽습니다.
- 여러 nginx/app 서버마다 인증서를 배포하지 않아도 됩니다.
- TLS 정책, cipher, HTTP/2, HTTP/3 설정을 중앙에서 통제할 수 있습니다.

어느 위치에서 TLS를 종료할지는 보안 경계와 운영 방식에 따라 결정합니다.

| 구조 | 장점 | 주의점 |
|------|------|--------|
| 앞단 TLS 종료 후 nginx는 HTTP | 단순하고 운영이 편함 | 내부망 신뢰가 전제됨 |
| 앞단 TLS 종료 후 nginx까지 HTTPS | 내부 구간도 암호화 가능 | nginx에도 인증서/신뢰 설정 필요 |
| nginx가 직접 TLS 종료 | nginx 단독 운영에 단순함 | WAF/API Gateway 앞단 정책과 역할 중복 가능 |

---

## 앞단에서 TLS 종료 시 nginx 설정

WAF/API Gateway/LB가 HTTPS를 종료하고 nginx로 HTTP 요청을 넘기면 nginx에는 `ssl_certificate`가 필요하지 않을 수 있습니다.
대신 원래 요청이 HTTPS였는지, 실제 클라이언트 IP가 무엇인지 전달받는 헤더 처리가 중요합니다.

앞단이 보통 전달하는 헤더:

```text
X-Forwarded-Proto: https
X-Forwarded-For: 203.0.113.10
X-Forwarded-Host: example.com
X-Real-IP: 203.0.113.10
```

nginx reverse proxy 예시:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;

        proxy_pass http://app_backend;
    }
}
```

주의할 점은 `X-Forwarded-*` 헤더를 아무 요청에서나 믿으면 안 된다는 것입니다.
nginx가 인터넷에 직접 노출되어 있으면 사용자가 임의로 `X-Forwarded-Proto: https` 또는 가짜 IP를 보낼 수 있습니다.

앞단 프록시 IP만 신뢰하도록 `real_ip`를 설정합니다.

```nginx
http {
    # WAF / LB / API Gateway의 내부 IP 대역만 신뢰
    set_real_ip_from 10.0.0.0/8;
    set_real_ip_from 172.16.0.0/12;
    set_real_ip_from 192.168.0.0/16;

    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
}
```

애플리케이션이 HTTPS 여부를 알아야 하는 경우, 앞단에서 받은 proto 값을 그대로 전달합니다.

```nginx
proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
```

단, nginx가 직접 외부 요청을 받는 구조라면 아래처럼 고정하는 편이 안전합니다.

```nginx
# HTTPS server block 내부
proxy_set_header X-Forwarded-Proto https;

# HTTP server block 내부
proxy_set_header X-Forwarded-Proto http;
```

앞단 TLS termination 구조에서는 HTTP에서 HTTPS로 리디렉션을 nginx가 담당하지 않는 경우도 많습니다.
WAF/API Gateway/LB에서 이미 HTTPS 강제 리디렉션을 하고 있다면 nginx의 80번 리디렉션 설정은 중복될 수 있습니다.

정리:

```text
nginx가 직접 TLS 종료:
- nginx에 ssl_certificate / ssl_certificate_key 설정
- HTTP -> HTTPS 리디렉션도 nginx에서 처리 가능

앞단에서 TLS 종료:
- nginx에는 인증서가 없을 수 있음
- X-Forwarded-Proto, X-Forwarded-For, real_ip 신뢰 설정이 중요
- HTTPS 리디렉션은 앞단에서 처리하는 경우가 많음
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

nginx가 직접 외부 HTTP 요청을 받는 경우에는 80번 포트에서 HTTPS로 리디렉션합니다.
앞단 WAF/API Gateway/LB에서 이미 HTTPS 강제 리디렉션을 처리한다면 nginx 설정과 중복되지 않게 역할을 나눕니다.

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
