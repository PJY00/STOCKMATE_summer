from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_tavily import TavilySearch
from langgraph.graph import END, START, StateGraph

from stockmate.schemas import NewsRAGState, RelevanceCheck

MAX_RAG_RETRIES = 2


def collect_news(state: NewsRAGState) -> dict:
    search = TavilySearch(max_results=8)
    search_query = state["query"]
    if state.get("date_range"):
        start, end = state["date_range"]
        search_query = f"{search_query} {start}~{end}"
    results = search.invoke({"query": search_query})
    docs = [
        Document(page_content=r["content"], metadata={"url": r.get("url", "")})
        for r in results.get("results", [])
    ]
    return {"documents": docs}


def grade_relevance(state: NewsRAGState) -> dict:
    llm = init_chat_model("openai:gpt-4o-mini", temperature=0)
    checker = llm.with_structured_output(RelevanceCheck)
    relevant = []
    for doc in state["documents"]:
        result = checker.invoke(
            f"질문: {state['query']}\n\n문서: {doc.page_content[:1000]}\n\n"
            "이 문서가 질문에 답하는 데 실제로 관련 있는지 판단하세요."
        )
        if result.is_relevant:
            relevant.append(doc)
    return {"relevant_documents": relevant}


def should_retry(state: NewsRAGState) -> str:
    if len(state["relevant_documents"]) >= 2:
        return "synthesize"
    if state["retry_count"] >= MAX_RAG_RETRIES:
        return "synthesize"
    return "rewrite_query"


def rewrite_query(state: NewsRAGState) -> dict:
    llm = init_chat_model("openai:gpt-4o-mini", temperature=0.3)
    new_query = llm.invoke(
        f"다음 검색 쿼리로 관련 뉴스를 충분히 찾지 못했습니다: '{state['query']}'\n"
        "더 구체적이거나 다른 키워드 조합의 검색 쿼리 1개를 새로 제안하세요. 쿼리만 출력하세요."
    ).content
    return {"query": new_query.strip(), "retry_count": state["retry_count"] + 1}


def synthesize(state: NewsRAGState) -> dict:
    if not state["relevant_documents"]:
        return {"answer": "관련 뉴스를 찾지 못했습니다."}
    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents(state["relevant_documents"], embeddings)
    top_docs = vectorstore.as_retriever(search_kwargs={"k": 3}).invoke(state["query"])
    context = "\n\n".join(d.page_content for d in top_docs)
    llm = init_chat_model("openai:gpt-4o-mini", temperature=0)
    answer = llm.invoke(
        f"다음 뉴스 내용을 바탕으로 질문에 답하세요.\n\n질문: {state['query']}\n\n뉴스:\n{context}"
    ).content
    return {"answer": answer}


def _build_news_rag_graph():
    builder = StateGraph(NewsRAGState)
    builder.add_node("collect_news", collect_news)
    builder.add_node("grade_relevance", grade_relevance)
    builder.add_node("rewrite_query", rewrite_query)
    builder.add_node("synthesize", synthesize)
    builder.add_edge(START, "collect_news")
    builder.add_edge("collect_news", "grade_relevance")
    builder.add_conditional_edges(
        "grade_relevance", should_retry, {"synthesize": "synthesize", "rewrite_query": "rewrite_query"}
    )
    builder.add_edge("rewrite_query", "collect_news")
    builder.add_edge("synthesize", END)
    return builder.compile()


_news_rag_graph = _build_news_rag_graph()


def run_news_rag(query: str, date_range: Optional[tuple] = None) -> str:
    result = _news_rag_graph.invoke(
        {"query": query, "date_range": date_range, "retry_count": 0, "documents": [], "relevant_documents": []}
    )
    return result["answer"]
