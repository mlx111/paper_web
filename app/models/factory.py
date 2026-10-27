from typing import Any

from core.http_client_factory import create_llm_async_http_client, create_llm_http_client
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class UniversalChatOpenAI(ChatOpenAI):
    """OpenAI-compatible transport with optional thinking metadata support.

    Most providers use the same chat-completions protocol.  Thinking providers
    such as DeepSeek additionally require the assistant's ``reasoning_content``
    to be sent back on subsequent turns.  The flag is provider-configured and
    defaults to true for custom OpenAI-compatible endpoints.
    """

    provider: str = "custom"
    preserve_reasoning_content: bool = True

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if not self.preserve_reasoning_content or "messages" not in payload:
            return payload
        for source, target in zip(messages, payload["messages"], strict=False):
            if isinstance(source, AIMessage):
                if "reasoning_content" in source.additional_kwargs:
                    target["reasoning_content"] = source.additional_kwargs["reasoning_content"]
        return payload

    def _create_chat_result(self, response: Any, generation_info: dict | None = None):
        result = super()._create_chat_result(response, generation_info)
        if not self.preserve_reasoning_content:
            return result
        response_dict = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, response_dict.get("choices") or [], strict=False):
            message = generation.message
            raw_message = choice.get("message") or {}
            if "reasoning_content" in raw_message and isinstance(message, AIMessage):
                message.additional_kwargs["reasoning_content"] = raw_message["reasoning_content"]
        return result

    def _convert_chunk_to_generation_chunk(self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None):
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if self.preserve_reasoning_content and generation_chunk is not None:
            choices = chunk.get("choices") or []
            delta = choices[0].get("delta") if choices else None
            if isinstance(delta, dict) and "reasoning_content" in delta:
                generation_chunk.message.additional_kwargs["reasoning_content"] = delta["reasoning_content"]
        return generation_chunk


class UniversalModelFactory:
    """Create the common transport from the active provider configuration."""

    @staticmethod
    def _preserves_reasoning(provider: str) -> bool:
        # These OpenAI-compatible services can expose a reasoning_content
        # extension. The field is sent only when a prior reply contains it.
        return provider in {"deepseek", "dashscope", "moonshot", "zhipu", "custom"}

    @staticmethod
    def _temperature_params(model: str, temperature: float) -> dict[str, float]:
        # OpenAI reasoning families currently reject a custom temperature.
        name = model.lower()
        if name.startswith(("gpt-5", "o1", "o3", "o4")):
            return {}
        return {"temperature": temperature}

    def init_model(self, streaming: bool, model: str | None = None, temperature: float = 0.7):
        from services.llm_config_service import llm_config_service

        params = llm_config_service.get_active_params()
        use_model = model or params["model"]
        return UniversalChatOpenAI(
            model=use_model,
            provider=params["provider"],
            preserve_reasoning_content=self._preserves_reasoning(params["provider"]),
            api_key=SecretStr(params["api_key"] or "not-configured"),
            base_url=params["base_url"],
            **self._temperature_params(use_model, temperature),
            streaming=streaming,
            use_responses_api=False,
            http_client=create_llm_http_client(),
            http_async_client=create_llm_async_http_client(),
        )

qwen_model = UniversalModelFactory()
