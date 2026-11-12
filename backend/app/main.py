from datetime import date
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.catalog.loader import load_catalog
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuPlan, PricedQuote
from app.services.corrections import Correction, CorrectionStore, Review
from app.services.editing import EditService
from app.services.extraction import ExtractionService
from app.services.menu import MenuPlanner
from app.services.pricing import PricingEngine
from app.services.tiers import build_tiers

app = FastAPI(title="AI Quote Agent", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],  # Angular dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- dependencies (overridable in tests) ----------

@lru_cache
def get_catalog() -> list[CatalogItem]:
    return load_catalog()


@lru_cache
def get_corrections() -> CorrectionStore:
    return CorrectionStore()


def get_extraction_service() -> ExtractionService:
    return ExtractionService()


def get_menu_planner() -> MenuPlanner:
    return MenuPlanner(get_catalog(), corrections=get_corrections())


def get_engine() -> PricingEngine:
    return PricingEngine(get_catalog())


def get_edit_service() -> EditService:
    return EditService(get_catalog())


# ---------- models ----------

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


class TierOut(BaseModel):
    key: str
    name: str
    changes: list[str]
    plan: MenuPlan
    quote: PricedQuote


class QuoteResponse(BaseModel):
    request: ExtractedRequest
    plan: MenuPlan
    tiers: list[TierOut]
    latency_ms: int
    input_tokens: int
    output_tokens: int


class EditBody(BaseModel):
    request: ExtractedRequest
    plan: MenuPlan
    instruction: str = Field(..., min_length=1, max_length=2000)


class EditResponse(BaseModel):
    request: ExtractedRequest
    plan: MenuPlan
    reply: str
    actions: list[dict]
    flags: list[str]
    tiers: list[TierOut]


def _tiers(req, plan, catalog, engine) -> list[TierOut]:
    return [TierOut(key=t.key, name=t.name, changes=t.changes, plan=t.plan, quote=t.quote)
            for t in build_tiers(req, plan, catalog, engine)]


# ---------- routes ----------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse)
def extract(body: ExtractRequestBody,
            service: ExtractionService = Depends(get_extraction_service)) -> ExtractResponse:
    try:
        result, stats = service.extract(body.message, body.reference_date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ExtractResponse(request=result, model=stats.model,
                           prompt_version=service.prompt_version,
                           input_tokens=stats.input_tokens, output_tokens=stats.output_tokens,
                           latency_ms=stats.latency_ms)


@app.post("/quote", response_model=QuoteResponse)
def quote(body: ExtractRequestBody,
          extractor: ExtractionService = Depends(get_extraction_service),
          planner: MenuPlanner = Depends(get_menu_planner),
          engine: PricingEngine = Depends(get_engine),
          catalog: list[CatalogItem] = Depends(get_catalog)) -> QuoteResponse:
    """Full pipeline: extract (LLM) -> plan menu (LLM) -> 3 priced tiers (code)."""
    try:
        req, s1 = extractor.extract(body.message, body.reference_date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    plan, s2 = planner.plan(req)
    return QuoteResponse(
        request=req, plan=plan, tiers=_tiers(req, plan, catalog, engine),
        latency_ms=s1.latency_ms + s2.latency_ms,
        input_tokens=s1.input_tokens + s2.input_tokens,
        output_tokens=s1.output_tokens + s2.output_tokens,
    )


@app.post("/quote/edit", response_model=EditResponse)
def edit_quote(body: EditBody, editor: EditService = Depends(get_edit_service),
               engine: PricingEngine = Depends(get_engine),
               catalog: list[CatalogItem] = Depends(get_catalog)) -> EditResponse:
    """Plain-language edit via tool use, then deterministic re-pricing."""
    r = editor.edit(body.request, body.plan, body.instruction)
    return EditResponse(request=r.request, plan=r.plan, reply=r.reply, actions=r.actions,
                        flags=r.flags, tiers=_tiers(r.request, r.plan, catalog, engine))


@app.post("/corrections", status_code=201)
def add_correction(c: Correction, store: CorrectionStore = Depends(get_corrections),
                   catalog: list[CatalogItem] = Depends(get_catalog)) -> dict:
    if c.correct_sku not in {i.sku for i in catalog}:
        raise HTTPException(status_code=422, detail=f"Unknown SKU {c.correct_sku}")
    store.add_correction(c)
    return {"ok": True}


@app.post("/reviews", status_code=201)
def add_review(r: Review, store: CorrectionStore = Depends(get_corrections)) -> dict:
    if r.lines_corrected > r.lines_total:
        raise HTTPException(status_code=422, detail="lines_corrected > lines_total")
    store.add_review(r)
    return {"ok": True}


@app.get("/metrics/accuracy")
def accuracy(store: CorrectionStore = Depends(get_corrections)) -> list[dict]:
    return store.accuracy_series()
