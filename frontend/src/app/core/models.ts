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

export interface Dashboard {
  stages: { stage: DealStage; count: number; value: number }[];
  open_pipeline_value: number;
  won_value_this_month: number;
  won_count_this_month: number;
  win_rate: number | null;
  avg_won_value: number | null;
  hot_leads: number;
  overdue_tasks: number;
  open_tasks: number;
  handed_off_chats: number;
  escalated_chats: number;
  chat_conversion: number | null;
  sources: Record<string, number>;
  upcoming_events: Deal[];
}

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
}
export interface QuoteOut { quote: StoredQuote; sync: { integration_id: string; ok: boolean; detail: string }[] }
export interface EditOut extends QuoteOut { reply: string; actions: { tool: string; input: Record<string, unknown>; error: boolean }[]; flags: string[] }

// ---------- owner screens ----------
export interface TodayView {
  waiting_chats: { id: string; deal_id: string | null; escalated: boolean; status: string; reason: string | null; last: string; updated_at: string }[];
  tasks_due: (Task & { deal_title: string | null })[];
  events_this_week: { id: string; title: string; stage: DealStage; value: number | null; event_date: string; temperature: Temperature; guests: number | null; deposit_paid: number; final_count_confirmed: boolean }[];
  hot_leads: { id: string; title: string; stage: DealStage; value: number | null; event_date: string | null; temperature: Temperature }[];
  quotes_waiting: number; open_quotes_value: number; deposits_this_month: number; won_this_month: number;
}
export interface CalendarDay { date: string; deals: { id: string; title: string; stage: DealStage; guests: number | null; temperature: Temperature }[]; events_booked: number; guests_booked: number; full: boolean }
export interface KitchenItem { sku: string; name: string; category: string; quantity: number; unit: string; serves: number | null; events: { deal_id: string; title: string; quantity: number }[] }
export interface KitchenSheet {
  date: string; total_guests: number; missing_quotes: string[]; food: KitchenItem[];
  events: { deal_id: string; title: string; guests: number | null; location: string | null; meal_type: string | null; dietary: string[]; staff: string[]; equipment: string[]; tier: string | null }[];
}
export interface CatalogItem {
  sku: string; name_he: string; name_en: string; category: string; unit: string; price: number; meal_type: string;
  tags: string[]; serves: number | null; min_qty: number | null; description_he: string; active: boolean;
}
export interface BusinessSettings {
  business_name: string; phone: string; email: string; business_id: string; vat_rate: number;
  waiter_ratio: number; bartender_ratio: number; head_waiter_from: number; auto_waiters_from: number; staff_hours: number;
  canapes_per_guest: number; volume_discounts: { min_subtotal: number; rate: number }[]; remote_areas: string[];
  max_events_per_day: number; max_guests_per_day: number; quote_valid_days: number; deposit_rate: number;
  payment_provider: string; public_base_url: string; followup_after_days: number; final_count_days_before: number;
  invoice_provider: string; service_info: string;
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
}

export interface ServiceChat { status: Conversation['status'] | null; messages: { role: 'user' | 'assistant'; text: string; by: string }[]; reply?: string | null; }

export interface CustomerMessage { kind: string; label: string; text: string; recommended: boolean; whatsapp_url: string | null; }
