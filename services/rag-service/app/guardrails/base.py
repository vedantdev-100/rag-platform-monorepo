"""
Guardrail interface. Every guardrail (prompt-injection detector, PII
redactor, toxicity filter, output-schema validator, jailbreak detector)
implements this so they can be composed into a pipeline and run as FastAPI
dependencies on any endpoint that accepts free text bound for an LLM, or
that returns LLM-generated text to the user.

Planned implementations (fill in as the RAG layer is built):
- app/guardrails/input/prompt_injection.py
- app/guardrails/input/pii_detector.py
- app/guardrails/output/toxicity_filter.py
- app/guardrails/output/schema_validator.py  (structured-output enforcement
  for RAG citations/metadata)
- app/guardrails/output/hallucination_check.py (cross-check generation
  against retrieved context for RAG)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class GuardrailAction(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    FLAG = "flag"       # allow but log for review
    REDACT = "redact"   # allow with content modified


@dataclass
class GuardrailResult:
    action: GuardrailAction
    reason: str | None = None
    modified_content: str | None = None


class Guardrail(ABC):
    name: str

    @abstractmethod
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        ...


class GuardrailPipeline:
    """Runs a sequence of guardrails; short-circuits on first BLOCK."""

    def __init__(self, guardrails: list[Guardrail]):
        self.guardrails = guardrails

    async def run(self, content: str, *, context: dict | None = None) -> GuardrailResult:
        current_content = content
        for guardrail in self.guardrails:
            result = await guardrail.check(current_content, context=context)
            if result.action == GuardrailAction.BLOCK:
                return result
            if result.action == GuardrailAction.REDACT and result.modified_content:
                current_content = result.modified_content
        return GuardrailResult(action=GuardrailAction.ALLOW, modified_content=current_content)
