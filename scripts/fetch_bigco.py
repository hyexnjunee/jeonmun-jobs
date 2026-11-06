#!/usr/bin/env python3
"""대기업 정보 수집: 전문연구요원 지정 대기업 연구소 목록 + 사람인 대기업 채용공고.

대기업은 현역 배정이 없어 병역일터에 공고를 거의 올리지 않고, 4급 보충역은 대기업 연구소에
신규편입이 가능하다. 그래서 두 가지를 모은다.

1) 지정 대기업 연구소 목록 (병무청 '전문연구/산업기능요원 지정업체 정보' API, 6일에 한 번)
   https://www.data.go.kr/data/3066759/openapi.do  → DATA_GO_KR_KEY 로 활용신청 필요
2) 사람인에 올라온 대기업 공고 중 내 분야 키워드 검색 결과 (매 실행)
   https://oapi.saramin.co.kr  → SARAMIN_KEY (사람인 API access-key) 필요, 없으면 건너뜀

어느 쪽이든 키가 없거나 실패하면 그 부분만 상태 메시지를 남기고 나머지는 계속한다.
결과: site/data/bigco.json
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_jobs import KST, SITE, _homepage, parse_page, write_json  # noqa: E402

# 문서상 주소는 첫 번째지만 '서비스 없음(12)'이 나는 경우가 있어 대소문자·버전 후보를 차례로 시도한다.
COMPANY_APIS = [
    "https://apis.data.go.kr/1300000/jjEopChe/list2/getjjEopChe",  # 영문 상세페이지의 Requested Link
    "https://apis.data.go.kr/1300000/jjEopChe/list2",
    "https://apis.data.go.kr/1300000/JjEopChe/list2",
    "https://apis.data.go.kr/1300000/jjEopChe/list",
    "https://apis.data.go.kr/1300000/JjEopChe/list",
    "https://apis.data.go.kr/1300000/JJEopChe/list2",
]
SARAMIN_API = "https://oapi.saramin.co.kr/job-search"
OUT = SITE / "data" / "bigco.json"
COMPANY_REFRESH_DAYS = 6


def http_get(url: str, headers: dict | None = None, retries: int = 3) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "jeonmun-jobs/1.0", **(headers or {})})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return res.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:  # 4xx는 재시도해도 같으니 바로 올린다
            body = e.read().decode("utf-8", errors="replace")[:3000]
            if 400 <= e.code < 500:
                raise RuntimeError(f"HTTP {e.code}: {body}")
            last = e
        except Exception as e:
            last = e
        time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"요청 실패: {last}")


# ---------------------------------------------------------------- 이름 정규화
ALIASES = [("엘지", "lg"), ("에스케이", "sk"), ("씨제이", "cj"), ("케이티", "kt"), ("지에스", "gs"), ("엘에스", "ls"), ("에이치디", "hd")]


def norm(name: str) -> str:
    s = html.unescape(name or "").lower()
    s = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(재\)|재단법인|\(사\)|사단법인", "", s)
    for ko, en in ALIASES:
        if s.startswith(ko) or re.match(rf"^\W*{ko}", s):
            s = s.replace(ko, en, 1)
    return re.sub(r"[\s\W_]+", "", s)


def group_of(name: str, groups: list[dict]) -> dict | None:
    n = norm(name)
    for g in groups:
        for m in g.get("match", []):
            if n.startswith(norm(m)):
                return g
    return None


# ---------------------------------------------------------------- 1) 지정 대기업 연구소
def _pick(row: dict, *needles: str, prefer_nm: bool = True) -> str:
    """needles를 앞에서부터 차례로 시도한다. 같은 needle에 걸린 키가 여럿이면 ...nm(이름) 키를 우선."""
    for nd in needles:
        keys = [k for k in row if nd in k and row[k]]
        if prefer_nm:
            keys.sort(key=lambda k: (not k.endswith("nm"), len(k)))
        if keys:
            return row[keys[0]]
    return ""


def _company_page(key: str, page: int, base: str | None = None) -> tuple[str, str]:
    q = urllib.parse.urlencode({"serviceKey": key, "numOfRows": 1000, "pageNo": page})
    if base:
        return base, http_get(f"{base}?{q}")
    errors = []
    for cand in COMPANY_APIS:
        try:
            text = http_get(f"{cand}?{q}", retries=1)
        except RuntimeError as e:
            text = str(e)
        if "NO_OPENAPI_SERVICE" in text or "<returnReasonCode>12<" in text:
            errors.append(cand.rsplit("/1300000/", 1)[1])
            print(f"  {cand} → 서비스 없음(12)")
            continue
        print(f"  지정업체 API 주소: {cand}")
        return cand, text.split(": ", 1)[1] if text.startswith("HTTP ") else text
    raise RuntimeError("지정업체 API 주소를 찾지 못했어요 (모두 '서비스 없음' 응답): " + ", ".join(errors))


def fetch_companies(key: str) -> list[dict]:
    key = urllib.parse.unquote(key.strip())
    rows: list[dict] = []
    base = None
    for page in range(1, 60):
        base, text = _company_page(key, page, base)
        items, total = parse_page(text)
        rows.extend(items)
        print(f"  지정업체 page {page}: {len(items)}건 (누적 {len(rows)} / 전체 {total})")
        if not items or len(items) < 1000 or (total is not None and len(rows) >= total):
            break
        time.sleep(1)
    return rows


BIGCO_LAB_CODE = "21501"  # 업종구분코드: 21502 중소, 21503 벤처, 21504 중견기업부설연구소 → 21501 대기업부설연구소로 추정
ANCHORS = ["삼성전자", "LG전자", "SK하이닉스", "현대자동차", "LG화학", "삼성SDI"]
GROUP_PREFIXES = ["삼성", "LG", "SK", "현대", "기아", "HD현대", "포스코", "한화", "CJ", "롯데", "GS", "두산", "LS",
                  "네이버", "카카오", "쿠팡", "KT", "HMM", "LIG", "엘아이지", "대한항공", "효성", "코오롱", "토스"]


def _is_bigco_factory(rows: list[dict]):
    """대기업 연구소 판별 함수를 만든다.
    - 이름값 방식: 값에 '대기업'과 '연구'가 들어 있으면 대기업 연구소
    - 코드 방식(병역일터 API는 업종·기업구분을 코드로 줌): 업종코드 2xxxx(전문연구요원)이면서
      업종코드가 21501이거나, 기업구분코드가 기준 대기업(삼성전자 등)들의 기업구분코드와 같으면 대기업
    """
    def low(raw):
        return {k.lower(): (v or "").strip() for k, v in raw.items()}
    rs = [low(r) for r in rows]
    eopjong = lambda r: _pick(r, "eopjonggbcd", "eopjong", "upjong", prefer_nm=False)
    gyumo = lambda r: _pick(r, "gegyumocd", "gyumo", prefer_nm=False)
    research = [r for r in rs if eopjong(r).startswith("2")]
    anchor_codes = [gyumo(r) for r in research
                    if gyumo(r) and any(norm(_pick(r, "eopchenm", "eopche")).startswith(norm(a)) for a in ANCHORS)]
    from collections import Counter
    big_code = Counter(anchor_codes).most_common(1)[0][0] if len(anchor_codes) >= 2 else None
    if rs:
        by_code: dict[str, list[str]] = {}
        for r in research:
            by_code.setdefault(eopjong(r), []).append(_pick(r, "eopchenm", "eopche"))
        for code, names in sorted(by_code.items()):
            print(f"  [확인용] 업종 {code} ({len(names)}곳): {', '.join(names[:4])}")
        g01 = [(_pick(r, "eopchenm", "eopche"), eopjong(r)) for r in research if gyumo(r) == "01"]
        print("  [확인용] 기업구분 01:", g01[:10])
        gm = [(_pick(r, "eopchenm", "eopche"), eopjong(r), gyumo(r)) for r in research
              if any(norm(_pick(r, "eopchenm", "eopche")).startswith(norm(a)) for a in GROUP_PREFIXES)]
        print(f"  [확인용] 대기업 그룹명으로 시작하는 전문연 업체 {len(gm)}곳:", gm[:40])
        print("  [확인용] 업종코드 분포(전문연):", Counter(eopjong(r) for r in research).most_common(8))
        print("  [확인용] 기업구분코드 분포(전문연):", Counter(gyumo(r) for r in research).most_common(8),
              "| 기준 대기업 코드:", anchor_codes, "→", big_code)

    def is_big(r: dict) -> bool:
        values = " ".join(r.values())
        if "대기업" in values and "연구" in values:
            return True
        code = eopjong(r)
        if not code.startswith("2"):
            return False
        return code == BIGCO_LAB_CODE or (big_code is not None and gyumo(r) == big_code)
    return is_big


def pick_bigco_labs(rows: list[dict], groups: list[dict]) -> list[dict]:
    """응답 필드명·코드표가 문서에 없어서 이름값과 코드 두 방식으로 대기업 연구소를 고른다."""
    if rows:
        print("  [확인용] 지정업체 응답 필드:", sorted(rows[0].keys()))
    is_big = _is_bigco_factory(rows)
    out = []
    for raw in rows:
        r = {k.lower(): (v or "").strip() for k, v in raw.items()}
        if not is_big(r):
            continue
        category = next((v for v in r.values() if re.fullmatch(r"\S*대기업\S*연구\S*", v)), "")
        name = _pick(r, "eopchenm", "eopche", "company", "bjeopche")
        if not name:  # 이름 키를 못 찾으면: 분류값이 아니면서 연구소/센터/(주)가 들어간 가장 긴 값
            cands = [v for v in r.values() if v != category and re.search(r"연구|센터|\(주\)|주식회사", v)]
            name = max(cands, key=len) if cands else ""
        if not name:
            continue
        g = group_of(name, groups)
        out.append({
            "name": html.unescape(name),
            "group": g["name"] if g else "",
            "location": _pick(r, "eopcheaddr", "juso", "addr", "sojaeji", "sido", prefer_nm=False),
            "year": re.sub(r"\D", "", _pick(r, "seonjeongyy", "seonjeong", "yeondo", "year", prefer_nm=False))[:4],
            "recruiting": bool(re.search(r"모집|^y$", _pick(r, "chaeyong", "cy", prefer_nm=False), re.I)),
            "homepage": _homepage(_pick(r, "hmpgaddr", "hmpg", "homepage", prefer_nm=False)),
            "category": category or _pick(r, "eopjong", "upjong"),
        })
    if out:
        print("  [확인용] 대기업 연구소 예시:", json.dumps(out[0], ensure_ascii=False))
    out = list({o["name"]: o for o in out}.values())
    out.sort(key=lambda o: (o["group"] == "", o["group"], o["name"]))
    return out


# 로그로 확인한 업종구분코드 (전문연구요원 = 2로 시작)
EOPJONG_LABELS = {
    "21101": "과학기술원", "21102": "과학기술원 부설연구소", "21103": "기초과학연구기관",
    "21201": "정부출연연구기관", "21301": "대학 선도연구센터", "21401": "기타 비영리 연구기관",
    "21501": "대기업부설연구소", "21502": "중소기업부설연구소", "21503": "벤처기업부설연구소",
    "21504": "중견기업부설연구소", "23101": "자연계 대학원", "23201": "대학부설연구소", "24101": "방위산업연구기관",
}
GYUMO_LABELS = {"01": "대기업", "02": "중소기업", "03": "벤처기업", "04": "중견기업"}
LABS_OUT = SITE / "data" / "labs.json"


def export_all_labs(rows: list[dict], groups: list[dict]) -> int:
    """전문연구요원 지정업체 전체(업종코드 2xxxx)를 labs.json으로 저장. 연락처·사업자번호는 넣지 않는다."""
    out = []
    for raw in rows:
        r = {k.lower(): (v or "").strip() for k, v in raw.items()}
        code = _pick(r, "eopjonggbcd", "eopjong", prefer_nm=False)
        if not code.startswith("2"):
            continue
        name = html.unescape(_pick(r, "eopchenm", "eopche"))
        addr = re.sub(r"\s+", " ", _pick(r, "eopcheaddr", "juso", "addr", prefer_nm=False))
        g = group_of(name, groups)
        out.append({
            "name": name,
            "type": EOPJONG_LABELS.get(code, code),
            "size": GYUMO_LABELS.get(_pick(r, "gegyumocd", "gyumo", prefer_nm=False), ""),
            "region": " ".join(addr.split()[:2]),
            "address": addr,
            "year": re.sub(r"\D", "", _pick(r, "seonjeongyy", "seonjeong", prefer_nm=False))[:4],
            "homepage": _homepage(_pick(r, "hmpgaddr", "hmpg", "homepage", prefer_nm=False)),
            "group": g["name"] if g else "",
        })
    # 확인용: 업종 무관(산업기능요원 포함) 항만·해운·물류 관련 지정업체
    port = re.compile(r"항만|해운|물류|로지스|로지텍|터미널|컨테이너|쉬핑|글로비스|판토스|소프트뱅크|싸이버|사이버로|부산신항|PNIT|BNCT|HPNT", re.I)
    pm = []
    for raw in rows:
        r = {k.lower(): (v or "").strip() for k, v in raw.items()}
        nm = _pick(r, "eopchenm", "eopche")
        if port.search(nm):
            pm.append(f"{nm}({_pick(r, 'eopjonggbcd', prefer_nm=False)}/{_pick(r, 'gegyumocd', prefer_nm=False)}/{' '.join(_pick(r, 'eopcheaddr', prefer_nm=False).split()[:2])})")
    print(f"  [확인용] 항만·해운·물류 관련 지정업체(전체 업종) {len(pm)}곳:", "; ".join(pm[:60]))
    out = sorted({o["name"]: o for o in out}.values(), key=lambda o: o["name"])
    write_json(LABS_OUT, {"generated_at": datetime.now(KST).isoformat(timespec="seconds"), "count": len(out), "labs": out})
    return len(out)


# ---------------------------------------------------------------- 2) 사람인 대기업 공고
def _g(d, *path, default=""):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d is None else d


def _date(v) -> str:
    if v in (None, "", 0, "0"):
        return ""
    s = str(v)
    if s.isdigit() and len(s) >= 9:  # unix timestamp
        return datetime.fromtimestamp(int(s), KST).strftime("%Y-%m-%d")
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def fetch_saramin(key: str, keywords: list[str]) -> list[dict]:
    jobs: dict[str, dict] = {}
    for kw in keywords:
        q = urllib.parse.urlencode({"access-key": key, "keywords": kw, "count": 110, "sort": "pd",
                                    "fields": "posting-date expiration-date"})
        text = http_get(f"{SARAMIN_API}?{q}", headers={"Accept": "application/json"})
        data = json.loads(text)
        if "jobs" not in data:
            raise RuntimeError(f"사람인 API 오류: {text[:300]}")
        lst = _g(data, "jobs", "job", default=[]) or []
        if isinstance(lst, dict):
            lst = [lst]
        print(f"  사람인 '{kw}': {len(lst)}건 (전체 {_g(data, 'jobs', 'total')})")
        for j in lst:
            jid = str(j.get("id") or "") or re.sub(r".*rec_idx=(\d+).*", r"\1", j.get("url", ""))
            if not jid or str(j.get("active", "1")) == "0":
                continue
            pos = j.get("position", {}) or {}
            rec = jobs.setdefault(jid, {
                "id": jid,
                "company": html.unescape(_g(j, "company", "detail", "name")),
                "title": html.unescape(_g(pos, "title")),
                "url": j.get("url", ""),
                "location": html.unescape(_g(pos, "location", "name")).replace(",", ", "),
                "job_type": _g(pos, "job-type", "name"),
                "experience": _g(pos, "experience-level", "name"),
                "education": _g(pos, "required-education-level", "name"),
                "salary": _g(j, "salary", "name"),
                "close_type": _g(j, "close-type", "name"),
                "deadline": _date(j.get("expiration-date") or j.get("expiration-timestamp")),
                "posted": _date(j.get("posting-date") or j.get("posting-timestamp")),
                "duty": html.unescape(_g(pos, "job-code", "name")),
                "queries": [],
            })
            if kw not in rec["queries"]:
                rec["queries"].append(kw)
        time.sleep(1)
    return list(jobs.values())


def match_bigco(jobs: list[dict], labs: list[dict], groups: list[dict]) -> list[dict]:
    lab_norms = [(norm(l["name"]), l) for l in labs]
    out = []
    for j in jobs:
        n = norm(j["company"])
        lab = next((l for ln, l in lab_norms if len(n) >= 2 and (ln.startswith(n) or n.startswith(ln))), None)
        g = group_of(j["company"], groups)
        # 지정 연구소 목록이 있으면 실제로 편입이 가능한(지정된) 회사 공고만. 목록이 없을 때만 그룹명으로 추정.
        if labs and not lab:
            continue
        if not lab and not g:
            continue
        j["unverified"] = not lab
        j["lab"] = lab["name"] if lab else ""
        j["group"] = (lab or {}).get("group") or (g["name"] if g else "")
        out.append(j)
    return out


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--companies-from", help="지정업체 API 응답 파일 (테스트용)")
    ap.add_argument("--saramin-from", nargs="*", help="사람인 API 응답 JSON 파일들 (테스트용)")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (테스트용)")
    args = ap.parse_args()

    now = datetime.now(KST)
    today = args.today or now.strftime("%Y-%m-%d")
    config = json.loads((SITE / "config.json").read_text(encoding="utf-8"))
    bc = config.get("bigco", {})
    groups = bc.get("groups", [])
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    result = {
        "generated_at": now.isoformat(timespec="seconds"),
        "companies_updated_at": prev.get("companies_updated_at", ""),
        "companies_status": prev.get("companies_status", ""),
        "companies": prev.get("companies", []),
        "jobs_status": "",
        "jobs": [],
        "groups": [{"name": g["name"], "url": g.get("url", "")} for g in groups],
    }

    # 그룹 매핑은 config가 바뀌면 바로 반영되도록 저장된 목록에도 매번 다시 적용
    for c in result["companies"]:
        g = group_of(c["name"], groups)
        c["group"] = g["name"] if g else ""

    # 1) 지정 대기업 연구소 (6일에 한 번)
    stale = True
    if result["companies_updated_at"] and result["companies"]:
        age = now - datetime.fromisoformat(result["companies_updated_at"])
        stale = age > timedelta(days=COMPANY_REFRESH_DAYS)
    if args.companies_from or os.environ.get("BIGCO_FORCE"):
        stale = True
    if stale:
        try:
            if args.companies_from:
                rows = parse_page(Path(args.companies_from).read_text(encoding="utf-8"))[0]
            else:
                key = os.environ.get("DATA_GO_KR_KEY", "")
                if not key:
                    raise RuntimeError("DATA_GO_KR_KEY가 없습니다.")
                print("지정업체 목록 수집 중...")
                rows = fetch_companies(key)
            print(f"전문연 지정업체 전체 {export_all_labs(rows, groups)}곳 → site/data/labs.json")
            labs = pick_bigco_labs(rows, groups)
            result["companies"] = labs
            result["companies_updated_at"] = now.isoformat(timespec="seconds")
            result["companies_status"] = "ok" if labs else "지정업체 응답에서 대기업 연구소를 찾지 못했어요. Actions 로그의 응답 필드를 확인해 주세요."
            print(f"대기업 연구소 {len(labs)}곳")
        except Exception as e:
            msg = str(e)
            if "주소를 찾지 못했" in msg:
                msg = ("병무청 지정업체 API가 지금 '서비스 없음' 응답을 주고 있어서 대기업 연구소 목록을 아직 받지 못했어요. "
                       "공공데이터포털에서 이 API 활용신청을 마친 뒤에도 같으면 API 주소가 바뀐 것이라 확인이 필요해요.")
            elif any(s in msg for s in ("SERVICE_KEY", "PERMISSION", "인증키", "SERVICE ERROR", "HTTP 401", "HTTP 403")):
                msg = ("공공데이터포털에서 '병무청_전문연구/산업기능요원 지정업체 정보' API 활용신청이 필요해요. "
                       "(기존 인증키 그대로 쓰고 활용신청만 추가) — " + msg)
            print("지정업체 수집 실패:", msg)
            result["companies_status"] = msg

    # 2) 사람인 대기업 공고 (매 실행)
    try:
        if args.saramin_from is not None:
            raw = []
            for f in args.saramin_from:
                raw += fetch_saramin_from_file(f)
        else:
            key = os.environ.get("SARAMIN_KEY", "")
            if not key:
                raise LookupError("사람인 API 키(SARAMIN_KEY)가 등록되지 않아 대기업 공고 검색을 건너뛰었어요.")
            print("사람인 대기업 공고 검색 중...")
            raw = fetch_saramin(key, bc.get("search_keywords", []))
        merged: dict[str, dict] = {}
        for j in raw:  # 여러 키워드에서 같은 공고가 나오면 하나로 합친다
            if j["id"] in merged:
                merged[j["id"]]["queries"] += [q for q in j["queries"] if q not in merged[j["id"]]["queries"]]
            else:
                merged[j["id"]] = j
        raw = list(merged.values())
        jobs = match_bigco(raw, result["companies"], groups)
        jobs = [j for j in jobs if not j["deadline"] or j["deadline"] >= today]
        jobs.sort(key=lambda j: (j["posted"], j["id"]), reverse=True)
        result["jobs"] = jobs
        result["jobs_status"] = "ok"
        print(f"사람인 검색 {len(raw)}건 중 대기업 공고 {len(jobs)}건")
    except LookupError as e:
        result["jobs_status"] = str(e)
        print(e)
    except Exception as e:
        result["jobs_status"] = f"사람인 공고 수집 실패: {e}"
        result["jobs"] = prev.get("jobs", [])  # 일시적 오류면 이전 결과 유지
        print(result["jobs_status"])

    write_json(OUT, result)
    print(f"저장: {OUT.relative_to(SITE.parent)}")
    return 0


def fetch_saramin_from_file(path: str) -> list[dict]:
    """테스트용: 저장된 사람인 응답을 fetch_saramin과 같은 형태로 바꾼다."""
    orig = http_get
    text = Path(path).read_text(encoding="utf-8")
    globals()["http_get"] = lambda *a, **k: text
    try:
        return fetch_saramin("TEST", [Path(path).stem])
    finally:
        globals()["http_get"] = orig


if __name__ == "__main__":
    sys.exit(main())
