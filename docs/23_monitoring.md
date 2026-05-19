# 23. 모니터링

---

## stub_status 모듈 (기본 내장)

nginx의 기본 상태 정보를 제공합니다.

### 활성화

```nginx
server {
    listen 80;
    server_name localhost;

    location /nginx_status {
        stub_status on;
        access_log off;
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;
    }
}
```

### 출력 예시

```
$ curl http://127.0.0.1/nginx_status

Active connections: 291
server accepts handled requests
 16630948 16630948 31070465
Reading: 6 Writing: 179 Waiting: 106
```

### 항목 설명

| 항목 | 설명 |
|------|------|
| `Active connections` | 현재 활성 연결 수 (Reading + Writing + Waiting) |
| `accepts` | 총 수락된 연결 수 |
| `handled` | 총 처리된 연결 수 (accepts = handled면 드롭 없음) |
| `requests` | 총 처리된 요청 수 |
| `Reading` | 요청 헤더를 읽는 중인 연결 수 |
| `Writing` | 응답을 전송 중인 연결 수 |
| `Waiting` | keepalive 유휴 연결 수 |

---

## 로그 기반 실시간 분석

```bash
# 초당 요청 수 (RPS) 실시간
tail -f /var/log/nginx/access.log | awk '{print $1}' | uniq -c

# 분당 요청 수
awk '{print $4}' /var/log/nginx/access.log | \
    cut -d: -f1,2 | sort | uniq -c

# 상태 코드 실시간 분포
tail -f /var/log/nginx/access.log | awk '{print $9}' | \
    while read code; do
        echo $code
    done | sort | uniq -c | sort -rn

# 에러 실시간 모니터링
tail -f /var/log/nginx/error.log

# 느린 요청 추출 (1초 이상)
awk '$(NF) > 1' /var/log/nginx/access.log

# 평균 응답 시간 계산
awk '{sum += $NF; count++} END {print "avg:", sum/count "s"}' \
    /var/log/nginx/access.log

# 상위 접근 URL
awk '{print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20

# 상위 접근 IP
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -20
```

---

## GoAccess (실시간 웹 로그 분석기)

```bash
# 설치
sudo dnf install goaccess

# 터미널 실시간 대시보드
goaccess /var/log/nginx/access.log \
    --log-format=COMBINED \
    --real-time-html \
    -o /var/www/html/report.html

# 특정 시간대 분석
grep "01/Jan/2024" /var/log/nginx/access.log | goaccess --log-format=COMBINED -

# HTML 리포트 생성
goaccess /var/log/nginx/access.log \
    --log-format=COMBINED \
    -o /tmp/report.html
```

---

## Prometheus + nginx-prometheus-exporter

```bash
# nginx-prometheus-exporter 설치
wget https://github.com/nginxinc/nginx-prometheus-exporter/releases/latest/download/nginx-prometheus-exporter_linux_amd64.tar.gz
tar -xzf nginx-prometheus-exporter_linux_amd64.tar.gz

# 실행 (stub_status 필요)
./nginx-prometheus-exporter -nginx.scrape-uri http://localhost/nginx_status
# 기본 포트: 9113
```

systemd 서비스:

```ini
# /etc/systemd/system/nginx-exporter.service
[Unit]
Description=Nginx Prometheus Exporter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/nginx-prometheus-exporter \
    -nginx.scrape-uri=http://localhost/nginx_status
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Prometheus 스크레이프 설정

```yaml
# prometheus.yml
scrape_configs:
  - job_name: nginx
    static_configs:
      - targets: ['localhost:9113']
```

### 제공되는 메트릭

```
nginx_connections_active     활성 연결 수
nginx_connections_reading    헤더 읽기 중
nginx_connections_writing    응답 전송 중
nginx_connections_waiting    keepalive 대기
nginx_connections_accepted   총 수락된 연결
nginx_connections_handled    총 처리된 연결
nginx_http_requests_total    총 HTTP 요청 수
nginx_up                     nginx 상태 (1=정상)
```

---

## JSON 로그 + Elasticsearch/Loki 연동

```nginx
log_format json_log escape=json
    '{'
        '"@timestamp":"$time_iso8601",'
        '"host":"$hostname",'
        '"client":"$remote_addr",'
        '"method":"$request_method",'
        '"path":"$uri",'
        '"status":$status,'
        '"size":$body_bytes_sent,'
        '"duration":$request_time,'
        '"upstream":"$upstream_addr",'
        '"upstream_time":"$upstream_response_time",'
        '"agent":"$http_user_agent"'
    '}';

access_log /var/log/nginx/json.log json_log;
```

Filebeat → Elasticsearch:

```yaml
# filebeat.yml
filebeat.inputs:
  - type: log
    paths:
      - /var/log/nginx/json.log
    json.keys_under_root: true
    json.add_error_key: true

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "nginx-access-%{+yyyy.MM.dd}"
```

---

## 헬스체크 엔드포인트

```nginx
server {
    listen 80;

    # 로드밸런서 헬스체크용
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    # 상세 상태 (JSON)
    location /status {
        access_log off;
        allow 10.0.0.0/8;
        deny all;
        return 200 '{"status":"ok","version":"$nginx_version"}';
        add_header Content-Type application/json;
    }
}
```

---

## 알람 기준 권장값

| 메트릭 | 경고 기준 | 위험 기준 |
|--------|-----------|-----------|
| Active connections | > 1000 | > worker_processes × worker_connections × 0.8 |
| 5xx 에러율 | > 1% | > 5% |
| 평균 응답시간 | > 200ms | > 1000ms |
| Worker CPU | > 70% | > 90% |
| Disk I/O (캐시) | > 80% | > 95% |

```bash
# 현재 5xx 에러율 계산
total=$(wc -l < /var/log/nginx/access.log)
errors=$(grep '" 5' /var/log/nginx/access.log | wc -l)
echo "5xx rate: $(echo "scale=2; $errors * 100 / $total" | bc)%"
```
