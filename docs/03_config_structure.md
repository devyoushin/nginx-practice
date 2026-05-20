# 03. nginx.conf 구조와 Context 계층

## 전체 구조 개요

```nginx
# ── main context (최상위) ──────────────────────────────
user  nginx;
worker_processes  auto;
error_log  /var/log/nginx/error.log notice;
pid  /var/run/nginx.pid;

events {                          # ── events context ──
    worker_connections  1024;
}

http {                            # ── http context ─────
    include  mime.types;
    default_type  application/octet-stream;

    upstream backend {            # ── upstream context ─
        server 127.0.0.1:8080;
    }

    server {                      # ── server context ───
        listen  80;
        server_name  example.com;

        location / {              # ── location context ─
            root  /usr/share/nginx/html;
            index index.html;
        }

        location /api/ {
            proxy_pass http://backend;
        }
    }
}

stream {                          # ── stream context ───
    server {
        listen 3306;
        proxy_pass db-backend;
    }
}
```

---

## Context 계층 및 지시어 적용 범위

```
main
├── events
├── http
│   ├── upstream
│   ├── server
│   │   └── location
│   │       └── location (중첩)
│   └── map
├── stream
│   └── server
└── mail
    └── server
```

### 각 Context의 역할 상세

| Context | 위치 | 역할 |
|---------|------|------|
| main | 최상위 | 전역 설정 (프로세스, 로그, 모듈 로드) |
| events | main 내부 | 연결 처리 방식 설정 |
| http | main 내부 | HTTP 프로토콜 관련 전체 설정 |
| server | http/stream 내부 | 가상 호스트 (도메인/포트별 설정) |
| location | server 내부 | URI 경로별 설정 |
| upstream | http 내부 | 백엔드 서버 그룹 정의 |
| map | http 내부 | 변수 매핑 정의 |
| stream | main 내부 | TCP/UDP 프록시 설정 |
| mail | main 내부 | 메일 프록시 설정 |

---

## 지시어 상속 규칙

대부분의 지시어는 하위 Context에 **상속**되며, 하위에서 재정의하면 **덮어씁니다**.

```nginx
http {
    gzip on;              # http 레벨 설정

    server {
        # gzip on 상속됨

        location /no-gzip/ {
            gzip off;     # 이 location만 gzip 해제
        }
    }
}
```

### 상속 함정 1: add_header 상속 문제

배열형 지시어(`add_header` 등)는 하위에서 재정의 시 상위 값이 완전히 **사라집니다**.

```nginx
# 문제가 되는 설정
http {
    add_header X-Frame-Options SAMEORIGIN;       # 상위

    server {
        add_header X-Content-Type-Options nosniff;  # 하위 재정의
        # 주의: X-Frame-Options는 이 server에서 사라짐!
        # 두 헤더 모두 원하면 server 블록에 둘 다 써야 함
    }
}
```

```nginx
# 올바른 설정 방법 1: server에서 모든 헤더 재선언
http {
    add_header X-Frame-Options SAMEORIGIN;

    server {
        add_header X-Frame-Options SAMEORIGIN;       # 반복 필요
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";

        location /api/ {
            # 이 location에서 add_header를 쓰면 위 server의 것이 모두 사라짐
            add_header X-Frame-Options SAMEORIGIN;
            add_header X-Content-Type-Options nosniff;
            add_header X-XSS-Protection "1; mode=block";
            add_header X-API-Version "v2";  # 추가 헤더
        }
    }
}
```

```nginx
# 올바른 설정 방법 2: include로 공통 헤더 관리 (권장)
# /etc/nginx/snippets/security-headers.conf
add_header X-Frame-Options SAMEORIGIN always;
add_header X-Content-Type-Options nosniff always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;

# nginx.conf에서 사용
server {
    include /etc/nginx/snippets/security-headers.conf;

    location /api/ {
        include /etc/nginx/snippets/security-headers.conf;
        add_header X-API-Version "v2";
        # include 후에 add_header를 쓰면 include의 것도 사라짐!
        # 따라서 X-API-Version도 snippets 파일에 넣거나,
        # 이 location 전용 snippets 파일을 만들어야 함
    }
}
```

### 상속 함정 2: proxy_set_header 상속 문제

`proxy_set_header`도 `add_header`와 동일한 상속 문제가 있습니다.

```nginx
# 문제가 되는 설정
http {
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    server {
        location /api/ {
            proxy_set_header X-Request-ID $request_id;
            # 위 3개 헤더가 모두 사라짐!
            # Host, X-Real-IP, X-Forwarded-For 모두 기본값으로 리셋
            proxy_pass http://backend;
        }
    }
}
```

```nginx
# 올바른 설정: 필요한 모든 proxy_set_header를 함께 선언
# /etc/nginx/snippets/proxy-headers.conf
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;

# nginx.conf
server {
    location /api/ {
        include /etc/nginx/snippets/proxy-headers.conf;
        proxy_set_header X-Request-ID $request_id;
        # 이 경우에도 include의 것이 사라짐!
        proxy_pass http://backend;
    }
}
```

```nginx
# 최종 해결: 모든 것을 한 곳에 모아서 관리
# /etc/nginx/snippets/proxy-headers-with-request-id.conf
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Request-ID $request_id;

# nginx.conf
server {
    location /api/ {
        include /etc/nginx/snippets/proxy-headers-with-request-id.conf;
        proxy_pass http://backend;
    }
}
```

### 상속 규칙 요약 표

| 지시어 유형 | 상속 방식 | 하위에서 재정의 시 |
|-------------|----------|-------------------|
| 단일 값 (`gzip`, `sendfile`) | 상위에서 하위로 상속 | 해당 값만 덮어씀 |
| 배열형 (`add_header`) | 상위에서 하위로 상속 | 상위 값 전부 사라짐, 하위 값만 적용 |
| 배열형 (`proxy_set_header`) | 상위에서 하위로 상속 | 상위 값 전부 사라짐, 하위 값만 적용 |
| 복합형 (`log_format`) | 상속 안 됨 | http context에서만 정의 가능 |
| `access_log` | 상위에서 하위로 상속 | 하위에서 재정의 시 상위 값 사라짐 |

---

## include 지시어

설정 파일을 분리해서 관리할 때 사용합니다.

```nginx
http {
    include /etc/nginx/mime.types;        # 단일 파일
    include /etc/nginx/conf.d/*.conf;     # 와일드카드 (알파벳순 포함)
    include /etc/nginx/sites-enabled/*;   # 디렉토리
}
```

### include 순서의 중요성

`include`로 여러 파일을 포함할 때 알파벳순으로 로드됩니다. 이것이 중요한 이유:

```
# 같은 listen 포트에 대해 default_server가 여러 파일에 있으면
# 알파벳순으로 먼저 오는 파일의 설정이 적용됨

/etc/nginx/conf.d/
├── 00-default.conf        ← listen 80 default_server; (이것이 적용됨)
├── api.example.com.conf   ← listen 80;
└── www.example.com.conf   ← listen 80;
```

파일 이름에 숫자 접두사를 붙여 로드 순서를 명시적으로 제어할 수 있습니다:

```
/etc/nginx/conf.d/
├── 00-global.conf          ← map, upstream 등 공통 정의 (먼저 로드)
├── 01-default.conf         ← default_server 설정
├── 10-example.com.conf     ← 개별 도메인 설정
├── 10-api.example.com.conf
└── 99-catch-all.conf       ← 매칭 안 되는 요청 처리
```

### include 실패 시 동작

```nginx
# 파일이 없으면 nginx가 시작 실패
include /etc/nginx/doesnt-exist.conf;    # 에러 발생

# 와일드카드는 매칭 파일이 없어도 에러 없음
include /etc/nginx/conf.d/*.conf;        # 파일 0개여도 OK
```

---

## conf.d/ 구조 패턴

### 기본 구조

```
/etc/nginx/
├── nginx.conf              ← http 블록에서 conf.d/*.conf include
├── conf.d/
│   ├── default.conf        ← 기본 서버
│   ├── example.com.conf    ← 도메인별 서버
│   └── api.example.com.conf
└── snippets/               ← 재사용 설정 조각
    ├── ssl-params.conf
    └── proxy-params.conf
```

### 대규모 배포를 위한 conf.d/ 구성

수십 개의 도메인을 관리하는 환경에서는 다음과 같이 체계적으로 구성합니다:

```
/etc/nginx/
├── nginx.conf
├── conf.d/
│   ├── 00-upstreams/            ← upstream 정의 (include로 포함)
│   │   ├── backend-api.conf
│   │   ├── backend-web.conf
│   │   └── backend-admin.conf
│   ├── 01-maps/                 ← map 블록 정의
│   │   ├── rate-limit-zones.conf
│   │   └── geo-block.conf
│   ├── 10-sites/                ← 도메인별 server 블록
│   │   ├── example.com.conf
│   │   ├── api.example.com.conf
│   │   ├── admin.example.com.conf
│   │   └── cdn.example.com.conf
│   └── 99-default.conf          ← catch-all 설정
├── snippets/
│   ├── ssl/
│   │   ├── ssl-params.conf      ← SSL 프로토콜/암호화 설정
│   │   └── ssl-stapling.conf    ← OCSP stapling 설정
│   ├── proxy/
│   │   ├── proxy-params.conf    ← 공통 프록시 헤더
│   │   └── proxy-cache.conf     ← 캐시 설정
│   ├── security/
│   │   ├── headers.conf         ← 보안 헤더
│   │   └── rate-limit.conf      ← Rate limiting 설정
│   └── logging/
│       ├── json-log.conf        ← JSON 로그 포맷
│       └── conditional-log.conf ← 조건부 로그
└── ssl/
    ├── example.com/
    │   ├── fullchain.pem
    │   └── privkey.pem
    └── dhparams.pem
```

이 구조에서 nginx.conf의 http 블록:

```nginx
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 공통 설정
    include /etc/nginx/snippets/logging/json-log.conf;

    # upstream 정의 (server 블록보다 먼저 로드되어야 함)
    include /etc/nginx/conf.d/00-upstreams/*.conf;

    # map 정의
    include /etc/nginx/conf.d/01-maps/*.conf;

    # 사이트 설정
    include /etc/nginx/conf.d/10-sites/*.conf;

    # catch-all
    include /etc/nginx/conf.d/99-default.conf;
}
```

### 환경별 설정 관리 (개발/스테이징/운영)

환경별로 다른 설정을 적용해야 할 때의 패턴:

```
/etc/nginx/
├── nginx.conf
├── env/
│   ├── development.conf     ← 개발 환경 변수
│   ├── staging.conf         ← 스테이징 환경 변수
│   └── production.conf      ← 운영 환경 변수
└── conf.d/
    └── site.conf            ← 환경 변수를 참조하는 설정
```

```nginx
# /etc/nginx/env/development.conf
set $env "development";
set $backend_host "localhost:3000";
set $log_level "debug";
error_log /var/log/nginx/error.log debug;
```

```nginx
# /etc/nginx/env/production.conf
set $env "production";
set $backend_host "10.0.1.100:8080";
set $log_level "warn";
error_log /var/log/nginx/error.log warn;
```

```bash
# 환경에 따라 심볼릭 링크로 전환
ln -sf /etc/nginx/env/production.conf /etc/nginx/env/current.conf
nginx -s reload
```

또 다른 방법으로 환경변수를 활용할 수도 있습니다 (주로 Docker 환경):

```nginx
# nginx.conf
env APP_ENV;

# Lua 모듈이나 perl 모듈로 환경변수 접근 가능
# 또는 envsubst로 템플릿 치환 (Docker에서 많이 사용)
```

```bash
# Docker에서 envsubst 사용 예시
envsubst '${BACKEND_HOST} ${BACKEND_PORT}' \
    < /etc/nginx/templates/default.conf.template \
    > /etc/nginx/conf.d/default.conf
```

---

## 기본 nginx.conf (AL2023 RPM 설치 기준)

```nginx
user  nginx;
worker_processes  auto;

error_log  /var/log/nginx/error.log notice;
pid        /var/run/nginx.pid;

events {
    worker_connections  1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';

    access_log  /var/log/nginx/access.log  main;

    sendfile        on;
    #tcp_nopush     on;

    keepalive_timeout  65;

    #gzip  on;

    include /etc/nginx/conf.d/*.conf;
}
```

---

## 문법 및 값 형식

### 크기 단위

```nginx
client_max_body_size 10m;    # 메가바이트
client_max_body_size 1g;     # 기가바이트
client_max_body_size 512k;   # 킬로바이트
client_max_body_size 1048576; # 바이트 (단위 없음)
```

### 시간 단위

```nginx
keepalive_timeout 65s;   # 초 (기본)
keepalive_timeout 1m;    # 분
keepalive_timeout 1h;    # 시간
keepalive_timeout 1d;    # 일
keepalive_timeout 1ms;   # 밀리초
```

복합 시간 표현도 가능합니다:
```nginx
proxy_read_timeout 1m30s;    # 1분 30초
send_timeout 1h30m;          # 1시간 30분
```

### on/off 불리언

```nginx
sendfile on;
gzip off;
autoindex on;
```

### 변수 참조

```nginx
log_format custom '$remote_addr $request_time';
root /var/www/$host;
proxy_pass http://$upstream_addr;
```

변수 사용 시 주의사항:
```nginx
# 변수명에 이어지는 문자가 있으면 중괄호로 감싸야 함
set $prefix "/api";
rewrite ^${prefix}/(.*)$ /$1 break;

# 리터럴 $ 기호가 필요하면 변수로 우회
geo $dollar {
    default "$";
}
```

---

## nginx -t 와 nginx -T

```bash
# 설정 문법 검사만 (파일 내용 미출력)
sudo nginx -t

# 전체 설정 내용 출력 + 검사 (include된 파일 모두 포함)
sudo nginx -T

# 특정 설정 파일로 검사
sudo nginx -t -c /path/to/nginx.conf
```

### nginx -T 출력 분석 활용법

`nginx -T`는 모든 include 파일을 포함한 전체 설정을 출력합니다. 디버깅에 매우 유용합니다.

```bash
# 전체 설정에서 특정 지시어 검색
sudo nginx -T 2>/dev/null | grep -n "proxy_pass"

# 어떤 server 블록이 특정 도메인을 처리하는지 확인
sudo nginx -T 2>/dev/null | grep -A5 "server_name.*example.com"

# SSL 인증서 경로 전체 확인
sudo nginx -T 2>/dev/null | grep "ssl_certificate"

# upstream 설정 확인
sudo nginx -T 2>/dev/null | grep -A10 "upstream"

# 현재 설정 백업
sudo nginx -T > /backup/nginx-config-$(date +%Y%m%d).conf

# 두 설정 간 차이 비교 (변경 전후)
diff <(sudo nginx -T 2>/dev/null) /backup/nginx-config-before.conf
```

### 설정 검증 시 자주 보는 에러 메시지

```bash
# 문법 에러
nginx: [emerg] unknown directive "proxypass" in /etc/nginx/conf.d/site.conf:15
# 해결: proxy_pass (언더스코어 필요)

# 중괄호 누락
nginx: [emerg] unexpected "}" in /etc/nginx/conf.d/site.conf:30
# 해결: 여는 중괄호 { 확인

# 세미콜론 누락
nginx: [emerg] directive "server_name" is not terminated by ";" in ...
# 해결: 지시어 끝에 세미콜론 추가

# include 파일 없음
nginx: [emerg] open() "/etc/nginx/doesnt-exist.conf" failed (2: No such file or directory)
# 해결: 파일 경로 확인 또는 와일드카드 사용

# listen 포트 충돌
nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
# 해결: 다른 프로세스가 80 포트를 사용 중인지 확인 (ss -tlnp | grep :80)
```

---

## 설정 디버깅 팁

### 특정 location이 매칭되는지 확인

```nginx
# 디버깅용: 어떤 location에 매칭되었는지 헤더로 확인
server {
    location / {
        add_header X-Debug-Location "root" always;
        # ...
    }

    location /api/ {
        add_header X-Debug-Location "api" always;
        # ...
    }

    location ~* \.(jpg|png|gif)$ {
        add_header X-Debug-Location "images-regex" always;
        # ...
    }
}
```

```bash
# 응답 헤더에서 매칭된 location 확인
curl -I http://localhost/api/users
# X-Debug-Location: api
```

### 변수 값 디버깅

```nginx
# 요청별 변수 값을 로그로 확인
log_format debug_vars '$remote_addr [$time_local] '
                      'host=$host '
                      'uri=$uri '
                      'args=$args '
                      'upstream=$upstream_addr '
                      'status=$status '
                      'request_time=$request_time';

server {
    access_log /var/log/nginx/debug.log debug_vars;
}
```

### 설정 문제 체계적 접근

```
1. nginx -t 로 문법 검사
   ↓ 통과
2. nginx -T | grep 으로 의도한 설정이 포함되었는지 확인
   ↓ 확인
3. error_log를 debug 레벨로 설정하고 특정 요청 테스트
   ↓ 로그 확인
4. curl -v 로 요청/응답 헤더 확인
   ↓ 문제 파악
5. 설정 수정 후 nginx -t → reload
```

---

## 흔한 설정 문법 오류와 해결

### 1. 세미콜론 관련

```nginx
# 잘못된 예: 블록 시작에 세미콜론
location /api/; {           # 에러!
    proxy_pass http://backend;
}

# 올바른 예
location /api/ {
    proxy_pass http://backend;
}
```

### 2. 따옴표 관련

```nginx
# 공백이 포함된 값은 따옴표 필요
add_header X-Custom "value with spaces";

# 정규표현식은 따옴표 없이도 가능하지만, 복잡한 경우 따옴표 권장
location ~ "^/api/v[0-9]+/users$" {
    # ...
}

# log_format에서 여러 줄은 따옴표로 연결
log_format main '$remote_addr - $remote_user [$time_local] '
                '"$request" $status $body_bytes_sent';
```

### 3. proxy_pass 끝의 슬래시 차이

```nginx
# /api/users 요청 시:

# 슬래시 없음: /api/users 그대로 백엔드에 전달
location /api/ {
    proxy_pass http://backend;
    # → 백엔드 요청: http://backend/api/users
}

# 슬래시 있음: /api/ 부분이 / 로 치환
location /api/ {
    proxy_pass http://backend/;
    # → 백엔드 요청: http://backend/users
}

# 경로 포함: /api/ 부분이 /v2/ 로 치환
location /api/ {
    proxy_pass http://backend/v2/;
    # → 백엔드 요청: http://backend/v2/users
}
```

### 4. if 문 사용 주의사항

Nginx에서 `if`는 다른 프로그래밍 언어와 다르게 동작합니다. 공식 문서에서도 "If is Evil"이라고 경고합니다.

```nginx
# 위험한 사용 (예측 불가능한 동작)
location / {
    if ($request_uri ~* "\.php$") {
        root /var/www/php;     # if 내부의 root는 예상대로 동작하지 않을 수 있음
    }
    root /var/www/html;
}

# 안전한 대안: location 분리
location / {
    root /var/www/html;
}
location ~ \.php$ {
    root /var/www/php;
}

# if에서 안전하게 사용할 수 있는 것들:
# - return
# - rewrite ... last/break
# - set
```

---

## 시그널 정리

```bash
kill -HUP   <master_pid>   # 설정 재로드 (graceful)
kill -QUIT  <master_pid>   # 정상 종료 (현재 요청 완료 후)
kill -TERM  <master_pid>   # 즉시 종료
kill -USR1  <master_pid>   # 로그 파일 재오픈 (logrotate 후 사용)
kill -USR2  <master_pid>   # 바이너리 업그레이드 시작
kill -WINCH <master_pid>   # Worker 프로세스 점진 종료
```

### systemctl과의 대응

| 동작 | systemctl 명령 | 시그널 | nginx -s 옵션 |
|------|---------------|--------|---------------|
| 시작 | `systemctl start nginx` | - | `nginx` |
| 정지 | `systemctl stop nginx` | QUIT | `nginx -s quit` |
| 재시작 | `systemctl restart nginx` | QUIT + start | - |
| 재로드 | `systemctl reload nginx` | HUP | `nginx -s reload` |
| 로그 재오픈 | - | USR1 | `nginx -s reopen` |
