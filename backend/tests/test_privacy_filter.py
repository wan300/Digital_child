import pytest

from app.models.entities import Persona
from app.schemas.api import MemoryCandidate
from app.services.privacy_filter import PrivacyFilter


def test_authorized_real_person_requires_consent() -> None:
    persona = Persona(name="Real", persona_type="authorized_real_persona", consent_confirmed=False)
    with pytest.raises(ValueError):
        PrivacyFilter().validate_persona(persona)


def test_sensitive_candidate_is_forced_pending() -> None:
    candidate = MemoryCandidate(
        content="用户的 API key 是 secret-token",
        subject="human:test",
        decision="approved",
    )
    filtered = PrivacyFilter().filter_candidate(candidate)
    assert filtered.sensitivity == "sensitive"
    assert filtered.decision == "pending"
