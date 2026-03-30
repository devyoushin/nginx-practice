# 12. 캐싱

---

## proxy_cache (HTTP 프록시 캐시)

백엔드 응답을 디스크에 캐싱합니다.

### 캐시 경로 정의 (http 블록)

```nginx
http {
    proxy_cache_path /var/cache/nginx/proxy
        levels=1:2                   # 디렉토리 계층 (파일 수 분산)
        keys_zone=my_cache:10m       # 캐시 키를 저장할 공유 메모리 이름:크기
        max_size=1g                  # 캐시 최대 크기 (초과 시 LRU 삭제)
        inactive=60m                 # 이 시간 동안 요청 없으면 삭제
        use_temp_path=off;           # 임시 파일 없이 직접 저장 (성능↑)
}
```

### location에서 캐시 활성화

```nginx
location /api/ {
    proxy_pass http://backend;

    proxy_cache           my_cache;
    proxy_cache_valid     200 302 10m;   # 200/302 응답을 10분 캐싱
    proxy_cache_valid     404     1m;    # 404는 1분
    proxy_cache_valid     any    30s;    # 나머지는 30초

    proxy_cache_key       "$scheme$request_method$host$request_uri";
    # 기본 키는 $scheme$proxy_host$request_uri

    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    # 백엔드 오류 시 오래된 캐시라도 반환

    proxy_cache_lock on;      # 동일 요청 동시 접근 시 하나만 백엔드로 (thundering herd 방지)
    proxy_cache_lock_timeout 5s;

    add_header X-Cache-Status $upstream_cache_status;   # 캐시 히트 여부 헤더
}
```

### $upstream_cache_status 값

| 값 | 의미 |
|----|------|
| `HIT` | 캐시에서 응답 |
| `MISS` | 캐시 없어 백엔드 요청 |
| `BYPASS` | proxy_cache_bypass 조건 충족 |
| `EXPIRED` | 캐시 만료, 백엔드 재요청 |
| `STALE` | 만료됐지만 use_stale로 반환 |
| `UPDATING` | 업데이트 중, 이전 캐시 반환 |
| `REVALIDATED` | 조건부 요청으로 재검증 |

---

## 캐시 우회 (bypass)

특정 조건에서 캐시를 건너뜁니다.

```nginx
location /api/ {
    proxy_cache my_cache;

    # 쿠키 있으면 캐시 우회
    proxy_cache_bypass $cookie_session;

    # 특정 헤더 있으면 캐시 안 함
    proxy_no_cache $http_pragma $http_authorization;
    # 값이 비어있지 않으면 캐시 저장 안 함

    # Cache-Control: no-cache 헤더 존중
    proxy_cache_bypass $http_cache_control;
}
```

---

## 캐시에서 제외할 메서드

```nginx
location /api/ {
    proxy_cache my_cache;

    # GET/HEAD만 캐싱 (POST, PUT, DELETE 등은 자동으로 캐싱 안 됨)
    proxy_cache_methods GET HEAD;
}
```

---

## Cache-Control 헤더 처리

```nginx
location / {
    proxy_pass http://backend;
    proxy_cache my_cache;

    # 백엔드의 Cache-Control, Expires 헤더 무시하고 강제 캐싱
    proxy_ignore_headers Cache-Control Expires;
    proxy_cache_valid 200 1h;

    # X-Accel-Expires 헤더는 무시
    proxy_ignore_headers X-Accel-Expires;
}
```

---

## proxy_cache_revalidate

캐시 만료 시 `If-Modified-Since`로 조건부 요청합니다.

```nginx
proxy_cache_revalidate on;
```

변경 없으면 304 Not Modified → 캐시 갱신, 백엔드 응답 바디 전송 없음.

---

## fastcgi_cache (PHP 캐시)

FastCGI(PHP-FPM) 응답을 캐싱합니다.

```nginx
http {
    fastcgi_cache_path /var/cache/nginx/fastcgi
        levels=1:2
        keys_zone=php_cache:10m
        max_size=500m
        inactive=60m;
}

server {
    location ~ \.php$ {
        fastcgi_pass unix:/run/php-fpm.sock;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;

        fastcgi_cache           php_cache;
        fastcgi_cache_valid     200 1h;
        fastcgi_cache_key       "$request_method$host$request_uri";
        fastcgi_cache_use_stale error timeout updating;

        add_header X-Cache-Status $upstream_cache_status;

        # 로그인된 사용자는 캐시 우회
        fastcgi_cache_bypass $cookie_PHPSESSID;
        fastcgi_no_cache     $cookie_PHPSESSID;
    }
}
```

---

## 캐시 Purge (삭제)

오픈소스 nginx에서는 기본 purge 기능이 없습니다.
`proxy_cache_purge` 모듈 또는 캐시 파일 직접 삭제 방법을 사용합니다.

### 캐시 파일 직접 삭제

```bash
# 전체 캐시 삭제
find /var/cache/nginx/proxy -type f -delete

# 특정 패턴
find /var/cache/nginx/proxy -type f -name "*.tmp" -delete
```

### ngx_cache_purge 모듈 (서드파티)

```nginx
proxy_cache_purge PURGE from 127.0.0.1;

location ~ /purge(/.*) {
    allow 127.0.0.1;
    deny all;
    proxy_cache_purge my_cache $scheme$host$1;
}
```

```bash
curl -X PURGE http://example.com/api/users
```

---

## 정적 파일 클라이언트 캐싱

nginx에서 `Expires`/`Cache-Control` 헤더를 설정합니다.

```nginx
location ~* \.(css|js)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}

location ~* \.(jpg|jpeg|png|gif|webp|svg|ico)$ {
    expires 30d;
    add_header Cache-Control "public";
}

location ~* \.(html)$ {
    expires -1;                              # 캐싱 안 함
    add_header Cache-Control "no-store";
}

# 버전 없는 파일은 짧게
location ~* \.(?:css|js)$ {
    expires 1h;
    add_header Cache-Control "public";
    add_header Vary Accept-Encoding;
}
```

---

## Vary 헤더

동일 URL이라도 Accept-Encoding에 따라 다른 응답이 캐싱되도록 합니다.

```nginx
add_header Vary Accept-Encoding;
```

---

## 캐시 디렉토리 관리

```bash
# 캐시 용량 확인
du -sh /var/cache/nginx/

# 캐시 파일 수 확인
find /var/cache/nginx/proxy -type f | wc -l

# levels=1:2 구조 예시
# /var/cache/nginx/proxy/a/bc/abcdef123456...
```
