# Nginx Deep Dive 학습 문서

Amazon Linux 2023 환경 기준의 Nginx 완전 분석 문서입니다.

## 문서 목록

| 파일 | 내용 |
|------|------|
| [01_installation.md](docs/01_installation.md) | AL2023 RPM 설치, 디렉토리 구조, systemd 관리 |
| [02_architecture.md](docs/02_architecture.md) | Master/Worker 프로세스 구조, 이벤트 루프, 요청 처리 흐름 |
| [03_config_structure.md](docs/03_config_structure.md) | nginx.conf 전체 구조, Context 계층, 지시어 상속 규칙 |
| [04_core_directives.md](docs/04_core_directives.md) | main context 핵심 지시어 (worker_processes, pid 등) |
| [05_events_module.md](docs/05_events_module.md) | events 블록, worker_connections, use epoll 등 |
| [06_http_module.md](docs/06_http_module.md) | http 블록 전체 지시어, MIME, keepalive 등 |
| [07_server_blocks.md](docs/07_server_blocks.md) | Virtual Host, server_name 매칭, listen 지시어 |
| [08_location_blocks.md](docs/08_location_blocks.md) | location 매칭 우선순위, 정규식, named location |
| [09_upstream.md](docs/09_upstream.md) | Upstream, 로드밸런싱 알고리즘, health check |
| [10_proxy.md](docs/10_proxy.md) | reverse proxy, proxy_pass, 헤더 조작, 버퍼 설정 |
| [11_ssl_tls.md](docs/11_ssl_tls.md) | SSL/TLS 설정, 인증서, OCSP, HTTP/2, mTLS |
| [12_caching.md](docs/12_caching.md) | proxy_cache, fastcgi_cache, 캐시 키, purge |
| [13_logging.md](docs/13_logging.md) | access_log, error_log, 커스텀 포맷, 조건부 로깅 |
| [14_gzip.md](docs/14_gzip.md) | gzip 압축 설정, gzip_static, Brotli |
| [15_security.md](docs/15_security.md) | 보안 헤더, IP 차단, DDoS 대응, 취약점 방어 |
| [16_rate_limiting.md](docs/16_rate_limiting.md) | limit_req, limit_conn, burst, nodelay |
| [17_rewrite_redirect.md](docs/17_rewrite_redirect.md) | rewrite, return, try_files, map |
| [18_fastcgi_php.md](docs/18_fastcgi_php.md) | FastCGI, PHP-FPM 연동, fastcgi_cache |
| [19_websocket.md](docs/19_websocket.md) | WebSocket 프록시 설정 |
| [20_stream_module.md](docs/20_stream_module.md) | TCP/UDP 프록시 (4계층 로드밸런싱) |
| [21_variables.md](docs/21_variables.md) | 내장 변수 전체 목록 및 활용법 |
| [22_performance_tuning.md](docs/22_performance_tuning.md) | OS 튜닝, worker 설정, sendfile, TCP 최적화 |
| [23_monitoring.md](docs/23_monitoring.md) | stub_status, 로그 분석, Prometheus 연동 |

## 빠른 참고

```bash
# 설정 문법 검사
nginx -t

# 설정 재로드 (무중단)
systemctl reload nginx

# 전체 재시작
systemctl restart nginx

# 프로세스 확인
ps aux | grep nginx
```
