# 04. Core 지시어 (main context)

main context는 nginx.conf 최상위에 위치하며, 전체 nginx 프로세스에 영향을 줍니다.

---

## user

Worker 프로세스가 실행될 OS 사용자/그룹을 지정합니다.

```nginx
user nginx;
user nginx nginx;    # user group 형식
```

- Master 프로세스는 root로 실행됨 (1024 미만 포트 바인딩 위해)
- Worker 프로세스는 이 user로 실행 → 파일 접근 권한이 이 user 기준
- 웹 루트의 파일이 nginx 유저로 읽힐 수 있어야 함

```bash
# nginx 유저 확인
id nginx

# 웹 루트 권한 확인
ls -la /usr/share/nginx/html/
```

---

## worker_processes

Worker 프로세스 수를 지정합니다.

```nginx
worker_processes 1;       # 단일 Worker
worker_processes 4;       # 4개 Worker
worker_processes auto;    # CPU 코어 수에 맞게 자동 (권장)
```

- `auto`: `/proc/cpuinfo`에서 CPU 코어 수를 읽어 설정
- 일반적으로 CPU 코어 수 = Worker 수로 설정
- I/O 바운드 작업이 많다면 코어 수 × 2도 고려

```bash
# CPU 코어 수 확인
nproc
grep -c processor /proc/cpuinfo
```

---

## worker_cpu_affinity

각 Worker 프로세스를 특정 CPU 코어에 바인딩합니다.

```nginx
worker_processes 4;

# 각 Worker를 개별 코어에 바인딩 (4코어)
worker_cpu_affinity 0001 0010 0100 1000;

# auto: nginx가 자동으로 배분
worker_cpu_affinity auto;

# 모든 Worker가 모든 코어 사용 (기본)
worker_cpu_affinity auto 1111;
```

CPU 캐시 히트율 향상 및 NUMA 아키텍처 최적화에 유용합니다.

---

## worker_rlimit_nofile

Worker 프로세스가 열 수 있는 최대 파일 디스크립터 수입니다.

```nginx
worker_rlimit_nofile 65535;
```

`worker_connections`와 관련: 각 연결은 최소 1개의 fd를 사용하므로
`worker_rlimit_nofile` ≥ `worker_connections`이어야 합니다.

```bash
# OS 전체 파일 디스크립터 한계 확인
ulimit -n
cat /proc/sys/fs/file-max

# OS 레벨 한계 올리기 (/etc/security/limits.conf)
# nginx soft nofile 65535
# nginx hard nofile 65535
```

---

## error_log

에러 로그 파일 경로와 로그 레벨을 설정합니다.

```nginx
error_log /var/log/nginx/error.log;             # 기본 (warn 레벨)
error_log /var/log/nginx/error.log notice;
error_log /var/log/nginx/error.log info;
error_log /var/log/nginx/error.log debug;       # 상세 (개발 시)
error_log /dev/null;                             # 로그 비활성화
```

### 로그 레벨 (낮을수록 상세)

| 레벨 | 설명 |
|------|------|
| `debug` | 모든 디버그 정보 (매우 상세, 고부하) |
| `info` | 정보성 메시지 |
| `notice` | 중요 이벤트 |
| `warn` | 경고 |
| `error` | 처리 오류 |
| `crit` | 심각한 오류 |
| `alert` | 즉각 조치 필요 |
| `emerg` | 시스템 사용 불가 |

지정한 레벨 이상의 로그만 기록됩니다. `warn`을 지정하면 warn/error/crit/alert/emerg만 기록.

---

## pid

Master 프로세스의 PID 파일 경로입니다.

```nginx
pid /var/run/nginx.pid;
```

systemd와 logrotate가 이 파일을 참조합니다.

---

## daemon

백그라운드 데몬으로 실행할지 여부입니다.

```nginx
daemon on;   # 기본값, 백그라운드 실행
daemon off;  # 포그라운드 실행 (Docker 컨테이너에서 사용)
```

Docker에서 nginx를 직접 실행할 때 `daemon off`를 사용하거나
CMD에서 `nginx -g 'daemon off;'`를 씁니다.

---

## master_process

Master/Worker 모델 사용 여부입니다.

```nginx
master_process on;   # 기본값
master_process off;  # 개발/디버깅 시 단일 프로세스로 실행
```

---

## load_module

동적 모듈을 로드합니다.

```nginx
load_module modules/ngx_http_image_filter_module.so;
load_module modules/ngx_stream_module.so;
```

```bash
# 사용 가능한 모듈 확인
ls /usr/lib64/nginx/modules/

# 컴파일된 모듈 목록
nginx -V 2>&1 | grep -o -- '--with-[a-z_]*'
```

---

## env

환경 변수를 Worker 프로세스에 전달합니다.

```nginx
env MALLOC_OPTIONS;         # 기존 환경변수 전달
env PERL5LIB=/data/site/modules;  # 값 설정하여 전달
env OPENSSL_ALLOW_PROXY_CERTS=1;
```

---

## thread_pool

비동기 파일 I/O를 위한 스레드 풀 설정입니다.
(컴파일 시 `--with-threads` 필요)

```nginx
thread_pool default threads=32 max_queue=65536;

# location에서 사용
location /video/ {
    aio threads=default;
    sendfile on;
}
```

---

## 정리: 실운영 권장 main context 설정

```nginx
user nginx;
worker_processes auto;
worker_rlimit_nofile 65535;

error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

load_module modules/ngx_http_geoip2_module.so;  # 필요 시
```
