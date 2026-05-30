# 06. HTTP 모듈 (http context)

http 블록은 모든 HTTP 처리의 전역 설정을 담당합니다.

---

## MIME 타입

```nginx
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
}
```

### mime.types 파일 구조

```nginx
types {
    text/html                    html htm shtml;
    text/css                     css;
    text/javascript              js;
    application/json             json;
    image/jpeg                   jpeg jpg;
    image/png                    png;
    image/svg+xml                svg svgz;
    application/pdf              pdf;
    video/mp4                    mp4;
    # ... 수백 가지 매핑
}
```

커스텀 MIME 타입 추가:

```nginx
types {
    include /etc/nginx/mime.types;
    application/wasm wasm;
    font/woff2 woff2;
}
```

---

## sendfile

커널 공간에서 파일을 직접 소켓으로 전송합니다 (zero-copy).

```nginx
sendfile on;       # 권장 (정적 파일 서빙 시 필수)
sendfile off;      # 기본값
```

### 일반 방식 vs sendfile

```
일반 방식:
디스크 → 커널 버퍼 → 유저 공간(nginx) → 커널 소켓 버퍼 → 네트워크
(데이터 복사 2회)

sendfile:
디스크 → 커널 버퍼 → 커널 소켓 버퍼 → 네트워크
(데이터 복사 1회, CPU 사용량 감소)
```

---

## tcp_nopush / tcp_nodelay

```nginx
tcp_nopush on;     # sendfile on 필요, 패킷 최대화하여 전송
tcp_nodelay on;    # Nagle 알고리즘 비활성화, 즉시 전송 (기본 on)
```

### 조합 권장

```nginx
sendfile    on;
tcp_nopush  on;    # 응답 헤더와 파일 시작 부분을 하나의 패킷에
tcp_nodelay on;    # keepalive 연결에서 즉시 전송
```

`tcp_nopush`와 `tcp_nodelay`를 같이 켜면 nginx가 최적 조합으로 동작합니다.

---

## keepalive

HTTP keepalive로 하나의 TCP 연결로 여러 요청을 처리합니다.

```nginx
keepalive_timeout 65;       # 연결 유지 시간(초), 0이면 비활성화
keepalive_timeout 65 60;    # 두 번째 값은 클라이언트에 전달하는 Keep-Alive 헤더 값
keepalive_requests 1000;    # 하나의 keepalive 연결로 처리할 최대 요청 수
keepalive_time 1h;          # keepalive 연결의 최대 총 유지 시간 (1.19.10+)
```

---

## 클라이언트 요청 크기 제한

```nginx
client_max_body_size 1m;           # 요청 바디 최대 크기 (기본 1m)
                                   # 0이면 제한 없음, 파일 업로드 시 늘려야 함
client_body_buffer_size 128k;      # 요청 바디 버퍼 크기
                                   # 초과 시 임시 파일에 저장
client_header_buffer_size 1k;      # 요청 헤더 버퍼
large_client_header_buffers 4 8k;  # 큰 헤더 처리를 위한 버퍼 (수 크기)
```

---

## 타임아웃 설정

```nginx
client_header_timeout 10s;    # 요청 헤더 수신 타임아웃
client_body_timeout 10s;      # 요청 바디 수신 타임아웃 (두 read 사이의 간격)
send_timeout 10s;              # 클라이언트로 응답 전송 타임아웃
reset_timedout_connection on;  # 타임아웃된 연결 즉시 RST (TIME_WAIT 감소)
```

---

## 서버 토큰 (버전 노출 제어)

```nginx
server_tokens off;    # nginx 버전 숨김 (보안 권장)
server_tokens on;     # 기본값: "nginx/1.24.0" 노출
server_tokens build;  # 빌드 이름도 포함
```

---

## 해시 테이블 설정

nginx는 server_names, MIME types 등을 해시 테이블로 저장합니다.

```nginx
server_names_hash_bucket_size 64;    # server_name 해시 버킷 크기
server_names_hash_max_size 512;      # 해시 테이블 최대 크기
types_hash_max_size 2048;            # MIME 타입 해시 크기
types_hash_bucket_size 64;
variables_hash_max_size 2048;
variables_hash_bucket_size 128;
```

긴 도메인 이름 사용 시 `server_names_hash_bucket_size`를 늘려야 합니다.

---

## 요청 처리 관련

```nginx
ignore_invalid_headers on;         # 잘못된 헤더 이름 무시 (기본 on)
underscores_in_headers on;         # 언더스코어 포함 헤더 허용 (기본 off)
                                   # off 시 언더스코어 헤더는 무시됨
merge_slashes on;                  # // → / 정규화 (기본 on)
```

---

## 출력 버퍼링

```nginx
output_buffers 2 32k;      # 출력 버퍼 수와 크기
postpone_output 1460;      # 이 크기 이상 쌓이면 전송 (MSS 단위)
```

---

## 파일 캐시 (Open File Cache)

자주 요청되는 파일의 fd(파일 디스크립터), 크기, 수정시간을 캐싱합니다.

```nginx
open_file_cache max=1000 inactive=20s;
# max: 캐시 최대 항목 수
# inactive: 이 시간 동안 접근 없으면 제거

open_file_cache_valid 30s;       # 캐시 유효성 재검사 간격
open_file_cache_min_uses 2;      # inactive 기간 동안 최소 요청 수 (캐시 유지 조건)
open_file_cache_errors on;       # 파일 없음(ENOENT) 등의 오류도 캐싱
```

---

## 재귀 처리 제한

```nginx
recursive_error_pages on;    # error_page에서 error_page로 재귀 허용
```

---

## HTTP 버전

```nginx
# HTTP/2는 ssl 설정과 함께 listen에서 활성화
server {
    listen 443 ssl;
    http2 on;          # nginx 1.25.1+ 방식
    # 이전 방식: listen 443 ssl http2;
}
```

---

## 실운영 권장 http 블록 기본 설정

```nginx
http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # 성능
    sendfile           on;
    tcp_nopush         on;
    tcp_nodelay        on;

    # keepalive
    keepalive_timeout  65;
    keepalive_requests 1000;

    # 보안
    server_tokens off;
    underscores_in_headers off;

    # 크기 제한
    client_max_body_size 10m;
    client_header_timeout 10s;
    client_body_timeout  10s;
    send_timeout         10s;
    reset_timedout_connection on;

    # 파일 캐시
    open_file_cache max=10000 inactive=20s;
    open_file_cache_valid 30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # 해시
    server_names_hash_bucket_size 64;

    include /etc/nginx/conf.d/*.conf;
}
```
