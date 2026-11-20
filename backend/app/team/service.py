"""Storage for staff, assignments and equipment (stage 5)."""

from __future__ import annotations

from pathlib import Path

from app.repositories.store import STORE_DIR, Collection
from app.team.models import Assignment, EquipmentType, EventEquipment, StaffMember


class TeamService:
    def __init__(self, base: Path = STORE_DIR):
        self.members = Collection(StaffMember, base / "staff.json")
        self.assignments = Collection(Assignment, base / "staff_assignments.json")
        self.equipment = Collection(EquipmentType, base / "equipment.json")
        self.event_equipment = Collection(EventEquipment, base / "event_equipment.json")

    # staff
    def staff(self, tenant: str, active_only: bool = False) -> list[StaffMember]:
        return sorted(self.members.list(tenant, (lambda m: m.active) if active_only else None),
                      key=lambda m: m.name)

    def for_deal(self, tenant: str, deal_id: str) -> list[Assignment]:
        return self.assignments.list(tenant, lambda a: a.deal_id == deal_id)

    def by_token(self, token: str) -> Assignment | None:
        """The confirmation page has no tenant: tokens are unique across businesses."""
        return next((a for a in self.assignments._load().values() if a.token == token), None)

    # equipment
    def stock(self, tenant: str) -> list[EquipmentType]:
        return sorted(self.equipment.list(tenant), key=lambda e: e.name)

    def put_type(self, tenant: str, e: EquipmentType) -> EquipmentType:
        return self.equipment.put(e.model_copy(update={"tenant_id": tenant,
                                                       "id": f"{tenant}:{e.code}"}))

    def event_list(self, tenant: str, deal_id: str) -> EventEquipment | None:
        return self.event_equipment.get(tenant, deal_id)

    def put_event_list(self, ev: EventEquipment) -> EventEquipment:
        return self.event_equipment.put(ev)
