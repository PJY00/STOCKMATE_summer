from langchain.chat_models import init_chat_model

from stockmate.schemas import RouteDecision
from stockmate.tickers import resolve_ticker

ROUTER_PROMPT = """이 서비스(StockMate)는 코스피 상장 종목에 관한 아래 7가지 질문만
처리한다. 사용자의 최신 질문을 다음 8가지 중 하나로 분류하세요.

- price: 현재 시세, 애널리스트 목표주가/투자의견, 배당(배당수익률/배당이력),
  이동평균선(골든크로스/데드크로스) 등 종목의 시세·시장 데이터를 묻는 질문
- news: 최신 이슈/뉴스를 묻는 질문 (기간 제한 없음)
- financial: 재무제표/실적(매출, 영업이익, 순이익)을 묻는 질문
- cause_analysis: 특정 시점의 급락/급등 "원인"을 묻는 질문
- opinion: "지금 사도 될까", "매수 어때", "투자 의견" 처럼 투자 판단 자체를 묻는 질문
  (원인/이유를 묻는 게 아니라 "지금 행동을 취해도 되는지"를 묻는 경우 이쪽으로 분류)
- comparison: 두 종목을 비교하는 질문 ("A랑 B 중에 뭐가 나아?", "A랑 B 비교해줘",
  "지금 종목이랑 SK하이닉스랑 비교해줘"). 종목이 하나만 언급됐다면 comparison이
  아니라 다른 카테고리로 분류하세요.
- followup: 새로운 정보 조회가 필요 없이 "직전 AI 답변"을 더 자세히/쉽게/다시
  설명해달라는 질문. 예: "더 자세히 설명해줘", "무슨 말이야", "쉽게 설명해줘",
  "왜 그런거야", "방금 그거 다시 말해줘". 새로운 종목명이나 새로운 조회 대상이
  언급되면 followup이 아니라 해당 카테고리로 분류하세요.
- unknown: 위 7가지 중 어디에도 해당하지 않는 모든 질문. 예를 들어
  - 특정 코스피 종목과 무관한 잡담, 인사, 서비스 사용법 질문
  - 코스피 전체 지수/시장 동향처럼 "개별 종목"이 아닌 질문
  - 부동산, 코인, 해외주식 등 이 서비스가 다루지 않는 자산에 대한 질문
  판단이 애매하면 무리해서 7가지에 끼워 맞추지 말고 unknown으로 분류하세요.

또한 이번 질문에서 새로운 종목명이 언급되었다면 company_name에 담고,
"저 기간", "그거"처럼 이전 종목을 가리키는 질문이면 company_name은 비워두세요.
followup으로 분류했다면 company_name은 항상 비워두세요(직전 종목 맥락을 그대로
유지합니다).

comparison으로 분류했다면 아래 규칙을 반드시 지키세요.
- 이번 질문에서 종목명이 2개 모두 명시적으로 언급됐다면(예: "삼성전자랑
  SK하이닉스 비교해줘"), 첫 번째 종목명은 company_name에, 두 번째(비교 대상)
  종목명은 compare_company_name에 각각 담으세요.
- 이번 질문에서 명시적으로 언급된 종목명이 1개뿐이고 나머지는 "이거",
  "이 종목", "지금 종목"처럼 이미 보고 있는 종목을 가리킨다면(예: "이거
  삼성전자랑 비교해줘"), company_name은 반드시 비워두고(None) 그 언급된
  종목명 하나만 compare_company_name에 담으세요. company_name과
  compare_company_name에 같은 종목명을 동시에 채우지 마세요.
- comparison이 아닌 route에서는 compare_company_name을 항상 비워두세요.

대화 이력:
{history}
"""


def router_node(state: dict) -> dict:
    llm = init_chat_model("openai:gpt-4o-mini", temperature=0)
    history_text = "\n".join(f"{m.type}: {m.content}" for m in state["messages"][-6:])
    decision = llm.with_structured_output(RouteDecision).invoke(
        ROUTER_PROMPT.format(history=history_text)
    )

    if decision.route == "comparison" and decision.company_name and decision.compare_company_name:
        _ticker_a = resolve_ticker(decision.company_name)
        _ticker_b = resolve_ticker(decision.compare_company_name)
        if _ticker_a is not None and _ticker_a == _ticker_b:
            decision.company_name = None

    updates: dict = {"route": decision.route}

    if decision.company_name:
        ticker = resolve_ticker(decision.company_name)
        if ticker:
            updates["active_ticker"] = ticker
            updates["active_company_name"] = decision.company_name
        else:
            updates["route"] = "unsupported"
            updates["final_response"] = {
                "type": "unsupported",
                "summary": (
                    f"'{decision.company_name}'을(를) 코스피 종목 목록에서 찾지 못했습니다. "
                    "정확한 상장사명으로 다시 검색해 주세요 (예: '삼성전자', 'SK하이닉스')."
                ),
            }

    if updates["route"] == "comparison":
        if decision.compare_company_name:
            compare_ticker = resolve_ticker(decision.compare_company_name)
            if compare_ticker:
                updates["compare_ticker"] = compare_ticker
                updates["compare_company_name"] = decision.compare_company_name
            else:
                updates["route"] = "unsupported"
                updates["final_response"] = {
                    "type": "unsupported",
                    "summary": (
                        f"'{decision.compare_company_name}'을(를) 코스피 종목 목록에서 "
                        "찾지 못했습니다. 정확한 상장사명으로 다시 검색해 주세요."
                    ),
                }
        else:
            updates["route"] = "unknown"
            updates["final_response"] = {
                "type": "unknown",
                "summary": (
                    "비교하실 두 번째 종목명을 함께 말씀해 주세요. "
                    "예: '삼성전자랑 SK하이닉스 비교해줘'"
                ),
            }

    return updates


def route_selector(state: dict) -> str:
    return state["route"]
