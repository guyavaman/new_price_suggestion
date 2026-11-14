export type DealStage = 'new' | 'contacted' | 'quoted' | 'negotiation' | 'won' | 'lost';
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
  lost_reason: string | null;
  source: Source;
  created_at: string;
  updated_at: string;
  stage_changed_at: string;
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
  by: 'ai' | 'human';
}

export interface Conversation {
  id: string;
  status: 'active' | 'handed_off' | 'closed';
  customer_id: string | null;
  deal_id: string | null;
  messages: ChatMessage[];
  lead_score: number;
  updated_at: string;
}

export interface QuoteSummary {
  id: string;
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
