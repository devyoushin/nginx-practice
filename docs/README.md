# Nginx Docs

Nginx 학습 문서는 주제별로 나눠 관리합니다.

| 폴더 | 내용 |
|------|------|
| `install/` | 설치, 패키지, systemd 기본 실행 |
| `architecture/` | Master/Worker 구조, 이벤트 처리 |
| `config/` | nginx.conf 구조, context, server/location, 변수, rewrite, 자주 쓰는 모듈 |
| `proxy/` | upstream, reverse proxy, FastCGI, WebSocket, stream |
| `security/` | TLS, 보안 헤더, rate limiting |
| `performance/` | 캐싱, gzip, OS/Nginx 튜닝 |
| `operations/` | 로깅, 모니터링, 설정 분리, 부하 대응 |

처음 읽을 문서는 `install/01_installation.md`입니다.

## 실무 운영 문서

- [24. 설정 분리와 운영 튜닝](operations/24_practical_tuning_and_split_conf.md)
- [25. 운영 중 부하 발생 시 대응 방법](operations/25_production_overload_response.md)
- [26. 무중단 배포와 빠른 롤백 운영](operations/26_zero_downtime_release.md)
- [28. Nginx 업그레이드 절차](operations/28_nginx_upgrade.md)
