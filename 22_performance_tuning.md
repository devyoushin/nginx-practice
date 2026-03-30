# 22. 성능 튜닝

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

# nginx 프로세스별 한계 (/etc/security/limits.conf)
sudo tee -a /etc/security/limits.conf << 'EOF'
nginx soft nofile 65535
nginx hard nofile 65535
root  soft nofile 65535
root  hard nofile 65535
EOF
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
