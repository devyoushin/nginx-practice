# 10. Reverse Proxy

nginx를 앞단에 두고 백엔드 서버로 요청을 전달합니다.

---

## proxy_pass 기본

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:3000;
    # 요청: /api/users  → 백엔드: /api/users (URI 그대로 전달)
}

location /api/ {
    proxy_pass http://127.0.0.1:3000/;
    # 요청: /api/users  → 백엔드: /users (슬래시 뒤로 URI 변환)
    # location 경로(/api/)가 / 로 치환됨
}
```

### URI 변환 규칙

```
proxy_pass에 URI가 있으면 (슬래시 포함):
  location /app/     + proxy_pass http://backend/service/
  요청: /app/page    → 백엔드: /service/page

proxy_pass에 URI가 없으면:
  location /app/     + proxy_pass http://backend
  요청: /app/page    → 백엔드: /app/page
```

---

## 헤더 설정

```nginx
location / {
    proxy_pass http://backend;

    # 원본 클라이언트 정보 전달 (필수 설정)
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-Port  $server_port;

    # keepalive 사용 시 필요
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    # 헤더 제거
    proxy_set_header Accept-Encoding "";    # 백엔드 압축 해제
}
```

### $proxy_add_x_forwarded_for

기존 `X-Forwarded-For` 헤더에 현재 클라이언트 IP를 추가합니다.

```
클라이언트(1.2.3.4) → Nginx(10.0.0.1) → 백엔드
X-Forwarded-For: 1.2.3.4                    ← nginx가 설정
                 1.2.3.4, 10.0.0.1          ← 체인이 있을 때
```

---

## 타임아웃 설정

```nginx
location / {
    proxy_pass http://backend;

    proxy_connect_timeout 5s;    # 백엔드 연결 타임아웃 (기본 60s)
    proxy_send_timeout    60s;   # 백엔드에 요청 전송 타임아웃 (기본 60s)
    proxy_read_timeout    60s;   # 백엔드 응답 대기 타임아웃 (기본 60s)
                                 # 두 read 사이의 간격 기준
}
```

긴 처리 시간이 필요한 API:

```nginx
location /long-task/ {
    proxy_pass http://backend;
    proxy_read_timeout 300s;     # 5분
}
```

---

## 버퍼 설정

```nginx
location / {
    proxy_pass http://backend;

    proxy_buffering on;              # 기본값 on, 백엔드 응답을 버퍼에 저장
    proxy_buffer_size 4k;            # 응답 첫 번째 부분 버퍼 (헤더)
    proxy_buffers 8 4k;              # 응답 본문 버퍼 (수 크기)
    proxy_busy_buffers_size 8k;      # 동시에 클라이언트로 보낼 버퍼 크기

    proxy_max_temp_file_size 1024m;  # 버퍼 초과 시 임시 파일 최대 크기
                                     # 0이면 파일 저장 비활성화
    proxy_temp_file_write_size 8k;   # 임시 파일 기록 단위
}
```

### 버퍼링 비활성화 (실시간 스트리밍, SSE)

```nginx
location /stream/ {
    proxy_pass http://backend;
    proxy_buffering off;          # 버퍼 없이 즉시 클라이언트로 전달
    proxy_cache off;
}
```

---

## 응답 헤더 조작

```nginx
location / {
    proxy_pass http://backend;

    # 백엔드 응답 헤더 숨기기
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;

    # 응답 헤더 추가
    add_header X-Proxy "nginx";

    # 응답 헤더 통과 설정 (기본적으로 일부 헤더는 필터링됨)
    proxy_pass_header Server;
}
```

---

## 쿠키 경로 재작성

```nginx
location /app/ {
    proxy_pass http://backend/;

    # 백엔드가 "/" 경로 쿠키를 설정할 때 "/app/"으로 변환
    proxy_cookie_path / /app/;

    # 쿠키 도메인 변환
    proxy_cookie_domain backend.internal example.com;
}
```

---

## proxy_intercept_errors

백엔드의 4xx/5xx 응답을 nginx의 error_page로 처리합니다.

```nginx
location / {
    proxy_pass http://backend;
    proxy_intercept_errors on;
    error_page 502 503 504 /maintenance.html;
}
```

---

## 요청 바디 처리

```nginx
location /upload/ {
    proxy_pass http://backend;

    client_max_body_size 100m;       # 큰 파일 업로드
    proxy_request_buffering on;      # 요청 바디 버퍼링 (기본 on)
                                     # off: 받으면서 즉시 백엔드로 스트리밍
}
```

---

## Snippet 파일로 재사용

반복되는 proxy 설정을 파일로 분리합니다.

`/etc/nginx/snippets/proxy-params.conf`:

```nginx
proxy_http_version 1.1;
proxy_set_header Connection        "";
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_connect_timeout 5s;
proxy_send_timeout    60s;
proxy_read_timeout    60s;
proxy_buffering       on;
```

사용:

```nginx
location /api/ {
    proxy_pass http://backend;
    include snippets/proxy-params.conf;
}
```

---

## 실전 구성: 포트별 라우팅

```nginx
upstream frontend { server 127.0.0.1:3000; }
upstream api      { server 127.0.0.1:8080; }
upstream admin    { server 127.0.0.1:9090; }

server {
    listen 443 ssl;
    server_name example.com;

    # React 프론트엔드
    location / {
        proxy_pass http://frontend;
        include snippets/proxy-params.conf;
    }

    # REST API
    location /api/ {
        proxy_pass http://api;
        include snippets/proxy-params.conf;
    }

    # 관리자 페이지 (IP 제한)
    location /admin/ {
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://admin;
        include snippets/proxy-params.conf;
    }
}
```
