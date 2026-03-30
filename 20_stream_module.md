# 20. Stream 모듈 (TCP/UDP 프록시)

nginx의 `ngx_stream_module`은 4계층(L4) 로드밸런서로 동작합니다.
HTTP를 파싱하지 않고 TCP/UDP 패킷을 그대로 전달합니다.

---

## 컴파일 옵션 확인

```bash
nginx -V 2>&1 | grep stream
# --with-stream 이 있어야 사용 가능

# AL2023 RPM 패키지는 보통 포함되어 있음
nginx -V 2>&1
```

동적 모듈로 로드:

```bash
# 모듈 파일 확인
ls /usr/lib64/nginx/modules/ | grep stream
```

```nginx
# 동적 모듈인 경우 main context에서 로드
load_module modules/ngx_stream_module.so;
```

---

## 기본 구조

stream 블록은 http 블록과 같은 레벨에 위치합니다.

```nginx
# nginx.conf

events { ... }

http { ... }

stream {
    upstream mysql_backends {
        server 192.168.1.10:3306;
        server 192.168.1.11:3306;
    }

    server {
        listen 3306;
        proxy_pass mysql_backends;
    }
}
```

---

## TCP 프록시 (데이터베이스, Redis 등)

```nginx
stream {
    # MySQL 로드밸런싱
    upstream mysql {
        least_conn;
        server 192.168.1.10:3306;
        server 192.168.1.11:3306;
    }

    server {
        listen 3306;
        proxy_pass mysql;
        proxy_connect_timeout 5s;
        proxy_timeout 300s;        # 연결 유지 시간 (비활성 기준)
    }

    # Redis
    upstream redis {
        server 192.168.1.20:6379;
        server 192.168.1.21:6379 backup;
    }

    server {
        listen 6379;
        proxy_pass redis;
    }

    # MongoDB
    upstream mongodb {
        server 192.168.1.30:27017;
        server 192.168.1.31:27017;
        server 192.168.1.32:27017;
    }

    server {
        listen 27017;
        proxy_pass mongodb;
    }
}
```

---

## UDP 프록시 (DNS, syslog 등)

```nginx
stream {
    # DNS 로드밸런싱
    upstream dns {
        server 8.8.8.8:53;
        server 8.8.4.4:53;
    }

    server {
        listen 53 udp;
        proxy_pass dns;
        proxy_responses 1;    # UDP: 예상 응답 패킷 수 (1이 기본)
        proxy_timeout 3s;
    }

    # syslog 수집 (UDP)
    server {
        listen 514 udp;
        proxy_pass syslog_server;
        proxy_responses 0;    # syslog는 응답 없음
    }
}
```

---

## SSL/TLS 종단 (SSL Termination)

백엔드는 평문으로, nginx가 SSL을 처리합니다.

```nginx
stream {
    server {
        listen 3306 ssl;

        ssl_certificate     /etc/nginx/ssl/server.crt;
        ssl_certificate_key /etc/nginx/ssl/server.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
        ssl_session_cache   shared:SSL:10m;
        ssl_session_timeout 10m;

        proxy_pass mysql_backends;
    }
}
```

---

## SSL Passthrough (SSL 그대로 전달)

nginx가 SSL을 처리하지 않고 백엔드로 그대로 전달합니다.
SNI를 파싱하여 어느 백엔드로 보낼지 결정합니다.

```nginx
stream {
    map $ssl_preread_server_name $backend {
        example.com     backend1:443;
        api.example.com backend2:443;
        default         backend1:443;
    }

    server {
        listen 443;
        ssl_preread on;     # SSL handshake를 파싱하되 처리하지 않음
        proxy_pass $backend;
        proxy_protocol on;  # 선택: 원본 IP를 백엔드에 전달
    }
}
```

---

## PROXY Protocol

원본 클라이언트 IP를 백엔드로 전달하는 프로토콜입니다.

```nginx
stream {
    server {
        listen 80;
        proxy_pass backend;
        proxy_protocol on;    # 백엔드에 PROXY protocol 헤더 추가
    }
}

# 백엔드 nginx에서 수신
http {
    server {
        listen 80 proxy_protocol;    # PROXY protocol 수신
        set_real_ip_from 10.0.0.0/8;
        real_ip_header proxy_protocol;    # PROXY protocol에서 IP 추출
    }
}
```

---

## Access Control

```nginx
stream {
    server {
        listen 3306;

        # IP 기반 접근 제어
        allow 10.0.0.0/8;
        allow 192.168.0.0/16;
        deny all;

        proxy_pass mysql_backends;
    }
}
```

---

## 헬스체크 (passive)

```nginx
stream {
    upstream backend {
        server 192.168.1.10:3306 max_fails=3 fail_timeout=30s;
        server 192.168.1.11:3306 max_fails=3 fail_timeout=30s;
    }
}
```

---

## 로깅

```nginx
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time';

    access_log /var/log/nginx/stream_access.log basic;

    server {
        listen 3306;
        proxy_pass mysql_backends;
    }
}
```

### stream 로그 변수

```
$remote_addr      클라이언트 IP
$remote_port      클라이언트 포트
$protocol         TCP 또는 UDP
$status           성공(200) 또는 실패(500)
$bytes_sent       보낸 바이트 수
$bytes_received   받은 바이트 수
$session_time     연결 유지 시간
$upstream_addr    업스트림 서버 주소
```

---

## HTTP + Stream 포트 구분

```nginx
# nginx.conf

http {
    server {
        listen 80;
        # HTTP 처리
    }
}

stream {
    server {
        listen 3306;
        # MySQL TCP 처리
    }

    server {
        listen 6379;
        # Redis TCP 처리
    }
}
```

같은 포트에서 HTTP와 TCP를 동시에 처리하는 것은 불가능합니다.
포트를 나눠서 사용해야 합니다.
