import hmac
import os
from datetime import date
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.catalog.loader import load_catalog
from app.integrations.canonical import STATUS_EVENT, EventType, QuoteEvent, build_event
from app.integrations.config import TenantConfig, load_tenant
from app.integrations.export import deals_csv, line_items_csv
from app.integrations.sync import SyncLog, SyncRecord, SyncService
from app.repositories.quotes import JsonQuoteRepository, StatusChange, StoredQuote
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import QuoteStatus, TierQuote
from app.services.corrections import Correction, CorrectionStore, Review
from app.services.editing import EditService
from app.services.extraction import ExtractionService
from app.services.menu import MenuPlanner
from app.services.pricing import PricingEngine
from app.services.tiers import build_tiers

app = FastAPI(
    title="AI Quote Agent",
    version="0.3.0",
    description="Free-text catering requests to priced quotes, with CRM integration. "
                "Send `X-Tenant-ID` (and `X-API-Key` when the tenant has one) on every call.",
)

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


@lru_cache
def get_repo() -> JsonQuoteRepository:
    return JsonQuoteRepository()


@lru_cache
def get_sync() -> SyncService:
    return SyncService(SyncLog())


def get_tenant_loader():
    return load_tenant


def get_extraction_service() -> ExtractionService:
    return ExtractionService()


def get_menu_planner() -> MenuPlanner:
    return MenuPlanner(get_catalog(), corrections=get_corrections())


def get_engine() -> PricingEngine:
    return PricingEngine(get_catalog())


def get_edit_service() -> EditService:
    return EditService(get_catalog())


def get_tenant(
    x_tenant_id: str = Header("demo"),
    x_api_key: str | None = Header(None),
    loader=Depends(get_tenant_loader),
) -> TenantConfig:
    tenant = loader(x_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"Unknown tenant '{x_tenant_id}'")
    if tenant.api_key_env:
        expected = os.environ.get(tenant.api_key_env, "")
        if not expected or not x_api_key or not hmac.compare_digest(expected, x_api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return tenant


# ---------- models ----------

class MessageBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    reference_date: date | None = None


class ExtractResponse(BaseModel):
    request: ExtractedRequest
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class QuoteOut(BaseModel):
    quote: StoredQuote
    sync: list[SyncRecord] = Field(default_factory=list)


class EditBody(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=2000)


class EditOut(QuoteOut):
    reply: str
    actions: list[dict]
    flags: list[str]


class StatusBody(BaseModel):
    status: QuoteStatus
    tier: str | None = Field(None, description="basic | recommended | premium")
    note: str | None = None


ALLOWED_TRANSITIONS = {
    QuoteStatus.draft: {QuoteStatus.sent, QuoteStatus.approved, QuoteStatus.rejected,
                        QuoteStatus.expired},
    QuoteStatus.sent: {QuoteStatus.approved, QuoteStatus.rejected, QuoteStatus.expired},
    QuoteStatus.expired: {QuoteStatus.sent},
    QuoteStatus.approved: set(),
    QuoteStatus.rejected: {QuoteStatus.sent},
}


def _tiers(req, plan, catalog, engine) -> list[TierQuote]:
    return [TierQuote(key=t.key, name=t.name, changes=t.changes, plan=t.plan, quote=t.quote)
            for t in build_tiers(req, plan, catalog, engine)]


def _get_quote(repo, tenant: TenantConfig, quote_id: str) -> StoredQuote:
    q = repo.get(tenant.tenant_id, quote_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return q


# ---------- routes: pipeline ----------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse)
def extract(body: MessageBody,
            service: ExtractionService = Depends(get_extraction_service)) -> ExtractResponse:
    try:
        result, stats = service.extract(body.message, body.reference_date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ExtractResponse(request=result, model=stats.model,
                           prompt_version=service.prompt_version,
                           input_tokens=stats.input_tokens, output_tokens=stats.output_tokens,
                           latency_ms=stats.latency_ms)


@app.post("/quotes", response_model=QuoteOut, status_code=201)
def create_quote(body: MessageBody, tenant: TenantConfig = Depends(get_tenant),
                 extractor: ExtractionService = Depends(get_extraction_service),
                 planner: MenuPlanner = Depends(get_menu_planner),
                 engine: PricingEngine = Depends(get_engine),
                 catalog: list[CatalogItem] = Depends(get_catalog),
                 repo=Depends(get_repo), sync: SyncService = Depends(get_sync)) -> QuoteOut:
    """Full pipeline: extract (LLM) -> menu (LLM) -> 3 priced tiers (code) -> save -> CRM."""
    try:
        req, _ = extractor.extract(body.message, body.reference_date)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    plan, _ = planner.plan(req)
    q = repo.add(StoredQuote(
        tenant_id=tenant.tenant_id, number=repo.next_number(tenant.tenant_id),
        source_message=body.message, request=req, plan=plan,
        tiers=_tiers(req, plan, catalog, engine),
        history=[StatusChange(status=QuoteStatus.draft)],
    ))
    return QuoteOut(quote=q, sync=sync.deliver(tenant, q, EventType.created))


@app.get("/quotes", response_model=list[StoredQuote])
def list_quotes(tenant: TenantConfig = Depends(get_tenant), repo=Depends(get_repo)):
    return repo.list(tenant.tenant_id)


@app.get("/quotes/{quote_id}", response_model=StoredQuote)
def get_quote(quote_id: str, tenant: TenantConfig = Depends(get_tenant), repo=Depends(get_repo)):
    return _get_quote(repo, tenant, quote_id)


@app.post("/quotes/{quote_id}/edit", response_model=EditOut)
def edit_quote(quote_id: str, body: EditBody, tenant: TenantConfig = Depends(get_tenant),
               editor: EditService = Depends(get_edit_service),
               engine: PricingEngine = Depends(get_engine),
               catalog: list[CatalogItem] = Depends(get_catalog),
               repo=Depends(get_repo), sync: SyncService = Depends(get_sync)) -> EditOut:
    """Plain-language edit via tool use, deterministic re-pricing, CRM update."""
    q = _get_quote(repo, tenant, quote_id)
    if q.status in (QuoteStatus.approved,):
        raise HTTPException(status_code=409, detail="Approved quotes cannot be edited")
    r = editor.edit(q.request, q.plan, body.instruction)
    q.request, q.plan = r.request, r.plan
    q.tiers = _tiers(r.request, r.plan, catalog, engine)
    q = repo.save(q)
    return EditOut(quote=q, sync=sync.deliver(tenant, q, EventType.updated), reply=r.reply,
                   actions=r.actions, flags=r.flags)


@app.post("/quotes/{quote_id}/status", response_model=QuoteOut)
def set_status(quote_id: str, body: StatusBody, tenant: TenantConfig = Depends(get_tenant),
               repo=Depends(get_repo), sync: SyncService = Depends(get_sync)) -> QuoteOut:
    q = _get_quote(repo, tenant, quote_id)
    if body.status not in ALLOWED_TRANSITIONS[q.status]:
        raise HTTPException(status_code=409,
                            detail=f"Cannot move from {q.status.value} to {body.status.value}")
    if body.tier:
        q.tier(body.tier)  # validates
        q.selected_tier = body.tier
    q.status = body.status
    q.history.append(StatusChange(status=body.status, note=body.note))
    q = repo.save(q)
    return QuoteOut(quote=q, sync=sync.deliver(tenant, q, STATUS_EVENT[body.status]))


# ---------- routes: integration ----------

@app.get("/quotes/{quote_id}/event", response_model=QuoteEvent)
def preview_event(quote_id: str, tenant: TenantConfig = Depends(get_tenant),
                  repo=Depends(get_repo)) -> QuoteEvent:
    """Exactly what a CRM integration receives for this quote, without sending it."""
    return build_event(_get_quote(repo, tenant, quote_id), EventType.updated)


@app.post("/quotes/{quote_id}/sync", response_model=list[SyncRecord])
def resync(quote_id: str, tenant: TenantConfig = Depends(get_tenant), repo=Depends(get_repo),
           sync: SyncService = Depends(get_sync)):
    """Push the current state again (e.g. after connecting a new CRM)."""
    return sync.deliver(tenant, _get_quote(repo, tenant, quote_id), EventType.updated)


@app.get("/quotes/{quote_id}/sync-log", response_model=list[SyncRecord])
def sync_log(quote_id: str, tenant: TenantConfig = Depends(get_tenant), repo=Depends(get_repo),
             sync: SyncService = Depends(get_sync)):
    _get_quote(repo, tenant, quote_id)
    return sync.log.for_quote(tenant.tenant_id, quote_id)


@app.post("/integrations/retry", response_model=list[SyncRecord])
def retry(tenant: TenantConfig = Depends(get_tenant), sync: SyncService = Depends(get_sync),
          loader=Depends(get_tenant_loader)):
    return [r for r in sync.retry_failed(loader) if r.tenant_id == tenant.tenant_id]


@app.get("/integrations/schema")
def event_schema() -> dict:
    """JSON Schema of the QuoteEvent payload (versioned)."""
    return QuoteEvent.model_json_schema()


def _events(tenant, repo) -> list[QuoteEvent]:
    return [build_event(q, EventType.updated) for q in repo.list(tenant.tenant_id)]


@app.get("/exports/deals.csv")
def export_deals(tenant: TenantConfig = Depends(get_tenant), repo=Depends(get_repo)):
    return Response(deals_csv(_events(tenant, repo)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="deals.csv"'})


@app.get("/exports/line-items.csv")
def export_lines(tenant: TenantConfig = Depends(get_tenant), repo=Depends(get_repo)):
    return Response(line_items_csv(_events(tenant, repo)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="line-items.csv"'})


# ---------- routes: learning ----------

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
