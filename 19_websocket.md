# 19. WebSocket 프록시

WebSocket은 HTTP Upgrade 메커니즘을 통해 TCP 연결을 지속합니다.
nginx에서 WebSocket을 프록시하려면 특별한 헤더 설정이 필요합니다.

---

## 기본 WebSocket 프록시 설정

```nginx
http {
    # WebSocket Upgrade 처리를 위한 map
    map $http_upgrade $connection_upgrade {
        default   upgrade;
        ""        close;
    }

    server {
        listen 80;
        server_name example.com;

        location /ws/ {
            proxy_pass http://websocket-backend;

            # WebSocket 필수 헤더
            proxy_http_version 1.1;
            proxy_set_header Upgrade    $http_upgrade;
            proxy_set_header Connection $connection_upgrade;

            # 일반 프록시 헤더
            proxy_set_header Host               $host;
            proxy_set_header X-Real-IP          $remote_addr;
            proxy_set_header X-Forwarded-For    $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto  $scheme;

            # WebSocket 연결은 오래 유지되므로 타임아웃 늘림
            proxy_read_timeout  3600s;    # 1시간
            proxy_send_timeout  3600s;
            proxy_connect_timeout 5s;

            # 버퍼 비활성화 (실시간 전달)
            proxy_buffering off;
        }
    }
}
```

---

## Connection 헤더 왜 필요한가

HTTP/1.1 연결 업그레이드 흐름:

```
클라이언트 → nginx → 백엔드

1. 클라이언트 요청:
   GET /ws HTTP/1.1
   Upgrade: websocket
   Connection: Upgrade

2. nginx가 백엔드로 전달:
   - $http_upgrade = "websocket"
   - Connection: upgrade  (map에 의해 설정)

3. 백엔드 응답:
   HTTP/1.1 101 Switching Protocols
   Upgrade: websocket
   Connection: Upgrade

4. 이후 TCP 터널로 양방향 통신
```

`Connection: upgrade`가 없으면 nginx가 연결 업그레이드를 전달하지 않습니다.

---

## WebSocket과 일반 HTTP 혼용

같은 서버 블록에서 일반 HTTP와 WebSocket을 함께 처리:

```nginx
upstream api_backend {
    server 127.0.0.1:3000;
    keepalive 32;
}

map $http_upgrade $connection_upgrade {
    default   upgrade;
    ""        close;
}

server {
    listen 443 ssl;
    server_name example.com;

    # 일반 REST API
    location /api/ {
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";    # keepalive용 빈 Connection
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # WebSocket
    location /api/ws {
        proxy_pass http://api_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host       $host;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }
}
```

---

## Socket.IO 프록시

Socket.IO는 WebSocket + HTTP long-polling 폴백을 사용합니다.

```nginx
upstream socketio_backend {
    ip_hash;    # 세션 고정 (필수: 같은 서버로 연결)
    server 127.0.0.1:3000;
    server 127.0.0.1:3001;
}

map $http_upgrade $connection_upgrade {
    default   upgrade;
    ""        close;
}

server {
    listen 443 ssl;
    server_name example.com;

    location /socket.io/ {
        proxy_pass http://socketio_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host       $host;
        proxy_set_header X-Real-IP  $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        proxy_read_timeout 86400s;    # 24시간
        proxy_send_timeout 86400s;
        proxy_buffering off;

        # long-polling을 위한 캐시 비활성화
        proxy_cache off;
    }
}
```

---

## wss:// (WebSocket Secure)

HTTPS 서버에서 WebSocket을 프록시하면 자동으로 WSS가 됩니다.
클라이언트가 `wss://example.com/ws`로 연결하면 nginx가 SSL을 처리하고
백엔드는 일반 ws://로 연결됩니다.

```nginx
server {
    listen 443 ssl;        # HTTPS = WSS 자동 처리
    server_name example.com;

    location /ws/ {
        proxy_pass http://127.0.0.1:8080;    # 백엔드는 ws:// (HTTP)
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }
}
```

---

## 연결 수 제한

WebSocket은 연결을 오래 유지하므로 연결 수 관리가 중요합니다.

```nginx
http {
    limit_conn_zone $binary_remote_addr zone=ws_conn:10m;
}

server {
    location /ws/ {
        limit_conn ws_conn 5;    # IP당 최대 5개 WebSocket 연결
        proxy_pass http://ws_backend;
        # ...
    }
}
```

---

## 디버깅

```bash
# WebSocket 연결 테스트 (websocat 사용)
websocat ws://localhost/ws/

# curl로 Upgrade 요청 테스트
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  http://example.com/ws/

# 응답에 "101 Switching Protocols"가 있어야 성공

# 현재 WebSocket 연결 수 확인
ss -tn | grep :80 | grep ESTABLISHED | wc -l
```
