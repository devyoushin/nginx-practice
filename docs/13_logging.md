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

### 운영 권장안

access log는 트래픽이 많으면 가장 빠르게 디스크를 채우는 파일입니다.
기본 방향은 **짧은 로컬 보관 + 압축 + 필요 시 외부 저장소 전송**입니다.

권장 기준:

| 상황 | 권장 설정 |
|------|----------|
| 일반 웹/API 서버 | `daily`, `rotate 14~30`, `compress`, `delaycompress` |
| 트래픽 많은 서버 | `daily` + `maxsize 100M~1G`, `rotate 7~14` |
| 감사/보안 요구 있음 | 로컬 7~30일 + S3/로그 플랫폼 장기 보관 |
| 디스크가 작음 | `rotate 7`, `maxage 7`, `maxsize 100M`, 적극적 조건부 로깅 |
| 컨테이너 환경 | 파일 로그보다 stdout/stderr + 런타임 로그 정책 사용 |

실무에서 무난한 예시:

```conf
/var/log/nginx/*.log {
    daily
    maxsize 500M
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    dateext
    dateformat -%Y%m%d
    create 640 nginx adm
    sharedscripts
    postrotate
        if [ -f /run/nginx.pid ]; then
            kill -USR1 `cat /run/nginx.pid`
        elif [ -f /var/run/nginx.pid ]; then
            kill -USR1 `cat /var/run/nginx.pid`
        fi
    endscript
}
```

핵심 옵션:

| 옵션 | 의미 |
|------|------|
| `daily` | 하루 단위로 회전 |
| `maxsize 500M` | 일 단위 회전 전이라도 500MB를 넘으면 회전 대상 |
| `rotate 14` | 압축된 과거 로그를 14개 보관 |
| `compress` | 과거 로그 gzip 압축 |
| `delaycompress` | 직전 로그는 다음 회전 때 압축 |
| `dateext` | `access.log-20240522.gz` 형태로 날짜 suffix 사용 |
| `notifempty` | 빈 로그 파일은 회전하지 않음 |
| `missingok` | 로그 파일이 없어도 에러 처리하지 않음 |
| `create 640 nginx adm` | 새 로그 파일 권한/소유자 지정 |
| `sharedscripts` | 여러 로그 파일이 매칭되어도 `postrotate`는 한 번만 실행 |

주의할 점:

- `copytruncate`는 nginx에는 보통 사용하지 않습니다. 복사 후 파일을 자르는 동안 로그 유실 가능성이 있습니다.
- nginx는 열린 파일 디스크립터에 계속 쓰므로, 회전 후 반드시 `USR1` 신호나 `nginx -s reopen`으로 로그 파일을 다시 열어야 합니다.
- 여기서 `kill -USR1`의 `kill`은 프로세스를 종료한다는 뜻이 아니라, nginx master process에 시그널을 보내는 명령입니다.
- `size`는 시간 기준(`daily`, `weekly` 등)과 조합 의도가 헷갈릴 수 있습니다. "매일 돌리되 너무 크면 더 빨리 회전"이 목적이면 `maxsize`를 사용합니다.
- logrotate가 하루 한 번만 실행되면 용량 조건도 하루 한 번만 판단합니다. 초고트래픽이면 logrotate 실행 주기(systemd timer/cron)도 같이 확인합니다.
- `rotate`만 믿지 말고 디스크 여유가 작은 서버는 `maxage`, `maxsize`도 함께 검토합니다.

### nginx와 Tomcat 로그 회전 차이

nginx 예시에서 자주 보이는 아래 명령은 nginx를 죽이는 명령이 아닙니다.

```bash
kill -USR1 $(cat /run/nginx.pid)
```

`kill` 명령으로 `USR1` 시그널을 보내면 nginx master process는 로그 파일을 다시 엽니다.
logrotate가 기존 `access.log`를 날짜가 붙은 파일로 바꾸고 새 `access.log`를 만든 뒤, nginx가 새 파일에 쓰도록 전환하는 절차입니다.

흐름:

```text
1. nginx가 /var/log/nginx/access.log 파일을 열고 계속 기록
2. logrotate가 access.log를 access.log-20260522 같은 이름으로 변경
3. logrotate가 새 access.log 파일 생성
4. nginx master process에 USR1 시그널 전송
5. nginx가 로그 파일을 close/reopen
6. 이후 로그는 새 access.log에 기록
```

Tomcat 같은 JVM 애플리케이션은 보통 방식이 다릅니다.
로그 파일 회전은 OS의 logrotate보다 JVM 내부 로깅 프레임워크가 처리하는 경우가 많습니다.

대표 예:

- Logback `RollingFileAppender`
- Log4j2 `RollingFile`
- java.util.logging
- Tomcat JULI/Catalina logging

비교:

| 구분 | nginx | Tomcat/JVM |
|------|-------|------------|
| 로그 작성 주체 | nginx master/worker | JVM 로깅 프레임워크 |
| 흔한 회전 방식 | OS logrotate + nginx reopen | Logback/Log4j2 등 내부 rolling |
| PID 시그널 | `USR1`로 로그 파일 재오픈 | 보통 사용하지 않음 |
| `kill -USR1` 의미 | 종료가 아니라 reopen 지시 | 일반적인 운영 방식 아님 |
| 주의점 | reopen 없으면 이전 파일에 계속 쓸 수 있음 | 외부 logrotate의 `copytruncate`는 유실 가능성 있음 |

정리하면 nginx는 외부 logrotate가 파일을 바꾼 뒤 nginx에게 "로그 파일 다시 열어라"라고 알려줘야 하고,
Tomcat/JVM은 애플리케이션 내부 로깅 설정에서 날짜/크기 기준으로 직접 rolling하는 구성이 일반적입니다.

디스크 보호를 더 강하게 걸고 싶을 때:

```conf
/var/log/nginx/*.log {
    daily
    maxsize 200M
    maxage 14
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    dateext
    create 640 nginx adm
    sharedscripts
    postrotate
        nginx -s reopen
    endscript
}
```

### access log 폭증 줄이는 방법

logrotate는 쌓인 파일을 정리하는 장치이고, 로그량 자체를 줄이지는 않습니다.
로그가 너무 많이 쌓이면 아래 설정을 같이 적용합니다.

헬스 체크, 정적 파일 로그 제외:

```nginx
map $request_uri $loggable_uri {
    ~^/(health|ping)$ 0;
    default 1;
}

map $uri $loggable_static {
    ~*\.(css|js|jpg|jpeg|png|gif|ico|svg|woff|woff2)$ 0;
    default 1;
}

map "$loggable_uri:$loggable_static" $access_loggable {
    "1:1" 1;
    default 0;
}

access_log /var/log/nginx/access.log main if=$access_loggable;
```

성공 요청은 샘플링하고 에러는 모두 남기는 방식:

```nginx
split_clients "$remote_addr$request_uri" $sampled {
    10%     1;
    *       0;
}

map $status $must_log {
    ~^[45]  1;
    default $sampled;
}

access_log /var/log/nginx/access.log main if=$must_log;
```

버퍼링으로 디스크 I/O 줄이기:

```nginx
access_log /var/log/nginx/access.log main buffer=64k flush=5s;
```

### 보관 정책 예시

운영 문서에는 아래처럼 기준을 숫자로 고정해두는 것이 좋습니다.

```text
access.log 보관 정책
- 로컬 원본 로그: 현재 파일만 유지
- 로컬 압축 로그: 14일 보관
- 회전 기준: 매일 또는 500MB 초과
- 압축: gzip, 직전 로그는 다음 회전 때 압축
- 장기 보관: 필요한 경우 S3/CloudWatch/OpenSearch 등 외부 저장소에 90일 이상 보관
- 제외 대상: /health, /ping, 정적 파일 요청
- 필수 기록 대상: 4xx/5xx, 느린 요청, 관리자/결제/인증 관련 경로
```

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
