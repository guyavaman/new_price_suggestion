import { DealStage } from './models';

export const STAGES: { key: DealStage; label: string }[] = [
  { key: 'new', label: 'ליד חדש' },
  { key: 'contacted', label: 'בשיחה' },
  { key: 'quoted', label: 'הצעה נשלחה' },
  { key: 'negotiation', label: 'משא ומתן' },
  { key: 'won', label: 'נסגר' },
  { key: 'lost', label: 'אבוד' },
];
export const STAGE_LABEL = Object.fromEntries(STAGES.map((s) => [s.key, s.label])) as Record<DealStage, string>;

export const EVENT_TYPE: Record<string, string> = {
  wedding: 'חתונה', bar_bat_mitzvah: 'בר/בת מצווה', brit: 'ברית', birthday: 'יום הולדת',
  corporate: 'אירוע חברה', conference: 'כנס', holiday: 'אירוע חג', private: 'אירוע פרטי', other: 'אחר',
};
export const MEAL: Record<string, string> = { meat: 'בשרי', dairy: 'חלבי', pareve: 'פרווה' };
export const KASHRUT: Record<string, string> = { none: 'ללא', kosher: 'כשר', mehadrin: 'מהדרין' };
export const SOURCE: Record<string, string> = {
  web_chat: "צ'אט AI", whatsapp: 'וואטסאפ', email: 'מייל', phone: 'טלפון', referral: 'המלצה', manual: 'ידני',
};
export const ACTOR: Record<string, string> = { agent: 'סוכן AI', user: 'נציג', system: 'מערכת', customer: 'לקוח' };
export const DIET: Record<string, string> = {
  vegan: 'טבעוני', vegetarian: 'צמחוני', gluten_free: 'ללא גלוטן', nut_free: 'ללא אגוזים', lactose_free: 'ללא לקטוז',
};

export function dietLabel(d: string): string {
  const [tag, n] = d.split(':');
  return `${DIET[tag] ?? tag}${n ? ' ×' + n : ''}`;
}

export const QUOTE_STATUS: Record<string, string> = {
  draft: 'טיוטה', sent: 'נשלחה', approved: 'אושרה', rejected: 'נדחתה', expired: 'פגה',
};
export const UNIT: Record<string, string> = { per_guest: 'לסועד', unit: "יח'", tray: 'מגש', kg: 'ק"ג', hour: 'שעות' };
export const LINE_SOURCE: Record<string, string> = { requested: 'ביקש הלקוח', suggested: 'הצעת AI', rule: 'אוטומטי' };
export const CONFIDENCE: Record<string, string> = { high: 'גבוהה', medium: 'לבדיקה', low: 'לא ודאי', rule: 'כלל' };
