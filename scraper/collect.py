"""애드로그 플레이스 순위 체크 → 대시보드 데이터 수집

매일 GitHub Actions에서 실행됩니다.
1. 애드로그 로그인 (ADLOG_ID / ADLOG_PW 는 GitHub Secrets 에서 주입)
2. 플레이스 순위 체크 목록에서 config/keywords.json 에 있는 키워드의 최근 기록을 읽음
3. 처음 추적하는 키워드나 기록이 끊긴 키워드는 이전 기록(최대 약 100일)을 추가로 읽음
4. data/history.json 에 누적 저장하고 site/data.js 를 다시 만듦
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://adlog.kr"
LIST_URL = BASE + "/adlog/naver_place_rank_check.php"
AJAX_URL = BASE + "/adlog/ajax_stat_list.php"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(ROOT, "config", "keywords.json")
HIST_PATH = os.path.join(ROOT, "data", "history.json")
OUT_PATH = os.path.join(ROOT, "site", "data.js")
KST = ZoneInfo("Asia/Seoul")
START = "2026-06-30"      # 대시보드 시작일
MAX_DAYS = 400            # data.js 에 담는 최대 일수
BACKFILL_DAYS = 100       # 새 키워드의 이전 기록을 읽어오는 범위
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def log(*a):
    print(*a, flush=True)


def num(text):
    if not text:
        return None
    m = re.search(r"-?\d+", text.replace(",", ""))
    return int(m.group()) if m else None


def infer_date(mmdd, today):
    """'10-07' 형태를 실제 날짜로. 오늘 이후가 되면 작년으로 본다."""
    m, d = map(int, mmdd.split("-"))
    y = today.year
    cand = date(y, m, d)
    if cand > today + timedelta(days=1):
        cand = date(y - 1, m, d)
    return cand.isoformat()


def parse_stats(html, today):
    out = {}
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.select(".stat_div"):
        key = el.get("stat_date")
        if not key:
            span = el.find("span")
            m = re.search(r"(\d{2})-(\d{2})", span.get_text() if span else "")
            if not m:
                continue
            key = infer_date(m.group(0), today)
        b = el.find("b")
        rm = re.search(r"(\d+)\s*위", b.get_text()) if b else None
        sel = lambda c: el.select_one(c).get_text() if el.select_one(c) else None
        vals = [
            int(rm.group(1)) if rm else None,
            num(sel(".blog_disp_area")),
            num(sel(".visit_disp_area")),
            num(sel(".search_disp_area")),
        ]
        # 애드로그는 당일 칸을 빈 값으로 먼저 만들어 둔다(13:40 이후 갱신). 빈 칸은 기록하지 않는다.
        if all(v is None for v in vals):
            continue
        out[key] = vals
    return out


def login(s):
    s.get(BASE + "/bbs/login.php", timeout=30)
    s.post(BASE + "/bbs/login_check.php", data={
        "url": BASE,
        "mb_id": os.environ["ADLOG_ID"],
        "mb_password": os.environ["ADLOG_PW"],
    }, timeout=30)


def fetch_list(s):
    items = []
    for page in range(1, 8):
        r = s.get(LIST_URL, params={"page": page, "page_rows": 100}, timeout=90)
        soup = BeautifulSoup(r.text, "html.parser")
        tag = soup.find(id="legacyJsonData")
        if not tag:
            break
        arr = json.loads(tag.string or tag.get_text())
        if isinstance(arr, dict):
            arr = arr.get("items") or arr.get("list") or list(arr.values())
        if not arr:
            break
        items.extend(arr)
        if len(arr) < 100:
            break
        time.sleep(1)
    return items


def fetch_history(s, item, cutoff, today):
    btn = BeautifulSoup(item.get("lg_more") or "", "html.parser").find("button")
    if not btn:
        return {}
    p, pageday, startday = btn.get("p"), btn.get("pageday"), btn.get("startday")
    out = {}
    for _ in range(8):
        if not pageday or pageday < cutoff:
            break
        r = s.post(AJAX_URL, data={
            "api_section": "10", "api_type": "64", "api_no": str(item["no"]),
            "p": p, "display": "30", "startday": startday, "pageday": pageday,
        }, headers={"X-Requested-With": "XMLHttpRequest", "Referer": LIST_URL}, timeout=60)
        try:
            j = json.loads(r.text.strip())
        except ValueError:
            break
        if j.get("code") != "0000" or not j.get("items"):
            break
        for k, v in parse_stats(j["items"], today).items():
            out.setdefault(k, v)
        p, pageday = j.get("p"), j.get("pageday")
        time.sleep(0.7)
    return out


def encode(days_map, dates):
    def delta(idx):
        prev, cells = None, []
        for d in dates:
            v = days_map.get(d, [None] * 4)[idx]
            if v is None:
                cells.append("x")
            elif prev is None:
                cells.append(str(v)); prev = v
            else:
                diff = v - prev; prev = v
                cells.append(str(diff) if diff else "")
        return ",".join(cells)
    ranks = ",".join("x" if days_map.get(d, [None])[0] is None else str(days_map[d][0]) for d in dates)
    return ranks, delta(1), delta(2), delta(3)


def build_js(cfg, hist):
    all_days = sorted({d for h in hist.values() for d in h["days"]})
    if not all_days:
        raise SystemExit("저장된 기록이 없습니다.")
    last = date.fromisoformat(all_days[-1])
    first = max(date.fromisoformat(START), last - timedelta(days=MAX_DAYS - 1))
    dates = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    lines = []
    for c in cfg:
        h = hist.get(str(c["api_no"]))
        if not h:
            continue
        r, b, v, s = encode(h["days"], dates)
        lines.append("|".join([str(c["api_no"]), c["group"], c["label"], dates[0], "0", r, b, v, s]))
    head = (f"// 애드로그 플레이스 순위 체크 ({dates[0]} ~ {dates[-1]}, 일별 · 자동 수집 "
            f"{datetime.now(KST):%Y-%m-%d %H:%M} KST)\n"
            "// 형식: api_no|그룹|키워드|시작일|누락일|순위들|블로그리뷰(델타)|영수증리뷰(델타)|월검색량(델타)\n")
    return head + "window.RANK_RAW = `" + "\n".join(lines) + "`;\n"


def main():
    for k in ("ADLOG_ID", "ADLOG_PW"):
        if not os.environ.get(k):
            raise SystemExit(f"{k} 가 설정되지 않았습니다. GitHub Secrets 를 확인해주세요.")
    today = datetime.now(KST).date()
    cfg = json.load(open(CFG_PATH, encoding="utf-8"))
    hist = json.load(open(HIST_PATH, encoding="utf-8")) if os.path.exists(HIST_PATH) else {}

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    login(s)
    items = {str(x.get("no")): x for x in fetch_list(s)}
    if not items:
        raise SystemExit("애드로그 목록을 읽지 못했습니다. 로그인 정보나 사이트 구조 변경을 확인해주세요.")
    log(f"애드로그 키워드 {len(items)}개 확인")

    cutoff = max(START, (today - timedelta(days=BACKFILL_DAYS)).isoformat())
    updated, missing = 0, []
    for c in cfg:
        key = str(c["api_no"])
        item = items.get(key)
        if not item:
            missing.append(f'{c["group"]} {c["label"]}')
            continue
        h = hist.setdefault(key, {"group": c["group"], "label": c["label"], "days": {}})
        h["group"], h["label"] = c["group"], c["label"]
        recent = parse_stats(item.get("lg_stat") or "", today)
        stored_last = max(h["days"]) if h["days"] else None
        recent_first = min(recent) if recent else None
        need_backfill = (not h["days"]) or (stored_last and recent_first and stored_last < recent_first)
        if need_backfill:
            older = fetch_history(s, item, cutoff, today)
            for k, v in older.items():
                h["days"].setdefault(k, v)
            log(f'  이전 기록 {len(older)}일 보강: {c["label"]}')
        h["days"].update(recent)
        h["days"] = {k: h["days"][k] for k in sorted(h["days"])
                     if k >= START and any(v is not None for v in h["days"][k])}
        updated += 1

    if missing:
        log("애드로그에서 찾지 못한 키워드:", ", ".join(missing))
    if updated == 0:
        raise SystemExit("갱신된 키워드가 없습니다.")

    os.makedirs(os.path.dirname(HIST_PATH), exist_ok=True)
    with open(HIST_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(build_js(cfg, hist))
    last = max(d for h in hist.values() for d in h["days"])
    log(f"완료 · 키워드 {updated}개 · 최신 기록일 {last}")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        log("애드로그 접속 오류:", e)
        sys.exit(1)
