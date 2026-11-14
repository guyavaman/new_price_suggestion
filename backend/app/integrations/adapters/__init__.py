import httpx

from app.integrations.adapters.hubspot import HubSpotAdapter
from app.integrations.adapters.internal import InternalCrmAdapter
from app.integrations.adapters.monday import MondayAdapter
from app.integrations.adapters.webhook import WebhookAdapter
from app.integrations.config import AdapterType, IntegrationConfig

REGISTRY = {
    AdapterType.webhook: WebhookAdapter,
    AdapterType.hubspot: HubSpotAdapter,
    AdapterType.monday: MondayAdapter,
    AdapterType.internal: InternalCrmAdapter,
}


def build_adapter(config: IntegrationConfig, client: httpx.Client | None = None):
    """To add a CRM: write an adapter with `sync(event, refs)`, register it here."""
    return REGISTRY[config.type](config, client)
