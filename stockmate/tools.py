import pandas as pd
import yfinance as yf
from langchain_core.tools import tool


@tool
def get_stock_price(ticker: str) -> str:
    """코스피 종목의 실시간(준실시간) 주가를 조회한다.
    ticker는 yfinance 형식이다. 예: 005930.KS (삼성전자)"""
    stock = yf.Ticker(ticker)
    info = stock.fast_info
    return (
        f"현재가: {info['lastPrice']:,.0f}원, "
        f"전일종가: {info['previousClose']:,.0f}원, "
        f"거래량: {info['lastVolume']:,}"
    )


def _safe_info(info, key: str, default: float) -> float:
    try:
        value = info[key]
        return float(value) if value is not None else default
    except Exception:
        return default


def get_stock_stats(ticker: str) -> dict:
    stock = yf.Ticker(ticker)
    info = stock.fast_info

    current = _safe_info(info, "lastPrice", 0.0)
    prev_close = _safe_info(info, "previousClose", current)
    change_pct = ((current - prev_close) / prev_close * 100) if prev_close else 0.0

    return {
        "current_price": round(current),
        "change_pct": round(change_pct, 2),
        "day_high": round(_safe_info(info, "dayHigh", current)),
        "day_low": round(_safe_info(info, "dayLow", current)),
        "year_high": round(_safe_info(info, "yearHigh", current)),
    }


def get_price_history(ticker: str, days: int = 90) -> list[dict]:
    stock = yf.Ticker(ticker)
    hist = stock.history(period=f"{days}d")
    hist = hist.reset_index()[["Date", "Close"]]
    return [
        {"date": row["Date"].strftime("%Y-%m-%d"), "close": float(row["Close"])}
        for _, row in hist.iterrows()
    ]


def get_weekly_chart_data(ticker: str, period: str = "1y") -> list[dict]:
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period, interval="1wk")
    if hist.empty:
        return []
    hist = hist.reset_index()[["Date", "Close"]]
    return [
        {"date": row["Date"].strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 0)}
        for _, row in hist.iterrows()
    ]


@tool
def get_financial_statement(ticker: str) -> str:
    """코스피 종목의 최근 재무제표 핵심 지표(매출, 영업이익, 순이익)를 조회한다.
    예: 005930.KS (삼성전자)"""
    stock = yf.Ticker(ticker)
    financials = stock.financials

    if financials.empty:
        return "해당 종목의 재무제표 데이터를 가져오지 못했습니다 (Yahoo Finance 미제공 종목일 수 있음)."

    latest_col = financials.columns[0]
    target_accounts = ["Total Revenue", "Operating Income", "Net Income"]
    lines = [
        f"{account}: {financials.loc[account, latest_col]:,.0f}"
        for account in target_accounts
        if account in financials.index
    ]

    if not lines:
        return "주요 재무 지표(매출/영업이익/순이익)를 찾을 수 없습니다."

    return f"{latest_col.strftime('%Y년 %m월')} 결산 기준\n" + "\n".join(lines)


@tool
def get_analyst_opinion(ticker: str) -> str:
    """코스피 종목의 애널리스트 목표주가 컨센서스와 투자의견을 조회.
    예: 005930.KS (삼성전자)"""
    stock = yf.Ticker(ticker)
    info = stock.info

    target_mean = info.get("targetMeanPrice")
    if target_mean is None:
        return "해당 종목의 애널리스트 목표주가 컨센서스를 찾지 못했습니다 (Yahoo Finance 미제공 종목일 수 있음)."

    lines = [f"평균 목표주가: {target_mean:,.0f}원"]
    if info.get("targetHighPrice") is not None:
        lines.append(f"최고 목표주가: {info['targetHighPrice']:,.0f}원")
    if info.get("targetLowPrice") is not None:
        lines.append(f"최저 목표주가: {info['targetLowPrice']:,.0f}원")
    if info.get("recommendationKey") is not None:
        lines.append(f"투자의견: {info['recommendationKey']}")
    if info.get("numberOfAnalystOpinions") is not None:
        lines.append(f"분석 참여 애널리스트 수: {info['numberOfAnalystOpinions']}명")

    return "\n".join(lines)


@tool
def get_dividend_info(ticker: str) -> str:
    """코스피 종목의 최근 배당 이력과 최근 1년 배당수익률(추정치)을 조회한다.
    예: 005930.KS (삼성전자)"""
    stock = yf.Ticker(ticker)
    dividends = stock.dividends

    if dividends.empty:
        return "해당 종목은 최근 배당 이력이 없습니다 (무배당 종목이거나 Yahoo Finance 미제공일 수 있음)."

    last_date = dividends.index[-1]
    last_amount = float(dividends.iloc[-1])

    one_year_ago = dividends.index[-1] - pd.Timedelta(days=365)
    trailing_total = float(dividends[dividends.index > one_year_ago].sum())

    current_price = _safe_info(stock.fast_info, "lastPrice", 0.0)
    yield_pct = (trailing_total / current_price * 100) if current_price else 0.0

    return (
        f"최근 배당: {last_date.strftime('%Y-%m-%d')}, 주당 {last_amount:,.0f}원\n"
        f"최근 1년 배당수익률(추정): {yield_pct:.2f}% "
        f"(최근 1년 배당 합계 {trailing_total:,.0f}원 기준)"
    )


@tool
def get_technical_signal(ticker: str) -> str:
    """코스피 종목의 5일/20일 이동평균선 배열과 최근 골든크로스·데드크로스 발생
    여부를 조회한다. 예: 005930.KS (삼성전자)"""
    history = get_price_history(ticker, days=120)
    if len(history) < 21:
        return "이동평균선을 계산하기에 데이터가 부족합니다."

    df = pd.DataFrame(history)
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df = df.dropna(subset=["ma5", "ma20"]).reset_index(drop=True)

    if len(df) < 2:
        return "이동평균선을 계산하기에 데이터가 부족합니다."

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    position = "5일선이 20일선 위" if latest["ma5"] > latest["ma20"] else "5일선이 20일선 아래"

    cross = "최근 크로스 없음"
    if prev["ma5"] <= prev["ma20"] and latest["ma5"] > latest["ma20"]:
        cross = f"{latest['date']} 골든크로스 발생(단기 상승 전환으로 해석되기도 함)"
    elif prev["ma5"] >= prev["ma20"] and latest["ma5"] < latest["ma20"]:
        cross = f"{latest['date']} 데드크로스 발생(단기 하락 전환으로 해석되기도 함)"

    return (
        f"현재 이동평균선 배열: {position} "
        f"(5일선 {latest['ma5']:,.0f}원, 20일선 {latest['ma20']:,.0f}원)\n"
        f"{cross}"
    )
