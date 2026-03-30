# 08. Location 블록

location 블록은 URI 패턴에 따라 요청을 다르게 처리합니다.
nginx에서 가장 자주 사용하고 가장 중요한 블록입니다.

---

## 매칭 수식어 (Modifier)

```nginx
location = /exact { }      # 정확히 일치 (exact match)
location ^~ /prefix/ { }   # 접두사 일치, 정규식 검사 중단
location /prefix/ { }      # 접두사 일치 (가장 긴 것 우선)
location ~ /regex/ { }     # 정규식 일치 (대소문자 구분)
location ~* /regex/ { }    # 정규식 일치 (대소문자 무시)
location @name { }         # Named location (내부 리디렉션용)
```

---

## 매칭 우선순위 (중요!)

```
1순위: = (정확 일치)       → 매칭 시 즉시 사용, 탐색 종료
2순위: ^~ (접두사 + 정규식 차단)  → 매칭 시 정규식 검사 없이 사용
3순위: ~ 또는 ~* (정규식)  → 설정 파일 순서대로 첫 번째 매칭
4순위: /prefix/ (접두사)   → 가장 길게 매칭되는 것 선택
5순위: / (기본)            → 아무것도 안 맞으면 여기
```

### 예시로 이해하기

```nginx
location = / {
    # 오직 "/" 요청만 (가장 빠름)
}

location / {
    # 모든 요청의 폴백
}

location /images/ {
    # /images/로 시작하는 모든 요청
}

location ^~ /static/ {
    # /static/으로 시작하면 정규식 검사 없이 바로 여기
    root /data;
}

location ~* \.(jpg|jpeg|png|gif|webp)$ {
    # 이미지 파일 확장자 (대소문자 무시)
    expires 30d;
}

location ~ \.php$ {
    # PHP 파일 처리
    fastcgi_pass unix:/run/php-fpm.sock;
}
```

### 매칭 순서 추적 예시

요청: `GET /images/photo.jpg`

```
1. = /images/photo.jpg   → 불일치
2. ^~ /images/           → 일치! → 정규식 건너뜀, 이 location 사용
   (만약 ^~가 없다면: ~* \.(jpg)$ 가 사용됨)
```

---

## 중첩 location

location 안에 location을 중첩할 수 있습니다.

```nginx
location /api/ {
    proxy_pass http://api-backend;

    location /api/admin/ {
        # /api/admin/에만 추가 인증
        auth_basic "Admin Area";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://api-backend;
    }
}
```

**주의**: 정규식 location 안에 중첩은 불가능합니다.

---

## Named Location (@name)

내부 리디렉션을 위한 특수한 location입니다.
외부 클라이언트가 직접 접근 불가능합니다.

```nginx
location / {
    try_files $uri @backend;
}

location @backend {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
}
```

`error_page`와 함께 자주 사용됩니다:

```nginx
error_page 404 @notfound;

location @notfound {
    return 200 '{"error": "not found"}';
    add_header Content-Type application/json;
}
```

---

## 파일/디렉토리 처리

```nginx
location /files/ {
    root /data;

    # 파일 없을 때 처리
    try_files $uri $uri/ =404;

    # 디렉토리 목록
    autoindex on;

    # 특정 파일 직접 반환
    location = /files/secret.txt {
        return 403;
    }
}
```

---

## 정적 파일 최적화 location

```nginx
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
    access_log off;    # 정적 파일 로그 생략으로 I/O 감소
    log_not_found off; # 없는 파일 에러 로그 억제
}
```

---

## internal 지시어

해당 location을 내부 리디렉션 전용으로 만듭니다.
외부 요청이 직접 접근하면 404를 반환합니다.

```nginx
location /internal-only/ {
    internal;
    root /data/private;
}

# error_page나 X-Accel-Redirect로만 접근 가능
location /download/ {
    # 애플리케이션이 인증 확인 후 X-Accel-Redirect 헤더로 보냄
    proxy_pass http://app;
    proxy_intercept_errors on;
}
```

### X-Accel-Redirect (내부 리디렉션)

애플리케이션에서 파일 접근 제어 후 nginx가 파일을 직접 전송하는 패턴:

```nginx
# 앱 서버가 Authorization 확인 후 헤더 응답
# X-Accel-Redirect: /protected/file.zip

location /protected/ {
    internal;
    root /data;
}
```

---

## limit_except

허용할 HTTP 메서드 외 나머지를 차단합니다.

```nginx
location /api/ {
    limit_except GET POST {
        deny all;    # GET, POST 외 모두 차단
    }
}
```

---

## 실전 location 패턴 모음

```nginx
# SPA (Single Page Application)
location / {
    try_files $uri $uri/ /index.html;
}

# API 프록시
location /api/ {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}

# PHP
location ~ \.php$ {
    fastcgi_pass unix:/run/php-fpm/php-fpm.sock;
    fastcgi_index index.php;
    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
}

# .htaccess 접근 차단
location ~ /\. {
    deny all;
    access_log off;
    log_not_found off;
}

# favicon 로그 억제
location = /favicon.ico {
    log_not_found off;
    access_log off;
}

# robots.txt
location = /robots.txt {
    log_not_found off;
    access_log off;
}

# 특정 파일 확장자 차단
location ~* \.(git|env|sql|bak|conf|log)$ {
    deny all;
    return 404;
}
```
