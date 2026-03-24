# =============================================================================
# 온라인 AI 전당포 - 꿀매물 탐지기  (Streamlit 대시보드 v5.0)
#
# ▶ 필요한 라이브러리 설치 명령어:
#   pip install streamlit requests pandas beautifulsoup4
#
# ▶ 실행 방법:
#   streamlit run app.py
#
# ▶ v5.0 핵심 변경:
#   - API Fetch / 로컬 Filter 완벽 분리
#     · session_state.raw_items 에 원본 전체 저장
#     · 제외키워드·가격범위·정렬·꿀매물 기준 변경 → API 재호출 없이 즉시 반영
#     · 검색어·API정렬·수집개수 변경 → 버튼 클릭 시에만 재크롤링
#   - 로컬 정렬 2종 추가: 가격 높은순, difflib 기반 정확도순
#   - 테이블 뷰에 정확도(%) 컬럼 추가
# =============================================================================

import re
import time
import difflib
from datetime import datetime, timezone, timedelta

import requests
import pandas as pd
import streamlit as st

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# =============================================================================
# [페이지 기본 설정]
# =============================================================================
st.set_page_config(
    page_title="온라인 AI 전당포 - 꿀매물 탐지기",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =============================================================================
# [전역 상수]
# =============================================================================
KST            = timezone(timedelta(hours=9))
API_URL        = "https://api.bunjang.co.kr/api/1/find_v2.json"
ITEMS_PER_PAGE = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin":          "https://m.bunjang.co.kr",
    "Referer":         "https://m.bunjang.co.kr/",
    "Connection":      "keep-alive",
    "Sec-Fetch-Dest":  "empty",
    "Sec-Fetch-Mode":  "cors",
    "Sec-Fetch-Site":  "same-site",
}

API_SORT_MAP = {
    "최신순":   "date",
    "정확도순": "score",
    "저가순":   "price",
}

# ── LOCAL_SORT_MAP (v5.0 확장) ──────────────────────────────────────────────
# 값: (정렬 컬럼명, ascending)
# "정확도순"은 accuracy_score 컬럼을 동적으로 생성한 뒤 정렬합니다.
LOCAL_SORT_OPTIONS = [
    "할인율 높은순",   # discount_rate DESC
    "최신순",          # registered_time DESC
    "가격 낮은순",     # price ASC
    "가격 높은순",     # price DESC  ← 신규
    "정확도순",        # accuracy_score DESC (difflib)  ← 신규
    "이름 가나다순",   # title ASC
]

LOCAL_SORT_COL = {
    "할인율 높은순":  ("discount_rate",   False),
    "최신순":         ("registered_time", False),
    "가격 낮은순":    ("price",           True),
    "가격 높은순":    ("price",           False),
    "정확도순":       ("accuracy_score",  False),
    "이름 가나다순":  ("title",           True),
}

RANK_ICONS = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

# =============================================================================
# [커스텀 CSS]
# =============================================================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #ffffff; color: #1a1a1a;
    }
    .main-title {
        font-size: 2.6rem; font-weight: 900;
        background: linear-gradient(90deg, #ff4500, #ff6b35, #f7931e);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text; margin-bottom: 0.1rem; letter-spacing: -0.5px;
    }
    .sub-title { font-size: 1rem; color: #999; margin-bottom: 1.5rem; }

    /* ── 추정 시세 배너 ── */
    .market-banner {
        background: linear-gradient(135deg, #ff6b35 0%, #f7931e 50%, #ffcd3c 100%);
        border-radius: 16px; padding: 18px 24px; margin-bottom: 18px;
        color: #fff; box-shadow: 0 4px 20px rgba(255,107,53,0.35);
    }
    .market-banner-title {
        font-size: 0.85rem; font-weight: 600; opacity: 0.9;
        letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 4px;
    }
    .market-banner-price  { font-size: 2.4rem; font-weight: 900; line-height:1.1; letter-spacing:-1px; }
    .market-banner-sub    { font-size: 0.82rem; opacity: 0.85; margin-top: 6px; }

    /* ── 꿀매물 배너 ── */
    .honey-banner {
        background: linear-gradient(135deg, #d94000, #ff4500);
        border-radius: 16px; padding: 18px 24px; margin-bottom: 18px;
        color: #fff; box-shadow: 0 4px 20px rgba(217,64,0,0.35);
    }
    .honey-banner-title { font-size: 0.85rem; font-weight: 600; opacity: 0.9; margin-bottom:4px; }
    .honey-banner-count { font-size: 2.4rem; font-weight: 900; line-height: 1.1; }
    .honey-banner-sub   { font-size: 0.82rem; opacity: 0.85; margin-top: 6px; }

    /* ── 실시간 필터 반영 알림 ── */
    .live-filter-badge {
        display: inline-block; padding: 3px 10px;
        background: #e8f5e8; color: #2e7d32;
        border: 1px solid #a5d6a7; border-radius: 20px;
        font-size: 0.75rem; font-weight: 700; margin-left: 8px;
    }

    /* ── 상품 카드 ── */
    .product-card {
        background: #fff; border: 1.5px solid #e8e8e8; border-radius: 14px;
        padding: 18px 20px; margin-bottom: 14px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05); transition: all 0.2s ease;
    }
    .product-card:hover {
        border-color: #ff6b35; box-shadow: 0 4px 16px rgba(255,107,53,0.15);
        transform: translateY(-1px);
    }
    .product-card-honey {
        background: linear-gradient(135deg, #fffbf0, #fff3e0);
        border: 2.5px solid #ff6b35; border-radius: 14px;
        padding: 18px 20px; margin-bottom: 14px;
        box-shadow: 0 6px 24px rgba(255,107,53,0.3); transition: all 0.2s ease;
    }
    .product-card-honey:hover {
        box-shadow: 0 8px 32px rgba(255,107,53,0.45); transform: translateY(-2px);
    }

    .card-title       { font-size:1.02rem; font-weight:600; color:#1a1a1a; margin-bottom:8px; line-height:1.4; }
    .card-price       { font-size:1.4rem; font-weight:800; color:#ff6b35; }
    .card-price-honey { font-size:1.6rem; font-weight:900; color:#d94000; }
    .card-time        { font-size:0.8rem; color:#aaa; margin-top:5px; }
    .card-link a {
        display:inline-block; margin-top:10px; padding:7px 16px;
        background:linear-gradient(90deg,#ff6b35,#f7931e);
        color:#fff!important; border-radius:8px; font-size:0.84rem;
        font-weight:600; text-decoration:none!important; transition:opacity 0.2s;
    }
    .card-link a:hover { opacity: 0.82; }

    .badge-new {
        display:inline-block; padding:2px 8px; background:#e8f5e8; color:#2e7d32;
        border-radius:20px; font-size:0.7rem; font-weight:700;
        margin-left:5px; vertical-align:middle;
    }
    .badge-honey {
        display:inline-block; padding:3px 10px;
        background:linear-gradient(90deg,#d94000,#ff4500);
        color:#fff; border-radius:20px; font-size:0.76rem; font-weight:800;
        margin-left:6px; vertical-align:middle;
        box-shadow:0 2px 8px rgba(255,69,0,0.45);
        animation: pulse-badge 2s infinite;
    }
    @keyframes pulse-badge {
        0%,100% { box-shadow:0 2px 8px rgba(255,69,0,0.45); }
        50%      { box-shadow:0 2px 16px rgba(255,69,0,0.75); }
    }

    .discount-bar {
        display:inline-block; margin-top:6px; padding:5px 13px;
        background:linear-gradient(90deg,#fff0e8,#ffe4d0);
        border:1.5px solid #ff9966; border-radius:8px;
        font-size:0.87rem; font-weight:700; color:#cc3300;
    }
    .discount-bar-normal {
        display:inline-block; margin-top:6px; padding:4px 12px;
        background:#f5f5f5; border:1px solid #ddd; border-radius:8px;
        font-size:0.85rem; color:#777;
    }

    .trend-header {
        font-size:0.78rem; font-weight:700; color:#ff4500;
        letter-spacing:0.04em; text-transform:uppercase; margin-bottom:6px;
    }
    .trend-source { font-size:0.72rem; color:#aaa; margin-bottom:10px; }

    [data-testid="metric-container"] {
        background:#fafafa; border:1.5px solid #ebebeb;
        border-radius:12px; padding:12px 16px;
        box-shadow:0 1px 4px rgba(0,0,0,0.04);
    }
    [data-testid="stSidebar"] { background-color:#f8f8f8; }
    hr { border-color: #e8e8e8; }
    .stDataFrame a { color:#ff6b35!important; }
    .kw-tag {
        display:inline-block; background:#fff3f0; color:#cc4400;
        border:1px solid #ffccbb; border-radius:20px;
        padding:2px 9px; font-size:0.75rem; margin:2px;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# [세션 상태 초기화]
# v5.0 핵심: raw_items를 session_state에 보관하여 필터링을 분리합니다.
#
# ┌─────────────────────────────────────────────────────────────────┐
# │ raw_items    : API에서 받아온 전체 파싱 결과 (필터링 없음)          │
# │ crawl_stats  : 마지막 크롤링의 원시 통계 (total_raw, elapsed)      │
# │ crawl_keyword: 마지막 크롤링에 사용된 검색어 (정확도 계산에 사용)    │
# │ searched     : 최소 한 번 크롤링 완료 여부                         │
# └─────────────────────────────────────────────────────────────────┘
# =============================================================================
_defaults = {
    "search_keyword": "아이패드 프로",
    "auto_search":    False,
    "raw_items":      [],          # API 원본 전체 (필터링 전)
    "crawl_stats":    {"total_raw": 0, "elapsed": 0.0},
    "crawl_keyword":  "",          # 마지막 크롤링 키워드 (정확도 계산용)
    "searched":       False,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =============================================================================
# [트렌드 키워드 수집] - 5분 캐시 적용
# =============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_trending_keywords() -> tuple[list[str], str]:
    """
    실시간 트렌드 키워드 Top 10 수집.
    Plan A: 번개장터 API → Plan B: 네이버 쇼핑 → Plan C: 기본 목록
    """
    for url in [
        "https://api.bunjang.co.kr/api/1/trending_searches.json",
        "https://api.bunjang.co.kr/api/trending",
        "https://api.bunjang.co.kr/api/1/popular_keywords.json",
        "https://search.bunjang.co.kr/api/v1/trending",
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=4)
            if r.status_code == 200:
                data = r.json()
                raw = (data.get("list") or data.get("keywords") or
                       data.get("trending") or data.get("queries") or
                       (data.get("data") or {}).get("keywords"))
                if raw and isinstance(raw, list) and len(raw) >= 3:
                    parsed = []
                    for item in raw[:10]:
                        kw = item if isinstance(item, str) else (
                            item.get("keyword") or item.get("name") or
                            item.get("query") or item.get("text") or ""
                        )
                        if str(kw).strip():
                            parsed.append(str(kw).strip())
                    if len(parsed) >= 3:
                        return parsed[:10], "번개장터 실시간"
        except Exception:
            continue

    if BS4_AVAILABLE:
        try:
            r = requests.get(
                "https://shopping.naver.com/home/p/index.nhn",
                headers={"User-Agent": HEADERS["User-Agent"], "Accept-Language": "ko-KR"},
                timeout=5,
            )
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for sel in ["span.item_name", "a.trend_keyword", "span.keyword", ".rankList a"]:
                    kws = [el.get_text(strip=True) for el in soup.select(sel) if el.get_text(strip=True)]
                    if len(kws) >= 5:
                        return kws[:10], "네이버 쇼핑 트렌드"
        except Exception:
            pass

    return [
        "아이폰 15 프로", "갤럭시 S24 울트라", "아이패드 프로", "맥북 프로 M3",
        "에어팟 프로 2", "갤럭시 탭 S9", "닌텐도 스위치 OLED",
        "플레이스테이션 5", "다이슨 에어랩", "LG 그램 360",
    ], "인기 추천 (기본)"

# =============================================================================
# [데이터 헬퍼 함수]
# =============================================================================

def parse_timestamp(ts_value) -> str:
    """Unix 타임스탬프 또는 ISO 8601 문자열 → KST "YYYY-MM-DD HH:MM"."""
    if ts_value is None:
        return "알 수 없음"
    try:
        if isinstance(ts_value, (int, float)):
            return datetime.fromtimestamp(int(str(int(ts_value))[:10]), tz=KST).strftime("%Y-%m-%d %H:%M")
        s = str(ts_value)
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M")
        if s.isdigit():
            return datetime.fromtimestamp(int(s[:10]), tz=KST).strftime("%Y-%m-%d %H:%M")
        return s
    except Exception:
        return str(ts_value)


def extract_price(v) -> int:
    """가격 값에서 숫자만 추출하여 정수 반환. 예: '1,200,000원' → 1200000"""
    if v is None:
        return 0
    try:
        c = re.sub(r"[^\d]", "", str(v))
        return int(c) if c else 0
    except (ValueError, TypeError):
        return 0


def calc_accuracy_score(title: str, keyword: str) -> float:
    """
    difflib.SequenceMatcher로 제목과 검색 키워드의 텍스트 유사도를 계산합니다.

    - 반환값: 0.0 ~ 100.0 (100.0 = 완전 일치, 소수점 첫째 자리)
    """
    if not title or not keyword:
        return 0.0
    return round(
        difflib.SequenceMatcher(None, keyword.lower().strip(), title.lower().strip()).ratio() * 100,
        1,
    )


def format_accuracy(score: float) -> str:
    """정확도 점수(0~100)를 이모지 포함 표시 문자열로 변환합니다."""
    if score >= 70:
        return f"🎯 {score:.1f}%"
    elif score >= 40:
        return f"📌 {score:.1f}%"
    else:
        return f"💭 {score:.1f}%"


def calc_market_price(prices: list[int]) -> tuple[int, str]:
    """상하위 10% 절사 중앙값으로 추정 평균 시세를 계산합니다."""
    valid = [p for p in prices if p > 0]
    if not valid:
        return 0, "계산 불가"
    s = pd.Series(valid, dtype=float)
    if len(valid) <= 3:
        return int(s.median()), f"단순 중앙값 ⚠️ ({len(valid)}개)"
    q10, q90 = s.quantile(0.10), s.quantile(0.90)
    trimmed  = s[(s >= q10) & (s <= q90)]
    if len(trimmed) == 0:
        return int(s.median()), f"전체 중앙값 ({len(valid)}개)"
    return int(trimmed.median()), f"상하위 10% 절사 중앙값 ({len(trimmed):,}개 기준)"


def calc_discount_rate(price: int, market_price: int) -> float:
    """추정 평균 시세 대비 할인율(%). market_price=0이면 0 반환."""
    if market_price <= 0:
        return 0.0
    return round(((market_price - price) / market_price) * 100, 1)


def format_discount_label(rate: float, honey_threshold: float) -> str:
    """할인율을 이모지 포함 표시 문자열로 변환합니다 (honey_threshold 동적 적용)."""
    if rate >= honey_threshold:
        return f"🚨 -{rate:.1f}%"
    elif rate >= 5:
        return f"✅ -{rate:.1f}%"
    elif rate >= 0:
        return f"💤 -{rate:.1f}%"
    else:
        return f"📈 +{abs(rate):.1f}%"


def fetch_single_page(keyword: str, sort_order: str, page: int) -> list[dict]:
    """번개장터 API 단일 페이지 호출. 실패 시 빈 리스트 반환."""
    params = {
        "q": keyword, "order": sort_order, "page": page,
        "n": ITEMS_PER_PAGE, "stat_device": "w",
        "req_ref": "search", "version": "4",
    }
    try:
        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        return data.get("list", []) if data.get("result") == "success" else []
    except Exception:
        return []


def parse_raw_item(item: dict) -> dict:
    """API 원시 상품 딕셔너리 → 정제된 dict (필터링 없이 전부 보존)."""
    pid   = str(item.get("pid", ""))
    title = item.get("name", "").strip()
    price = extract_price(item.get("price", 0))
    ts    = item.get("updated_at") or item.get("updatedAt") or item.get("created_at")
    return {
        "title":           title,
        "price":           price,
        "price_formatted": f"{price:,}원",
        "registered_time": parse_timestamp(ts),
        "url":             f"https://m.bunjang.co.kr/products/{pid}" if pid else "",
        "pid":             pid,
    }


def crawl_with_progress(
    keyword: str,
    api_sort: str,
    target_count: int,
) -> tuple[list[dict], int, float]:
    """
    다중 페이지 크롤링 (v5.0 변경: 제외 키워드 필터링을 하지 않습니다).
    API에서 받아온 모든 파싱 결과를 raw_items로 반환하여
    session_state에 저장합니다. 필터링은 render 단계에서 수행됩니다.

    Returns:
        (모든_파싱_결과, 원시_총수, 소요초)
    """
    start_time   = time.time()
    progress_bar = st.progress(0, text="크롤링 준비 중...")
    status_text  = st.empty()
    raw_pool:    list[dict] = []
    all_parsed:  list[dict] = []
    page = 0

    while len(raw_pool) < target_count:
        ratio = min(len(raw_pool) / target_count, 1.0)
        progress_bar.progress(
            ratio,
            text=f"🔍 {len(raw_pool):,} / {target_count:,}개 수집 중... (페이지 {page + 1})"
        )
        status_text.caption(
            f"페이지 {page + 1} │ 수집: {len(raw_pool):,}개"
        )
        page_items = fetch_single_page(keyword, api_sort, page)
        if not page_items:
            break
        for raw in page_items:
            raw_pool.append(raw)
            item = parse_raw_item(raw)
            if item["title"]:          # 제목이 있는 항목만 보존 (빈 제목 제외)
                item["accuracy_score"] = calc_accuracy_score(item["title"], keyword)
                all_parsed.append(item)
        page += 1
        time.sleep(0.3)

    elapsed = time.time() - start_time
    progress_bar.progress(1.0, text=f"✅ 수집 완료! 총 {len(raw_pool):,}개 원시 데이터")
    status_text.empty()
    return all_parsed, len(raw_pool), elapsed


def apply_filters_and_sort(
    raw_items:        list[dict],
    exclude_kws:      list[str],
    price_min_won:    int,
    price_max_won:    int,
    honey_threshold:  float,
    local_sort_label: str,
) -> tuple[list[dict], int, int]:
    """
    session_state.raw_items를 받아 아래 순서로 처리합니다.
    API 재호출 없이 즉시 실행됩니다.

    1. 제외 키워드 필터링
    2. 가격 범위 필터링
    3. 추정 평균 시세 계산 (절사 중앙값)
    4. 할인율(discount_rate) 계산
       (accuracy_score는 크롤링 단계에서 이미 raw_items에 주입됨)
    5. 로컬 정렬 적용

    Returns:
        (최종_정렬_리스트, 제외된_수, 가격_필터_전_통과_수)
    """
    excluded = 0

    # ── 1. 제외 키워드 필터링 ─────────────────────────────────────────────────
    kw_passed = []
    for it in raw_items:
        if any(kw in it["title"] for kw in exclude_kws):
            excluded += 1
        else:
            kw_passed.append(it)

    kw_passed_count = len(kw_passed)  # 가격 필터 전 통과 수 (메트릭 표시용)

    # ── 2. 가격 범위 필터링 ───────────────────────────────────────────────────
    price_passed = [it for it in kw_passed if price_min_won <= it["price"] <= price_max_won]

    if not price_passed:
        return [], excluded, kw_passed_count

    # ── 3. 추정 평균 시세 계산 ────────────────────────────────────────────────
    prices = [it["price"] for it in price_passed]
    market_price, _ = calc_market_price(prices)

    # ── 4. 할인율 계산 후 각 아이템에 주입 ───────────────────────────────────
    # accuracy_score는 크롤링 시 parse 단계에서 이미 주입되어 있습니다.
    for it in price_passed:
        it["discount_rate"] = calc_discount_rate(it["price"], market_price)

    # ── 5. 로컬 정렬 ─────────────────────────────────────────────────────────
    col, ascending = LOCAL_SORT_COL[local_sort_label]
    df = pd.DataFrame(price_passed).sort_values(by=col, ascending=ascending)
    return df.to_dict(orient="records"), excluded, kw_passed_count

# =============================================================================
# [사이드바 UI]
# =============================================================================
with st.sidebar:

    # ── 실시간 트렌드 Top 10 ──────────────────────────────────────────────────
    st.markdown('<p class="trend-header">🔥 실시간 급상승 트렌드 Top 10</p>',
                unsafe_allow_html=True)

    with st.spinner("트렌드 로딩 중..."):
        trend_keywords, trend_source = get_trending_keywords()

    st.markdown(f'<p class="trend-source">📡 출처: {trend_source} · 1시간 캐시</p>',
                unsafe_allow_html=True)

    tcols = st.columns(2, gap="small")
    for i, kw in enumerate(trend_keywords):
        with tcols[i % 2]:
            icon = RANK_ICONS[i] if i < len(RANK_ICONS) else f"{i+1}."
            if st.button(f"{icon} {kw}", key=f"trend_{i}",
                         use_container_width=True, help=f"'{kw}' 검색"):
                st.session_state.search_keyword = kw
                st.session_state.auto_search    = True
                st.rerun()

    st.markdown("---")
    st.markdown("## ⚙️ 검색 설정")

    # ── 검색 키워드 (key 연동으로 트렌드 클릭 시 자동 채움) ─────────────────
    st.text_input(
        "🔍 검색 키워드",
        key="search_keyword",
        placeholder="예: 아이폰 15 프로, 갤럭시 S24...",
    )

    # ── 탐색 버튼 (검색어 바로 아래) ────────────────────────────────────────
    search_clicked = st.button(
        "🔎 매물 탐색 시작",
        use_container_width=True,
        type="primary",
    )

    st.markdown("---")

    # ── API 수집 설정 (변경 후 버튼 클릭 필요) ──────────────────────────────
    st.markdown("### 📡 API 수집 설정")
    st.caption("⚠️ 아래 설정 변경 시 '매물 탐색 시작' 버튼을 다시 눌러야 적용됩니다.")

    api_sort_label = st.selectbox(
        "번개장터 검색 정렬 (API)",
        options=list(API_SORT_MAP.keys()), index=0,
        help="• 최신순: 최근 등록 우선\n• 정확도순: 관련도 순\n• 저가순: 가격 낮은 순",
    )
    api_sort_value = API_SORT_MAP[api_sort_label]

    target_count = st.slider(
        "목표 수집 개수", min_value=100, max_value=1000, value=300, step=100,
        help="API는 100개씩 반환 → 300개 = 최대 3회 호출",
    )
    st.caption(f"예상 API 호출: 최대 {target_count // ITEMS_PER_PAGE}회")

    st.markdown("---")

    # ── 아래 설정들은 변경 즉시 API 재호출 없이 화면 반영 ────────────────────
    st.markdown("### 🚫 제외 키워드")
    st.markdown(
        '<span style="font-size:0.75rem;color:#2e7d32;font-weight:700;">'
        '⚡ 실시간 반영</span>',
        unsafe_allow_html=True,
    )

    exclude_raw = st.text_area(
        "제외 키워드",
        value="매입, 부품, 파손, 찍힘, 교신, 업자, 대납, 가개통, 케이스, 필름, 펜슬만, 키보드만",
        height=100, label_visibility="collapsed",
    )
    exclude_keywords_list = [kw.strip() for kw in exclude_raw.split(",") if kw.strip()]
    if exclude_keywords_list:
        st.markdown(
            " ".join(f'<span class="kw-tag">{kw}</span>' for kw in exclude_keywords_list),
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("### 💰 가격 범위")
    st.markdown(
        '<span style="font-size:0.75rem;color:#2e7d32;font-weight:700;">'
        '⚡ 실시간 반영</span>',
        unsafe_allow_html=True,
    )
    price_min, price_max = st.slider(
        "가격 범위 (만원)", min_value=0, max_value=500,
        value=(0, 300), step=5, format="%d만원",
    )

    st.markdown("---")
    st.markdown("### 🔽 화면 정렬")
    st.markdown(
        '<span style="font-size:0.75rem;color:#2e7d32;font-weight:700;">'
        '⚡ 실시간 반영</span>',
        unsafe_allow_html=True,
    )
    local_sort_label = st.selectbox(
        "화면 정렬", options=LOCAL_SORT_OPTIONS, index=0,
        label_visibility="collapsed",
        help=(
            "• 할인율 높은순: 꿀매물 먼저\n"
            "• 최신순: 등록시간 내림차순\n"
            "• 가격 낮은순 / 높은순\n"
            "• 정확도순: 검색어 유사도 (difflib)\n"
            "• 이름 가나다순"
        ),
    )

    st.markdown("---")
    st.markdown("### 🚨 꿀매물 기준")
    st.markdown(
        '<span style="font-size:0.75rem;color:#2e7d32;font-weight:700;">'
        '⚡ 실시간 반영</span>',
        unsafe_allow_html=True,
    )
    honey_threshold = st.slider(
        "할인율 기준 (%)", min_value=5, max_value=40, value=15, step=1,
        help="추정 평균 시세 대비 이 % 이상 저렴한 매물을 꿀매물로 강조합니다.",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("📡 번개장터 (bunjang.co.kr)")
    st.caption(f"🔄 API 정렬: {api_sort_label} ({api_sort_value})")

# =============================================================================
# [메인 헤더]
# =============================================================================
st.markdown('<p class="main-title">🏪 온라인 AI 전당포</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-title">번개장터 꿀매물 탐지기 | 실시간 차익 거래 봇 v5.0</p>',
    unsafe_allow_html=True,
)
st.markdown("---")

# =============================================================================
# [크롤링 실행 트리거]
# ▶ 실행 조건: 버튼 클릭 OR 트렌드 키워드 클릭(auto_search=True)
# ▶ 방어: API 정렬·수집개수는 이 블록에서만 사용 → 버튼 없이는 API 재호출 없음
# =============================================================================
should_crawl = search_clicked or st.session_state.get("auto_search", False)

if should_crawl:
    st.session_state.auto_search = False          # 플래그 즉시 소비
    kw = st.session_state.search_keyword.strip()
    if not kw:
        st.warning("⚠️ 검색 키워드를 입력해 주세요.")
    else:
        st.info(
            f"🚀 **'{kw}'** 매물 탐색 시작 │ "
            f"API 정렬: **{api_sort_label}** │ 목표: **{target_count:,}개**"
        )
        # ── API 크롤링 실행 (제외 키워드 필터링 없음 - raw 전체 저장) ──────────
        all_parsed, total_raw, elapsed = crawl_with_progress(
            keyword=kw,
            api_sort=api_sort_value,
            target_count=target_count,
        )
        # raw_items에 파싱 결과 전체를 저장합니다.
        # 이후 사이드바 설정 변경 시 이 데이터를 재사용합니다.
        st.session_state.raw_items     = all_parsed
        st.session_state.crawl_stats   = {"total_raw": total_raw, "elapsed": elapsed}
        st.session_state.crawl_keyword = kw
        st.session_state.searched      = True
        st.rerun()

# =============================================================================
# [결과 표시 영역]
# 사이드바 설정(제외키워드·가격범위·정렬·꿀매물기준) 변경 시
# 이 블록이 자동 재실행되어 API 호출 없이 즉시 화면이 갱신됩니다.
# =============================================================================
if st.session_state.searched:
    raw_items    = st.session_state.raw_items
    crawl_stats  = st.session_state.crawl_stats
    crawl_kw     = st.session_state.crawl_keyword

    price_min_won = price_min * 10_000
    price_max_won = price_max * 10_000

    # ── apply_filters_and_sort: API 호출 없이 즉시 필터링·정렬 ──────────────
    sorted_items, excluded_count, kw_passed_count = apply_filters_and_sort(
        raw_items        = raw_items,
        exclude_kws      = exclude_keywords_list,
        price_min_won    = price_min_won,
        price_max_won    = price_max_won,
        honey_threshold  = honey_threshold,
        local_sort_label = local_sort_label,
    )

    # 추정 시세·꿀매물 재계산 (메트릭 표시용)
    prices_for_market = [it["price"] for it in sorted_items]
    market_price, market_note = calc_market_price(prices_for_market)
    honey_items  = [it for it in sorted_items if it.get("discount_rate", 0) >= honey_threshold]
    honey_count  = len(honey_items)

    # ── 메트릭 1행: 수집 통계 ────────────────────────────────────────────────
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("📦 원시 수집", f"{crawl_stats['total_raw']:,}개",
                  help="API 원시 수집 건수 (파싱 전 전체)")
    with m2:
        st.metric("🚫 키워드 제외", f"{excluded_count:,}개",
                  delta=f"-{excluded_count:,}", delta_color="inverse",
                  help="제외 키워드에 걸린 매물 수 (실시간 반영)")
    with m3:
        st.metric("✅ 키워드 통과", f"{kw_passed_count:,}개",
                  help="제외 키워드 필터 통과 (가격 필터 전)")
    with m4:
        st.metric("💰 가격 범위 통과", f"{len(sorted_items):,}개",
                  help=f"{price_min}만~{price_max}만원 (실시간 반영)")
    with m5:
        st.metric("⏱️ 수집 시간", f"{crawl_stats['elapsed']:.1f}초")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 메트릭 2행: 시세 분석 배너 ───────────────────────────────────────────
    bc1, bc2, bc3, bc4 = st.columns([2, 2, 1.5, 1.5])
    with bc1:
        if market_price > 0:
            st.markdown(
                f'<div class="market-banner">'
                f'<div class="market-banner-title">📊 추정 평균 시세</div>'
                f'<div class="market-banner-price">{market_price:,}원</div>'
                f'<div class="market-banner-sub">{market_note}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning("📊 추정 평균 시세 계산 불가 (데이터 부족)")

    with bc2:
        if honey_count > 0:
            max_disc     = max(it["discount_rate"] for it in honey_items)
            min_honey_p  = min(it["price"] for it in honey_items)
            st.markdown(
                f'<div class="honey-banner">'
                f'<div class="honey-banner-title">🚨 꿀매물 ({honey_threshold}%↑)</div>'
                f'<div class="honey-banner-count">{honey_count}개 발견!</div>'
                f'<div class="honey-banner-sub">'
                f'최대 {max_disc:.1f}% 할인 · 최저가 {min_honey_p:,}원'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="honey-banner" style="opacity:0.5;">'
                f'<div class="honey-banner-title">🚨 꿀매물 ({honey_threshold}%↑)</div>'
                f'<div class="honey-banner-count">없음</div>'
                f'<div class="honey-banner-sub">기준을 낮추거나 수집량을 늘려보세요</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with bc3:
        st.metric("💎 꿀매물 최저가",
                  f"{min(it['price'] for it in honey_items):,}원" if honey_items else "-")
    with bc4:
        st.metric("📉 최대 할인율",
                  f"{max(it['discount_rate'] for it in honey_items):.1f}%" if honey_items else "-")

    st.markdown("<br>", unsafe_allow_html=True)

    if not sorted_items:
        st.info("😢 조건에 맞는 매물이 없습니다. 검색어·필터를 조정해 보세요.")
        st.stop()

    st.markdown(
        f"**'{crawl_kw}'** │ API 정렬: **{api_sort_label}** │ "
        f"화면 정렬: **{local_sort_label}** │ 표시: **{len(sorted_items):,}개**"
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # ── 탭 ───────────────────────────────────────────────────────────────────
    tab_card, tab_table = st.tabs(["🃏 카드 뷰", "📋 테이블 뷰"])

    # ─────────────────────────────────────────────────────────────────────────
    # 탭 1: 카드 뷰
    # ─────────────────────────────────────────────────────────────────────────
    with tab_card:
        if not sorted_items:
            st.info("😢 조건에 맞는 매물이 없습니다.")
        else:
            cols = st.columns(2, gap="medium")
            for idx, item in enumerate(sorted_items):
                rate     = item.get("discount_rate", 0.0)
                is_honey = rate >= honey_threshold

                with cols[idx % 2]:
                    # 🔥 NEW 배지: 1시간 이내 등록 매물
                    new_badge = ""
                    try:
                        dt_item = datetime.strptime(item["registered_time"], "%Y-%m-%d %H:%M")
                        if (datetime.now(tz=KST) - dt_item.replace(tzinfo=KST)).total_seconds() < 3600:
                            new_badge = '<span class="badge-new">🔥 NEW</span>'
                    except Exception:
                        pass

                    honey_badge = (
                        f'<span class="badge-honey">🚨 꿀매물 {rate:.1f}% 절약!</span>'
                        if is_honey else ""
                    )

                    if market_price > 0:
                        if is_honey:
                            disc_html = (
                                f'<div class="discount-bar">'
                                f'평균({market_price:,}원) 대비 {rate:.1f}% 저렴</div>'
                            )
                        elif rate >= 0:
                            disc_html = (
                                f'<div class="discount-bar-normal">'
                                f'평균 대비 {rate:.1f}% 저렴</div>'
                            )
                        else:
                            disc_html = (
                                f'<div class="discount-bar-normal">'
                                f'평균 대비 {abs(rate):.1f}% 비쌈</div>'
                            )
                    else:
                        disc_html = ""

                    card_class  = "product-card-honey" if is_honey else "product-card"
                    price_class = "card-price-honey"   if is_honey else "card-price"

                    st.markdown(
                        f"""
                        <div class="{card_class}">
                            <div class="card-title">
                                {idx + 1}. {item['title']}{honey_badge}{new_badge}
                            </div>
                            <div class="{price_class}">{item['price_formatted']}</div>
                            {disc_html}
                            <div class="card-time">🕒 {item['registered_time']}</div>
                            <div class="card-link">
                                <a href="{item['url']}" target="_blank" rel="noopener noreferrer">
                                    🔗 번개장터에서 보기
                                </a>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    # ─────────────────────────────────────────────────────────────────────────
    # 탭 2: 테이블 뷰 (v5.0: 정확도 컬럼 추가)
    # ─────────────────────────────────────────────────────────────────────────
    with tab_table:
        if not sorted_items:
            st.info("😢 조건에 맞는 매물이 없습니다.")
        else:
            # ── 컬럼 순서를 먼저 명시적으로 지정 (링크 버그 원천 차단) ──────────
            df = pd.DataFrame(sorted_items)[
                ["title", "price_formatted", "discount_rate",
                 "accuracy_score", "registered_time", "url"]
            ].copy()

            # 할인율 → 이모지 포함 표시 문자열 (신규 열이 맨 끝에 추가됨)
            df["discount_display"] = df["discount_rate"].apply(
                lambda r: format_discount_label(r, honey_threshold)
            )

            # 최종 컬럼 순서를 명시적으로 재배치한 뒤 한글 컬럼명을 덮어씁니다.
            # accuracy_score는 numeric(0-100) 그대로 유지하여 NumberColumn으로 표시합니다.
            df = df[["title", "price_formatted", "accuracy_score",
                     "discount_display", "registered_time", "url"]].copy()
            df.index   = range(1, len(df) + 1)
            df.columns = ["상품명", "가격", "정확도(%)", "할인율", "등록 시간", "링크"]

            st.dataframe(
                df,
                use_container_width=True,
                height=640,
                column_config={
                    "상품명":    st.column_config.TextColumn("상품명",   width="large"),
                    "가격":      st.column_config.TextColumn("가격",     width="small"),
                    "정확도(%)": st.column_config.NumberColumn(
                        "정확도(%)",
                        format="%.1f %%",
                        width="small",
                        help="검색어와 상품명 간 difflib 유사도 (0~100%)",
                    ),
                    "할인율":    st.column_config.TextColumn(
                        "할인율", width="small",
                        help="🚨 꿀매물 · ✅ 할인 · 💤 소폭 · 📈 평균 초과",
                    ),
                    "등록 시간":  st.column_config.TextColumn("등록 시간", width="medium"),
                    "링크":      st.column_config.LinkColumn(
                        "번개장터 링크",
                        display_text="🔗 보러가기",
                        width="small",
                        help="클릭 시 새 창으로 번개장터 상품 페이지 오픈",
                    ),
                },
            )

            now_str  = datetime.now(tz=KST).strftime("%Y%m%d_%H%M%S")
            csv_data = df.to_csv(index=True, encoding="utf-8-sig")
            st.download_button(
                label="⬇️ CSV 다운로드 (엑셀 호환)",
                data=csv_data.encode("utf-8-sig"),
                file_name=f"번개장터_{crawl_kw}_{now_str}.csv",
                mime="text/csv",
            )

# =============================================================================
# [초기 안내 화면]
# =============================================================================
else:
    st.markdown(
        """
        <div style="text-align:center; padding:50px 20px;">
            <div style="font-size:5rem;">🔍</div>
            <h2 style="color:#888;font-weight:600;">
                사이드바 트렌드 키워드를 클릭하거나<br>검색어를 직접 입력하세요
            </h2>
            <h3 style="color:#ff6b35;">'매물 탐색 시작' 버튼을 눌러주세요</h3>
            <br>
            <p style="color:#bbb;font-size:0.95rem;line-height:2.4;">
                🔥 트렌드 키워드 클릭 → 자동 검색 실행<br>
                📦 다중 페이지 크롤링 → 최대 1,000개 수집<br>
                📊 절사 중앙값 → <b>추정 평균 시세</b> 실시간 산출<br>
                🚨 <b>할인율 자동 계산</b> → 꿀매물 강조<br>
                ⚡ 제외 키워드·가격범위·정렬 변경 → <b>API 재호출 없이 즉시 반영</b>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
