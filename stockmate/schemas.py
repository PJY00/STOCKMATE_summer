from typing import Annotated, Literal, Optional, TypedDict

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    route: Literal[
        "price", "news", "financial", "cause_analysis", "opinion", "comparison",
        "followup", "unknown",
    ] = Field(
        description=(
            "price=현재 시세/목표주가/배당/이동평균선 등 시세·시장 데이터, "
            "news=최신 이슈, financial=재무제표, "
            "cause_analysis=특정 시점 급락/급등 원인 분석, "
            "opinion=지금 사도 될지/투자 판단을 묻는 질문, "
            "comparison=두 코스피 종목의 시세/특징을 비교하는 질문, "
            "followup=새로운 정보 조회 없이 직전 답변을 더 자세히/쉽게/다시 "
            "설명해달라는 질문, "
            "unknown=이 서비스가 다루는 코스피 종목 관련 질문이 아니거나 "
            "위 7가지 중 어디에도 해당하지 않는 질문 중 하나"
        )
    )
    company_name: Optional[str] = Field(
        default=None,
        description="이번 질문에서 새로 언급된 종목명. 이전 종목을 가리키면 None",
    )
    compare_company_name: Optional[str] = Field(
        default=None,
        description=(
            "route가 comparison일 때만 사용. 비교 대상이 되는 두 번째 종목명. "
            "그 외 route에서는 항상 None"
        ),
    )


class RelevanceCheck(BaseModel):
    is_relevant: bool
    reason: str


class InvestmentOpinion(BaseModel):
    positive_factors: list[str]
    risk_factors: list[str]
    disclaimer: str = "본 내용은 정보 제공 목적이며, 투자 판단과 책임은 본인에게 있습니다."


class ComparisonFactors(BaseModel):
    company_a_factors: list[str]
    company_b_factors: list[str]
    disclaimer: str = (
        "본 내용은 정보 제공 목적이며, 특정 종목의 매수를 권유하지 않습니다. "
        "투자 판단과 책임은 본인에게 있습니다."
    )


class NewsRAGState(TypedDict, total=False):
    query: str
    date_range: Optional[tuple]
    retry_count: int
    documents: list
    relevant_documents: list
    answer: str


class State(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    route: Optional[str]
    active_ticker: Optional[str]
    active_company_name: Optional[str]
    compare_ticker: Optional[str]
    compare_company_name: Optional[str]
    price_history: Optional[list]
    drop_detected: Optional[bool]
    drop_date: Optional[str]
    drop_pct: Optional[float]
    final_response: Optional[dict]
