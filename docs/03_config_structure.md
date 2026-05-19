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

### 지시어 상속 규칙

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

**예외**: 배열형 지시어(add_header 등)는 하위에서 재정의 시 상위 값이 완전히 **사라집니다**.

```nginx
http {
    add_header X-Frame-Options SAMEORIGIN;  # 상위

    server {
        add_header X-Content-Type-Options nosniff;  # 하위 재정의
        # 주의: X-Frame-Options는 이 server에서 사라짐!
        # 두 헤더 모두 원하면 server 블록에 둘 다 써야 함
    }
}
```

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

### conf.d/ 구조 패턴 예시

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

## 시그널 정리

```bash
kill -HUP   <master_pid>   # 설정 재로드 (graceful)
kill -QUIT  <master_pid>   # 정상 종료 (현재 요청 완료 후)
kill -TERM  <master_pid>   # 즉시 종료
kill -USR1  <master_pid>   # 로그 파일 재오픈 (logrotate 후 사용)
kill -USR2  <master_pid>   # 바이너리 업그레이드 시작
kill -WINCH <master_pid>   # Worker 프로세스 점진 종료
```
