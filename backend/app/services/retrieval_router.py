from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalRoute:
    use_mem0: bool
    use_graphiti: bool
    use_lightrag: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "use_mem0": self.use_mem0,
            "use_graphiti": self.use_graphiti,
            "use_lightrag": self.use_lightrag,
            "reason": self.reason,
        }


class RetrievalRouter:
    memory_keywords = ("喜欢", "不喜欢", "偏好", "习惯", "目标", "记得", "告诉过", "remember", "prefer", "habit", "goal")
    time_keywords = ("什么时候", "何时", "哪天", "上次", "过去", "发生", "以前", "timeline", "when", "happen")
    document_keywords = ("哪篇", "文档", "资料", "日记", "访谈", "原文", "引用", "邮件", "document", "diary", "source", "quote")

    def route(self, query: str) -> RetrievalRoute:
        normalized = query.lower()
        wants_memory = any(keyword in normalized for keyword in self.memory_keywords)
        wants_time = any(keyword in normalized for keyword in self.time_keywords)
        wants_docs = any(keyword in normalized for keyword in self.document_keywords)

        if wants_docs:
            return RetrievalRoute(True, True, True, "query asks for source/document-backed evidence")
        if wants_time:
            return RetrievalRoute(True, True, False, "query asks for temporal or relationship context")
        if wants_memory:
            return RetrievalRoute(True, False, False, "query asks for long-term facts or preferences")
        return RetrievalRoute(True, True, False, "default recall uses long-term memory plus recent timeline")
