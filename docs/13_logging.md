# 13. 로깅

---

## access_log

```nginx
access_log /var/log/nginx/access.log;           # 기본 combined 포맷
access_log /var/log/nginx/access.log main;      # 포맷 지정
access_log /var/log/nginx/access.log main buffer=16k;  # 버퍼 사용
access_log /var/log/nginx/access.log main buffer=16k flush=5s;  # 5초마다 플러시
access_log off;                                  # 로그 비활성화
```

---

## error_log

```nginx
error_log /var/log/nginx/error.log;        # 기본 (warn)
error_log /var/log/nginx/error.log warn;
error_log /var/log/nginx/error.log debug;  # 개발용
error_log /dev/stderr warn;               # 표준 에러 (Docker)
```

---

## log_format

커스텀 로그 포맷을 정의합니다.

```nginx
http {
    # 기본 main 포맷 (AL2023 RPM 설치 기준)
    log_format main
        '$remote_addr - $remote_user [$time_local] "$request" '
        '$status $body_bytes_sent "$http_referer" '
        '"$http_user_agent" "$http_x_forwarded_for"';

    # JSON 포맷 (로그 수집 시스템 연동에 유용)
    log_format json_combined escape=json
        '{'
            '"time":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"method":"$request_method",'
            '"uri":"$uri",'
            '"args":"$args",'
            '"status":$status,'
            '"body_bytes":$body_bytes_sent,'
            '"request_time":$request_time,'
            '"upstream_time":"$upstream_response_time",'
            '"upstream_addr":"$upstream_addr",'
            '"http_referer":"$http_referer",'
            '"http_user_agent":"$http_user_agent",'
            '"http_x_forwarded_for":"$http_x_forwarded_for",'
            '"ssl_protocol":"$ssl_protocol",'
            '"ssl_cipher":"$ssl_cipher"'
        '}';

    # 성능 분석용 포맷
    log_format performance
        '$remote_addr [$time_local] "$request" $status '
        'rt=$request_time ut="$upstream_response_time" '
        'cs=$upstream_cache_status';

    access_log /var/log/nginx/access.log main;
    access_log /var/log/nginx/json_access.log json_combined;
}
```

---

## 주요 로그 변수

```
$remote_addr          클라이언트 IP
$remote_user          Basic Auth 사용자명
$time_local           로컬 시간 [01/Jan/2024:12:00:00 +0900]
$time_iso8601         ISO 8601 형식 시간
$request              첫 번째 요청 줄 ("GET /path HTTP/1.1")
$request_method       HTTP 메서드
$request_uri          원본 URI (인코딩 포함, 쿼리스트링 포함)
$uri                  정규화된 URI (rewrite 후 변경될 수 있음)
$args                 쿼리 스트링
$status               HTTP 응답 코드
$body_bytes_sent      응답 바디 크기 (헤더 제외)
$bytes_sent           응답 전체 크기 (헤더 포함)
$request_length       요청 전체 크기
$request_time         요청 처리 시간 (초, 밀리초 단위 소수점)
$http_referer         Referer 헤더
$http_user_agent      User-Agent 헤더
$http_x_forwarded_for X-Forwarded-For 헤더
$upstream_addr        업스트림 서버 주소
$upstream_status      업스트림 응답 코드
$upstream_response_time 업스트림 응답 시간
$upstream_cache_status 캐시 히트 여부 (HIT/MISS 등)
$ssl_protocol         TLS 버전 (TLSv1.2, TLSv1.3)
$ssl_cipher           사용된 암호화 알고리즘
$server_name          server_name 지시어 값
$server_port          서버 포트
$connection           연결 번호
$msec                 현재 시간 (유닉스 타임스탬프, 밀리초 소수점)
$pipe                 파이프라인 요청 여부 (p 또는 .)
```

---

## 조건부 로깅

특정 요청만 로깅하거나 제외합니다.

```nginx
http {
    # 건강 체크 요청 로그 제외
    map $request_uri $log_condition {
        ~^/health  0;
        ~^/ping    0;
        default    1;
    }

    server {
        access_log /var/log/nginx/access.log main if=$log_condition;
    }
}
```

```nginx
# 200/304 성공 응답은 로그 제외 (에러만 기록)
map $status $loggable {
    ~^[23] 0;
    default 1;
}

access_log /var/log/nginx/error_only.log combined if=$loggable;
```

---

## 여러 로그 파일에 동시 기록

```nginx
server {
    access_log /var/log/nginx/access.log main;
    access_log /var/log/nginx/json_access.log json_combined;
    access_log syslog:server=unix:/dev/log main;    # syslog로도 전송
}
```

---

## syslog 전송

```nginx
access_log syslog:server=192.168.1.100:514,facility=local7,tag=nginx,severity=info main;
error_log  syslog:server=unix:/dev/log,nohostname warn;
```

---

## logrotate 설정

`/etc/logrotate.d/nginx` (RPM 설치 시 자동 생성):

```
/var/log/nginx/*.log {
    daily
    missingok
    rotate 52
    compress
    delaycompress
    notifempty
    create 640 nginx adm
    sharedscripts
    postrotate
        if [ -f /var/run/nginx.pid ]; then
            kill -USR1 `cat /var/run/nginx.pid`
        fi
    endscript
}
```

`kill -USR1`은 nginx에게 로그 파일 재오픈(reopen) 신호를 보냅니다.
이를 통해 로테이션 후 새 파일에 계속 기록할 수 있습니다.

수동 실행:

```bash
sudo logrotate -f /etc/logrotate.d/nginx
sudo nginx -s reopen
# 또는
sudo kill -USR1 $(cat /var/run/nginx.pid)
```

---

## 로그 분석 명령어

```bash
# 최다 접근 IP 상위 10개
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10

# 상태 코드별 집계
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn

# 느린 요청 (5초 이상)
awk '$NF > 5 {print}' /var/log/nginx/access.log

# 404 URL 목록
grep '" 404 ' /var/log/nginx/access.log | awk '{print $7}' | sort | uniq -c | sort -rn

# 실시간 모니터링
tail -f /var/log/nginx/access.log

# 특정 IP 요청만
grep "192.168.1.100" /var/log/nginx/access.log

# JSON 로그를 jq로 분석
tail -f /var/log/nginx/json_access.log | jq '.status'
```

---

## 로그 버퍼링으로 성능 향상

```nginx
access_log /var/log/nginx/access.log main buffer=64k flush=5s;
# - buffer=64k: 64KB 버퍼가 찼을 때 한 번에 씀
# - flush=5s: 5초마다 강제 플러시
# 고트래픽 환경에서 I/O 부하 감소
```
