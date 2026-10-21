#!/usr/bin/env python3
"""
수도권(서울·경기) 아파트 매매 실거래 → data/apartments.json

1) 국토교통부 아파트 매매 실거래가 API로 최근 N개월 거래 수집
2) 단지 × 전용면적별로 최근 거래가(최근 3건 중앙값) 집계, 해제 거래 제외
3) 카카오 주소 검색으로 좌표 변환 (data/geocache.json 에 캐시, 다음 달부터는 신규 단지만 호출)

환경변수
  DATA_GO_KR_KEY  공공데이터포털 일반 인증키 (Decoding 키)
  KAKAO_REST_KEY  카카오 개발자 REST API 키
  MONTHS          수집 개월 수 (기본 6)
"""
import datetime as dt
import json
import os
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "apartments.json"
CACHE = ROOT / "data" / "geocache.json"

# 상세 자료(TradeDev)와 일반 자료(Trade) 중 키가 승인된 쪽을 자동으로 고른다
API_CANDIDATES = [
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
]
API = API_CANDIDATES[0]
KAKAO_ADDR = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KW = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 시군구 코드 → 표시 이름. 분구·개편으로 코드가 바뀐 곳은 옛 코드도 함께 조회한다.
REGIONS = {
    # 서울
    "11110": "서울 종로구", "11140": "서울 중구", "11170": "서울 용산구", "11200": "서울 성동구",
    "11215": "서울 광진구", "11230": "서울 동대문구", "11260": "서울 중랑구", "11290": "서울 성북구",
    "11305": "서울 강북구", "11320": "서울 도봉구", "11350": "서울 노원구", "11380": "서울 은평구",
    "11410": "서울 서대문구", "11440": "서울 마포구", "11470": "서울 양천구", "11500": "서울 강서구",
    "11530": "서울 구로구", "11545": "서울 금천구", "11560": "서울 영등포구", "11590": "서울 동작구",
    "11620": "서울 관악구", "11650": "서울 서초구", "11680": "서울 강남구", "11710": "서울 송파구",
    "11740": "서울 강동구",
    # 경기
    "41111": "경기 수원시 장안구", "41113": "경기 수원시 권선구", "41115": "경기 수원시 팔달구",
    "41117": "경기 수원시 영통구", "41131": "경기 성남시 수정구", "41133": "경기 성남시 중원구",
    "41135": "경기 성남시 분당구", "41150": "경기 의정부시", "41171": "경기 안양시 만안구",
    "41173": "경기 안양시 동안구", "41190": "경기 부천시", "41192": "경기 부천시 원미구",
    "41194": "경기 부천시 소사구", "41196": "경기 부천시 오정구", "41210": "경기 광명시",
    "41220": "경기 평택시", "41250": "경기 동두천시", "41271": "경기 안산시 상록구",
    "41273": "경기 안산시 단원구", "41281": "경기 고양시 덕양구", "41285": "경기 고양시 일산동구",
    "41287": "경기 고양시 일산서구", "41290": "경기 과천시", "41310": "경기 구리시",
    "41360": "경기 남양주시", "41370": "경기 오산시", "41390": "경기 시흥시", "41410": "경기 군포시",
    "41430": "경기 의왕시", "41450": "경기 하남시", "41461": "경기 용인시 처인구",
    "41463": "경기 용인시 기흥구", "41465": "경기 용인시 수지구", "41480": "경기 파주시",
    "41500": "경기 이천시", "41550": "경기 안성시", "41570": "경기 김포시", "41590": "경기 화성시",
    "41591": "경기 화성시 만세구", "41593": "경기 화성시 효행구", "41595": "경기 화성시 병점구",
    "41597": "경기 화성시 동탄구", "41610": "경기 광주시", "41630": "경기 양주시",
    "41650": "경기 포천시", "41670": "경기 여주시", "41800": "경기 연천군", "41820": "경기 가평군",
    "41830": "경기 양평군",
}
# 코드가 확실치 않은 분구 지역은 카카오에서 현재 코드를 한 번 더 확인한다
VERIFY = ["경기도 부천시 원미구", "경기도 부천시 소사구", "경기도 부천시 오정구",
          "경기도 화성시 만세구", "경기도 화성시 효행구", "경기도 화성시 병점구", "경기도 화성시 동탄구"]

SIDO_FULL = {"서울": "서울특별시", "경기": "경기도"}
SIDO_SHORT = {"서울특별시": "서울", "경기도": "경기", "서울": "서울", "경기": "경기"}


def log(*a):
    print(*a, flush=True)


def get(url, *, params=None, headers=None, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except (requests.RequestException,) as e:
            if i == tries - 1:
                raise
            wait = 2 ** i
            log(f"  재시도 {i + 1}/{tries - 1} ({e}) {wait}s 후")
            time.sleep(wait)


def months_back(n, today=None):
    today = today or dt.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


# ---------- 1. 수집 ----------

def parse_items(xml_text):
    """API XML 응답 → (거래 dict 목록, totalCount)"""
    root = ET.fromstring(xml_text)
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in ("000", "00"):
        msg = (root.findtext(".//resultMsg") or "").strip()
        raise RuntimeError(f"API 오류 {code}: {msg}")
    total = int((root.findtext(".//totalCount") or "0").strip() or 0)
    rows = []
    for it in root.iter("item"):
        rows.append({c.tag: (c.text or "").strip() for c in it})
    return rows, total


def pick_api(key, ym):
    """강동구 1건으로 각 주소를 시험해 보고, 인증키가 통하는 주소를 쓴다"""
    global API
    errors = []
    for url in API_CANDIDATES:
        text = ""
        try:
            r = requests.get(url, params={"serviceKey": key, "LAWD_CD": "11740", "DEAL_YMD": ym,
                                          "pageNo": 1, "numOfRows": 1}, timeout=30)
            text = r.text
            parse_items(text)
            API = url
            log(f"사용할 API: {url.split('/')[-1]}")
            return
        except Exception as e:
            errors.append(f"{url.split('/')[-1]}: {str(e)[:120]} / 응답 앞부분: {text[:150]}")
    sys.exit("인증키가 어느 API에서도 통하지 않습니다. 활용신청 승인 여부와 Decoding 키인지 확인하세요.\n" + "\n".join(errors))


def fetch_month(key, lawd, ym):
    rows, page = [], 1
    while True:
        r = get(API, params={"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym,
                             "pageNo": page, "numOfRows": 1000})
        items, total = parse_items(r.text)
        rows += items
        if len(rows) >= total or not items:
            return rows
        page += 1
        time.sleep(0.1)


# ---------- 2. 집계 ----------

def to_int(s):
    try:
        return int(str(s).replace(",", "").strip())
    except ValueError:
        return None


def aggregate(deals):
    """거래 목록 → {단지키: {meta..., areas: {면적버킷: [거래...]}}}"""
    cx = {}
    for d in deals:
        if d.get("cdealType", "").strip():  # 해제된 거래 제외
            continue
        price = to_int(d.get("dealAmount"))
        try:
            area = float(d.get("excluUseAr") or 0)
        except ValueError:
            continue
        if not price or area <= 0:
            continue
        sgg = d.get("sggCd", "")
        key = d.get("aptSeq") or f"{sgg}-{d.get('umdNm')}-{d.get('jibun')}-{d.get('aptNm')}"
        date = f"{d.get('dealYear')}-{int(d.get('dealMonth') or 0):02d}-{int(d.get('dealDay') or 0):02d}"
        c = cx.setdefault(key, {"name": d.get("aptNm", ""), "sgg": sgg, "umd": d.get("umdNm", ""),
                                "jibun": d.get("jibun", ""), "built": to_int(d.get("buildYear")) or 0,
                                "areas": defaultdict(list)})
        c["areas"][round(area)].append((date, price, area))
    return cx


def summarize_area(trades):
    trades.sort(key=lambda t: t[0], reverse=True)
    recent = [t[1] for t in trades[:3]]
    price = int(round(statistics.median(recent) / 10) * 10)  # 만원, 10만 단위
    area = round(statistics.median(t[2] for t in trades), 2)
    return [area, price, len(trades), trades[0][0]]


# ---------- 3. 좌표 ----------

class Geocoder:
    def __init__(self, key):
        self.h = {"Authorization": f"KakaoAK {key}"}
        self.cache = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
        self.calls = 0

    def _addr(self, q):
        self.calls += 1
        r = get(KAKAO_ADDR, params={"query": q, "size": 1}, headers=self.h)
        docs = r.json().get("documents", [])
        return docs[0] if docs else None

    def region_code(self, q):
        d = self._addr(q)
        a = d and d.get("address")
        return a["b_code"][:5] if a and a.get("b_code") else None

    def locate(self, key, c):
        if key in self.cache:
            return self.cache[key]
        sido = SIDO_FULL.get(REGIONS.get(c["sgg"], "경기").split()[0], "경기도")
        sgg_name = " ".join(REGIONS.get(c["sgg"], "").split()[1:])
        hit = None
        if c["jibun"]:
            d = self._addr(f"{sido} {sgg_name} {c['umd']} {c['jibun']}")
            if d and d.get("address"):
                a = d["address"]
                name = f"{SIDO_SHORT.get(a['region_1depth_name'], a['region_1depth_name'])} {a['region_2depth_name']}"
                hit = [round(float(d["y"]), 6), round(float(d["x"]), 6), a["b_code"][:5], name]
        if not hit:  # 지번이 없거나 못 찾으면 단지명으로 키워드 검색
            self.calls += 1
            r = get(KAKAO_KW, params={"query": f"{sgg_name} {c['umd']} {c['name']}", "size": 1}, headers=self.h)
            docs = r.json().get("documents", [])
            if docs:
                hit = [round(float(docs[0]["y"]), 6), round(float(docs[0]["x"]), 6), None, None]
        self.cache[key] = hit
        time.sleep(0.03)
        return hit

    def save(self):
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, separators=(",", ":")), "utf-8")


# ---------- main ----------

def main():
    key, kakao = os.environ.get("DATA_GO_KR_KEY"), os.environ.get("KAKAO_REST_KEY")
    if not key or not kakao:
        sys.exit("DATA_GO_KR_KEY, KAKAO_REST_KEY 환경변수가 필요합니다.")
    n = int(os.environ.get("MONTHS", "6"))
    months = months_back(n)
    geo = Geocoder(kakao)
    pick_api(key, months[1])

    codes = dict(REGIONS)
    for q in VERIFY:  # 분구 지역의 현재 코드 확인
        try:
            c = geo.region_code(q)
            if c and c not in codes:
                short = q.replace("경기도", "경기")
                log(f"새 코드 발견: {q} → {c}")
                codes[c] = short
        except Exception as e:
            log(f"코드 확인 실패 {q}: {e}")
    REGIONS.update(codes)

    deals, per_code = [], {}
    for code, name in codes.items():
        cnt = 0
        for ym in months:
            rows = fetch_month(key, code, ym)
            deals += rows
            cnt += len(rows)
            time.sleep(0.1)
        per_code[code] = cnt
        log(f"{name} ({code}): {cnt}건")
    empty = [f"{codes[c]}({c})" for c, v in per_code.items() if v == 0]
    if empty:
        log("거래 0건 코드(옛 코드면 정상):", ", ".join(empty))

    cx = aggregate(deals)
    log(f"단지 {len(cx)}곳 좌표 확인 중…")
    regions, out, miss = {}, [], 0
    for i, (k, c) in enumerate(cx.items()):
        hit = geo.locate(k, c)
        if i % 500 == 0:
            geo.save()
        if not hit:
            miss += 1
            continue
        lat, lng, rcode, rname = hit
        rcode = rcode or c["sgg"]
        regions[rcode] = rname or REGIONS.get(rcode) or REGIONS.get(c["sgg"], rcode)
        areas = sorted((summarize_area(t) for t in c["areas"].values()), key=lambda a: a[0])
        out.append([c["name"], rcode, c["umd"], lat, lng, c["built"], areas])
    geo.save()

    data = {
        "updated": dt.date.today().isoformat(),
        "period": f"{months[-1][:4]}.{months[-1][4:]}~{months[0][:4]}.{months[0][4:]}",
        "sample": False,
        "source": "국토교통부 아파트 매매 실거래가 (해제 거래 제외, 단지·면적별 최근 3건 중앙값)",
        "regions": dict(sorted(regions.items())),
        "complexes": out,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    log(f"완료: 단지 {len(out)}곳, 좌표 실패 {miss}곳, 카카오 호출 {geo.calls}회 → {OUT}")


if __name__ == "__main__":
    main()
