from langgraph.graph import END, START, StateGraph

from app.rag.generation.context import build_context, validate_answer
from app.rag.generation.types import Answer, GraphState


def build_standard(settings, retriever, provider):
    async def event(config, name, data):
        await config["configurable"]["emit"](name, data)

    async def retrieve(state, config):
        await event(config, "stage", {"stage": "retrieving"})
        chunks = await retriever.retrieve(
            state["query"], owner_id=state["owner_id"], top_k=state["top_k"]
        )
        return {"chunks": chunks}

    async def prepare(state, config):
        await event(config, "stage", {"stage": "preparing_context"})
        messages, sources = build_context(state["query"], state["chunks"], settings)
        await event(config, "sources", {"sources": [s.model_dump() for s in sources]})
        return {"messages": messages, "sources": sources}

    async def generate(state, config):
        await event(config, "stage", {"stage": "generating"})
        result = await provider.generate(
            state["messages"], config["configurable"]["emit"]
        )
        return {"result": result}

    async def validate(state, config):
        await event(config, "stage", {"stage": "validating"})
        status, text, sources = validate_answer(state["result"], state["sources"])
        return {
            "answer": Answer(
                request_id=state["request_id"],
                status=status,
                answer=text,
                sources=sources,
                provider=state["result"].provider or settings.RAG_LLM_PROVIDER,
                model=state["result"].model or settings.model,
                usage=state["result"].usage,
            )
        }

    async def abstain(state):
        return {
            "answer": Answer(
                request_id=state["request_id"],
                status="insufficient_context",
                answer="The available documents do not provide enough information.",
                sources=[],
                provider=settings.RAG_LLM_PROVIDER,
                model=settings.model,
            )
        }

    graph = StateGraph(GraphState)
    for name, node in [
        ("retrieve", retrieve),
        ("prepare", prepare),
        ("generate", generate),
        ("validate", validate),
        ("abstain", abstain),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "prepare")
    graph.add_conditional_edges(
        "prepare",
        lambda s: "generate" if s["sources"] else "abstain",
        {"generate": "generate", "abstain": "abstain"},
    )
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", END)
    graph.add_edge("abstain", END)
    return graph.compile()
