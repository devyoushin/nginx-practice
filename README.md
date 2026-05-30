# nginx-practice

Nginx를 설치하고 운영하기 위한 개인 학습 공간입니다.

## 어디서 시작할까

- 문서 지도: `docs/README.md`
- 첫 문서: `docs/install/01_installation.md`
- 운영 보조 자료: `ops/README.md`
- AI 작업 지침: `CLAUDE.md`

## 구조

| 경로 | 내용 |
|------|------|
| `docs/` | 설치, 설정, 프록시, 보안, 성능, 운영 문서 |
| `ops/` | 설정 예시, 리팩터링 도구, 프로젝트 메모리 |
| `CLAUDE.md` | 이 레포에서 Claude가 참고할 작업 지침 |

## 빠른 명령

```bash
nginx -t
systemctl reload nginx
systemctl restart nginx
```
