export type DealStage = 'new' | 'quoted' | 'won' | 'completed' | 'lost';
export type Temperature = 'hot' | 'warm' | 'cold';
export interface Payment { id: string; kind: string; amount: number; status: 'pending' | 'paid' | 'failed'; provider: string; paid_at: string | null; created_at: string }
export interface Invoice { provider: string; number: string; url: string | null; amount: number; issued_at: string }
export type Source = 'web_chat' | 'whatsapp' | 'email' | 'phone' | 'referral' | 'manual';

export interface Customer {
  id: string;
  name: string | null;
  phone: string | null;
  email: string | null;
  company: string | null;
  source: Source;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface Deal {
  id: string;
  customer_id: string;
  title: string;
  stage: DealStage;
  value: number | null;
  event_type: string | null;
  event_date: string | null;
  guest_count: number | null;
  location: string | null;
  kashrut: string | null;
  meal_type: string | null;
  dietary: string[];
  service_style?: string | null; site_contact_name?: string | null; site_contact_phone?: string | null;
  site?: SiteConditions; ready_marks?: Record<string, string>; change_requests?: ChangeRequest[];
  budget: number | null;
  budget_scope: string | null;
  quote_ids: string[];
  conversation_id: string | null;
  lead_score: number;
  score_reasons: string[];
  ready_to_book: boolean;
  temperature: Temperature;
  final_guest_count: number | null;
  payments: Payment[];
  deposit_paid: number;
  invoice: Invoice | null;
  lost_reason: string | null;
  source: Source;
  created_at: string;
  updated_at: string;
  stage_changed_at: string;
  sent_messages?: Record<string, string>;
}

export interface Activity {
  id: string;
  deal_id: string | null;
  kind: 'note' | 'chat' | 'quote' | 'stage' | 'task' | 'call' | 'handoff' | 'system';
  text: string;
  actor: 'agent' | 'user' | 'system' | 'customer';
  at: string;
}

export interface Task {
  id: string;
  deal_id: string | null;
  title: string;
  due_at: string | null;
  done: boolean;
  priority: 'high' | 'normal';
  created_by: 'agent' | 'user' | 'system';
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  at: string;
  tools: { tool: string; error: boolean }[];
  by: 'ai' | 'human' | 'system';
}

export interface Conversation {
  id: string;
  status: 'active' | 'handed_off' | 'human' | 'closed';
  escalated: boolean;
  handoff_reason: string | null;
  customer_id: string | null;
  deal_id: string | null;
  quote_id?: string | null;
  messages: ChatMessage[];
  lead_score: number;
  updated_at: string;
}

export interface QuoteSummary {
  id: string;
  public_token: string;
  number: string;
  status: string;
  selected_tier: string;
  created_at: string;
  tiers: {
    key: string;
    name: string;
    total: number;
    per_guest: number | null;
    lines: { name: string; quantity: number; unit: string; total: number }[];
  }[];
}

export interface DealDetail {
  deal: Deal;
  customer: Customer | null;
  timeline: Activity[];
  tasks: Task[];
  quotes: QuoteSummary[];
  conversation: Conversation | null;
}

/** One KPI set for every screen (backend app/business/kpis.py, docs/KPIS.md). Money before VAT. */
export interface Kpis {
  as_of: string; vat_included: boolean;
  stages: { stage: DealStage; count: number; value: number }[];
  open_pipeline_value: number; quotes_waiting: number; quotes_waiting_value: number;
  booked_this_month_value: number; booked_this_month_count: number; deposits_this_month: number;
  win_rate: number | null; avg_booked_value: number | null; hot_leads: number;
  open_tasks: number; overdue_tasks: number; handed_off_chats: number; escalated_chats: number;
  chat_conversion: number | null; sources: Record<string, number>;
}
export interface Dashboard { kpis: Kpis; upcoming_events: Deal[]; }

export interface ChatReply {
  conversation_id: string;
  reply: string;
  status: Conversation['status'];
  lead_score: number;
  actions: string[];
}

// ---------- quotes ----------
export interface QuoteLine {
  sku: string; name_he: string; unit: string; unit_price: number; quantity: number; total: number;
  note: string; source: 'requested' | 'suggested' | 'rule'; confidence: 'high' | 'medium' | 'low' | 'rule'; reason: string;
}
export interface PricedQuote {
  lines: QuoteLine[]; subtotal: number; discount_rate: number; discount: number; net: number; vat: number;
  total: number; per_guest: number | null; budget: { ok: boolean; text: string } | null; guards: string[];
}
export interface TierQuote { key: 'basic' | 'recommended' | 'premium'; name: string; changes: string[]; plan: { cover_note: string; unmatched: string[] }; quote: PricedQuote }
export interface ExtractedRequest {
  language: string;
  contact: { name: string | null; phone: string | null; email: string | null; company: string | null };
  event_type: string | null; guest_count: number | null; event_date: string | null; location: string | null;
  kashrut: string | null; meal_type: string | null;
  dietary_requirements: { tag: string; guest_count: number | null }[];
  budget: { amount: number; scope: 'total' | 'per_guest' } | null;
  requested_items: { description: string; quantity: number | null }[];
  missing_info: string[]; suspicious_instructions: boolean;
}
export type QuoteStatus = 'draft' | 'sent' | 'approved' | 'rejected' | 'expired';
export interface StoredQuote {
  public_token: string;
  id: string; number: string; status: QuoteStatus; selected_tier: string; source_message: string;
  request: ExtractedRequest; tiers: TierQuote[]; created_at: string; updated_at: string;
  history: { status: QuoteStatus; at: string; note: string | null }[];
  menu_choices?: Record<string, Record<string, string[]>>;
}
export interface QuoteOut { quote: StoredQuote; sync: { integration_id: string; ok: boolean; detail: string }[] }
export interface EditOut extends QuoteOut { reply: string; actions: { tool: string; input: Record<string, unknown>; error: boolean }[]; flags: string[] }

// ---------- owner screens ----------
export interface UiAction { kind: 'whatsapp' | 'link' | 'edit' | 'mark' | 'approve' | 'quote'; label: string; url: string | null; target: string | null }
export interface WatchRow { kind: 'readiness' | 'order' | 'change'; key: string; severity: 'high' | 'normal'; deal_id: string | null; title: string; text: string; when: string | null; actions: UiAction[]; meta: Record<string, string> }
export interface AgendaRow {
  deal_id: string | null; title: string; value: number | null; stage: string | null; temperature: string | null; event_date: string | null;
  tasks: { id: string; title: string; due_at: string | null; overdue: boolean; priority: string }[]; overdue: boolean; priority: string; action: UiAction | null;
}
export interface TodayView {
  watch: WatchRow[]; agenda: AgendaRow[];
  waiting_chats: { id: string; deal_id: string | null; escalated: boolean; status: string; reason: string | null; last: string; updated_at: string }[];
  events_this_week: { id: string; title: string; event_date: string; guests: number | null; done: number; total: number; ready: boolean }[];
  reminders: { at: string; deal_id: string | null; text: string; rule: string }[]; automation_last_run: string | null;
  kpis: Kpis;
}
export interface ReadyItem { key: string; label: string; ok: boolean; detail: string; action: UiAction | null }
export interface Readiness { deal_id: string; items: ReadyItem[]; done: number; total: number; ready: boolean; days_left: number | null }
export interface SiteConditions { electricity: boolean | null; kitchenette: boolean | null; fridge: boolean | null; parking: boolean | null; notes: string }
export interface ChangeRequest { id: string; kind: 'guests' | 'menu'; payload: Record<string, unknown>; summary: string; status: 'pending' | 'approved' | 'declined'; created_at: string; decided_at: string | null; price_note: string | null }
export interface CalendarDay { date: string; deals: { id: string; title: string; stage: DealStage; guests: number | null; temperature: Temperature }[]; events_booked: number; guests_booked: number; full: boolean }
export interface EventInfo { deal_id: string; title: string; event_date: string; guests: number | null; location: string | null; meal_type: string | null; dietary: string[]; staff: string[]; equipment: string[]; tier: string | null }
export interface KitchenRow { sku: string; name: string; category: string; units: number; unit: string; measure: 'g' | 'unit' | null; total_amount: number | null; problem: string | null; events: { deal_id: string; title: string; units: number | null; package: string | null }[] }
export interface KitchenSheet {
  date: string; total_guests: number; missing_quotes: string[]; warnings: string[]; events: EventInfo[];
  sections: { kashrut: '' | 'meat' | 'dairy' | 'pareve'; label: string; events: string[]; groups: { station: string; rows: KitchenRow[] }[] }[];
}
export interface PrepTask { sku: string; name: string; station: string; units: number | null; unit: string; measure: 'g' | 'unit' | null; total_amount: number | null; deal_id: string; title: string; event_date: string; event_meal: string; days_before: number; problem: string | null }
export interface PrepDay { date: string; tasks: PrepTask[] }
export interface PurchaseItem { code: string; name: string; unit: string; quantity: number; price: number | null; cost: number | null; needed_by: string; dishes: string[]; events: string[] }
export interface OrderBatch { deliver_on: string; order_by: string | null; late: boolean; items: PurchaseItem[]; total: number | null; text: string; whatsapp_url: string | null }
export interface SupplierOrders { code: string | null; name: string; phone: string; lead_days: number | null; delivery_days: string[]; batches: OrderBatch[]; total: number | null }
export interface PurchaseList {
  start: string; end: string; suppliers: SupplierOrders[]; missing_recipes: { sku: string; name: string; events: string[] }[];
  unknown_ingredients: { code: string; dishes: string[] }[]; missing_quantities: { name: string; problem: string | null; events: string[] }[]; missing_prices: string[];
}
export interface Supplier { code: string; name: string; phone: string; email: string; lead_days: number; delivery_days: number[]; order_cutoff: string; notes: string }
export interface Ingredient { code: string; name_he: string; unit: 'kg' | 'liter' | 'unit'; kashrut: 'meat' | 'dairy' | 'pareve'; supplier: string | null; price: number | null; price_updated_at?: string | null }
export interface RecipeLine { ingredient: string; quantity: number }
export interface CatalogItem {
  sku: string; name_he: string; name_en: string; category: string; unit: string; price: number; meal_type: string;
  tags: string[]; serves: number | null; min_qty: number | null; description_he: string; active: boolean;
  // owner-only cost data
  cost?: number | null; cost_updated_at?: string | null; cost_source?: 'manual' | 'recipe' | 'supplier' | 'components' | null;
  kind?: ItemKind; yield_amount?: number | null; slots?: Slot[]; measure?: 'g' | 'unit' | null;
  recipe?: RecipeLine[]; station?: string | null; prep_days?: number; recipe_cost?: number | null; recipe_missing?: string[];
  unit_cost?: number | null; cost_missing?: string[]; item_margin?: number | null;
}
export type ItemKind = 'food' | 'drink' | 'equipment' | 'staff' | 'logistics' | 'package';
export interface Slot { id: string; label_he: string; choose: number; options: string[]; per_guest: number | null; customer_choice: boolean }
export interface PortionRule { measure: 'g' | 'unit'; total_per_guest: number; extra_per_variety: number }
export interface MenuSlot { id: string; label_he: string; choose: number; can_choose: boolean; options: { sku: string; name_he: string; description_he: string }[]; chosen: string[] }
export interface DishRow {
  slot_id: string; slot_label: string; sku: string; name_he: string; category: string; measure: 'g' | 'unit' | null;
  per_guest: number | null; total_amount: number | null; units: number | null; unit: string; unit_cost: number | null; cost: number | null; problem: string | null;
}
export interface Breakdown { sku: string; name_he: string; guests: number; rows: DishRow[]; status: 'complete' | 'missing'; total_cost: number | null; cost_per_guest: number | null; missing: string[] }
export interface PackageMenu { sku: string; name_he: string; tiers: string[]; guests: number; slots: MenuSlot[]; breakdown: Breakdown }
export interface MenuLock { customer_can_choose: boolean; lock_date: string | null; reason: string | null; needs_approval?: boolean }
export interface OwnerMenu { packages: PackageMenu[]; lock: MenuLock }
export interface DealMenu { quote_id: string | null; quote_number: string | null; tier: string | null; packages: PackageMenu[] }
export interface ImpactRow {
  kind: 'open_quote' | 'booked_event'; quote_id: string; quote_number: string; deal_id: string | null; title: string;
  event_date: string | null; profit_before: number; profit_after: number; margin_before: number | null; margin_after: number | null; delta: number;
}
export interface ImportReport {
  rows: number; unchanged: number; applied: boolean;
  creates: { sku: string; name: string }[];
  updates: { sku: string; name: string; fields: Record<string, [unknown, unknown]> }[];
  errors: { sheet: string; row: number; column: string; message: string }[];
}
export interface CostSummary {
  status: 'complete' | 'missing'; revenue_net: number; total_cost: number | null; gross_profit: number | null; margin: number | null;
  by_group: { group: string; label: string; revenue: number; cost: number | null }[];
  missing: { sku: string; name: string }[]; below_floor: boolean | null; floor: number | null;
}
export interface QuoteProfit { floor: number; tiers: { key: string; name: string; summary: CostSummary; missing_detail: string[] }[]; send_blockers: string[] }
export interface ProfitRow { key: string; label: string; events: number; revenue: number; profit: number | null; margin: number | null; missing_cost: number }
export interface ProfitReport {
  floor: number; by_month: ProfitRow[]; by_event_type: ProfitRow[]; by_package: ProfitRow[];
  events: { deal_id: string; title: string; event_date: string | null; event_type: string | null; package: string | null; revenue: number; cost: number | null; profit: number | null; margin: number | null; missing: string[] }[];
}
export interface BusinessSettings {
  business_name: string; phone: string; email: string; business_id: string; vat_rate: number;
  waiter_ratio: number; bartender_ratio: number; head_waiter_from: number; auto_waiters_from: number; staff_hours: number;
  canapes_per_guest: number; volume_discounts: { min_subtotal: number; rate: number }[]; remote_areas: string[];
  max_events_per_day: number; max_guests_per_day: number; quote_valid_days: number; deposit_rate: number;
  payment_provider: string; public_base_url: string; followup_after_days: number; final_count_days_before: number;
  invoice_provider: string; service_info: string; profit_floor: number; cost_alert_threshold: number; timezone?: string;
  portion_rules: Record<string, PortionRule>; reference_guests: number; menu_lock_days: number; delivery_buffer_days: number;
  style_staffing: Record<string, { waiter_ratio: number; chef_ratio: number | null }>; guest_lock_days: number; late_guest_surcharge: number; late_decrease_charged: boolean;
  balance_reminder_days: number; automation_enabled: boolean; automation_hour: number; automation_last_run: string | null;
}
export interface PublicQuote {
  business_name: string; business_phone: string; business_email?: string; business_id?: string; vat_rate?: number; created_at?: string | null;
  number: string; status: string; customer_name: string | null;
  event: { type: string; date: string | null; guests: number | null; location: string | null; meal_type: string | null; kashrut: string | null };
  cover_note: string | null;
  tiers: { key: string; name: string; total: number; per_guest: number | null; deposit: number; items: { name: string; quantity: number; unit: string }[]; services: string[];
    subtotal?: number; discount_rate?: number; discount?: number; net?: number; vat?: number }[];
  selected_tier: string; valid_until: string; expired: boolean; deposit_rate: number; deposit_paid: number;
  can_accept: boolean; can_update_count: boolean; final_guest_count: number | null;
  guest_lock_date?: string | null; count_needs_approval?: boolean; pending_changes?: { kind: string; summary: string }[];
  menu?: { sku: string; name_he: string; tiers: string[]; slots: MenuSlot[] }[]; menu_lock?: MenuLock | null;
}

export interface ServiceChat { status: Conversation['status'] | null; messages: { role: 'user' | 'assistant'; text: string; by: string }[]; reply?: string | null; }

export interface CustomerMessage { kind: string; label: string; text: string; recommended: boolean; whatsapp_url: string | null; }

export type StaffRole = 'waiter' | 'head_waiter' | 'bartender' | 'chef';
export interface StaffMember { id: string; name: string; phone: string; roles: StaffRole[]; hourly_rate: number | null; available_days: number[]; unavailable_dates: string[]; notes: string; active: boolean }
export interface RoleNeed { role: StaffRole; label: string; needed: number; hours: number; assigned: number; confirmed: number; declined: number }
export interface StaffAssignment { id: string; member_id: string; name: string; phone: string; role: StaffRole; status: 'invited' | 'confirmed' | 'declined'; planned_hours: number; actual_hours: number | null; rate: number | null; invite_url: string | null; responded_at: string | null }
export interface DealStaff { needs: RoleNeed[]; assignments: StaffAssignment[]; ok: boolean; summary: string; candidates: Record<string, { id: string; name: string; phone: string }[]> }
export interface PayRow { member_id: string; name: string; phone: string; rate: number | null; shifts: { deal_id: string; title: string; date: string; role: StaffRole; hours: number; actual: boolean }[]; hours: number; planned_only: number; total: number | null }
export interface EquipmentType { code: string; name: string; owned: number; notes: string }
export interface EquipmentLine { code: string; name: string; quantity: number; returned: number | null }
export interface EquipmentState { lines: (EquipmentLine & { owned: number | null; short: number; missing: number })[]; packed: boolean; returned: boolean; shortages: string[]; missing: string[]; from_quote: boolean }
export interface MissingReturn { deal_id: string; title: string; event_date: string; counted: boolean; items: { code: string; name: string; out: number; returned: number | null; missing: number }[] }
export interface ShiftView { name: string; role: string; event: string; event_date: string | null; location: string | null; guests: number | null; hours: number; status: 'invited' | 'confirmed' | 'declined'; business_name: string }
