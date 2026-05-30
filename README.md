# nginx-practice

Amazon Linux 2023 기준으로 Nginx 설치, 설정 구조, 프록시, TLS, 캐싱, 보안, 성능 튜닝을 정리한 개인 학습 문서입니다.

## 빠른 시작

- 처음 볼 문서: `docs/install/01_installation.md`
- 전체 흐름: 설치 -> 아키텍처 -> 설정 구조 -> HTTP/Proxy/TLS -> 보안/성능/운영
- AI 작업 지침: `CLAUDE.md`

## 구조

```text
nginx-practice/
├── README.md
├── CLAUDE.md
├── docs/
│   ├── README.md
│   ├── install/
│   ├── architecture/
│   ├── config/
│   ├── proxy/
│   ├── security/
│   ├── performance/
│   └── operations/
└── ops/
    ├── memory/    # 프로젝트 메모리
    └── tools/     # 설정 예시와 보조 도구
```

## 주요 문서

| 범위 | 문서 |
|------|------|
| 시작 | `docs/install/01_installation.md`, `docs/architecture/02_architecture.md` |
| 설정 | `docs/config/03_config_structure.md`, `docs/config/04_core_directives.md` |
| HTTP | `docs/config/06_http_module.md`, `docs/config/07_server_blocks.md`, `docs/config/08_location_blocks.md` |
| 프록시 | `docs/proxy/09_upstream.md`, `docs/proxy/10_proxy.md`, `docs/proxy/19_websocket.md` |
| 운영 | `docs/operations/13_logging.md`, `docs/performance/22_performance_tuning.md`, `docs/operations/25_production_overload_response.md` |

## 빠른 명령

```bash
nginx -t
systemctl reload nginx
systemctl restart nginx
ps aux | grep nginx
```
