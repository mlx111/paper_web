"""LLM repair — use the LLM to fix malformed tool arguments.

Sends the tool schema, the bad args, and the validation errors to the LLM,
asking it to return corrected args as JSON. Includes double-validation to
ensure the repaired args pass schema checks before returning.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from .schema_validator import ToolSchema, ArgError


class LLMRepair:
    """LLM-based argument repair for failed tool calls."""

    REPAIR_PROMPT = """You are a parameter repair agent. A tool was called with incorrect arguments. Fix them.

Tool: {tool_name}

Schema:
{schema_description}

Bad arguments: {bad_args}

Validation errors:
{errors}

User's original question (for context): {question}

Return ONLY a JSON object with the corrected arguments. No markdown, no explanation.
Example: {{"query": "transformer attention", "count": 5}}
"""

    def __init__(self, model: Any = None):
        self._model = model

    async def repair(
        self,
        tool_name: str,
        schema: ToolSchema,
        bad_args: dict[str, Any],
        errors: list[ArgError],
        question: str = "",
    ) -> dict[str, Any] | None:
        """Attempt to repair *bad_args* using the LLM.

        Returns corrected args dict if successful, None otherwise.
        """
        if self._model is None:
            logger.warning("LLMRepair: no model available, skipping repair")
            return None

        error_desc = "\n".join(f"  - {e.field}: {e.message}" for e in errors)
        prompt = self.REPAIR_PROMPT.format(
            tool_name=tool_name,
            schema_description=schema.describe(),
            bad_args=json.dumps(bad_args, ensure_ascii=False, default=str),
            errors=error_desc,
            question=question[:200],
        )

        try:
            # Use the model to generate repaired args
            messages = [{"role": "user", "content": prompt}]
            if hasattr(self._model, "ainvoke"):
                response = await self._model.ainvoke(messages)
            elif hasattr(self._model, "agenerate"):
                response = await self._model.agenerate([messages])
                response = response.generations[0][0].text
            else:
                response = self._model.invoke(messages)

            # Extract text content
            content = ""
            if hasattr(response, "content"):
                content = response.content
            elif isinstance(response, str):
                content = response
            elif isinstance(response, dict):
                content = response.get("content", str(response))

            # Parse JSON — strip markdown code fences if present
            content = content.strip()
            if content.startswith("```"):
                # Remove ```json ... ``` wrapper
                lines = content.split("\n")
                content = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                ).strip()

            try:
                repaired = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from the text
                import re
                match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if match:
                    try:
                        repaired = json.loads(match.group())
                    except json.JSONDecodeError:
                        logger.warning("LLMRepair: LLM output not valid JSON: {}", content[:100])
                        return None
                else:
                    logger.warning("LLMRepair: no JSON found in output: {}", content[:100])
                    return None

            # Double-validate repaired args
            vr = schema.validate(repaired)
            if vr.ok:
                logger.info("LLMRepair: successfully repaired {} args: {} → {}",
                            tool_name, bad_args, vr.coerced_args)
                return vr.coerced_args
            else:
                logger.warning("LLMRepair: repaired args still invalid: {}",
                               [e.message for e in vr.errors])
                return None

        except Exception as exc:
            logger.error("LLMRepair: repair failed for {}: {}", tool_name, exc)
            return None
