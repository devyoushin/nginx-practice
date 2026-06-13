# 22. 성능 튜닝

---

## 튜닝 기본 원칙

nginx 튜닝은 설정값을 크게 잡는 작업이 아니라, 병목을 확인하고 그 병목에 맞는 값을 조정하는 작업입니다.
대부분의 운영 환경에서는 아래 순서로 접근합니다.

```text
1. 목표 정의: 동시 접속 수, RPS, 평균/상위 백분위 응답 시간, 에러율
2. 현재 상태 측정: CPU, 메모리, fd, 연결 수, upstream 응답 시간, 디스크 I/O
3. 병목 분리: nginx 자체 문제인지, upstream 문제인지, 네트워크/OS 문제인지 확인
4. 설정 변경: 한 번에 한 영역만 변경
5. 부하 테스트: 변경 전/후 지표 비교
6. 운영 반영: nginx -t 후 reload, 모니터링으로 검증
```

우선순위:

| 우선순위 | 확인 항목 | 대표 설정/지표 |
|----------|----------|----------------|
| 1 | 파일 디스크립터 한계 | `LimitNOFILE`, `worker_rlimit_nofile`, fd 사용량 |
| 2 | worker 동시 연결 | `worker_processes`, `worker_connections` |
| 3 | upstream 병목 | `proxy_connect_timeout`, `proxy_read_timeout`, upstream keepalive |
| 4 | 버퍼/메모리 | `proxy_buffering`, `proxy_buffers`, `client_body_buffer_size` |
| 5 | 정적 파일/캐시 | `sendfile`, `open_file_cache`, `expires`, `Cache-Control` |
| 6 | 로그 I/O | `access_log buffer=`, 조건부 로깅, logrotate |
| 7 | TLS 비용 | 세션 캐시, HTTP/2, 앞단 TLS termination 여부 |

주의:

- 튜닝값은 서버 스펙, 트래픽 패턴, upstream 지연 시간에 따라 달라집니다.
- `worker_connections`만 크게 올려도 OS fd 한계가 낮으면 효과가 없습니다.
- upstream이 느린 상태에서 nginx 연결 수만 늘리면 대기 요청과 메모리 사용량이 늘어날 수 있습니다.
- `reload`는 무중단에 가깝지만, 설정 오류를 막기 위해 항상 `nginx -t`를 먼저 실행합니다.

---

## 운영 기준 예시

일반적인 reverse proxy/API gateway 역할의 nginx라면 아래 정도를 기준값으로 잡고, 측정 결과에 따라 조정합니다.

```nginx
# main context
worker_processes auto;
worker_rlimit_nofile 65536;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    keepalive_timeout 65;
    keepalive_requests 10000;

    client_header_timeout 10s;
    client_body_timeout 10s;
    send_timeout 30s;
    reset_timedout_connection on;

    access_log /var/log/nginx/access.log main buffer=64k flush=5s;
}
```

대략적인 동시 연결 수 계산:

```text
최대 이론 연결 수 = worker_processes × worker_connections

예:
worker_processes auto  # 4코어
worker_connections 4096
=> 최대 약 16,384 연결
```

프록시 서버에서는 클라이언트 연결과 upstream 연결을 모두 고려해야 합니다.
그래서 fd 한계는 최소한 아래보다 크게 잡습니다.

```text
필요 fd ≈ worker_processes × worker_connections × 2
```

---

## OS 레벨 튜닝

### 파일 디스크립터 한계

```bash
# 현재 한계 확인
ulimit -n
cat /proc/sys/fs/file-max

# 시스템 전체 한계 늘리기
echo "fs.file-max = 2097152" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

#### systemd로 기동할 때: LimitNOFILE 설정

> **주의**: systemd로 기동하는 서비스는 `/etc/security/limits.conf`가 **적용되지 않는다.**
> 반드시 systemd 유닛 파일에 `LimitNOFILE=`을 직접 설정해야 한다.

```bash
# nginx systemd 유닛 파일에 drop-in 설정 추가
sudo systemctl edit nginx
```

```ini
# /etc/systemd/system/nginx.service.d/override.conf
[Service]
LimitNOFILE=65536
# soft=65536, hard=1048576으로 분리 설정도 가능
# LimitNOFILE=65536:1048576
```

```bash
# 설정 적용
sudo systemctl daemon-reload
sudo systemctl restart nginx

# 적용 확인 (nginx master PID 기준)
cat /proc/$(cat /var/run/nginx.pid)/limits | grep "open files"
```

#### 적정값 계산 방법

`LimitNOFILE`은 nginx.conf의 `worker_processes × worker_connections × 2`보다 커야 한다.
클라이언트 소켓 + upstream 소켓을 동시에 열기 때문에 연결 1개당 fd 2개를 소비한다.

```
worker_processes 4  ×  worker_connections 4096  ×  2 = 32768  →  65536이면 충분
worker_processes 8  ×  worker_connections 10240 ×  2 = 163840 →  65536이면 부족, 262144 이상 필요
```

| 트래픽 규모 | worker_connections | 권장 LimitNOFILE |
|-------------|-------------------|-----------------|
| 소규모       | 1024              | 65536           |
| 중규모       | 4096              | 65536           |
| 대규모       | 10240             | 262144          |
| 초대규모     | 65535             | 1048576         |

#### nginx.conf의 worker_rlimit_nofile과의 관계

```nginx
# nginx.conf (main context)
worker_rlimit_nofile 65536;
# → nginx가 자체적으로 worker 프로세스의 fd 한도를 설정
# → LimitNOFILE 값보다 클 수 없음 (LimitNOFILE가 상한선)
```

```bash
# 현재 실제 fd 사용량 확인 (worker 프로세스 전체)
for pid in $(pgrep nginx); do
  echo -n "PID $pid ($(cat /proc/$pid/comm)): "
  ls /proc/$pid/fd 2>/dev/null | wc -l
done
```

### TCP 튜닝

```bash
sudo tee -a /etc/sysctl.conf << 'EOF'
# 백로그 큐 크기 (SYN 큐)
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# TIME_WAIT 소켓 재사용
net.ipv4.tcp_tw_reuse = 1

# TIME_WAIT 빠른 재활용 (비권장: NAT 환경 문제)
# net.ipv4.tcp_tw_recycle = 1

# FIN_WAIT2 타임아웃
net.ipv4.tcp_fin_timeout = 15

# keepalive 설정
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# 수신/송신 버퍼
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# backlog 기본값
net.core.netdev_max_backlog = 65535

# 로컬 포트 범위 (ephemeral ports)
net.ipv4.ip_local_port_range = 1024 65535
EOF

sudo sysctl -p
```

---

## nginx.conf 성능 설정 모음

```nginx
# main context
user nginx;
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
    accept_mutex off;
}

http {
    # I/O 최적화
    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;
    aio             on;        # 비동기 I/O (대용량 파일에 효과적)
    directio        512;       # 이 크기 이상 파일은 directio 사용
    output_buffers  1 512k;

    # keepalive
    keepalive_timeout  65;
    keepalive_requests 10000;
    keepalive_time     1h;

    # 클라이언트
    client_header_timeout 10s;
    client_body_timeout   10s;
    send_timeout          30s;
    reset_timedout_connection on;

    # 오픈 파일 캐시
    open_file_cache          max=10000 inactive=20s;
    open_file_cache_valid    30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors   on;

    # 압축
    gzip on;
    gzip_comp_level 6;
    gzip_vary on;
    gzip_proxied any;
    gzip_min_length 256;
    gzip_types text/plain text/css application/json application/javascript
               text/xml application/xml application/rss+xml image/svg+xml;

    # 해시 테이블
    server_names_hash_bucket_size 128;
    types_hash_max_size 4096;
    variables_hash_max_size 4096;

    # 보안 + 성능
    server_tokens off;
}
```

---

## Worker 프로세스 최적화

```bash
# CPU 코어 수 확인
nproc
lscpu | grep "CPU(s):"

# NUMA 토폴로지 확인 (멀티소켓 서버)
numactl --hardware
```

```nginx
# 멀티소켓 서버 (2소켓 × 8코어 = 16코어)
worker_processes 16;
worker_cpu_affinity auto;

# NUMA 인식 설정 (고급)
# 소켓 0의 코어: 0000000011111111
# 소켓 1의 코어: 1111111100000000
```

---

## upstream keepalive (프록시 연결 풀)

```nginx
upstream backend {
    server 127.0.0.1:8080;
    keepalive 100;               # Worker당 유휴 연결 유지 수
    keepalive_requests 10000;
    keepalive_timeout 60s;
}

location / {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Connection "";    # keepalive 필수
}
```

### upstream keepalive 튜닝 기준

`keepalive`는 전체 연결 수가 아니라 **worker process당 유지할 유휴 upstream 연결 수**입니다.

```text
worker_processes 4
upstream keepalive 100
=> 최대 400개의 유휴 upstream 연결 유지 가능
```

권장 방향:

| 상황 | 권장 |
|------|------|
| 짧은 API 요청이 많음 | upstream keepalive 사용 |
| upstream 연결 생성 비용이 큼 | `keepalive` 값을 충분히 확보 |
| upstream 서버 수가 많음 | 서버별 연결 수가 과도하지 않은지 확인 |
| upstream이 connection limit을 가짐 | nginx keepalive 값을 upstream 한계보다 낮게 설정 |

주의:

- `proxy_http_version 1.1`과 `proxy_set_header Connection ""`가 빠지면 upstream keepalive가 제대로 동작하지 않을 수 있습니다.
- upstream keepalive를 너무 크게 잡으면 백엔드 서버의 connection pool, thread pool, fd를 먼저 소진할 수 있습니다.

---

## 프록시 버퍼 튜닝

nginx가 reverse proxy로 동작할 때는 upstream 응답을 버퍼링할지 여부가 성능과 메모리에 큰 영향을 줍니다.

기본 API 서버 권장 예:

```nginx
location /api/ {
    proxy_pass http://backend;

    proxy_buffering on;
    proxy_buffer_size 8k;
    proxy_buffers 16 16k;
    proxy_busy_buffers_size 64k;

    proxy_connect_timeout 3s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;
}
```

버퍼링을 켜면 nginx가 upstream 응답을 먼저 받아 클라이언트 속도와 upstream 속도를 분리할 수 있습니다.
느린 클라이언트 때문에 upstream 연결이 오래 붙잡히는 상황을 줄이는 데 유리합니다.

버퍼링을 끄는 경우:

```nginx
location /stream/ {
    proxy_pass http://backend;
    proxy_buffering off;
    proxy_cache off;
}
```

`proxy_buffering off`가 어울리는 경우:

- SSE(Server-Sent Events)
- 스트리밍 응답
- 긴 polling
- 응답을 즉시 흘려보내야 하는 API

주의:

- 버퍼를 크게 잡으면 요청당 메모리 사용량이 늘어납니다.
- 대용량 응답이 많으면 임시 파일(`proxy_temp_path`)로 떨어질 수 있어 디스크 I/O도 확인해야 합니다.
- API 응답이 작고 빠르면 과도한 버퍼 튜닝보다 upstream keepalive와 timeout 설정이 더 중요합니다.

---

## Timeout 튜닝

timeout은 크게 잡는 것이 항상 좋은 게 아닙니다.
너무 길면 장애가 난 upstream에 요청이 오래 매달리고, 너무 짧으면 정상적인 느린 요청도 끊깁니다.

```nginx
location / {
    proxy_connect_timeout 3s;   # upstream TCP 연결 대기 시간
    proxy_send_timeout    30s;  # nginx -> upstream 요청 전송 대기
    proxy_read_timeout    30s;  # upstream 응답 대기

    client_header_timeout 10s;
    client_body_timeout   10s;
    send_timeout          30s;
}
```

권장 방향:

| 요청 유형 | 권장 |
|-----------|------|
| 일반 API | `proxy_connect_timeout 1~3s`, `proxy_read_timeout 10~30s` |
| 파일 업로드 | `client_body_timeout`, `proxy_send_timeout`을 더 길게 |
| 리포트/배치성 API | 별도 location으로 timeout 분리 |
| WebSocket/SSE | 긴 `proxy_read_timeout` 필요 |

장시간 요청은 전체 서버 기본값을 늘리기보다 별도 location으로 분리합니다.

```nginx
location /reports/ {
    proxy_pass http://backend;
    proxy_read_timeout 300s;
}
```

---

## 정적 파일 서빙 최적화

```nginx
location /static/ {
    root /var/www;

    sendfile on;
    tcp_nopush on;
    aio on;

    # 클라이언트 캐싱
    expires 1y;
    add_header Cache-Control "public, immutable";
    add_header Vary Accept-Encoding;

    # 로그 비활성화 (I/O 감소)
    access_log off;

    # 오픈 파일 캐시
    open_file_cache max=10000 inactive=30s;
    open_file_cache_valid 60s;
    open_file_cache_min_uses 3;
}
```

---

## 대용량 파일 처리

```nginx
location /downloads/ {
    root /var/www;

    sendfile on;
    aio on;
    directio 4m;            # 4MB 이상은 directio (OS 캐시 우회)
    output_buffers 2 512k;

    limit_rate_after 5m;    # 처음 5MB 후 속도 제한
    limit_rate 1m;          # 1MB/s
}
```

---

## 메모리 사용량 최적화

```nginx
# 버퍼 크기 최적화 (메모리 vs 성능 트레이드오프)
client_body_buffer_size     128k;    # 기본 8k/16k
client_header_buffer_size   1k;      # 기본 1k
large_client_header_buffers 4 4k;   # 기본 4 8k

proxy_buffer_size           4k;      # 기본 4k/8k
proxy_buffers               8 16k;   # 기본 8 4k/8k
proxy_busy_buffers_size     32k;     # 기본 8k/16k
```

요청당 메모리 사용량은 동시 접속 수와 함께 계산해야 합니다.

```text
요청당 버퍼 메모리 × 동시 요청 수 = 대략적인 버퍼 메모리 사용량

예:
proxy_buffers 16 16k = 256k
동시 upstream 응답 2,000개
=> 약 512MB 이상 사용 가능
```

따라서 버퍼는 "크게 잡으면 빠르다"가 아니라, 응답 크기와 동시성에 맞춰 조정합니다.

---

## TLS/HTTP 튜닝

nginx가 직접 TLS termination을 담당한다면 TLS 세션 재사용과 프로토콜 설정도 성능에 영향을 줍니다.

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;

# nginx 1.25.1+
http2 on;
```

앞단 WAF/CDN/API Gateway/LB에서 TLS termination을 담당한다면 nginx의 TLS 튜닝보다 아래 항목이 더 중요합니다.

- 앞단에서 `X-Forwarded-Proto` 전달
- nginx의 `real_ip` 신뢰 설정
- 내부 구간 HTTP/HTTPS 여부 결정
- 앞단과 nginx 사이의 keepalive/timeout 설정

---

## 로그 I/O 튜닝

access log는 트래픽이 많을수록 디스크 I/O와 저장 공간을 크게 사용합니다.

```nginx
access_log /var/log/nginx/access.log main buffer=64k flush=5s;
```

로그량이 많으면 아래를 함께 검토합니다.

- `/health`, `/ping` 같은 헬스 체크 로그 제외
- 정적 파일 access log 제외
- 2xx/3xx 성공 요청 샘플링
- 4xx/5xx와 느린 요청은 반드시 기록
- logrotate 압축/보관 기간 설정

자세한 내용은 [13_logging.md](../operations/13_logging.md)를 참고합니다.

---

## 성능 측정

```bash
# ab (Apache Bench)
ab -n 10000 -c 100 http://localhost/

# wrk
wrk -t4 -c100 -d30s http://localhost/

# wrk2 (더 정밀한 RPS 제어)
wrk2 -t4 -c100 -d30s -R1000 http://localhost/

# siege
siege -c 100 -t 60S http://localhost/

# nginx 응답 시간 확인
curl -w "@curl-format.txt" -o /dev/null -s http://localhost/

# curl-format.txt 내용:
#     time_namelookup:  %{time_namelookup}\n
#     time_connect:  %{time_connect}\n
#     time_starttransfer:  %{time_starttransfer}\n
#     time_total:  %{time_total}\n
```

---

## 병목 지점 확인

```bash
# nginx worker CPU 사용량
top -p $(pgrep -d, nginx)
# 또는
pidstat -p $(pgrep nginx | tr '\n' ',') 1

# 네트워크 I/O
iftop -i eth0
nload eth0

# 파일 디스크립터 사용량
cat /proc/$(cat /var/run/nginx.pid)/limits | grep "open files"
ls /proc/$(cat /var/run/nginx.pid)/fd | wc -l

# 현재 연결 수
ss -s
netstat -an | awk '/^tcp/ {print $6}' | sort | uniq -c

# nginx access 로그에서 느린 요청 추출
awk '$NF > 1.0' /var/log/nginx/access.log | wc -l
```

### 지표별 해석

| 증상 | 의심 지점 | 확인 |
|------|----------|------|
| `too many open files` | fd 한계 부족 | `LimitNOFILE`, `worker_rlimit_nofile`, `/proc/PID/limits` |
| 499 증가 | 클라이언트가 먼저 연결 종료 | 응답 지연, timeout, 클라이언트 timeout |
| 502 증가 | upstream 연결 실패 | upstream 상태, `proxy_connect_timeout`, 백엔드 로그 |
| 504 증가 | upstream 응답 지연 | `proxy_read_timeout`, upstream 처리 시간 |
| CPU 100% | worker CPU 병목 | `top`, `pidstat`, gzip/TLS 비용 |
| 메모리 증가 | 버퍼/동시 요청 증가 | `proxy_buffers`, 동시 upstream 응답 수 |
| 디스크 I/O 증가 | access log 또는 temp file | access log buffer, `proxy_temp_path`, logrotate |

### 변경 전후 검증 절차

```bash
# 1. 설정 문법 확인
sudo nginx -t

# 2. 무중단 reload
sudo systemctl reload nginx

# 3. 적용된 설정 확인
sudo nginx -T | less

# 4. 연결/에러/응답 시간 확인
ss -s
tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/access.log
```

운영 반영 후에는 최소한 아래 지표를 같이 봅니다.

- RPS
- 평균 응답 시간
- p95/p99 응답 시간
- 4xx/5xx 비율
- nginx worker CPU
- fd 사용량
- upstream 응답 시간
- 네트워크 송수신량
