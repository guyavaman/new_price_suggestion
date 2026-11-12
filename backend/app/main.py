from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.schemas.extraction import ExtractedRequest
from app.services.extraction import ExtractionService

app = FastAPI(title="AI Quote Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],  # Angular dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractRequestBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    reference_date: date | None = None


class ExtractResponse(BaseModel):
    request: ExtractedRequest
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


def get_extraction_service() -> ExtractionService:
    return ExtractionService()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse)
def extract(
    body: ExtractRequestBody,
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractResponse:
    try:
        result, stats = service.extract(body.message, body.reference_date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ExtractResponse(
        request=result,
        model=stats.model,
        prompt_version=service.prompt_version,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        latency_ms=stats.latency_ms,
    )
