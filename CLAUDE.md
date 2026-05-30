# Nginx Deep Dive 학습 프로젝트

Amazon Linux 2023 환경 기준의 Nginx 완전 분석 문서 모음입니다.

## 프로젝트 구조

```
.
├── README.md          # 프로젝트 소개 및 문서 목록
├── CLAUDE.md          # 이 파일
├── docs/
│   ├── README.md      # 문서 구조 안내
│   ├── install/       # 설치
│   ├── architecture/  # 구조
│   ├── config/        # 설정
│   ├── proxy/         # 프록시
│   ├── security/      # 보안
│   ├── performance/   # 성능
│   └── operations/    # 운영
└── ops/
    ├── memory/        # AI 작업용 프로젝트 메모리
    └── tools/         # 실습용 설정 예시와 보조 자료
```

## 문서 규칙

- 문서 파일명은 `{번호}_{주제}.md` 형식 (예: `01_installation.md`)
- 모든 학습 문서는 `docs/` 디렉토리에 위치
- 한국어로 작성
