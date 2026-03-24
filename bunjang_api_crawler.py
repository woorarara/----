# =============================================================================
# [방법 1] requests 기반 번개장터 내부 API 직접 호출 크롤러 (권장 - 가장 빠름)
#
# ▶ 필요한 라이브러리 설치 명령어:
#   pip install requests
#
# ▶ 실행 방법:
#   python bunjang_api_crawler.py
#
# ▶ 동작 원리:
#   번개장터 앱/웹이 내부적으로 사용하는 JSON 검색 API를 직접 호출합니다.
#   브라우저 없이 순수 HTTP 요청만으로 동작하므로 Selenium 대비 10~50배 빠릅니다.
# =============================================================================

import requests
import json
from datetime import datetime, timezone, timedelta
import time
import re

# =============================================================================
# [설정 섹션] - 검색 조건 및 필터링 키워드를 여기서 관리하세요
# =============================================================================

# 검색할 키워드
SEARCH_KEYWORD = "아이폰 15 프로"

# 한 번 검색 시 가져올 최대 상품 수 (번개장터 API 최대 허용치: 100)
ITEMS_PER_PAGE = 100

# 검색 정렬 방식: "date" = 최신순, "score" = 정확도순, "price" = 가격 낮은순
SORT_ORDER = "date"

# ▶ 1차 필터링: 아래 키워드 중 하나라도 제목에 포함된 매물은 수집에서 제외
EXCLUDE_KEYWORDS = ["매입", "부품", "부품용", "파손", "찍힘", "교신", "업자", "대납", "가개통"]

# 한국 시간대 (UTC+9) 정의
KST = timezone(timedelta(hours=9))

# =============================================================================
# [HTTP 헤더 섹션]
# 번개장터 API 서버가 봇 요청을 차단하지 않도록 실제 브라우저처럼 위장하는 헤더
# Chrome 브라우저가 번개장터에 실제로 보내는 헤더와 동일하게 설정합니다
# =============================================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://m.bunjang.co.kr",
    "Referer": "https://m.bunjang.co.kr/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def fetch_bunjang_listings(keyword: str, page: int = 0) -> dict | None:
    """
    번개장터 내부 검색 API를 호출하여 원시 JSON 데이터를 반환하는 함수.

    Args:
        keyword: 검색 키워드 (예: "아이폰 15 프로")
        page:    페이지 번호 (0부터 시작, 0 = 첫 번째 페이지)

    Returns:
        API 응답 JSON dict, 실패 시 None
    """

    # 번개장터 공개 검색 API 엔드포인트
    # (브라우저 개발자 도구 Network 탭에서 확인할 수 있는 실제 API URL)
    api_url = "https://api.bunjang.co.kr/api/1/find_v2.json"

    # API에 전달할 쿼리 파라미터 구성
    params = {
        "q": keyword,           # 검색 키워드
        "order": SORT_ORDER,    # 정렬 방식
        "page": page,           # 페이지 번호 (0-indexed)
        "n": ITEMS_PER_PAGE,    # 페이지당 결과 수
        "stat_device": "w",     # 디바이스 타입 (w = web)
        "req_ref": "search",    # 요청 출처
        "version": "4",         # API 버전
    }

    try:
        # HTTP GET 요청 전송 (타임아웃 10초)
        response = requests.get(api_url, headers=HEADERS, params=params, timeout=10)

        # HTTP 응답 코드가 4xx, 5xx이면 예외 발생
        response.raise_for_status()

        # 응답 본문을 JSON으로 파싱하여 반환
        return response.json()

    except requests.exceptions.Timeout:
        print("❌ 오류: API 응답 시간 초과 (10초)")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ 오류: 인터넷 연결 실패 또는 API 서버 접속 불가")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP 오류: {e}")
        print("   → 번개장터가 요청을 차단했을 수 있습니다. Selenium 버전을 시도하세요.")
        return None
    except json.JSONDecodeError:
        print("❌ 오류: JSON 파싱 실패. API 응답 형식이 변경되었을 수 있습니다.")
        return None


def is_excluded(title: str) -> tuple[bool, str]:
    """
    상품 제목에 필터링 제외 키워드가 포함되어 있는지 검사하는 함수.

    Args:
        title: 검사할 상품 제목 문자열

    Returns:
        (제외_여부, 발견된_키워드) 튜플
        예: (True, "부품") 또는 (False, "")
    """
    for kw in EXCLUDE_KEYWORDS:
        if kw in title:
            return True, kw
    return False, ""


def parse_timestamp(ts_value) -> str:
    """
    번개장터 API가 반환하는 시간 값을 한국 시간(KST) 문자열로 변환하는 함수.
    API는 Unix 타임스탬프(정수) 또는 ISO 8601 형식 문자열을 반환할 수 있습니다.

    Args:
        ts_value: Unix 타임스탬프(int/float) 또는 날짜 문자열

    Returns:
        "YYYY-MM-DD HH:MM:SS" 형식의 한국 시간 문자열
    """
    if ts_value is None:
        return "알 수 없음"

    try:
        # Unix 타임스탬프 (숫자) 처리
        if isinstance(ts_value, (int, float)):
            ts = int(str(ts_value)[:10])  # 밀리초 단위라면 10자리로 잘라서 처리
            dt = datetime.fromtimestamp(ts, tz=KST)
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        # 문자열 형식 처리
        ts_str = str(ts_value)
        # ISO 8601 형식 처리 (예: "2024-01-15T12:30:00Z")
        if "T" in ts_str:
            ts_str = ts_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str).astimezone(KST)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        # 숫자만 있는 문자열 (Unix timestamp)
        if ts_str.isdigit():
            ts = int(ts_str[:10])
            dt = datetime.fromtimestamp(ts, tz=KST)
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        return ts_str

    except Exception:
        return str(ts_value)


def extract_price(price_value) -> int:
    """
    가격 데이터를 순수 정수(int)로 변환하는 함수.
    API 응답에서 가격은 "1,200,000" 같은 문자열 또는 1200000 같은 숫자로 옵니다.

    Args:
        price_value: 가격 (str 또는 int)

    Returns:
        정수형 가격 (변환 실패 시 0 반환)
    """
    if price_value is None:
        return 0
    try:
        # 숫자, 점, 쉼표를 제외한 모든 문자 제거 후 정수 변환
        cleaned = re.sub(r"[^\d]", "", str(price_value))
        return int(cleaned) if cleaned else 0
    except (ValueError, TypeError):
        return 0


def process_and_filter(raw_data: dict) -> list[dict]:
    """
    API 응답 JSON에서 필요한 필드만 추출하고 1차 필터링을 적용하는 함수.

    Args:
        raw_data: fetch_bunjang_listings()가 반환한 원시 JSON dict

    Returns:
        필터링 통과 상품들의 정제된 dict 리스트
    """
    result = []

    # API 응답 구조 검증
    if not raw_data or raw_data.get("result") != "success":
        print("⚠️  API 응답이 success가 아닙니다.")
        print(f"   응답 내용: {json.dumps(raw_data, ensure_ascii=False)[:300]}")
        return result

    # 상품 목록 추출 (번개장터 API는 'list' 키 안에 배열로 제공)
    items = raw_data.get("list", [])

    if not items:
        print("⚠️  검색 결과가 없습니다.")
        return result

    excluded_count = 0

    for item in items:
        # 상품 제목 추출
        title = item.get("name", "제목 없음").strip()

        # ─── 1차 필터링 적용 ───────────────────────────────────────────────
        # 제목에 제외 키워드가 포함되어 있으면 해당 상품을 건너뜀
        should_exclude, found_kw = is_excluded(title)
        if should_exclude:
            excluded_count += 1
            # 디버깅 시 아래 주석을 해제하면 제외된 상품을 확인할 수 있습니다
            # print(f"  [SKIP] '{found_kw}' 키워드 감지 → {title}")
            continue
        # ────────────────────────────────────────────────────────────────────

        # 상품 고유 ID 추출 (URL 생성에 사용)
        pid = item.get("pid", "")

        # 상품 상세 페이지 URL 조합
        product_url = f"https://m.bunjang.co.kr/products/{pid}" if pid else "URL 없음"

        # 가격 추출 및 정수 변환
        price_raw = item.get("price", 0)
        price_int = extract_price(price_raw)

        # 등록/업데이트 시간 변환
        # 번개장터 API는 'updated_at' 또는 'updatedAt' 필드를 사용합니다
        timestamp_raw = item.get("updated_at") or item.get("updatedAt") or item.get("created_at")
        registered_time = parse_timestamp(timestamp_raw)

        # 정제된 상품 정보 딕셔너리 구성
        result.append({
            "title": title,
            "price": price_int,
            "price_formatted": f"{price_int:,}원",
            "registered_time": registered_time,
            "url": product_url,
            "pid": pid,
        })

    # 처리 결과 요약 출력
    total = len(items)
    passed = len(result)
    print(f"\n📊 필터링 결과: 전체 {total}개 중 {excluded_count}개 제외 → 최종 {passed}개 통과\n")

    return result


def print_results(items: list[dict]) -> None:
    """
    수집된 상품 목록을 터미널에 보기 좋게 포맷팅하여 출력하는 함수.

    Args:
        items: process_and_filter()가 반환한 정제된 상품 딕셔너리 리스트
    """
    if not items:
        print("표시할 상품이 없습니다.")
        return

    # 헤더 출력
    print("=" * 80)
    print(f"  번개장터 검색 결과: '{SEARCH_KEYWORD}'  (총 {len(items)}개)")
    print("=" * 80)

    for idx, item in enumerate(items, start=1):
        print(f"\n  [{idx:02d}] {item['title']}")
        print(f"       💰 가격       : {item['price_formatted']}")
        print(f"       🕒 등록 시간  : {item['registered_time']}")
        print(f"       🔗 링크       : {item['url']}")
        print(f"       {'─' * 60}")

    print("\n" + "=" * 80)
    print(f"  검색 완료. 총 {len(items)}개 매물 수집됨.")
    print("=" * 80 + "\n")


def main():
    """
    메인 실행 함수.
    API 호출 → 필터링 → 출력 순서로 전체 파이프라인을 실행합니다.
    """
    print("\n" + "=" * 80)
    print("  번개장터 매물 수집 봇 시작")
    print(f"  검색어: {SEARCH_KEYWORD}  |  정렬: {SORT_ORDER}  |  페이지당 {ITEMS_PER_PAGE}개")
    print("=" * 80)

    start_time = time.time()

    # ── STEP 1: API 호출 ──────────────────────────────────────────────────────
    print(f"\n🔍 번개장터 API 요청 중... (키워드: '{SEARCH_KEYWORD}')")
    raw_data = fetch_bunjang_listings(keyword=SEARCH_KEYWORD, page=0)

    if raw_data is None:
        print("\n❌ 데이터를 가져오지 못했습니다.")
        print("   → bunjang_selenium_crawler.py (Selenium 버전)을 실행해 보세요.")
        return

    # ── STEP 2: 파싱 및 1차 필터링 ────────────────────────────────────────────
    print("⚙️  데이터 파싱 및 필터링 처리 중...")
    filtered_items = process_and_filter(raw_data)

    # ── STEP 3: 결과 출력 ─────────────────────────────────────────────────────
    print_results(filtered_items)

    elapsed = time.time() - start_time
    print(f"⏱️  총 실행 시간: {elapsed:.2f}초\n")


# 스크립트 직접 실행 시 main() 함수 호출
if __name__ == "__main__":
    main()
