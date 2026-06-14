# 26. 무중단 배포와 빠른 롤백 운영

---

## 핵심 관점

실무에서 nginx는 단순 reverse proxy뿐 아니라 배포 전환 지점으로 자주 사용합니다.
애플리케이션 서버를 새 버전으로 교체할 때 nginx upstream을 조정하면, 전체 서비스를 내리지 않고 트래픽을 점진적으로 옮기거나 문제가 생겼을 때 빠르게 되돌릴 수 있습니다.

운영 목표는 세 가지입니다.

```text
1. 새 버전을 일부 트래픽에만 먼저 노출한다.
2. 헬스 체크와 로그로 이상 여부를 확인한다.
3. 문제가 있으면 nginx 설정만 되돌려 즉시 롤백한다.
```

이 문서는 `blue/green`, `canary`, `drain`, `rollback`을 nginx 설정과 운영 절차 중심으로 정리합니다.

---

## 1. 기본 구조

예시는 아래처럼 두 개의 애플리케이션 그룹이 있다고 가정합니다.

| 그룹 | 용도 | 서버 |
|------|------|------|
| `blue` | 현재 운영 버전 | `10.0.10.11:8080`, `10.0.10.12:8080` |
| `green` | 새 배포 버전 | `10.0.20.11:8080`, `10.0.20.12:8080` |

평소에는 `blue`로 대부분의 요청을 보내고, 배포 검증 시 `green`으로 일부 요청만 보냅니다.

```nginx
upstream app_blue {
    zone app_blue 64k;
    server 10.0.10.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.10.12:8080 max_fails=3 fail_timeout=10s;
}

upstream app_green {
    zone app_green 64k;
    server 10.0.20.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.20.12:8080 max_fails=3 fail_timeout=10s;
}
```

`zone`은 upstream 상태를 worker 간 공유하기 위해 둡니다. 운영에서 upstream 서버 수가 많거나 worker가 여러 개라면 넣어두는 편이 안전합니다.

---

## 2. 공통 proxy 설정

배포 전환용 설정은 timeout과 헤더가 일관되어야 합니다.
버전별 location마다 proxy 설정이 다르면 장애 분석이 어려워집니다.

```nginx
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;

proxy_connect_timeout 3s;
proxy_send_timeout 30s;
proxy_read_timeout 30s;

proxy_next_upstream error timeout http_502 http_503 http_504;
proxy_next_upstream_tries 2;
```

주의할 점:

- `proxy_next_upstream`은 멱등 요청 중심으로 쓰는 것이 안전합니다.
- 결제, 주문, 상태 변경 API는 재시도 때문에 중복 처리 문제가 생길 수 있습니다.
- 애플리케이션이 idempotency key를 지원하지 않는다면 `POST`, `PATCH` 요청 재시도는 보수적으로 다룹니다.

---

## 3. Blue/Green 전환

가장 단순한 방식은 `map`으로 현재 active upstream을 선택하는 것입니다.

```nginx
map $http_x_release_target $app_upstream {
    default app_blue;
    green   app_green;
}

server {
    listen 80;
    server_name app.example.com;

    location = /health {
        access_log off;
        return 200 "ok\n";
    }

    location / {
        proxy_pass http://$app_upstream;
    }
}
```

이 방식은 기본 트래픽은 `blue`로 보내고, 검증 요청만 헤더로 `green`에 보낼 수 있습니다.

```bash
curl -H 'X-Release-Target: green' http://app.example.com/health
curl -H 'X-Release-Target: green' http://app.example.com/api/version
```

검증이 끝나면 `default app_green;`으로 변경하고 reload합니다.

```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## 4. Canary 배포

일부 사용자만 새 버전으로 보내려면 `split_clients`를 사용합니다.

```nginx
split_clients "${remote_addr}${http_user_agent}" $release_group {
    5%      green;
    *       blue;
}

map $release_group $app_upstream {
    green   app_green;
    default app_blue;
}

server {
    listen 80;
    server_name app.example.com;

    location / {
        add_header X-Release-Group $release_group always;
        proxy_pass http://$app_upstream;
    }
}
```

운영에서는 1%, 5%, 10%, 25%, 50%, 100%처럼 단계적으로 올립니다.
각 단계마다 최소한 아래 지표를 확인합니다.

```bash
# 5xx 비율
awk '$9 ~ /^5/ {count++} END {print count+0}' /var/log/nginx/access.log

# release group별 응답 상태를 로그에 넣은 경우
grep 'release=green' /var/log/nginx/access.log | awk '{print $9}' | sort | uniq -c

# upstream timeout 확인
grep -E 'upstream timed out|connect\\(\\) failed|no live upstreams' /var/log/nginx/error.log | tail -50
```

`split_clients` 기준값은 바꾸면 사용자 일부가 다른 그룹으로 이동할 수 있습니다.
같은 사용자를 최대한 같은 그룹에 묶고 싶다면 `remote_addr`보다 로그인 사용자 ID, 세션 ID, 고정 쿠키 같은 값을 기준으로 삼는 편이 좋습니다.

---

## 5. Drain 후 서버 교체

특정 upstream 서버를 빼고 새 버전으로 교체할 때는 바로 프로세스를 죽이지 말고 먼저 nginx에서 트래픽을 빼는 것이 안전합니다.

```nginx
upstream app_blue {
    server 10.0.10.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.10.12:8080 max_fails=3 fail_timeout=10s down;
}
```

절차:

```text
1. 교체할 서버에 down 표시
2. nginx -t
3. nginx reload
4. 기존 요청이 빠질 시간을 둠
5. 애플리케이션 배포
6. 서버 자체 health 확인
7. down 제거
8. nginx -t 후 reload
```

확인 명령:

```bash
# 해당 서버로 가는 연결이 줄어드는지 확인
ss -tan dst 10.0.10.12:8080

# access log에서 upstream 주소를 기록하고 있다면 확인
grep 'upstream=10.0.10.12:8080' /var/log/nginx/access.log | tail
```

로그 포맷에 `$upstream_addr`를 넣어두면 서버 교체 시 훨씬 빨리 판단할 수 있습니다.

```nginx
log_format main '$remote_addr "$request" $status '
                'rt=$request_time urt=$upstream_response_time '
                'upstream=$upstream_addr release=$release_group';
```

---

## 6. 빠른 롤백

배포 중 문제가 생기면 애플리케이션을 다시 배포하기보다 먼저 nginx 트래픽 방향을 되돌립니다.

### Blue/Green 롤백

`map` 기본값을 이전 버전으로 바꿉니다.

```nginx
map $http_x_release_target $app_upstream {
    default app_blue;
    green   app_green;
}
```

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Canary 롤백

`green` 비율을 0%로 내립니다.

```nginx
split_clients "${remote_addr}${http_user_agent}" $release_group {
    0%      green;
    *       blue;
}
```

nginx reload 후 새 요청은 다시 `blue`로 흐릅니다.

```bash
sudo nginx -t && sudo systemctl reload nginx
```

롤백 후에는 아래를 확인합니다.

```bash
tail -f /var/log/nginx/error.log
awk '$9 ~ /^5/ {print}' /var/log/nginx/access.log | tail -50
curl -i http://app.example.com/health
```

---

## 7. 운영 체크리스트

배포 전:

- `nginx -t`가 통과하는지 확인
- 새 버전 서버의 `/health`가 정상인지 확인
- access log에 `$upstream_addr`, `$request_time`, `$upstream_response_time`이 있는지 확인
- 롤백할 이전 설정 파일을 보관
- 배포 대상 서버와 upstream 목록이 실제 인프라 상태와 맞는지 확인

배포 중:

- canary 비율은 한 번에 크게 올리지 않음
- 5xx, timeout, latency, upstream별 에러를 단계마다 확인
- 특정 upstream만 에러가 높으면 전체 롤백보다 해당 서버만 `down` 처리
- 설정 변경 후에는 항상 `nginx -t` 후 reload

배포 후:

- 이전 버전 서버를 바로 제거하지 말고 관찰 시간을 둠
- 롤백 기준과 실제 발생 지표를 기록
- 배포 중 사용한 임시 헤더, 임시 location, debug log를 제거

---

## 8. 실무 기준 예시

일반적인 API 서비스라면 아래 기준으로 시작할 수 있습니다.

| 단계 | green 비율 | 관찰 시간 | 확인 지표 |
|------|------------|-----------|-----------|
| smoke | 헤더 검증만 | 5분 | health, version, 주요 API |
| canary 1 | 1% | 10분 | 5xx, p95 latency, upstream timeout |
| canary 2 | 5% | 20분 | 에러율, DB/API dependency |
| canary 3 | 25% | 30분 | 리소스 사용률, 비즈니스 지표 |
| full | 100% | 1시간 이상 | 전체 지표 안정성 |

롤백 기준은 배포 전에 정합니다.

```text
- 5xx 비율이 평소 대비 2배 이상 증가
- p95 응답 시간이 30% 이상 증가
- upstream timed out 증가
- 특정 핵심 API 오류 증가
- 애플리케이션 로그에서 새 버전 오류 반복
```

기준이 없으면 장애 상황에서 판단이 늦어집니다. 배포 절차에는 항상 전환 방법과 롤백 방법을 같이 적어둡니다.
