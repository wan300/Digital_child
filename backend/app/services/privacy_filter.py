from __future__ import annotations

from app.models.entities import Persona
from app.schemas.api import MemoryCandidate


class PrivacyFilter:
    sensitive_keywords = (
        "身份证",
        "护照",
        "手机号",
        "电话号码",
        "家庭住址",
        "银行卡",
        "密码",
        "密钥",
        "api key",
        "secret",
        "token",
        "address",
        "phone",
        "passport",
    )

    def validate_persona(self, persona: Persona) -> None:
        if persona.persona_type == "authorized_real_persona" and not persona.consent_confirmed:
            raise ValueError("真实人物人格必须确认 consent_confirmed 后才能初始化和聊天。")
        if persona.persona_type not in {"fictional_persona", "authorized_real_persona"}:
            raise ValueError("第一版只支持 fictional_persona 和 authorized_real_persona。")

    def classify_sensitivity(self, text: str) -> str:
        lowered = text.lower()
        if any(keyword in lowered for keyword in self.sensitive_keywords):
            return "sensitive"
        return "normal"

    def filter_candidate(self, candidate: MemoryCandidate) -> MemoryCandidate:
        sensitivity = self.classify_sensitivity(candidate.content)
        decision = "pending" if sensitivity == "sensitive" else candidate.decision
        return candidate.model_copy(update={"sensitivity": sensitivity, "decision": decision})
