# 18. FastCGI & PHP-FPM

---

## FastCGI 개요

FastCGI는 웹 서버와 외부 프로세스(PHP-FPM 등)가 통신하는 프로토콜입니다.

```
클라이언트 → nginx (HTTP) → PHP-FPM (FastCGI) → PHP 스크립트
```

Apache가 PHP를 mod_php로 내장하는 것과 달리,
nginx는 외부 PHP-FPM 프로세스에 요청을 전달합니다.

---

## PHP-FPM 설치 (AL2023)

```bash
# PHP 및 PHP-FPM 설치
sudo dnf install php php-fpm php-mysqlnd php-mbstring php-xml php-gd

# 버전 확인
php --version

# PHP-FPM 서비스 시작
sudo systemctl enable --now php-fpm

# 상태 확인
systemctl status php-fpm
```

### PHP-FPM 설정 파일

```
/etc/php-fpm.conf               ← 전역 설정
/etc/php-fpm.d/www.conf         ← www 풀 설정
/etc/php.ini                    ← PHP 설정
```

`/etc/php-fpm.d/www.conf` 주요 설정:

```ini
[www]
user = nginx            ; nginx와 같은 사용자 (파일 권한 일치)
group = nginx

; Unix Socket (추천, TCP보다 빠름)
listen = /run/php-fpm/www.sock
listen.owner = nginx
listen.group = nginx
listen.mode = 0660

; 또는 TCP
; listen = 127.0.0.1:9000

pm = dynamic
pm.max_children = 50
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 35
pm.max_requests = 500     ; 이 횟수 후 Worker 재시작 (메모리 누수 방지)
```

---

## nginx 기본 PHP FastCGI 설정

```nginx
server {
    listen 80;
    server_name example.com;
    root /var/www/html;
    index index.php index.html;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
        # URI에 해당하는 파일/디렉토리 없으면 index.php로 (Laravel, WordPress 등)
    }

    location ~ \.php$ {
        # 파일 없음 방지 (Path Traversal 보안)
        try_files $fastcgi_script_name =404;

        # Unix Socket
        fastcgi_pass unix:/run/php-fpm/www.sock;
        # 또는 TCP
        # fastcgi_pass 127.0.0.1:9000;

        fastcgi_index index.php;
        include fastcgi_params;

        # SCRIPT_FILENAME 필수: 실행할 PHP 파일 절대 경로
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param PATH_INFO $fastcgi_path_info;
    }

    # PHP 파일 직접 접근 차단 (uploads 등)
    location ~* /(?:uploads|files)/.*\.php$ {
        deny all;
    }
}
```

---

## fastcgi_params vs fastcgi.conf

```bash
# 차이점 확인
diff /etc/nginx/fastcgi_params /etc/nginx/fastcgi.conf
# fastcgi.conf에는 SCRIPT_FILENAME 라인이 추가되어 있음
```

`fastcgi.conf` 사용 시 SCRIPT_FILENAME 중복 선언 불필요:

```nginx
location ~ \.php$ {
    fastcgi_pass unix:/run/php-fpm/www.sock;
    fastcgi_index index.php;
    include fastcgi.conf;    # SCRIPT_FILENAME 포함
}
```

---

## FastCGI 주요 파라미터

```nginx
location ~ \.php$ {
    fastcgi_pass unix:/run/php-fpm/www.sock;
    include fastcgi_params;

    fastcgi_param SCRIPT_FILENAME  $document_root$fastcgi_script_name;
    fastcgi_param DOCUMENT_ROOT    $document_root;
    fastcgi_param SERVER_NAME      $host;
    fastcgi_param HTTPS            $https if_not_empty;
    fastcgi_param HTTP_PROXY       "";    # HTTPoxy 취약점 방어

    # 타임아웃
    fastcgi_connect_timeout 60s;
    fastcgi_send_timeout    60s;
    fastcgi_read_timeout    60s;

    # 버퍼
    fastcgi_buffer_size          128k;
    fastcgi_buffers              4 256k;
    fastcgi_busy_buffers_size    256k;
}
```

---

## fastcgi_cache (FastCGI 응답 캐싱)

```nginx
http {
    fastcgi_cache_path /var/cache/nginx/fastcgi
        levels=1:2
        keys_zone=php_cache:10m
        max_size=500m
        inactive=60m
        use_temp_path=off;
}

server {
    # 캐시 우회 조건
    set $skip_cache 0;

    if ($request_method = POST)       { set $skip_cache 1; }
    if ($query_string != "")          { set $skip_cache 1; }
    if ($request_uri ~* "/admin/")    { set $skip_cache 1; }
    if ($http_cookie ~* "PHPSESSID")  { set $skip_cache 1; }

    location ~ \.php$ {
        fastcgi_pass unix:/run/php-fpm/www.sock;
        include fastcgi.conf;

        fastcgi_cache           php_cache;
        fastcgi_cache_valid     200 1h;
        fastcgi_cache_key       "$scheme$request_method$host$request_uri";
        fastcgi_cache_bypass    $skip_cache;
        fastcgi_no_cache        $skip_cache;
        fastcgi_cache_use_stale error timeout updating;

        add_header X-Cache-Status $upstream_cache_status;
    }
}
```

---

## WordPress 최적화 설정 예시

```nginx
server {
    listen 443 ssl;
    server_name example.com www.example.com;
    root /var/www/wordpress;
    index index.php;

    # 정적 파일 캐싱
    location ~* \.(css|js|jpg|jpeg|png|gif|ico|woff|woff2|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # WordPress 퍼머링크
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # robots.txt, favicon
    location = /favicon.ico { log_not_found off; access_log off; }
    location = /robots.txt  { log_not_found off; access_log off; }

    # 업로드 디렉토리 PHP 차단
    location ~* /(?:uploads|files|wp-content)/.*\.php$ { deny all; }

    # XML-RPC 차단 (불필요 시)
    location = /xmlrpc.php { deny all; }

    # .htaccess 등 숨김 파일 차단
    location ~ /\. { deny all; }

    # PHP 처리
    location ~ \.php$ {
        try_files $fastcgi_script_name =404;
        fastcgi_pass unix:/run/php-fpm/www.sock;
        include fastcgi.conf;
        fastcgi_param HTTPS $https if_not_empty;
    }
}
```

---

## PHP-FPM 상태 페이지

```nginx
location ~ ^/(status|ping)$ {
    access_log off;
    allow 127.0.0.1;
    deny all;
    fastcgi_pass unix:/run/php-fpm/www.sock;
    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME $fastcgi_script_name;
}
```

```bash
# PHP-FPM 상태 확인
curl http://127.0.0.1/status
curl http://127.0.0.1/status?full
curl http://127.0.0.1/ping
```
