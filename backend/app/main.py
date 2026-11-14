import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app import security
from app.api import agent as agent_api
from app.api import business as business_api
from app.api import crm as crm_api
from app.api import public as public_api
from app.deps import (
    get_catalog,
    get_corrections,
    get_crm,
    get_edit_service,
    get_engine,
    get_extraction_service,
    get_menu_planner,
    get_public_tenant,
    get_repo,
    get_sales_agent,
    get_sync,
    get_tenant,
    get_tenant_loader,
)
from app.integrations.canonical import STATUS_EVENT, EventType, QuoteEvent, build_event
from app.integrations.config import TenantConfig
from app.integrations.export import deals_csv, line_items_csv
from app.integrations.sync import SyncRecord, SyncService
from app.repositories.quotes import StatusChange, StoredQuote
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import QuoteStatus, TierQuote
from app.services.corrections import Correction, CorrectionStore, Review
from app.services.editing import EditService
from app.services.extraction import ExtractionService
from app.services.menu import MenuPlanner
from app.services.pricing import PricingEngine
from app.services.quotes import create_quote as create_stored_quote
from app.services.quotes import tiers_for

app = FastAPI(
    title="AI Quote Agent",
    version="0.4.0",
    description="Free-text catering requests to priced quotes, with CRM integration. "
                "Send `X-Tenant-ID` (and `X-API-Key` when the tenant has one) on every call.",
)

app.include_router(crm_api.router)
app.include_router(agent_api.router)
app.include_router(public_api.router)
app.include_router(business_api.router)

__all__ = ["get_crm", "get_public_tenant", "get_sales_agent", "get_tenant_loader"]

@app.middleware("http")
async def owner_auth(request: Request, call_next):
    """With OWNER_PASSWORD set: owner routes need a login token; viewers may only read."""
    if not security.auth_required() or request.method == "OPTIONS":
        return await call_next(request)
    if security.is_public(request.method, request.url.path):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    role = security.verify_token(auth[7:] if auth.lower().startswith("bearer ") else None)
    if role is None:
        return JSONResponse({"detail": "נדרשת התחברות", "code": "login"}, status_code=401)
    if role == "viewer" and request.method not in security.READ_METHODS:
        return JSONResponse({"detail": "מצב צפייה: בדמו הציבורי אי אפשר לשנות נתונים",
                             "code": "viewer"}, status_code=403)
    return await call_next(request)


@app.exception_handler(security.RateLimited)
async def _rate_limited(request: Request, e: security.RateLimited):
    return JSONResponse({"detail": "יותר מדי הודעות, נסו שוב בעוד דקה"}, status_code=429,
                        headers={"Retry-After": str(e.retry_after)})


@app.exception_handler(security.AiBudgetExceeded)
async def _ai_budget(request: Request, e: security.AiBudgetExceeded):
    return JSONResponse({"detail": "ה-AI לא זמין כרגע (הגענו למכסה היומית). אפשר להתקשר אלינו."},
                        status_code=503)


class LoginBody(BaseModel):
    password: str | None = Field(None, max_length=200)
    guest: bool = False


@app.get("/auth/status", tags=["auth"])
def auth_status() -> dict:
    return {"required": security.auth_required(), "guest": security.guest_allowed()}


@app.post("/auth/login", tags=["auth"])
def login(body: LoginBody, request: Request) -> dict:
    security.limit_login(request)
    if body.guest and security.guest_allowed():
        return {"token": security.make_token("viewer"), "role": "viewer"}
    if body.password and security.check_password(body.password):
        return {"token": security.make_token("owner"), "role": "owner"}
    raise HTTPException(status_code=401, detail="סיסמה שגויה")


app.add_middleware(
    CORSMiddleware,
    # Angular dev server + sites embedding the chat widget (comma-separated env var)
    allow_origins=["http://localhost:4200",
                   *[o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o]],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return tiers_for(req, plan, catalog, engine)


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
    q = create_stored_quote(repo, tenant.tenant_id, req, plan, catalog, engine, body.message)
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


# ---------- one-service deploy: demo data + the Angular app from the same origin ----------

@app.on_event("startup")
def _seed_demo() -> None:
    if os.environ.get("SEED_DEMO") == "1" and not get_crm().deals.list("demo"):
        from scripts.seed_crm import seed
        seed(reset=True)


FRONTEND_DIST = Path(os.environ.get(
    "FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist" / "crm" / "browser"))

if FRONTEND_DIST.is_dir():
    API_DOCS = ("/docs", "/redoc", "/openapi.json")
    # same URL can be a page or JSON: tell the browser cache the two must never be mixed up
    _NO_MIX = {"Vary": "Accept", "Cache-Control": "no-cache"}

    def _index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html", headers=_NO_MIX)

    @app.middleware("http")
    async def spa_navigation(request, call_next):
        """A browser *navigation* (Accept: text/html) always gets the Angular app, even where a
        page and an API route share a path (/settings, /quotes, /kitchen). API calls from the app
        send Accept: application/json and reach the API as usual."""
        if (request.method == "GET" and "text/html" in request.headers.get("accept", "")
                and not request.url.path.startswith(API_DOCS)):
            return _index()
        response = await call_next(request)
        response.headers["Vary"] = "Accept"
        return response

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Serve the built Angular app; unknown paths fall back to index.html (client routing).
        Registered last, so every API route above takes precedence."""
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return _index()
