from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware, ToolRetryMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from stockmate.news_rag import run_news_rag
from stockmate.router import route_selector, router_node
from stockmate.schemas import ComparisonFactors, InvestmentOpinion, State
from stockmate.tools import (
    get_analyst_opinion,
    get_dividend_info,
    get_financial_statement,
    get_price_history,
    get_stock_price,
    get_stock_stats,
    get_technical_signal,
)

tool_agent = create_agent(
    model=init_chat_model("openai:gpt-4o-mini"),
    tools=[
        get_stock_price,
        get_financial_statement,
        get_analyst_opinion,
        get_dividend_info,
        get_technical_signal,
    ],
    middleware=[
        ToolRetryMiddleware(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=1.0,
            retry_on=(ConnectionError, TimeoutError),
            on_failure="continue",
        ),
        ToolCallLimitMiddleware(run_limit=5),
    ],
)


def run_tool_agent(state: dict) -> dict:
    context = SystemMessage(
        content=(
            f"현재 대화의 대상 종목: {state.get('active_company_name', '미지정')} "
            f"(yfinance ticker: {state.get('active_ticker', '미지정')})"
        )
    )
    result = tool_agent.invoke({"messages": [context] + state["messages"]})
    return {"messages": result["messages"]}


DROP_THRESHOLD = -0.05
LOOKBACK_DAYS = 90


def fetch_price_history_node(state: dict) -> dict:
    ticker = state.get("active_ticker")
    if not ticker:
        return {"price_history": []}
    return {"price_history": get_price_history(ticker, days=LOOKBACK_DAYS)}


def detect_drop_node(state: dict) -> dict:
    history = state.get("price_history", [])
    if len(history) < 2:
        return {"drop_detected": False}
    df = pd.DataFrame(history)
    df["pct_change"] = df["close"].pct_change()
    worst = df.loc[df["pct_change"].idxmin()]
    if worst["pct_change"] < DROP_THRESHOLD:
        return {
            "drop_detected": True,
            "drop_date": str(worst["date"]),
            "drop_pct": round(float(worst["pct_change"]) * 100, 2),
        }
    return {"drop_detected": False}


def route_after_drop_detection(state: dict) -> str:
    return "news_lookup" if state.get("drop_detected") else "no_drop_response"


def cause_news_lookup_node(state: dict) -> dict:
    drop_date = datetime.strptime(state["drop_date"], "%Y-%m-%d")
    start = (drop_date - timedelta(days=3)).strftime("%Y-%m-%d")
    end = (drop_date + timedelta(days=3)).strftime("%Y-%m-%d")
    company = state.get("active_company_name", "")
    answer = run_news_rag(f"{company} 주가 하락 원인", date_range=(start, end))
    summary = (
        f"{company} 주가는 {state['drop_date']}에 {state['drop_pct']}% 하락했습니다.\n\n"
        f"관련 뉴스 분석:\n{answer}"
    )
    return {"final_response": {"type": "cause_analysis", "summary": summary}}


def no_drop_response_node(state: dict) -> dict:
    company = state.get("active_company_name", "")
    summary = f"{company}의 최근 {LOOKBACK_DAYS}일간 데이터에서 특이한 급락은 확인되지 않았습니다."
    return {"final_response": {"type": "cause_analysis", "summary": summary}}


def news_node(state: dict) -> dict:
    company = state.get("active_company_name")
    query = state["messages"][-1].content
    search_query = f"{company} {query}" if company else query
    answer = run_news_rag(search_query)
    return {"final_response": {"type": "news", "summary": answer}}


def opinion_node(state: dict) -> dict:
    ticker = state.get("active_ticker")
    company = state.get("active_company_name", "종목 미지정")

    price_summary = "정보 없음"
    if ticker:
        try:
            price_summary = get_stock_price.invoke({"ticker": ticker})
        except Exception:
            pass

    drop_summary = "최근 특이 급락 이력 없음"
    if state.get("drop_detected"):
        drop_summary = f"{state.get('drop_date')}에 {state.get('drop_pct')}% 하락한 이력이 있음"

    llm = init_chat_model("openai:gpt-4o-mini", temperature=0)
    prompt = f"""당신은 투자 자문업자가 아닌 정보 제공 도구입니다.
'사세요/파세요' 식의 결론을 내리지 마세요. 아래 맥락을 바탕으로
긍정 요인과 리스크 요인을 각각 2~3개씩 균형 있게 정리하세요.

종목: {company}
현재 시세: {price_summary}
최근 급락 이력: {drop_summary}
"""
    opinion = llm.with_structured_output(InvestmentOpinion).invoke(prompt)

    positive = "\n".join(f"- {p}" for p in opinion.positive_factors)
    risk = "\n".join(f"- {r}" for r in opinion.risk_factors)
    summary = (
        f"[{company}] 투자 판단에 참고할 만한 요인을 정리했습니다.\n\n"
        f"긍정 요인:\n{positive}\n\n"
        f"리스크 요인:\n{risk}\n\n"
        f"{opinion.disclaimer}"
    )
    return {"final_response": {"type": "opinion", "summary": summary}}


def _comparison_stats_line(ticker: Optional[str]) -> str:
    if not ticker:
        return "정보 없음"
    try:
        stats = get_stock_stats(ticker)
        return (
            f"현재가 {stats['current_price']:,}원 "
            f"(전일대비 {stats['change_pct']:+.2f}%), 52주최고 {stats['year_high']:,}원"
        )
    except Exception:
        return "시세 정보를 가져오지 못했습니다."


def comparison_node(state: dict) -> dict:
    ticker_a = state.get("active_ticker")
    company_a = state.get("active_company_name", "종목 A")
    ticker_b = state.get("compare_ticker")
    company_b = state.get("compare_company_name", "종목 B")

    stats_a = _comparison_stats_line(ticker_a)
    stats_b = _comparison_stats_line(ticker_b)

    llm = init_chat_model("openai:gpt-4o-mini", temperature=0)
    prompt = f"""당신은 투자 자문업자가 아닌 정보 제공 도구입니다.
두 종목 중 어느 쪽을 사라고 결론 내리지 마세요. '1주당 가격이 더 싸다/비싸다'만을
근거로 저평가·고평가나 매수 우선순위를 판단하는 서술도 금지합니다(액면가·유통주식수
차이일 뿐 실제 가치와는 무관합니다). 아래 두 종목의 시세를 참고해서 각 종목의
긍정 요인과 리스크 요인을 2~3개씩 정리하세요.

[{company_a}] {stats_a}
[{company_b}] {stats_b}
"""
    comparison = llm.with_structured_output(ComparisonFactors).invoke(prompt)

    factors_a = "\n".join(f"- {f}" for f in comparison.company_a_factors)
    factors_b = "\n".join(f"- {f}" for f in comparison.company_b_factors)
    summary = (
        f"[{company_a}] vs [{company_b}] 비교\n\n"
        f"{company_a}: {stats_a}\n{factors_a}\n\n"
        f"{company_b}: {stats_b}\n{factors_b}\n\n"
        f"{comparison.disclaimer}"
    )
    return {"final_response": {"type": "comparison", "summary": summary}}


def followup_node(state: dict) -> dict:
    last_ai = next(
        (m for m in reversed(state["messages"][:-1]) if isinstance(m, AIMessage)), None
    )
    if last_ai is None:
        summary = "아직 이전 답변이 없습니다. 궁금하신 코스피 종목과 질문을 말씀해 주세요."
        return {"final_response": {"type": "followup", "summary": summary}}

    user_request = state["messages"][-1].content
    llm = init_chat_model("openai:gpt-4o-mini", temperature=0)
    answer = llm.invoke(
        "아래는 방금 사용자에게 준 답변입니다. 새로운 정보를 조사하지 말고, "
        "이 답변에 담긴 내용만 바탕으로 사용자의 요청에 맞게 다시 설명하세요.\n\n"
        f"직전 답변:\n{last_ai.content}\n\n"
        f"사용자의 요청:\n{user_request}"
    ).content
    return {"final_response": {"type": "followup", "summary": answer}}


def wrap_tool_agent_response(state: dict) -> dict:
    last = state["messages"][-1]
    return {"final_response": {"type": state.get("route", "price"), "summary": last.content}}


def unsupported_node(state: dict) -> dict:
    return {}


def unknown_node(state: dict) -> dict:
    summary = (
        "죄송합니다, 이 서비스는 코스피 개별 종목의 "
        "시세 / 최신 뉴스 / 재무제표 / 급락·급등 원인 / 투자 참고 의견 / 종목 간 비교 / "
        "직전 답변에 대한 부연설명, 이 7가지 질문만 답변할 수 있습니다. "
        "궁금한 코스피 종목명과 함께 다시 질문해 주세요."
    )
    return {"final_response": {"type": "unknown", "summary": summary}}


def finalize_response_node(state: dict) -> dict:
    response = state.get("final_response") or {"summary": "죄송합니다, 응답을 생성하지 못했습니다."}
    return {"messages": [AIMessage(content=response["summary"])]}


def build_graph():
    builder = StateGraph(State)

    builder.add_node("router", router_node)
    builder.add_node("tool_agent_node", run_tool_agent)
    builder.add_node("tool_agent_wrap", wrap_tool_agent_response)
    builder.add_node("news_node", news_node)
    builder.add_node("opinion_node", opinion_node)
    builder.add_node("comparison_node", comparison_node)
    builder.add_node("fetch_price_history", fetch_price_history_node)
    builder.add_node("detect_drop", detect_drop_node)
    builder.add_node("cause_news_lookup", cause_news_lookup_node)
    builder.add_node("no_drop_response", no_drop_response_node)
    builder.add_node("unsupported_node", unsupported_node)
    builder.add_node("unknown_node", unknown_node)
    builder.add_node("followup_node", followup_node)
    builder.add_node("finalize_response", finalize_response_node)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        route_selector,
        {
            "price": "tool_agent_node",
            "financial": "tool_agent_node",
            "news": "news_node",
            "cause_analysis": "fetch_price_history",
            "opinion": "opinion_node",
            "comparison": "comparison_node",
            "followup": "followup_node",
            "unsupported": "unsupported_node",
            "unknown": "unknown_node",
        },
    )

    builder.add_edge("tool_agent_node", "tool_agent_wrap")
    builder.add_edge("tool_agent_wrap", "finalize_response")
    builder.add_edge("news_node", "finalize_response")
    builder.add_edge("opinion_node", "finalize_response")
    builder.add_edge("comparison_node", "finalize_response")
    builder.add_edge("followup_node", "finalize_response")
    builder.add_edge("unsupported_node", "finalize_response")
    builder.add_edge("unknown_node", "finalize_response")

    builder.add_edge("fetch_price_history", "detect_drop")
    builder.add_conditional_edges(
        "detect_drop",
        route_after_drop_detection,
        {"news_lookup": "cause_news_lookup", "no_drop_response": "no_drop_response"},
    )
    builder.add_edge("cause_news_lookup", "finalize_response")
    builder.add_edge("no_drop_response", "finalize_response")

    builder.add_edge("finalize_response", END)

    return builder.compile(checkpointer=MemorySaver())


graph = build_graph()
