# 14. 압축 (Gzip / Brotli)

---

## Gzip 기본 설정

```nginx
http {
    gzip on;                      # 압축 활성화
    gzip_vary on;                 # Vary: Accept-Encoding 헤더 추가
    gzip_proxied any;             # 프록시된 요청도 압축
    gzip_comp_level 6;            # 압축 레벨 (1~9, 기본 1)
                                  # 6이 속도/압축률 균형점
    gzip_buffers 16 8k;           # 압축 버퍼
    gzip_http_version 1.1;        # HTTP/1.1 이상에서만 압축
    gzip_min_length 256;          # 이 크기 이상만 압축 (바이트)
                                  # 작은 파일 압축은 오히려 손해
    gzip_types
        text/plain
        text/css
        text/javascript
        application/javascript
        application/json
        application/xml
        application/rss+xml
        application/atom+xml
        image/svg+xml
        font/truetype
        font/opentype
        application/vnd.ms-fontobject;
    # text/html은 항상 압축됨 (명시 불필요)
    # 이미지(jpg, png 등)는 이미 압축됨 → 제외
}
```

---

## gzip_proxied

프록시 서버를 통한 요청에 대한 압축 정책입니다.

```nginx
gzip_proxied off;          # 프록시 요청 압축 안 함 (기본)
gzip_proxied expired;      # 캐시 만료된 응답
gzip_proxied no-cache;     # Cache-Control: no-cache
gzip_proxied no-store;     # Cache-Control: no-store
gzip_proxied private;      # Cache-Control: private
gzip_proxied no_last_modified;  # Last-Modified 헤더 없는 경우
gzip_proxied no_etag;      # ETag 헤더 없는 경우
gzip_proxied auth;         # Authorization 헤더 있는 경우
gzip_proxied any;          # 모든 프록시 요청 압축 (권장)
```

---

## gzip_static

사전 압축된 `.gz` 파일을 제공합니다.
동적 압축 대신 미리 압축한 파일을 전송하므로 CPU 부하 없음.

```nginx
location /static/ {
    gzip_static on;    # .gz 파일이 있으면 우선 전송
    root /var/www;
}
```

파일 준비:

```bash
# 배포 시 미리 압축
gzip -k -9 /var/www/static/app.js        # app.js.gz 생성
gzip -k -9 /var/www/static/style.css     # style.css.gz 생성

# 또는 zopfli (더 나은 압축률, 느림)
zopfli /var/www/static/app.js

# nginx는 app.js 요청 시 Accept-Encoding: gzip이면 app.js.gz 전송
```

---

## gzip_disable

특정 User-Agent에 대해 압축 비활성화합니다.

```nginx
gzip_disable "msie6";                    # IE6 압축 버그 대응
gzip_disable "MSIE [1-6]\.(?!.*SV1)";   # IE 1~6 (SV1 패치 제외)
```

---

## 압축 확인

```bash
# gzip 압축 확인
curl -H "Accept-Encoding: gzip" -I http://example.com/style.css
# Content-Encoding: gzip 헤더가 있어야 함

# 압축된 응답 크기 vs 원본 크기
curl -H "Accept-Encoding: gzip" -s http://example.com/app.js | wc -c
curl -s http://example.com/app.js | wc -c
```

---

## Brotli 압축 (서드파티 모듈)

Gzip보다 20~26% 높은 압축률입니다.
nginx 오픈소스는 기본 포함되지 않아 모듈 추가 필요합니다.

### ngx_brotli 모듈 설치 방법

RPM 기반 설치 시 별도로 빌드해야 합니다.

```bash
# 빌드 의존성
sudo dnf install gcc gcc-c++ make pcre2-devel openssl-devel zlib-devel git

# nginx 소스 코드 다운로드 (설치된 버전과 동일)
nginx_version=$(nginx -v 2>&1 | grep -o '[0-9.]*')
curl -O http://nginx.org/download/nginx-${nginx_version}.tar.gz
tar -xzf nginx-${nginx_version}.tar.gz

# ngx_brotli 소스
git clone https://github.com/google/ngx_brotli.git
cd ngx_brotli && git submodule update --init --recursive

# 동적 모듈로 빌드
cd nginx-${nginx_version}
./configure --with-compat --add-dynamic-module=../ngx_brotli
make modules

# 모듈 복사
sudo cp objs/ngx_http_brotli_filter_module.so /usr/lib64/nginx/modules/
sudo cp objs/ngx_http_brotli_static_module.so /usr/lib64/nginx/modules/
```

### nginx.conf에서 로드 및 설정

```nginx
# 최상단 (main context)
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;

http {
    # Brotli 동적 압축
    brotli on;
    brotli_comp_level 6;          # 압축 레벨 (0~11)
    brotli_static on;             # .br 파일 있으면 우선 제공
    brotli_types
        text/plain
        text/css
        text/javascript
        application/javascript
        application/json
        application/xml
        image/svg+xml;
    brotli_min_length 256;
}
```

사전 압축 파일 생성:

```bash
brotli -q 11 /var/www/static/app.js     # app.js.br 생성
```

---

## Gzip과 Brotli 동시 사용

```nginx
http {
    gzip on;
    gzip_types text/plain text/css application/javascript application/json;

    brotli on;
    brotli_types text/plain text/css application/javascript application/json;
}
```

클라이언트의 `Accept-Encoding` 헤더에 따라 nginx가 자동으로 선택합니다.
Brotli 지원 브라우저는 `br`을 요청하고, 아니면 `gzip`이 사용됩니다.

---

## 압축 레벨 가이드

| 레벨 | 압축률 | CPU 사용 | 권장 상황 |
|------|--------|----------|-----------|
| gzip 1 | 낮음 | 최소 | 실시간 압축, 저사양 서버 |
| gzip 6 | 중간 | 중간 | 일반적인 웹 서버 (기본 권장) |
| gzip 9 | 높음 | 높음 | 대역폭 절약 최우선 |
| brotli 4 | gzip 6 수준 | 낮음 | 동적 압축 권장 |
| brotli 11 | 최고 | 매우 높음 | 정적 파일 사전 압축용 |
