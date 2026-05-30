# 21. 내장 변수 (Built-in Variables)

nginx는 설정 파일에서 다양한 내장 변수를 사용할 수 있습니다.
변수는 `$` 접두사로 시작합니다.

---

## 요청 관련 변수

```
$request               전체 요청 라인 ("GET /path?query HTTP/1.1")
$request_method        HTTP 메서드 (GET, POST, PUT 등)
$request_uri           원본 요청 URI (경로 + 쿼리, 인코딩 포함, rewrite 전)
$uri                   현재 요청 URI (정규화됨, rewrite로 변경될 수 있음, 쿼리 미포함)
$document_uri          $uri의 별칭
$args                  쿼리 스트링 (? 이후 전체)
$arg_NAME              특정 쿼리 파라미터 값: $arg_id, $arg_page
$query_string          $args의 별칭
$is_args               쿼리 스트링이 있으면 "?", 없으면 ""
$request_body          요청 바디 (proxy_pass, fastcgi_pass 사용 시)
$request_filename      요청에 대응하는 파일 전체 경로 ($document_root + $uri)
$request_length        요청 전체 크기 (바이트)
$request_time          요청 처리 시간 (초, ms 소수점)
$request_completion    완료된 요청이면 "OK", 아니면 ""
$request_id            16바이트 랜덤 요청 ID (hex, 1.11.0+)
$content_length        Content-Length 요청 헤더
$content_type          Content-Type 요청 헤더
```

---

## 클라이언트 관련 변수

```
$remote_addr           클라이언트 IP 주소
$remote_port           클라이언트 포트
$remote_user           Basic Auth 사용자명 (인증된 경우)
$binary_remote_addr    클라이언트 IP (바이너리, 4/16바이트)
                       limit_req_zone의 키로 메모리 효율적
```

---

## 서버 관련 변수

```
$server_name           매칭된 server_name 값
$server_addr           서버 IP 주소 (요청을 처리한 인터페이스)
$server_port           서버 포트
$server_protocol       요청 프로토콜 (HTTP/1.0, HTTP/1.1, HTTP/2.0)
$hostname              서버 호스트명 (OS hostname)
```

---

## HTTP 헤더 변수

요청 헤더는 `$http_헤더명` 형식으로 접근합니다 (소문자, 하이픈→언더스코어).

```
$http_host             Host 헤더
$http_user_agent       User-Agent 헤더
$http_referer          Referer 헤더
$http_cookie           Cookie 헤더 전체
$http_x_forwarded_for  X-Forwarded-For 헤더
$http_x_real_ip        X-Real-IP 헤더
$http_authorization    Authorization 헤더
$http_accept           Accept 헤더
$http_accept_encoding  Accept-Encoding 헤더
$http_accept_language  Accept-Language 헤더
$http_upgrade          Upgrade 헤더 (WebSocket)
$http_origin           Origin 헤더 (CORS)
$http_cache_control    Cache-Control 헤더

# 임의 헤더: X-Custom-Header → $http_x_custom_header
```

---

## 응답 헤더 변수

```
$sent_http_헤더명      전송된 응답 헤더
$sent_http_content_type
$sent_http_content_length
$sent_http_location
$sent_http_last_modified
$sent_http_etag

$status                HTTP 응답 상태 코드
$body_bytes_sent       응답 바디 크기 (헤더 제외)
$bytes_sent            응답 전체 크기 (헤더 포함)
```

---

## 업스트림(프록시) 관련 변수

```
$upstream_addr              업스트림 서버 주소 (IP:포트)
$upstream_status            업스트림 HTTP 상태 코드
$upstream_response_time     업스트림 응답 시간 (초)
$upstream_response_length   업스트림 응답 크기
$upstream_cache_status      캐시 상태 (HIT, MISS, BYPASS 등)
$upstream_connect_time      업스트림 연결 시간
$upstream_header_time       업스트림 헤더 수신 시간
$upstream_bytes_received    업스트림에서 받은 바이트 수
$upstream_bytes_sent        업스트림으로 보낸 바이트 수
```

여러 업스트림 서버를 거쳤으면 쉼표로 구분됩니다:
`$upstream_addr = "192.168.1.10:8080, 192.168.1.11:8080"`

---

## SSL/TLS 변수

```
$ssl_protocol              TLS 버전 (TLSv1.2, TLSv1.3)
$ssl_cipher                암호화 알고리즘
$ssl_session_id            SSL 세션 ID
$ssl_session_reused        세션 재사용 여부 (r 또는 .)
$ssl_early_data            TLS 1.3 0-RTT 데이터 사용 여부
$https                     HTTPS이면 "on", 아니면 ""

# 클라이언트 인증서 (mTLS)
$ssl_client_cert           클라이언트 인증서 (PEM)
$ssl_client_raw_cert       클라이언트 인증서 (raw PEM)
$ssl_client_s_dn           클라이언트 인증서 DN
$ssl_client_i_dn           발급자 DN
$ssl_client_serial         인증서 시리얼 번호
$ssl_client_fingerprint    인증서 SHA1 핑거프린트
$ssl_client_verify         검증 결과 (SUCCESS, FAILED, NONE)
$ssl_client_v_start        인증서 유효 시작일
$ssl_client_v_end          인증서 만료일
$ssl_client_v_remain       만료까지 남은 일수
```

---

## 시간 관련 변수

```
$time_local                로컬 시간 "01/Jan/2024:12:00:00 +0900"
$time_iso8601              ISO 8601 "2024-01-01T12:00:00+09:00"
$msec                      밀리초 포함 유닉스 타임스탬프 "1704067200.123"
$nginx_version             nginx 버전
$pid                       Worker 프로세스 PID
$connection                연결 번호
$connection_requests       현재 연결에서의 요청 수
$pipe                      파이프라인 요청이면 "p", 아니면 "."
```

---

## 기타 유용한 변수

```
$host          Host 헤더 값 (없으면 server_name)
$scheme        요청 스키마 (http 또는 https)
$document_root root/alias 지시어로 설정된 루트 경로
$realpath_root $document_root의 실제 경로 (심볼릭 링크 해결)
$limit_rate    현재 응답 속도 제한값
$cookie_NAME   쿠키 값: $cookie_session, $cookie_user_id
```

---

## 변수 활용 예시

```nginx
# 조건부 로그
map $status $log_it {
    ~^[23] 0;
    default 1;
}
access_log /var/log/nginx/error_only.log combined if=$log_it;

# 동적 업스트림 선택
map $http_x_api_version $backend {
    "v2"    backend_v2;
    default backend_v1;
}
location /api/ {
    proxy_pass http://$backend;
}

# 쿼리 파라미터 기반 분기
location / {
    if ($arg_debug = "1") {
        access_log /var/log/nginx/debug.log;
    }
}

# 요청 ID를 응답 헤더로 추가 (추적용)
add_header X-Request-ID $request_id;
proxy_set_header X-Request-ID $request_id;

# HTTPS 강제 변수 활용
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-SSL   $https;
```

---

## 변수 설정 (set 지시어)

```nginx
location / {
    set $my_var "hello";
    set $combined "$host-$remote_addr";

    add_header X-Debug $combined;
}
```
