# place-report

리조트피플 지점별 네이버 플레이스 순위 · 리뷰 수 · 월 검색량 리포트

- 매일 오후 3시(KST) 전후로 애드로그 '플레이스 순위 체크'에서 당일 데이터를 자동 수집합니다. 애드로그는 13:40 이후 당일 순위를 갱신합니다.
- 수집이 끝나면 대시보드가 GitHub Pages에 자동으로 반영됩니다.

## 구성

| 경로 | 내용 |
|---|---|
| `site/` | 대시보드 (index.html, data.js, 폰트, 로고) |
| `scraper/collect.py` | 애드로그 로그인 · 수집 · data.js 생성 |
| `config/keywords.json` | 추적 키워드 목록 (애드로그 키워드 번호 · 지점 그룹 · 표시 이름) |
| `data/history.json` | 누적 기록 |
| `.github/workflows/daily.yml` | 매일 자동 실행 설정 |

## 키워드 추가 · 삭제

1. 애드로그에서 키워드를 등록합니다.
2. `config/keywords.json`에 키워드를 추가하고 `site/index.html`의 지점 키워드 목록(`BR`)에도 같은 이름으로 넣습니다.
3. 다음 수집 때 이전 기록(최대 약 100일)까지 함께 채워집니다.

## 로그인 정보

`Settings → Secrets and variables → Actions`의 `ADLOG_ID`, `ADLOG_PW`를 사용합니다. 애드로그 비밀번호를 바꾸면 `ADLOG_PW`도 함께 수정해주세요.
