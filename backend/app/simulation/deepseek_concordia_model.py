from __future__ import annotations

import os
from collections.abc import Collection
from typing import override

import openai
from concordia.contrib.language_models.openai.base_gpt_model import BaseGPTModel
from concordia.language_model import language_model
from concordia.utils import measurements as measurements_lib

DEEPSEEK_REASONING_EFFORT = "xhigh"


class DeepSeekGptLanguageModel(BaseGPTModel):
    """Concordia OpenAI-compatible model tuned for DeepSeek reasoning APIs.

    Concordia's stock OpenAI wrapper sends reasoning_effort="minimal" for
    sample_text. DeepSeek's reasoning API rejects that value, while accepting
    xhigh/ high / medium / low / max. Keep the rest of BaseGPTModel behavior,
    including sample_choice's existing medium effort path.
    """

    def __init__(
        self,
        model_name: str,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        measurements: measurements_lib.Measurements | None = None,
        channel: str = language_model.DEFAULT_STATS_CHANNEL,
    ):
        if api_key is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY not found. Please provide it via the api_key "
                    "parameter or set the OPENAI_API_KEY environment variable."
                )
        self._api_key = api_key
        client = openai.OpenAI(api_key=self._api_key, base_url=api_base)
        super().__init__(model_name=model_name, client=client, measurements=measurements, channel=channel)

    @override
    def sample_text(
        self,
        prompt: str,
        *,
        max_tokens: int = language_model.DEFAULT_MAX_TOKENS,
        terminators: Collection[str] = language_model.DEFAULT_TERMINATORS,
        temperature: float = 1.0,
        top_p: float = language_model.DEFAULT_TOP_P,
        top_k: int = language_model.DEFAULT_TOP_K,
        timeout: float = language_model.DEFAULT_TIMEOUT_SECONDS,
        seed: int | None = None,
    ) -> str:
        del top_k
        return self._sample_text(
            prompt=prompt,
            reasoning_effort=DEEPSEEK_REASONING_EFFORT,
            verbosity=self._verbosity,
            max_tokens=max_tokens,
            terminators=terminators,
            temperature=temperature,
            top_p=top_p,
            timeout=timeout,
            seed=seed,
        )
