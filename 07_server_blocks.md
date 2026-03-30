# 07. Server 블록 (Virtual Host)

server 블록은 하나의 가상 호스트를 정의합니다.
하나의 nginx 인스턴스로 여러 도메인/포트를 서빙할 수 있습니다.

---

## listen 지시어

```nginx
listen 80;                    # IPv4, 포트 80
listen 0.0.0.0:80;           # 명시적 IPv4 all
listen [::]:80;               # IPv6
listen [::]:80 ipv6only=off;  # IPv4+IPv6 동시 (Linux 기본 동작)
listen 127.0.0.1:8080;        # 로컬호스트만
listen 443 ssl;               # HTTPS
listen 443 ssl http2;         # HTTP/2 (1.25.1 이전 방식)
listen 443 ssl; http2 on;     # HTTP/2 (1.25.1+ 방식)
listen 80 default_server;     # 기본 서버 지정
listen *:80;                  # 모든 IP
```

### default_server

매칭되는 server 블록이 없을 때 사용하는 기본 서버입니다.

```nginx
# 정의되지 않은 호스트 접근 차단
server {
    listen 80 default_server;
    return 444;    # nginx 전용: 응답 없이 연결 닫기
}

server {
    listen 80;
    server_name example.com;
    # ...
}
```

---

## server_name

요청의 Host 헤더와 매칭할 이름을 지정합니다.

```nginx
server_name example.com;                    # 정확히 일치
server_name example.com www.example.com;   # 복수 지정

server_name *.example.com;                 # 와일드카드 (앞부분)
server_name example.*;                     # 와일드카드 (뒷부분)

server_name ~^www\.(.+)\.com$;            # 정규식 (~ 접두사)

server_name "";                             # Host 헤더 없는 요청 처리
server_name _;                             # 모든 요청 매칭 (와일드카드 표현)
```

### server_name 매칭 우선순위

1. **정확히 일치**: `example.com`
2. **와일드카드 앞부분**: `*.example.com`
3. **와일드카드 뒷부분**: `example.*`
4. **정규식**: `~^www\.(.+)\.com$` (파일 순서대로 첫 번째 매칭)

---

## 서버 선택 로직

```
HTTP 요청 도착
→ listen 포트 매칭
→ server_name 으로 server 블록 선택
→ location 으로 세부 처리

매칭 실패 시 → default_server (없으면 conf.d/ 첫 번째 server 블록)
```

---

## root 와 alias

```nginx
server {
    root /var/www/html;   # 이 server의 기본 루트

    location /images/ {
        root /data;
        # 요청: /images/photo.jpg
        # 실제: /data/images/photo.jpg (root + 전체 URI)
    }

    location /downloads/ {
        alias /data/files/;
        # 요청: /downloads/file.zip
        # 실제: /data/files/file.zip (alias가 location 경로를 대체)
    }
}
```

**핵심 차이**: `root`는 URI 전체를 경로에 추가, `alias`는 location 경로 부분을 대체

---

## index

디렉토리 요청 시 기본 파일 목록입니다.

```nginx
index index.html index.htm index.php;
# 순서대로 존재 여부 확인, 첫 번째 존재 파일 반환
```

---

## error_page

에러 코드별 커스텀 응답을 지정합니다.

```nginx
error_page 404 /404.html;
error_page 500 502 503 504 /50x.html;

# 다른 URL로 리디렉션
error_page 404 = /not-found;

# 다른 상태 코드로 변경하여 응답
error_page 404 =200 /index.html;    # 404를 200으로 변경 (SPA에 유용)

# 외부 URL로 리디렉션
error_page 403 http://example.com/forbidden.html;

# named location 사용
error_page 404 @fallback;
location @fallback {
    proxy_pass http://backend;
}
```

---

## autoindex

디렉토리 목록 자동 생성을 활성화합니다.

```nginx
location /files/ {
    autoindex on;
    autoindex_exact_size off;   # 파일 크기를 KB/MB/GB로 표시
    autoindex_localtime on;     # 로컬 시간으로 표시
    autoindex_format html;      # html, xml, json, jsonp
}
```

---

## try_files

파일 존재 여부를 순서대로 확인하고 없으면 마지막 인자로 처리합니다.

```nginx
location / {
    try_files $uri $uri/ /index.html;
    # 1. 정확한 파일 확인: /var/www/html/path
    # 2. 디렉토리 확인: /var/www/html/path/
    # 3. 없으면 /index.html 반환 (SPA 라우팅)
}

location / {
    try_files $uri $uri/ =404;
    # 없으면 404 반환
}

# named location으로 폴백
location / {
    try_files $uri @backend;
}
location @backend {
    proxy_pass http://127.0.0.1:3000;
}
```

---

## 여러 서버 블록 예시

```nginx
# HTTP → HTTPS 리디렉션
server {
    listen 80;
    server_name example.com www.example.com;
    return 301 https://$host$request_uri;
}

# HTTPS 메인 서버
server {
    listen 443 ssl;
    server_name example.com www.example.com;

    ssl_certificate     /etc/nginx/ssl/example.com.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.key;

    root /var/www/example.com;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}

# 서브도메인
server {
    listen 443 ssl;
    server_name api.example.com;
    # ...
}

# IP 직접 접근 차단
server {
    listen 80 default_server;
    listen 443 ssl default_server;
    ssl_certificate     /etc/nginx/ssl/default.crt;
    ssl_certificate_key /etc/nginx/ssl/default.key;
    return 444;
}
```

---

## 포트 기반 가상 호스트

```nginx
server {
    listen 8080;
    server_name _;
    root /var/www/site1;
}

server {
    listen 8090;
    server_name _;
    root /var/www/site2;
}
```
