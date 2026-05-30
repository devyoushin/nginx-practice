# 17. Rewrite, Redirect, map

---

## return

가장 빠르고 간단한 응답/리디렉션 방법입니다.

```nginx
# 리디렉션
return 301 https://$host$request_uri;       # 영구 리디렉션
return 302 https://$host$request_uri;       # 임시 리디렉션
return 307 https://new.example.com$request_uri;  # 307: 메서드 유지

# 응답 반환
return 200 "OK";
return 404;
return 403 "Forbidden";
return 444;    # nginx 전용: 응답 없이 연결 종료 (봇 차단)

# JSON 응답
location /health {
    return 200 '{"status":"ok"}';
    add_header Content-Type application/json;
}
```

---

## rewrite

URI를 내부적으로 재작성하거나 리디렉션합니다.

```nginx
rewrite ^/old-page$    /new-page    permanent;    # 301 리디렉션
rewrite ^/old-page$    /new-page    redirect;     # 302 리디렉션
rewrite ^/old/(.*)$    /new/$1      permanent;    # 캡처 그룹 활용
rewrite ^/(.*)$        /$1          break;        # 내부 재작성 후 처리 중단
rewrite ^/(.*)$        /$1          last;         # 내부 재작성 후 location 재매칭
```

### last vs break vs permanent vs redirect

| 플래그 | 동작 |
|--------|------|
| `last` | 재작성 후 location 블록 재매칭 (최대 10회 루프 방지) |
| `break` | 재작성 후 현재 블록에서 계속 처리 (재매칭 없음) |
| `permanent` | 301 외부 리디렉션 |
| `redirect` | 302 외부 리디렉션 |

```nginx
# last 예시: location 재매칭
server {
    rewrite ^/user/(.*)$ /profile?id=$1 last;

    location /profile {
        # 재매칭되어 이 블록이 처리
        proxy_pass http://backend;
    }
}

# break 예시: 파일 경로 재작성
location /images/ {
    rewrite ^/images/(.*)$ /data/img/$1 break;
    # 재매칭 없이 /data/img/... 파일 서빙
}
```

---

## if 지시어 (주의해서 사용)

nginx의 `if`는 C 언어의 `if`와 다르게 동작합니다.
"If is Evil" (https://www.nginx.com/resources/wiki/start/topics/depth/ifisevil/)

**권장**: `if` 대신 `map`, `try_files`, `return`을 사용하세요.

```nginx
# 허용되는 if 사용법 (return과 rewrite만)
if ($host = "old.example.com") {
    return 301 https://new.example.com$request_uri;
}

if ($request_method = POST) {
    return 405;
}

# 파일 존재 여부
if (-f $request_filename) {
    # 파일이 있으면
}
if (!-f $request_filename) {
    # 파일이 없으면
}
if (-d $request_filename) {
    # 디렉토리이면
}
if (-e $request_filename) {
    # 파일/디렉토리/심볼릭링크가 있으면
}
```

---

## map 모듈

변수를 다른 변수 값으로 매핑합니다. `if` 대신 사용하는 권장 방법입니다.

```nginx
http {
    # 단순 매핑
    map $request_method $is_get {
        GET     1;
        default 0;
    }

    # 와일드카드 매핑
    map $host $site_root {
        example.com     /var/www/example;
        ~^www\.(.+)$    /var/www/$1;
        default         /var/www/default;
    }

    # 정규식 매핑
    map $uri $new_uri {
        ~^/api/v1/(.+)$  /api/v2/$1;
        default          $uri;
    }

    # 여러 값에서 하나로 (첫 번째 매칭)
    map $http_user_agent $device {
        ~*(android|iphone|ipad)   mobile;
        default                   desktop;
    }
}

server {
    root $site_root;

    location / {
        if ($is_get = 0) {
            return 405;
        }
    }

    location /mobile/ {
        if ($device = mobile) {
            return 302 /m/;
        }
    }
}
```

### map + hostnames 플래그

도메인 와일드카드를 더 쉽게:

```nginx
map $host $canonical {
    hostnames;
    *.example.com   example.com;
    example.com     example.com;
    default         $host;
}
```

### map + volatile

캐시 없이 매 요청마다 평가:

```nginx
map $request_uri $no_cache {
    volatile;    # 캐시 비활성화
    ~^/admin/   1;
    default     0;
}
```

---

## geo 모듈

IP 주소 기반 변수 설정:

```nginx
http {
    geo $remote_addr $geo {
        default         unknown;
        127.0.0.1       local;
        192.168.0.0/24  internal;
        10.0.0.0/8      corporate;
    }

    # 프록시 뒤에 있을 때 실제 IP 사용
    geo $http_x_forwarded_for $geo {
        # ...
    }
}
```

---

## split_clients (A/B 테스팅)

요청을 특정 비율로 분배합니다.

```nginx
http {
    split_clients "${remote_addr}${uri}" $variant {
        33.3%   "a";
        33.3%   "b";
        *       "c";
    }
}

server {
    location / {
        proxy_pass http://backend-$variant;
    }
}
```

---

## 실전 패턴 모음

```nginx
# www → non-www 리디렉션
server {
    listen 80;
    server_name www.example.com;
    return 301 https://example.com$request_uri;
}

# URL 정규화: 끝 슬래시 제거
if ($request_uri ~ ^/(.+)/$) {
    return 301 /$1;
}

# 대소문자 정규화 (소문자로)
rewrite ^/([A-Z].*)$ /$1 redirect;

# 확장자 없는 URL에서 .html 찾기
location / {
    try_files $uri $uri.html $uri/ =404;
}

# API 버전 업그레이드
location /api/v1/ {
    rewrite ^/api/v1/(.*)$ /api/v2/$1 permanent;
}

# 유지보수 모드
map $remote_addr $maintenance {
    127.0.0.1   0;    # 관리자 IP는 허용
    default     1;
}

server {
    if ($maintenance) {
        return 503;
    }
    error_page 503 /maintenance.html;
}
```
