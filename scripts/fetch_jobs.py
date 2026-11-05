#!/usr/bin/env python3
"""병무청 병역일터 채용공고 API에서 전문연구요원 공고만 모아 정적 사이트용 JSON/RSS를 만든다.

API: 공공데이터포털 '병무청 병역일터 채용공고' (https://www.data.go.kr/data/3065599/openapi.do)
     요청 주소 https://apis.data.go.kr/1300000/CyJeongBo/list

사용법
  DATA_GO_KR_KEY=발급받은키 python scripts/fetch_jobs.py
  python scripts/fetch_jobs.py --from-xml samples/*.xml      # 오프라인 테스트

표준 라이브러리만 사용하므로 별도 설치가 필요 없다.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

API_URL = "https://apis.data.go.kr/1300000/CyJeongBo/list"
DETAIL_URL = "https://work.mma.go.kr/caisBYIS/search/cygonggogeomsaekView.do?cygonggo_no={id}"
PAGE_SIZE = 1000
MAX_PAGES = 50
KST = timezone(timedelta(hours=9))

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
STATE = ROOT / "state"


# ---------------------------------------------------------------- 수집
def _request(params: dict, retries: int = 3) -> str:
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "jeonmun-jobs/1.0"})
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return res.read().decode("utf-8", errors="replace")
        except Exception as e:  # 네트워크 오류는 잠시 후 재시도
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"API 요청 실패: {last_err}")


def parse_page(text: str) -> tuple[list[dict], int | None]:
    """API 응답(XML 또는 JSON) 한 페이지를 (항목 목록, 전체 건수)로 바꾼다."""
    text = text.lstrip("﻿ \r\n\t")
    if not text:
        raise RuntimeError("API 응답이 비어 있습니다.")
    if text.startswith("<"):
        root = ET.fromstring(text)
        # 공공데이터포털 게이트웨이 오류 형식 (인증키 오류 등)
        if root.tag == "OpenAPI_ServiceResponse":
            msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "알 수 없는 오류"
            code = root.findtext(".//returnReasonCode") or "?"
            raise RuntimeError(f"공공데이터포털 오류 {code}: {msg} (인증키·활용신청 승인 여부를 확인하세요)")
        code = root.findtext(".//header/resultCode") or root.findtext(".//resultCode")
        if code not in (None, "00", "0", "0000"):
            raise RuntimeError(f"API 오류 resultCode={code}: {root.findtext('.//resultMsg')}")
        items = [{child.tag: (child.text or "").strip() for child in item} for item in root.iter("item")]
        total = root.findtext(".//totalCount")
        return items, int(total) if total and total.isdigit() else None
    data = json.loads(text)
    resp = data.get("response", data)
    code = resp.get("header", {}).get("resultCode")
    if code not in (None, "00", "0", "0000"):
        raise RuntimeError(f"API 오류 resultCode={code}: {resp.get('header', {}).get('resultMsg')}")
    body = resp.get("body", {})
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    total = body.get("totalCount")
    return [{k: str(v or "").strip() for k, v in it.items()} for it in items], int(total) if total else None


def fetch_all(key: str) -> list[dict]:
    key = urllib.parse.unquote(key.strip())  # 'Encoding' 키를 넣어도 이중 인코딩되지 않게
    out: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        items, total = parse_page(_request({"serviceKey": key, "numOfRows": PAGE_SIZE, "pageNo": page}))
        out.extend(items)
        print(f"  page {page}: {len(items)}건 (누적 {len(out)} / 전체 {total})")
        if not items or len(items) < PAGE_SIZE or (total is not None and len(out) >= total):
            break
        time.sleep(1)
    return out


# ---------------------------------------------------------------- 정리
def _ymd(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")[:8]
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) == 8 else ""


def _salary_min(text: str) -> int | None:
    """'4000~5000만원' → 4000, '~2000만원이하' → 0, '회사내규에 따름' → None"""
    if not text:
        return None
    if text.startswith("~"):
        return 0
    m = re.search(r"(\d{3,5})", text.replace(",", ""))
    return int(m.group(1)) if m else None


def _homepage(url: str) -> str:
    url = (url or "").strip()
    if not url or url in ("-", "없음"):
        return ""
    return url if re.match(r"^https?://", url, re.I) else "https://" + url


def normalize(raw: dict) -> dict:
    r = {k.lower(): v for k, v in raw.items()}  # 응답 필드 대소문자 차이(Bokrihs 등) 흡수
    g = lambda k: (r.get(k.lower()) or "").strip()
    jid = g("cygonggoNo")
    location = g("geunmujy")
    welfare = [w.strip() for w in re.split(r"[,，]", g("bokrihs")) if w.strip()]
    return {
        "id": jid,
        "title": html.unescape(g("cyjemokNm")),
        "company": html.unescape(g("eopcheNm")),
        "industry": g("eopjongGbcdNm"),
        "location": location,
        "sido": g("geunmujysido") or (location.split()[0] if location else ""),
        "service": g("yeokjongBrcdNm"),          # 현역 / 보충역 / 기타
        "education": g("cjhakryeok"),
        "major": g("jggyeyeolCdNm"),
        "career": g("gyeongryeokGbcdNm"),
        "salary": g("gyjogeonCdNm"),
        "salary_min": _salary_min(g("gyjogeonCdNm")),
        "duty": html.unescape(g("ddeopmuNm")),
        "welfare": welfare,
        "apply_method": g("jeopsubb"),
        "headcount": g("mjinwonNm"),
        "deadline": _ymd(g("magamDt")),
        "always_open": g("sschaeyongYn").upper() == "Y",
        "posted": _ymd(g("ccdatabalsaengDtm")),
        "updated": _ymd(g("cjdatabyeongyeongDtm")),
        "homepage": _homepage(g("hmpgAddr")),
        "url": DETAIL_URL.format(id=jid),
        "_valid": g("yuhyoYn").upper() != "N",
        "_type_code": g("yowonGbcd"),
        "_type_name": g("yowonGbcdNm"),
    }


def is_research_personnel(job: dict) -> bool:
    return job["_type_code"] == "2" or "전문연구" in job["_type_name"]


def is_open(job: dict, today: str) -> bool:
    if not job["_valid"]:
        return False
    return job["always_open"] or not job["deadline"] or job["deadline"] >= today


# ---------------------------------------------------------------- 관심 키워드
def keyword_matcher(keywords: list[str]):
    pats = []
    for kw in keywords:
        if re.fullmatch(r"[A-Za-z]{1,2}", kw):   # OR, AI 같은 두 글자 영문은 대소문자·단어경계를 지켜서
            pats.append(re.compile(rf"(?<![A-Za-z]){re.escape(kw)}(?![A-Za-z])"))
        elif re.fullmatch(r"[A-Za-z0-9 ]+", kw):
            pats.append(re.compile(rf"(?<![A-Za-z]){re.escape(kw)}(?![A-Za-z])", re.I))
        else:
            pats.append(re.compile(re.escape(kw), re.I))

    def match(job: dict) -> list[str]:
        text = " ".join([job["title"], job["duty"], job["company"]])
        return [kw for kw, p in zip(keywords, pats) if p.search(text)]
    return match


# ---------------------------------------------------------------- 출력
def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def write_rss(path: Path, jobs: list[dict], title: str, site_url: str) -> None:
    items = []
    for j in sorted(jobs, key=lambda j: (j["first_seen"], j["id"]), reverse=True)[:50]:
        pub = datetime.strptime(j["first_seen"], "%Y-%m-%d").replace(hour=9, tzinfo=KST)
        desc = " · ".join(x for x in [j["service"], j["salary"], j["location"], j["education"],
                                       "상시채용" if j["always_open"] else (f"마감 {j['deadline']}" if j["deadline"] else "")] if x)
        item_title = "[{}] {}".format(j["company"], j["title"])
        items.append(
            "<item>"
            f"<title>{html.escape(item_title)}</title>"
            f"<link>{html.escape(j['url'])}</link>"
            f"<guid isPermaLink=\"false\">mma-{html.escape(j['id'])}</guid>"
            f"<pubDate>{format_datetime(pub)}</pubDate>"
            f"<description>{html.escape(desc)}</description>"
            "</item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>{html.escape(title)}</title><link>{html.escape(site_url or 'https://work.mma.go.kr')}</link>"
        "<description>병무청 병역일터 전문연구요원 신규 채용공고</description><language>ko</language>"
        + "".join(items) + "</channel></rss>\n"
    )
    path.write_text(rss, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-xml", nargs="*", help="API 대신 저장된 응답 파일(XML/JSON)을 읽는다 (테스트용)")
    ap.add_argument("--notify-file", help="관심 키워드에 맞는 신규 공고가 있으면 이 경로에 마크다운 요약을 쓴다")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (테스트용, 기본: 오늘 KST)")
    args = ap.parse_args()

    now = datetime.now(KST)
    today = args.today or now.strftime("%Y-%m-%d")
    config = json.loads((SITE / "config.json").read_text(encoding="utf-8"))

    # 1) 수집
    if args.from_xml is not None:
        files = sorted({f for pat in args.from_xml for f in glob.glob(pat)})
        raw = [it for f in files for it in parse_page(Path(f).read_text(encoding="utf-8"))[0]]
        print(f"파일 {len(files)}개에서 {len(raw)}건 읽음")
    else:
        key = os.environ.get("DATA_GO_KR_KEY", "")
        if not key:
            print("환경변수 DATA_GO_KR_KEY(공공데이터포털 인증키)가 없습니다.", file=sys.stderr)
            return 2
        print("병역일터 API 수집 중...")
        raw = fetch_all(key)
    if not raw:
        print("받은 공고가 0건입니다. 기존 데이터를 지우지 않도록 중단합니다.", file=sys.stderr)
        return 1

    # 2) 전문연구요원 + 진행 중인 공고만
    jobs = [normalize(r) for r in raw]
    jobs = [j for j in jobs if j["id"] and is_research_personnel(j) and is_open(j, today)]
    jobs = list({j["id"]: j for j in jobs}.values())  # 중복 제거

    # 3) 처음 본 날짜 기록 → 신규 공고 표시용
    seen_path = STATE / "seen.json"
    seen: dict = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
    bootstrap = not seen
    newly_seen = []
    for j in jobs:
        if j["id"] not in seen:
            first = (j["posted"] or today) if bootstrap else today
            seen[j["id"]] = {"first": first, "last": today}
            if not bootstrap:
                newly_seen.append(j)
        else:
            seen[j["id"]]["last"] = today
        j["first_seen"] = seen[j["id"]]["first"]
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in seen.items() if v["last"] >= cutoff}  # 오래전에 사라진 공고 기록은 정리

    match = keyword_matcher(config.get("interest_keywords", []))
    for j in jobs:
        j["keywords"] = match(j)
        for k in [k for k in j if k.startswith("_")]:
            del j[k]
    jobs.sort(key=lambda j: (j["first_seen"], j["posted"], j["id"]), reverse=True)

    # 4) 저장
    site_url = os.environ.get("SITE_URL", "")
    write_json(SITE / "data" / "jobs.json", {
        "generated_at": now.isoformat(timespec="seconds"),
        "source": "병무청 병역일터 채용공고 (공공데이터포털 오픈API)",
        "count": len(jobs),
        "jobs": jobs,
    })
    write_json(seen_path, dict(sorted(seen.items())))
    write_rss(SITE / "feed.xml", jobs, config.get("site_title", "전문연구요원 채용공고"), site_url)
    print(f"전문연구요원 진행 중 공고 {len(jobs)}건 저장 (이번에 새로 발견 {len(newly_seen)}건)")

    # 5) 관심 키워드에 맞는 신규 공고 요약 (GitHub 이슈 알림용)
    if args.notify_file and config.get("notify_new_matches", True):
        hits = [j for j in newly_seen if j["keywords"]]
        if hits:
            lines = [f"새로 올라온 관심 공고 {len(hits)}건 ({today})", ""]
            if site_url:
                lines += [f"전체 목록: {site_url}", ""]
            for j in hits:
                due = "상시채용" if j["always_open"] else (f"마감 {j['deadline']}" if j["deadline"] else "")
                meta = " · ".join(x for x in [j["service"], j["salary"], j["sido"], due] if x)
                lines.append(f"- **[{j['company']}] {j['title']}** — {meta}  ")
                lines.append(f"  키워드: {', '.join(j['keywords'])} · [병역일터에서 보기]({j['url']})")
            Path(args.notify_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"알림 대상 {len(hits)}건 → {args.notify_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
