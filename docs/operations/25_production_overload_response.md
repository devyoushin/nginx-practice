# 25. 운영 중 부하 발생 시 대응 방법

---

## 핵심 관점

운영 중 nginx 서버에 부하가 생겼을 때는 바로 설정값을 키우기보다, 먼저 병목 위치를 분리해야 합니다.
nginx 자체가 병목인지, 백엔드가 느린 것인지, 특정 클라이언트나 URL이 트래픽을 몰고 있는지에 따라 해결 방법이 완전히 달라집니다.

```text
1. 현재 장애 영향 확인
2. nginx, OS, upstream, 네트워크 중 병목 위치 분리
3. 즉시 완화 조치 적용
4. 근본 원인에 맞는 설정/구조 변경
5. 필요하면 scale out
6. 재발 방지 기준과 알림 설정
```

운영 대응의 목표는 한 번에 완벽한 최적화를 하는 것이 아니라, 먼저 장애 영향을 줄이고 그 다음 원인을 좁히는 것입니다.

---

## 1단계: 부하 상황 빠르게 파악

### 현재 연결 상태

```bash
# TCP 전체 요약
ss -s

# 80/443 포트 연결 상태 분포
ss -tan sport = :80 or sport = :443 | awk 'NR > 1 {print $1}' | sort | uniq -c | sort -rn

# nginx 프로세스 CPU/메모리
top -p $(pgrep -d, nginx)

# nginx worker별 fd 사용량
for pid in $(pgrep nginx); do
  echo -n "PID $pid: "
  ls /proc/$pid/fd 2>/dev/null | wc -l
done
```

### nginx 상태 확인

`stub_status`가 켜져 있다면 먼저 봅니다.

```bash
curl -s http://127.0.0.1/nginx_status
```

예시:

```text
Active connections: 291
server accepts handled requests
 16630948 16630948 31070465
Reading: 6 Writing: 179 Waiting: 106
```

해석:

| 지표 | 의미 |
|------|------|
| `Reading` 높음 | 클라이언트 요청 헤더를 읽는 중. 느린 클라이언트, L7 공격, 헤더 timeout 문제 가능 |
| `Writing` 높음 | 응답 전송 중. 백엔드 지연, 큰 응답, 느린 클라이언트 가능 |
| `Waiting` 높음 | keepalive 유휴 연결이 많음. 정상일 수도 있지만 fd를 많이 잡을 수 있음 |
| `accepts`와 `handled` 차이 | 연결을 받았지만 처리 못한 연결이 있음. worker/fd/backlog 문제 가능 |

### 에러 로그 확인

```bash
tail -n 200 /var/log/nginx/error.log
```

자주 보는 메시지:

| 메시지 | 의심 원인 |
|--------|----------|
| `too many open files` | fd 한계 부족 |
| `connect() failed (111: Connection refused)` | 백엔드 포트 죽음 또는 connection limit |
| `upstream timed out` | 백엔드 응답 지연 |
| `no live upstreams` | upstream 서버 전부 장애 판정 |
| `client timed out` | 느린 클라이언트 또는 네트워크 문제 |
| `worker_connections are not enough` | `worker_connections` 부족 |

### access log로 트래픽 원인 확인

```bash
# 상태 코드 분포
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head

# 상위 URL
awk '{print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20

# 상위 IP
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20

# 5xx가 많이 나는 URL
awk '$9 ~ /^5/ {print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20
```

로그 포맷에 `$request_time`, `$upstream_response_time`을 넣어 두었다면 원인 분리가 훨씬 쉬워집니다.

```nginx
log_format main '$remote_addr "$request" $status '
                'rt=$request_time '
                'uct=$upstream_connect_time '
                'uht=$upstream_header_time '
                'urt=$upstream_response_time '
                'ua="$http_user_agent"';
```

```bash
# upstream 응답 시간이 긴 요청 찾기
grep 'urt=' /var/log/nginx/access.log | sort -k10 -rn | head
```

---

## 2단계: 병목 유형별 판단

### A. nginx CPU가 높음

가능한 원인:

- TLS handshake가 많음
- gzip 압축 비용이 큼
- 정적 파일 전송량이 큼
- 너무 상세한 access log 또는 동기 디스크 I/O
- 정규식 location/rewrite가 과도함
- 트래픽 자체가 서버 용량을 초과함

확인:

```bash
top -H -p $(pgrep -d, nginx)
pidstat -p $(pgrep -d, nginx) 1
sar -u 1
```

즉시 완화:

```nginx
# gzip 압축 레벨이 너무 높다면 낮춤
gzip_comp_level 4;

# access log buffering
access_log /var/log/nginx/access.log main buffer=64k flush=5s;

# 헬스 체크/정적 파일 로그 제외
location = /health {
    access_log off;
    return 200 "OK\n";
}
```

구조적 해결:

- TLS termination을 ALB, NLB+TLS, CDN, WAF 등 앞단으로 이동
- 정적 파일은 CDN 또는 object storage로 분리
- nginx 인스턴스 scale out
- gzip 대신 미리 압축된 파일 제공
- 불필요한 rewrite/정규식 location 정리

### B. 메모리가 높음

가능한 원인:

- 동시 요청 수 증가
- proxy buffer가 너무 큼
- 대용량 응답이 많음
- upload body가 메모리에 많이 머묾
- 캐시 zone 또는 open file cache 크기 과다

확인:

```bash
free -m
ps -o pid,ppid,rss,vsz,cmd -C nginx
vmstat 1
```

proxy buffer 계산:

```text
proxy_buffers 16 16k = 요청당 최대 256KB
동시 upstream 응답 4000개 = 약 1GB 이상 가능
```

완화:

```nginx
location /api/ {
    proxy_buffering on;
    proxy_buffer_size 8k;
    proxy_buffers 8 16k;
    proxy_busy_buffers_size 64k;
}
```

스트리밍 응답은 별도 location으로 빼고 buffering을 끕니다.

```nginx
location /events/ {
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
    proxy_pass http://api_backend;
}
```

### C. fd가 부족함

증상:

- `too many open files`
- `worker_connections are not enough`
- 새 연결 실패
- upstream connect 실패 증가

확인:

```bash
cat /proc/$(cat /run/nginx.pid)/limits | grep "open files"

for pid in $(pgrep nginx); do
  echo -n "$pid "
  ls /proc/$pid/fd 2>/dev/null | wc -l
done
```

조치:

```nginx
# nginx.conf main context
worker_processes auto;
worker_rlimit_nofile 262144;

events {
    worker_connections 16384;
}
```

systemd 한계도 같이 올려야 합니다.

```ini
# /etc/systemd/system/nginx.service.d/override.conf
[Service]
LimitNOFILE=262144
```

적용:

```bash
sudo systemctl daemon-reload
sudo nginx -t
sudo systemctl restart nginx
```

주의: `reload`만으로는 systemd `LimitNOFILE` 변경이 완전히 반영되지 않을 수 있으므로, fd 한계를 바꾼 경우에는 restart가 필요할 수 있습니다.

### D. upstream이 느림

증상:

- 502, 504 증가
- `$upstream_response_time` 증가
- nginx CPU는 낮은데 `Writing` 연결이 많음
- 백엔드 connection pool이 포화됨

확인:

```bash
# 5xx 원인 확인
tail -f /var/log/nginx/error.log

# upstream별 응답 시간 로그 확인
awk '$0 ~ /urt=/ {print}' /var/log/nginx/access.log | tail -100
```

완화:

```nginx
upstream api_backend {
    least_conn;
    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;
    keepalive 100;
}

location /api/ {
    proxy_pass http://api_backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    proxy_connect_timeout 3s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;
}
```

근본 해결:

- 백엔드 서버 scale out
- DB 병목 확인
- 느린 API를 캐싱
- 장시간 API를 별도 upstream/location으로 분리
- 백엔드 connection pool 크기 조정
- nginx의 keepalive 값이 백엔드 한계를 넘지 않게 조정

### E. 특정 IP 또는 URL이 과도한 요청을 보냄

확인:

```bash
# 상위 IP
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20

# 상위 URL
awk '{print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20
```

완화:

```nginx
http {
    limit_req_zone $binary_remote_addr zone=per_ip:10m rate=10r/s;
    limit_conn_zone $binary_remote_addr zone=conn_per_ip:10m;

    server {
        location /api/ {
            limit_req zone=per_ip burst=20 nodelay;
            limit_conn conn_per_ip 20;
            proxy_pass http://api_backend;
        }
    }
}
```

특정 path만 강하게 제한:

```nginx
location /login {
    limit_req zone=per_ip burst=5 nodelay;
    proxy_pass http://api_backend;
}
```

특정 IP 임시 차단:

```nginx
deny 203.0.113.10;
```

주의: 실제 운영에서는 CDN/WAF/로드밸런서 레벨에서 차단하는 편이 nginx 리소스를 덜 씁니다.

---

## 3단계: 즉시 완화 조치

부하가 이미 사용자 장애로 이어지고 있다면, 아래 순서로 영향도를 줄입니다.

### 1. 헬스 체크와 불필요한 로그 제거

```nginx
location = /health {
    access_log off;
    return 200 "OK\n";
}

location /static/ {
    access_log off;
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

### 2. 트래픽 제한

```nginx
limit_req_zone $binary_remote_addr zone=api_per_ip:10m rate=20r/s;

server {
    location /api/ {
        limit_req zone=api_per_ip burst=50 nodelay;
        proxy_pass http://api_backend;
    }
}
```

`burst`는 순간적으로 쌓아둘 수 있는 초과 요청 수입니다.
`nodelay`를 쓰면 대기시키지 않고 가능한 만큼 즉시 처리하고 초과분은 거절합니다.

### 3. 느린 API 분리

전체 timeout을 늘리지 말고 느린 API만 분리합니다.

```nginx
location /api/reports/ {
    proxy_pass http://report_backend;
    proxy_connect_timeout 3s;
    proxy_send_timeout 60s;
    proxy_read_timeout 300s;
}

location /api/ {
    proxy_pass http://api_backend;
    proxy_connect_timeout 3s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;
}
```

### 4. 캐시 적용

조회성 API나 정적 응답은 짧게라도 캐시하면 장애 완화 효과가 큽니다.

```nginx
proxy_cache_path /var/cache/nginx/api levels=1:2 keys_zone=api_cache:100m inactive=10m max_size=5g;

server {
    location /api/public/ {
        proxy_cache api_cache;
        proxy_cache_valid 200 30s;
        proxy_cache_valid 500 502 503 504 5s;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        add_header X-Cache-Status $upstream_cache_status always;

        proxy_pass http://api_backend;
    }
}
```

주의:

- 사용자별 데이터는 캐시 키에 인증/사용자 정보를 고려해야 합니다.
- `Authorization`, `Cookie`가 있는 요청을 무작정 캐시하면 보안 사고가 납니다.
- 캐시 적용은 public/read-only API부터 시작합니다.

### 5. 정적 파일/CDN 우회

이미지, JS, CSS, 다운로드 파일이 nginx를 압박한다면 애플리케이션 경로와 분리합니다.

```nginx
location /assets/ {
    root /var/www/app;
    expires 1y;
    add_header Cache-Control "public, immutable";
    access_log off;
}
```

가능하면 CDN 또는 object storage로 이동합니다.

---

## 4단계: nginx 서버 Scale Out

nginx 자체 CPU, 네트워크 대역폭, fd, TLS 처리량이 한 서버 한계를 넘으면 scale out이 필요합니다.
scale up은 서버 스펙을 키우는 방식이고, scale out은 nginx 인스턴스 수를 늘리는 방식입니다.

### 기본 구조

```text
Client
  |
  v
DNS / CDN / L4 Load Balancer / L7 Load Balancer
  |
  +--> nginx-1
  +--> nginx-2
  +--> nginx-3
          |
          v
      upstream backend servers
```

### Scale Out 절차

1. 새 nginx 서버 생성
2. 동일한 nginx 설정 배포
3. 인증서, snippet, upstream 설정 동기화
4. `/health` endpoint 정상 확인
5. 로드밸런서 target group에 추가
6. 낮은 비율 또는 일부 트래픽부터 유입
7. CPU, 5xx, latency 확인
8. 정상 확인 후 전체 트래픽 분산

### 로드밸런서 앞단 구성

AWS ALB 예시 개념:

```text
ALB listener 443
  -> target group: nginx instances
      health check path: /health
      protocol: HTTP
      port: 80
```

nginx는 ALB 뒤에서 HTTP로 받고, 원본 client IP는 `X-Forwarded-For`로 받습니다.

```nginx
set_real_ip_from 10.0.0.0/8;
real_ip_header X-Forwarded-For;
real_ip_recursive on;
```

주의: `set_real_ip_from`에는 신뢰할 수 있는 로드밸런서/CDN 대역만 넣어야 합니다.
아무 IP나 신뢰하면 클라이언트가 `X-Forwarded-For`를 조작할 수 있습니다.

### nginx 인스턴스 간 설정 동기화

권장 방식:

```text
Git repository
  -> CI/CD
  -> nginx -t
  -> 배포
  -> systemctl reload nginx
```

수동 복사는 운영 규모가 커질수록 설정 drift가 생깁니다.
최소한 설정 배포 전후에 아래 명령으로 최종 설정을 비교합니다.

```bash
sudo nginx -T > nginx-final.conf
```

### 상태 저장 여부 확인

nginx scale out이 쉬우려면 nginx 서버가 상태를 갖지 않는 구조여야 합니다.

점검할 것:

- 로컬 디스크에 업로드 파일을 저장하고 있지 않은가
- 로컬 proxy cache가 서버별로 달라도 괜찮은가
- sticky session이 필요한가
- TLS 인증서가 모든 노드에 배포되는가
- 로그 수집이 중앙화되어 있는가

### Sticky Session이 필요한 경우

가능하면 애플리케이션 세션은 Redis, DB, 외부 세션 스토어로 빼는 것이 좋습니다.
정말 필요하면 로드밸런서 또는 nginx upstream에서 세션 고정을 고려합니다.

```nginx
upstream app_backend {
    ip_hash;
    server 10.0.2.10:3000;
    server 10.0.2.11:3000;
}
```

주의:

- `ip_hash`는 클라이언트 IP 기준이라 NAT 환경에서 분산이 치우칠 수 있습니다.
- ALB/CDN 뒤에서는 nginx가 보는 IP가 로드밸런서 IP일 수 있으므로 real_ip 설정이 중요합니다.
- sticky session은 장애 조치와 균등 분산을 어렵게 만들 수 있습니다.

---

## 5단계: upstream 서버 Scale Out

부하 원인이 nginx가 아니라 백엔드라면 nginx를 늘려도 효과가 제한적입니다.
이 경우 upstream 서버를 늘리고 nginx upstream 블록에 추가합니다.

```nginx
upstream api_backend {
    least_conn;

    server 10.0.1.10:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:8080 max_fails=3 fail_timeout=10s;

    keepalive 100;
}
```

배포 절차:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

신규 upstream 추가 전 확인:

- 백엔드 `/health` 정상
- 앱 버전 동일
- DB migration 호환
- 환경변수 동일
- connection pool 크기 적절
- 로그/메트릭 수집 연결

### least_conn 사용

요청 처리 시간이 균일하지 않은 API는 `least_conn`이 단순 round-robin보다 유리할 수 있습니다.

```nginx
upstream api_backend {
    least_conn;
    server 10.0.1.10:8080;
    server 10.0.1.11:8080;
}
```

### weight 조정

서버 스펙이 다르면 weight를 다르게 줄 수 있습니다.

```nginx
upstream api_backend {
    server 10.0.1.10:8080 weight=2;
    server 10.0.1.11:8080 weight=1;
}
```

### 일부 서버 제외

장애 서버를 임시 제외:

```nginx
upstream api_backend {
    server 10.0.1.10:8080;
    server 10.0.1.11:8080 down;
}
```

천천히 복귀:

```nginx
upstream api_backend {
    server 10.0.1.10:8080;
    server 10.0.1.11:8080 weight=1;
    server 10.0.1.12:8080 weight=1;
}
```

---

## 6단계: OS/네트워크 레벨 확인

nginx 설정만으로 해결되지 않는 경우 OS 큐와 네트워크 한계를 봐야 합니다.

### backlog

연결이 순간적으로 몰릴 때 listen backlog가 부족하면 연결 수락 전에 밀릴 수 있습니다.

```bash
sysctl net.core.somaxconn
sysctl net.ipv4.tcp_max_syn_backlog
```

```nginx
server {
    listen 80 backlog=65535;
}
```

```conf
# /etc/sysctl.conf
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
```

### ephemeral port 고갈

nginx가 upstream으로 많은 연결을 만들 때 로컬 포트가 부족할 수 있습니다.
upstream keepalive를 쓰면 연결 재사용으로 완화됩니다.

```bash
sysctl net.ipv4.ip_local_port_range
ss -tan state time-wait | wc -l
```

```conf
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
```

### 네트워크 대역폭

```bash
sar -n DEV 1
iftop -i eth0
```

정적 파일이나 다운로드 트래픽이 원인이면 nginx 설정 튜닝보다 CDN 분리가 효과적입니다.

---

## 7단계: 장애 대응 중 안전한 배포 방식

운영 중 부하 상황에서 설정을 바꿀 때는 반드시 아래 순서를 지킵니다.

```bash
# 1. 설정 문법 검사
sudo nginx -t

# 2. include까지 합쳐진 설정 확인
sudo nginx -T | less

# 3. 무중단 reload
sudo systemctl reload nginx

# 4. 에러 로그 확인
tail -f /var/log/nginx/error.log
```

주의:

- `worker_connections`, `proxy_*`, `limit_req` 같은 대부분의 설정은 reload로 반영됩니다.
- systemd `LimitNOFILE` 변경은 restart가 필요할 수 있습니다.
- restart는 짧은 중단이나 연결 종료를 만들 수 있으므로 트래픽 분산 구조에서 순차 적용합니다.
- 여러 nginx 노드가 있다면 한 대씩 빼고 변경 후 다시 넣는 rolling 방식이 안전합니다.

---

## 상황별 빠른 처방표

| 증상 | 우선 확인 | 즉시 조치 | 근본 해결 |
|------|----------|----------|----------|
| CPU 100% | `top`, TLS/gzip/log | gzip 낮춤, 로그 buffer, rate limit | CDN/TLS offload/nginx scale out |
| 메모리 증가 | `free`, proxy buffer | buffer 축소, streaming 분리 | 응답 크기 개선, 서버 증설 |
| 502 증가 | error log, upstream 상태 | 장애 upstream 제외 | 백엔드 복구/scale out |
| 504 증가 | upstream response time | timeout 분리, slow API 격리 | 백엔드 성능 개선/캐시 |
| 499 증가 | request time, client timeout | 느린 API 개선, timeout 조정 | 프론트/앱 timeout 정책 정리 |
| fd 부족 | `/proc/PID/limits`, fd 수 | worker/fd 상향 | scale out, keepalive 조정 |
| 특정 IP 폭주 | access log top IP | limit_req, deny | WAF/CDN 차단 |
| 특정 URL 폭주 | access log top URL | 캐시, rate limit | API 최적화/비동기화 |
| 네트워크 포화 | `sar -n DEV`, 전송량 | 정적 파일 로그 off | CDN/object storage 분리 |

---

## 운영 체크리스트

```text
[ ] nginx_status 또는 exporter가 켜져 있는가
[ ] access log에 request_time, upstream_response_time이 있는가
[ ] error_log를 빠르게 볼 수 있는가
[ ] fd 한계와 worker_connections 계산이 되어 있는가
[ ] upstream keepalive가 설정되어 있는가
[ ] health check endpoint가 있는가
[ ] rate limit을 적용할 수 있는 zone이 준비되어 있는가
[ ] public API/정적 파일 캐시 전략이 있는가
[ ] nginx scale out 절차가 문서화되어 있는가
[ ] upstream 서버 추가/제외 절차가 문서화되어 있는가
[ ] 설정 변경은 nginx -t 후 reload하는가
[ ] 여러 nginx 노드는 rolling 방식으로 변경하는가
```
