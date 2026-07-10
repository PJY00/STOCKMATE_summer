from io import StringIO
from pathlib import Path
from typing import Optional
import json

import pandas as pd
import requests

_TICKER_CACHE_PATH = Path("kospi_tickers_cache.json")

_FALLBACK_TICKER_MAP: dict[str, str] = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "LG에너지솔루션": "373220.KS",
    "삼성바이오로직스": "207940.KS",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "POSCO홀딩스": "005490.KS",
    "LG화학": "051910.KS",
    "삼성SDI": "006400.KS",
    "네이버": "035420.KS",
    "카카오": "035720.KS",
    "KB금융": "105560.KS",
    "신한지주": "055550.KS",
    "하나금융지주": "086790.KS",
    "삼성화재": "000810.KS",
    "삼성생명": "032830.KS",
    "현대모비스": "012330.KS",
    "SK이노베이션": "096770.KS",
    "SK텔레콤": "017670.KS",
    "KT": "030200.KS",
    "한국전력": "015760.KS",
    "삼성전기": "009150.KS",
    "삼성에스디에스": "018260.KS",
    "HMM": "011200.KS",
    "고려아연": "010130.KS",
    "삼성물산": "028260.KS",
    "LG전자": "066570.KS",
    "LG": "003550.KS",
    "엔씨소프트": "036570.KS",
    "넷마블": "251270.KS",
    "S-Oil": "010950.KS",
    "기업은행": "024110.KS",
    "LG유플러스": "032640.KS",
    "LG이노텍": "011070.KS",
    "SK": "034730.KS",
}


def _fetch_kospi_listing_from_kind() -> dict[str, str]:
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do"
    params = {"method": "download", "marketType": "stockMkt", "searchType": "13"}
    resp = requests.get(url, params=params, timeout=15)
    resp.encoding = "euc-kr"

    df = pd.read_html(StringIO(resp.text), header=0)[0]

    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        name = str(row["회사명"]).strip()
        code = str(row["종목코드"]).zfill(6)
        mapping[name] = f"{code}.KS"
    return mapping


def _build_ticker_map() -> dict[str, str]:
    if _TICKER_CACHE_PATH.exists():
        try:
            cached = json.loads(_TICKER_CACHE_PATH.read_text(encoding="utf-8"))
            if cached:
                return cached
        except Exception:
            pass

    try:
        mapping = _fetch_kospi_listing_from_kind()
        if mapping:
            _TICKER_CACHE_PATH.write_text(
                json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[StockMate] KIND에서 코스피 {len(mapping)}개 종목 매핑 완료 (캐시 저장)")
            return mapping
    except Exception as e:
        print(
            f"[StockMate] KIND 종목 목록 조회 실패, 폴백 목록"
            f"({len(_FALLBACK_TICKER_MAP)}개) 사용: {e}"
        )

    return dict(_FALLBACK_TICKER_MAP)


TICKER_MAP: dict[str, str] = _build_ticker_map()


def resolve_ticker(company_name: str) -> Optional[str]:
    return TICKER_MAP.get(company_name)
