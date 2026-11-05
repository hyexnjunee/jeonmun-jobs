# 전문연구요원 채용공고 모아보기

병무청 병역일터에 올라오는 **전문연구요원** 채용공고를 3시간마다 자동으로 모아 보여주는 웹사이트입니다.
서버 없이 GitHub만으로 돌아가고, 비용은 들지 않습니다.

- 지금 지원할 수 있는 전문연구요원 공고만 표시 (마감 지난 공고, 산업기능요원 공고 제외)
- 앞으로 6주 마감 일정을 한눈에 보는 마감 일정 띠, 날짜를 누르면 그날 마감 공고만 표시
- 역종(보충역/현역), 지역, 학력, 연봉, 업종 필터와 검색
- 관심 키워드(최적화, 스케줄링, 물류, AI 등)가 들어간 공고를 형광펜으로 표시
- 최근 3일 안에 새로 올라온 공고에 '새 공고' 표시, 관심 공고 저장
- 관심 키워드에 맞는 새 공고가 올라오면 GitHub 이슈로 알림, RSS 구독(`feed.xml`)

## 동작 방식

```
GitHub Actions (3시간마다)
  └ scripts/fetch_jobs.py
      ├ 공공데이터포털 '병무청 병역일터 채용공고' API 호출
      ├ 전문연구요원 + 진행 중인 공고만 골라 site/data/jobs.json 저장
      ├ state/seen.json 으로 처음 본 날짜를 기록해 새 공고 판별
      └ 관심 키워드에 맞는 새 공고가 있으면 이슈 생성
  └ site/ 폴더를 GitHub Pages로 배포
```

## 설정 방법 (처음 한 번, 15분 정도)

### 1. 공공데이터포털 인증키 받기

1. [공공데이터포털](https://www.data.go.kr)에 회원가입하고 로그인합니다.
2. [병무청 병역일터 채용공고](https://www.data.go.kr/data/3065599/openapi.do) 페이지에서 **활용신청**을 누릅니다. 활용 목적은 "개인 취업 준비용 공고 모아보기" 정도로 적으면 됩니다.
3. 마이페이지 → 데이터활용 → Open API → 활용신청 현황에서 **일반 인증키(Decoding)** 를 복사합니다.
   - 승인 직후에는 키가 바로 동작하지 않을 수 있습니다. 첫 실행이 인증키 오류로 실패하면 한두 시간 뒤 다시 실행해 보세요.

### 2. GitHub 저장소 만들기

1. GitHub에서 새 저장소를 만듭니다 (예: `jeonmun-jobs`, **Public**). 무료 계정에서 GitHub Pages를 쓰려면 공개 저장소여야 합니다.
2. 이 폴더의 파일을 모두 올립니다. 명령줄을 쓴다면:
   ```bash
   cd jeonmun-jobs
   git init -b main
   git add .
   git commit -m "처음 올리기"
   git remote add origin https://github.com/<내아이디>/jeonmun-jobs.git
   git push -u origin main
   ```
   웹에서 올린다면 저장소 화면의 **Add file → Upload files**로 폴더째 끌어다 놓으면 됩니다. `.github` 폴더가 빠지지 않았는지 꼭 확인하세요.

### 3. 인증키 등록

저장소 **Settings → Secrets and variables → Actions → New repository secret**
- Name: `DATA_GO_KR_KEY`
- Secret: 1단계에서 복사한 인증키

### 4. GitHub Pages 켜기

저장소 **Settings → Pages → Build and deployment → Source** 를 **GitHub Actions** 로 바꿉니다.

### 5. 첫 실행

**Actions** 탭 → 왼쪽 **공고 업데이트** → **Run workflow**. 1~2분 뒤 초록색 체크가 뜨면
`https://<내아이디>.github.io/jeonmun-jobs/` 에서 사이트를 볼 수 있습니다. 이후로는 3시간마다 저절로 업데이트됩니다.

### 6. 새 공고 알림 받기 (선택)

관심 키워드에 맞는 새 공고가 올라오면 저장소에 이슈가 하나 생깁니다. 저장소 오른쪽 위 **Watch** 가 `All Activity` 로 되어 있으면
GitHub 알림(이메일·모바일 앱)으로 받을 수 있습니다. 알림 메일이 안 오면 GitHub **Settings → Notifications** 에서 이메일 알림이 켜져 있는지 확인하세요.

## 바꿔 쓰기

`site/config.json`

| 항목 | 설명 |
|---|---|
| `site_title` | 사이트 제목 |
| `default_service` | 처음 열 때 역종 필터. `""`(전체), `"보충역"`, `"현역"` |
| `interest_keywords` | 형광펜 표시와 알림에 쓰는 관심 키워드 |
| `new_days` | 며칠 안에 처음 발견된 공고를 '새 공고'로 볼지 |
| `notify_new_matches` | `false`로 바꾸면 이슈 알림을 끕니다 |

`OR`, `AI` 처럼 두 글자 영문 키워드는 `ORDER`, `MAIN` 같은 단어에 잘못 걸리지 않도록 대문자 그대로, 단어 단위로만 찾습니다.
사이트의 **관심 키워드 바꾸기** 에서 바꾼 키워드는 그 브라우저에만 적용되고, 알림 키워드는 `config.json` 값을 씁니다.

업데이트 주기는 `.github/workflows/update.yml` 의 `cron` 을 고치면 됩니다. 공공데이터포털 개발계정은 하루 호출 수 제한이 있으니 1시간보다 자주 돌리지 않는 걸 권합니다.

## 내 컴퓨터에서 테스트

Python 3.9 이상, 추가 설치 필요 없음.

```bash
DATA_GO_KR_KEY=인증키 python scripts/fetch_jobs.py   # site/data/jobs.json 생성
python -m http.server -d site 8000                  # http://localhost:8000 에서 확인
```

Windows PowerShell에서는 `$env:DATA_GO_KR_KEY="인증키"; python scripts/fetch_jobs.py`

## 폴더 구조

```
.github/workflows/update.yml  자동 수집·배포 워크플로
scripts/fetch_jobs.py         API 수집·정리 스크립트
site/index.html               웹사이트 (HTML·CSS·JS 한 파일)
site/config.json              사이트 설정, 관심 키워드
site/data/jobs.json           수집한 공고 (자동 생성)
site/feed.xml                 RSS (자동 생성)
state/seen.json               공고를 처음 본 날짜 기록 (자동 생성)
```

## 알아둘 점

- API에는 공고 상세 본문(자격요건, 우대사항)과 현역·보충역 배정 인원이 들어 있지 않습니다. 이런 내용은 각 공고의 **병역일터 원문** 링크에서 확인하세요.
- 역종은 공고에 표시된 값입니다. '현역'으로 올라온 공고라도 회사에 보충역 편입이 가능한지 문의해 볼 수 있습니다.
- 첫 실행 때는 이미 올라와 있던 공고를 공고 등록일 기준으로 기록하기 때문에, 첫날부터 모든 공고가 '새 공고'로 뜨지는 않습니다.
- API가 0건을 돌려주는 등 이상한 응답이 오면 기존 데이터를 지우지 않고 실행을 실패로 끝냅니다. Actions 탭의 실행 기록에서 원인을 볼 수 있습니다.
- 공개 저장소에 60일 동안 아무 활동이 없으면 GitHub가 예약 실행을 멈춥니다. 공고가 바뀔 때마다 자동 커밋이 생기므로 보통은 문제없지만, 멈췄다면 Actions 탭에서 다시 켜면 됩니다.

데이터 출처: 병무청 병역일터 채용공고 (공공데이터포털 오픈API, 이용허락범위 제한 없음)
