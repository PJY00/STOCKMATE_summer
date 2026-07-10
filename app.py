from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from stockmate.graph import graph
from stockmate.tickers import TICKER_MAP, resolve_ticker
from stockmate.tools import get_stock_stats, get_weekly_chart_data

app = FastAPI(title="StockMate")
app.mount("/static", StaticFiles(directory="static"), name="static")


class ChatRequest(BaseModel):
    message: str
    thread_id: str


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    company_name: Optional[str] = None
    chart: Optional[list[dict]] = None


class SearchRequest(BaseModel):
    company_name: str
    thread_id: str


class StockStats(BaseModel):
    current_price: float
    change_pct: float
    day_high: float
    day_low: float
    year_high: float


class SearchResponse(BaseModel):
    ticker: str
    company_name: str
    stats: StockStats
    chart: list[dict]


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/graph/mermaid")
def graph_mermaid():
    return {"mermaid": graph.get_graph().draw_mermaid()}


@app.get("/tickers")
def list_tickers():
    return {
        "tickers": [
            {"name": name, "code": ticker.replace(".KS", "")}
            for name, ticker in sorted(TICKER_MAP.items())
        ]
    }


@app.post("/search", response_model=SearchResponse)
def search_stock(req: SearchRequest):
    ticker = resolve_ticker(req.company_name)
    if not ticker:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{req.company_name}'을(를) 코스피 종목 목록에서 찾지 못했습니다. "
                "검색창의 자동완성 목록에서 정확한 종목명을 선택해 주세요."
            ),
        )

    try:
        stats = get_stock_stats(ticker)
        chart_data = get_weekly_chart_data(ticker)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="시세 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )

    config = {"configurable": {"thread_id": req.thread_id}}
    graph.update_state(
        config, {"active_ticker": ticker, "active_company_name": req.company_name}
    )

    return SearchResponse(
        ticker=ticker,
        company_name=req.company_name,
        stats=StockStats(**stats),
        chart=chart_data,
    )


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    try:
        result = graph.invoke({"messages": [HumanMessage(content=req.message)]}, config=config)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )

    ticker = result.get("active_ticker")
    chart_data = None
    if ticker:
        try:
            chart_data = get_weekly_chart_data(ticker)
        except Exception:
            chart_data = None

    return ChatResponse(
        response=result["messages"][-1].content,
        thread_id=req.thread_id,
        company_name=result.get("active_company_name"),
        chart=chart_data or None,
    )


if __name__ == "__main__":
    uvicorn.run("App:app", host="127.0.0.1", port=8000, reload=True)
