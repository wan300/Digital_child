from app.services.retrieval_router import RetrievalRouter


def test_document_queries_use_all_sources() -> None:
    route = RetrievalRouter().route("你在哪篇日记里提到过公开演讲？")
    assert route.use_mem0 is True
    assert route.use_graphiti is True
    assert route.use_lightrag is True


def test_timeline_queries_use_graphiti_without_documents() -> None:
    route = RetrievalRouter().route("我们什么时候聊过这个计划？")
    assert route.use_mem0 is True
    assert route.use_graphiti is True
    assert route.use_lightrag is False


def test_preference_queries_use_long_term_memory() -> None:
    route = RetrievalRouter().route("我喜欢什么样的回答？")
    assert route.use_mem0 is True
    assert route.use_graphiti is False
    assert route.use_lightrag is False
