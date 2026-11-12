from datetime import date

from app.llm.client import LLMCallStats, LLMClient
from app.llm.prompts import (
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_SYSTEM_PROMPT,
    build_extraction_user_message,
)
from app.schemas.extraction import ExtractedRequest

MAX_MESSAGE_CHARS = 8000


class ExtractionService:
    prompt_version = EXTRACTION_PROMPT_VERSION

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()

    def extract(
        self, message: str, reference_date: date | None = None
    ) -> tuple[ExtractedRequest, LLMCallStats]:
        message = message.strip()
        if not message:
            raise ValueError("Empty message")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"Message too long (max {MAX_MESSAGE_CHARS} chars)")

        ref = (reference_date or date.today()).isoformat()
        return self.llm.structured(
            system=EXTRACTION_SYSTEM_PROMPT,
            user=build_extraction_user_message(message, ref),
            schema=ExtractedRequest,
            tool_name="record_request",
            tool_description="Record the structured details of the customer's catering request.",
        )
