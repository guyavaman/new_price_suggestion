import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { CATEGORY } from '../core/labels';
import { BusinessSettings, CatalogItem, DeliveryWindow, DeliveryZone, PortionRule } from '../core/models';

const PORTIONED = ['salad', 'starter', 'main', 'side', 'canape', 'breakfast', 'dessert', 'drink', 'bar'];

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="page-head"><div><h1>הגדרות העסק</h1><p>הכללים שלפיהם המערכת מתמחרת, בודקת זמינות ושולחת תזכורות</p></div></div>
    @if (s(); as s) {
      <form class="grid" (ngSubmit)="save()">
        <section class="card">
          <h2>פרטי העסק</h2>
          <div class="fields">
            <label>שם העסק<input name="bn" [(ngModel)]="s.business_name"></label>
            <label>טלפון<input name="ph" [(ngModel)]="s.phone"></label>
            <label>מייל<input name="em" type="email" [(ngModel)]="s.email"></label>
            <label>ח.פ / עוסק מורשה<input name="bid" [(ngModel)]="s.business_id"></label>
          </div>
        </section>
        <section class="card">
          <h2>צוות ותמחור</h2>
          <div class="fields">
            <label>מלצר לכל X אורחים<input name="wr" type="number" min="1" [(ngModel)]="s.waiter_ratio"></label>
            <label>מלצרים אוטומטית מ-X אורחים<input name="aw" type="number" min="1" [(ngModel)]="s.auto_waiters_from"></label>
            <label>מנהל אירוע מ-X אורחים<input name="hw" type="number" min="1" [(ngModel)]="s.head_waiter_from"></label>
            <label>ברמן לכל X אורחים<input name="br" type="number" min="1" [(ngModel)]="s.bartender_ratio"></label>
            <label>שעות עבודה לאירוע<input name="sh" type="number" min="1" [(ngModel)]="s.staff_hours"></label>
            <label>יחידות קבלת פנים לאורח<input name="cp" type="number" min="1" [(ngModel)]="s.canapes_per_guest"></label>
            <label>מע"מ (%)<input name="vat" type="number" min="0" max="50" step="0.5" [ngModel]="pct(s.vat_rate)" (ngModelChange)="s.vat_rate = $event / 100"></label>
          </div>
          <h3>הנחות כמות</h3>
          @for (d of s.volume_discounts; track $index) {
            <div class="disc">מעל ₪<input [name]="'dm' + $index" type="number" min="1" [(ngModel)]="d.min_subtotal">
              הנחה של <input [name]="'dr' + $index" type="number" min="0" max="50" [ngModel]="pct(d.rate)" (ngModelChange)="d.rate = $event / 100">%
              <button type="button" class="btn ghost sm" (click)="s.volume_discounts.splice($index, 1)">הסר</button></div>
          }
          <button type="button" class="btn ghost sm" (click)="s.volume_discounts.push({ min_subtotal: 100000, rate: 0.1 })">+ הנחה</button>
        </section>
        <section class="card" aria-labelledby="dl-h">
          <h2 id="dl-h">משלוח</h2>
          <p class="muted">האזור נקבע לפי המרחק (אם הוזן באירוע), אחרת לפי מילה בכתובת, אחרת אזור ברירת המחדל. המחיר והעלות של כל אזור באים מפריט המשלוח בתפריט.</p>
          <div class="tw"><table class="zones">
            <thead><tr><th>אזור</th><th>מחיר מפריט</th><th>עד ק"מ</th><th>מילים בכתובת</th><th>ברירת מחדל</th><th></th></tr></thead>
            <tbody>
              @for (z of s.delivery_zones; track $index) {
                <tr>
                  <td><input [name]="'zn' + $index" [(ngModel)]="z.name" maxlength="60" aria-label="שם האזור"></td>
                  <td><select [name]="'zs' + $index" [ngModel]="zoneItem(z)" (ngModelChange)="setZoneItem(z, $event)" aria-label="פריט משלוח">
                    <option value="role:delivery_center">משלוח מרכז (לפי תפקיד)</option>
                    <option value="role:delivery_remote">משלוח מרוחק (לפי תפקיד)</option>
                    @for (i of deliveryItems(); track i.sku) { <option [value]="'sku:' + i.sku">{{ i.name_he }} · ₪{{ i.price }}</option> }
                  </select></td>
                  <td><input [name]="'zk' + $index" type="number" min="1" max="1000" [(ngModel)]="z.max_km" placeholder="—" aria-label="עד ק״מ"></td>
                  <td><input [name]="'zw' + $index" class="wide" [ngModel]="z.keywords.join(', ')" (ngModelChange)="z.keywords = split($event)" aria-label="מילים בכתובת"></td>
                  <td><input type="radio" name="zdef" [checked]="z.default" (change)="setDefaultZone(s, $index)" aria-label="ברירת מחדל"></td>
                  <td><button type="button" class="btn ghost sm" (click)="s.delivery_zones.splice($index, 1)" [disabled]="s.delivery_zones.length < 2">הסר</button></td>
                </tr>
              }
            </tbody>
          </table></div>
          <button type="button" class="btn ghost sm" (click)="addZone(s)">+ אזור</button>
          <h3>תוספת לפי שעה</h3>
          <div class="tw"><table class="zones">
            <thead><tr><th>שם</th><th>משעה</th><th>עד שעה</th><th>ימים</th><th>מחיר (₪)</th><th>עלות (₪)</th><th></th></tr></thead>
            <tbody>
              @for (w of s.delivery_windows; track $index) {
                <tr>
                  <td><input [name]="'wn' + $index" [(ngModel)]="w.name" maxlength="60" aria-label="שם"></td>
                  <td><input [name]="'ws' + $index" type="time" [(ngModel)]="w.start" aria-label="משעה"></td>
                  <td><input [name]="'we' + $index" type="time" [(ngModel)]="w.end" aria-label="עד שעה"></td>
                  <td class="days">@for (d of dayNames; track $index; let i = $index) {
                    <label class="chk"><input type="checkbox" [checked]="w.days.includes(i)" (change)="toggleDay(w, i)">{{ d }}</label> }
                    @if (!w.days.length) { <small class="muted">כל יום</small> }</td>
                  <td><input [name]="'wp' + $index" type="number" min="0" [(ngModel)]="w.price" aria-label="מחיר"></td>
                  <td><input [name]="'wc' + $index" type="number" min="0" [(ngModel)]="w.cost" placeholder="לא ידוע" aria-label="עלות"></td>
                  <td><button type="button" class="btn ghost sm" (click)="s.delivery_windows.splice($index, 1)">הסר</button></td>
                </tr>
              }
            </tbody>
          </table></div>
          <button type="button" class="btn ghost sm" (click)="addWindow(s)">+ תוספת לפי שעה</button>
          <p class="muted small">התוספת נכנסת רק כשידועה שעת ההגעה באירוע. חלון יכול לעבור את חצות (22:00 עד 06:00).</p>
        </section>
        <section class="card" aria-labelledby="tr-h">
          <h2 id="tr-h">תנאי הזמנה</h2>
          <label class="chk"><input type="checkbox" name="rt" [(ngModel)]="s.require_terms"> הלקוח מאשר את התנאים בקישור לפני תשלום המקדמה</label>
          <h3>מדיניות ביטולים</h3>
          @for (c of s.cancellation_policy; track $index) {
            <div class="disc">ביטול <input [name]="'cd' + $index" type="number" min="0" max="365" [(ngModel)]="c.days_before"> ימים או יותר לפני האירוע: מוחזרים
              <input [name]="'cr' + $index" type="number" min="0" max="100" [ngModel]="pct(c.refund_rate)" (ngModelChange)="c.refund_rate = $event / 100">% מהמקדמה
              <button type="button" class="btn ghost sm" (click)="s.cancellation_policy.splice($index, 1)">הסר</button></div>
          }
          <button type="button" class="btn ghost sm" (click)="s.cancellation_policy.push({ days_before: 7, refund_rate: 0.25 })">+ שלב</button>
          <h3>שורות נוספות (שורה לכל תנאי)</h3>
          <textarea name="tx" rows="3" class="wide" [ngModel]="s.terms_extra.join('\n')" (ngModelChange)="s.terms_extra = lines($event)" placeholder="למשל: חניה לרכב המשלוח באחריות הלקוח"></textarea>
          @if (terms(); as t) {
            <details><summary>איך הלקוח רואה את התנאים (אחרי שמירה)</summary>
              <ul class="tlist">@for (l of t.lines; track $index) { <li>{{ l }}</li> }</ul></details>
          }
          <p class="muted small">נעילת אורחים, תוספת האיחור, נעילת המנות, המקדמה והתוקף נלקחים מההגדרות שבעמוד הזה, כך שהלקוח מאשר בדיוק את מה שהמערכת אוכפת.</p>
        </section>
        <section class="card" aria-labelledby="cr-h">
          <h2 id="cr-h">לקוחות חוזרים וציון לידים</h2>
          <div class="fields">
            <label>תזכורת ללקוח עסקי שלא הזמין (ימים)<input name="rr" type="number" min="7" max="730" [(ngModel)]="s.reorder_reminder_days"></label>
          </div>
          <h3>נקודות לכל סימן בציון ליד (70 ומעלה = חם)</h3>
          <div class="fields">
            @for (k of scoreKeys; track k[0]) {
              <label>{{ k[1] }}<input [name]="'sw' + k[0]" type="number" min="0" max="100" [ngModel]="s.score_weights[k[0]]" (ngModelChange)="s.score_weights[k[0]] = +$event"></label>
            }
          </div>
        </section>
        <section class="card">
          <h2>קיבולת</h2>
          <div class="fields">
            <label>מקסימום אירועים ביום<input name="me" type="number" min="1" [(ngModel)]="s.max_events_per_day"></label>
            <label>מקסימום אורחים ביום<input name="mg" type="number" min="1" [(ngModel)]="s.max_guests_per_day"></label>
          </div>
        </section>
        <section class="card">
          <h2>רווחיות ועלויות</h2>
          <div class="fields">
            <label>רצפת רווח גולמי (%)<input name="pf" type="number" min="0" max="95" [ngModel]="pct(s.profit_floor)" (ngModelChange)="s.profit_floor = $event / 100"></label>
            <label>התראה על עליית עלות מעל (%)<input name="ct" type="number" min="0" max="100" [ngModel]="pct(s.cost_alert_threshold)" (ngModelChange)="s.cost_alert_threshold = $event / 100"></label>
          </div>
          <p class="muted">הצעה מתחת לרצפה או עם עלות חסרה תדרוש אישור לפני שליחה, ונועה תעביר אותה אליך במקום לתת מחיר.</p>
        </section>
        <section class="card" aria-labelledby="por-h">
          <h2 id="por-h">מנות וכמויות</h2>
          <p class="muted small">כמה מקבל כל סועד מכל קטגוריה כשיש מנה אחת ממנה. כשיש כמה מנות מאותה קטגוריה, כל מנה מוסיפה אחוז מהכמות, והכמות מתחלקת ביניהן.
            מזה מחושבים מגשים, כמויות למטבח ועלות החבילה.</p>
          <div class="por-wrap">
            <table class="por">
              <thead><tr><th>קטגוריה</th><th>נמדד ב</th><th>לסועד, מנה אחת</th><th>תוספת לכל מנה נוספת</th><th>לדוגמה</th><th></th></tr></thead>
              <tbody>
                @for (k of ruleKeys(s); track k) {
                  @let r = s.portion_rules[k];
                  <tr>
                    <td data-l="קטגוריה">{{ catLabel[k] || k }}</td>
                    <td data-l="נמדד ב"><select [name]="'pm' + k" [(ngModel)]="r.measure" [attr.aria-label]="'יחידת מידה ' + (catLabel[k] || k)"><option value="g">גרם</option><option value="unit">מנות / יחידות</option></select></td>
                    <td data-l="לסועד, מנה אחת"><input [name]="'pt' + k" type="number" min="0.01" step="any" [(ngModel)]="r.total_per_guest" [attr.aria-label]="'כמות לסועד ' + (catLabel[k] || k)"></td>
                    <td data-l="תוספת לכל מנה נוספת"><span class="pctin"><input [name]="'pe' + k" type="number" min="0" max="100" [ngModel]="pct(r.extra_per_variety)" (ngModelChange)="r.extra_per_variety = $event / 100" [attr.aria-label]="'תוספת גיוון ' + (catLabel[k] || k)">%</span></td>
                    <td data-l="לדוגמה" class="muted small">{{ example(r) }}</td>
                    <td><button type="button" class="linkish" (click)="removeRule(s, k)" [attr.aria-label]="'מחיקת הכלל ל' + (catLabel[k] || k)">מחיקה</button></td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          @if (missingRules(s).length) {
            <label class="addrule">כלל לקטגוריה נוספת
              <select name="newrule" [ngModel]="''" (ngModelChange)="addRule(s, $event)"><option value="">בחירה…</option>
                @for (c of missingRules(s); track c) { <option [value]="c">{{ catLabel[c] || c }}</option> }</select></label>
          }
          <div class="fields">
            <label>עלות חבילה בתפריט מחושבת ל-(סועדים)<input name="rg" type="number" min="1" max="5000" [(ngModel)]="s.reference_guests"></label>
            <label>הלקוח יכול לבחור מנות עד (ימים לפני האירוע)<input name="ml" type="number" min="0" max="90" [(ngModel)]="s.menu_lock_days"></label>
            <label>חומרי גלם מגיעים (ימים לפני ההכנה)<input name="db" type="number" min="0" max="7" [(ngModel)]="s.delivery_buffer_days"></label>
          </div>
        </section>
        <section class="card" aria-labelledby="ln-h">
          <h2 id="ln-h">סגירת אירוע ולמידה</h2>
          <p class="muted">אחרי כל אירוע מסמנים כמה נשאר מכל מנה. מזה המערכת מציעה כמות בסיס חדשה לסועד, ולא משנה אותה בלי אישור שלך.</p>
          <h3>כמה מהכמות נאכל, לפי הסימון</h3>
          <div class="fields">
            <label>"נשאר הרבה" (%)<input name="lcl" type="number" min="10" max="100" [ngModel]="pct(s.leftover_consumption['lot'])" (ngModelChange)="s.leftover_consumption['lot'] = $event / 100"></label>
            <label>"סביר" (%)<input name="lco" type="number" min="50" max="150" [ngModel]="pct(s.leftover_consumption['ok'])" (ngModelChange)="s.leftover_consumption['ok'] = $event / 100"></label>
            <label>"נגמר" (%)<input name="lcx" type="number" min="100" max="200" [ngModel]="pct(s.leftover_consumption['out'])" (ngModelChange)="s.leftover_consumption['out'] = $event / 100"></label>
          </div>
          <div class="fields">
            <label>להציע רק אחרי (אירועים עם סיכום)<input name="lme" type="number" min="1" max="50" [(ngModel)]="s.learning_min_events"></label>
            <label>להציע רק שינוי של לפחות (%)<input name="lmc" type="number" min="0" max="100" [ngModel]="pct(s.learning_min_change)" (ngModelChange)="s.learning_min_change = $event / 100"></label>
            <label>לפי האירועים האחרונים (כמה)<input name="lw" type="number" min="1" max="100" [(ngModel)]="s.learning_window"></label>
            <label>לבקש סיכום עד (ימים אחרי האירוע)<input name="cwd" type="number" min="1" max="90" [(ngModel)]="s.closing_window_days"></label>
          </div>
        </section>
        <section class="card" aria-labelledby="st-h">
          <h2 id="st-h">סגנון הגשה, נעילה ושינויים מאוחרים</h2>
          <h3>מלצרים לפי סגנון הגשה</h3>
          <div class="fields">
            @for (k of styleKeys; track k[0]) {
              @if (s.style_staffing[k[0]]; as st) {
                <label>{{ k[1] }}: מלצר לכל<input [name]="'sw' + k[0]" type="number" min="1" [(ngModel)]="st.waiter_ratio"></label>
                @if (k[0] === 'chef_station') { <label>שף במקום: אחד לכל (אורחים)<input name="chefr" type="number" min="1" [(ngModel)]="st.chef_ratio"></label> }
              }
            }
            <label>בלי סגנון: מלצר לכל<input name="wr0" type="number" min="1" [(ngModel)]="s.waiter_ratio"></label>
          </div>
          <h3>נעילה</h3>
          <div class="fields">
            <label>מספר האורחים ננעל (ימים לפני האירוע)<input name="gl" type="number" min="0" max="60" [(ngModel)]="s.guest_lock_days"></label>
            <label>תוספת על אורחים שנוספו אחרי הנעילה (%)<input name="lgs" type="number" min="0" max="200" [ngModel]="pct(s.late_guest_surcharge)" (ngModelChange)="s.late_guest_surcharge = $event / 100"></label>
            <label class="chk"><input name="ldc" type="checkbox" [(ngModel)]="s.late_decrease_charged"> הפחתת אורחים אחרי הנעילה: החיוב נשאר לפי הכמות שננעלה</label>
          </div>
          <p class="muted">אחרי הנעילה, שינוי של הלקוח בקישור (אורחים או מנות) לא מתבצע מיד: הוא מגיע אליך לאישור במסך "היום".</p>
          <h3>תזכורות אוטומטיות</h3>
          <div class="fields">
            <label class="chk"><input name="ae" type="checkbox" [(ngModel)]="s.automation_enabled"> להריץ תזכורות כל יום</label>
            <label>בשעה<input name="ah" type="number" min="0" max="23" [(ngModel)]="s.automation_hour"></label>
            <label>תזכורת יתרה (ימים לפני)<input name="brd" type="number" min="0" max="60" [(ngModel)]="s.balance_reminder_days"></label>
          </div>
        </section>
        <section class="card">
          <h2>הצעות, מקדמה ותזכורות</h2>
          <div class="fields">
            <label>תוקף הצעה (ימים)<input name="qv" type="number" min="1" [(ngModel)]="s.quote_valid_days"></label>
            <label>מקדמה לאישור (%)<input name="dp" type="number" min="0" max="100" [ngModel]="pct(s.deposit_rate)" (ngModelChange)="s.deposit_rate = $event / 100"></label>
            <label>מעקב על הצעה שלא נענתה אחרי (ימים)<input name="fu" type="number" min="1" [(ngModel)]="s.followup_after_days"></label>
            <label>בקשת מספר אורחים סופי (ימים לפני)<input name="fc" type="number" min="1" [(ngModel)]="s.final_count_days_before"></label>
            <label>חשבוניות
              <select name="ip" [(ngModel)]="s.invoice_provider"><option value="manual">ידני (מזינים מספר)</option><option value="morning">חשבונית ירוקה (Morning)</option></select></label>
            <label>תשלומים
              <select name="pp" [(ngModel)]="s.payment_provider"><option value="demo">דמו (בלי חיוב אמיתי)</option></select></label>
            <label class="span">כתובת דף הלקוח<input name="pb" dir="ltr" [(ngModel)]="s.public_base_url"></label>
          </div>
        </section>
        <section class="card">
          <h2>שירות לקוחות (נועה)</h2>
          <p class="muted">לקוחות ששואלים בצ'אט שבעמוד ההצעה שלהם מקבלים תשובה מהמידע הזה. מה שלא כתוב כאן, נועה מעבירה אליך.</p>
          <textarea name="si" rows="7" [(ngModel)]="s.service_info" placeholder="כשרות, שעות הגעה, תשלום יתרה, שאריות, ביטולים…"></textarea>
        </section>
        <div class="bar"><button class="btn" [disabled]="saving()">{{ saving() ? 'שומר…' : 'שמירה' }}</button>
          @if (msg()) { <span [class.bad]="bad()">{{ msg() }}</span> }</div>
      </form>
    }
  `,
  styles: [`
    section.card, form, .grid { min-width: 0; }
    .tw { overflow-x: auto; max-width: 100%; } .zones { width: 100%; border-collapse: collapse; } .zones th { text-align: start; font-size: .78rem; color: var(--muted); font-weight: 600; padding: 4px; }
    .zones td { padding: 4px; vertical-align: middle; } .zones input:not([type=radio]):not([type=checkbox]), .zones select { width: 100%; min-width: 70px; }
    .days { white-space: nowrap; min-width: 250px; } .chk { display: inline-flex; gap: 3px; align-items: center; margin-inline-end: 6px; font-size: .84rem; }
    .tlist { margin: 6px 0 0; padding-inline-start: 20px; font-size: .9rem; display: grid; gap: 3px; }
    form.grid { max-width: 920px; }
    textarea { width: 100%; box-sizing: border-box; line-height: 1.6; resize: vertical; }
    h2 { margin-bottom: 10px; } h3 { font-size: 1rem; margin: 14px 0 6px; }
    .fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
    label { display: grid; gap: 4px; font-size: .88rem; color: var(--muted); } label.span { grid-column: 1 / -1; }
    label input, label select { color: var(--ink); }
    .disc { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; } .disc input { width: 90px; }
    .wide { width: 100%; } .sm { padding: 4px 10px; font-size: .85rem; }
    .bar { position: sticky; bottom: 0; background: var(--bg); padding: 10px 0; display: flex; gap: 12px; align-items: center; }
    .bad { color: var(--bad); }
    .small { font-size: .82rem; }
    .por-wrap { overflow-x: auto; margin: 8px 0; }
    .por { width: 100%; border-collapse: collapse; font-size: .9rem; }
    .por th { text-align: start; font-size: .78rem; color: var(--muted); font-weight: 600; padding: 4px 6px; }
    .por td { padding: 5px 6px; border-top: 1px solid var(--line); }
    .por input { width: 90px; } .pctin { display: inline-flex; gap: 4px; align-items: center; } .pctin input { width: 64px; }
    .linkish { background: none; border: 0; padding: 0; color: var(--bad); text-decoration: underline; font: inherit; font-size: .85rem; cursor: pointer; }
    .addrule { max-width: 260px; margin-bottom: 10px; }
    label.chk { display: flex; gap: 8px; align-items: center; color: var(--ink); }
    @media (max-width: 640px) {
      .por thead { display: none; }
      .por tr { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; padding: 8px 0; border-top: 1px solid var(--line); }
      .por td { border: 0; padding: 2px 0; }
      .por td:first-child { grid-column: 1 / -1; font-weight: 700; }
      .por td[data-l]:not(:first-child)::before { content: attr(data-l); display: block; font-size: .72rem; color: var(--muted); }
    }
  `],
})
export class SettingsComponent {
  private api = inject(ApiService);
  s = signal<BusinessSettings | null>(null);
  saving = signal(false); msg = signal(''); bad = signal(false);
  constructor() {
    this.api.settings().subscribe((s) => this.s.set(structuredClone(s)));
    this.api.termsPreview().subscribe((t) => this.terms.set(t));
    this.api.catalog().subscribe((c) => this.catalogItems.set(c));
  }
  pct(v: number) { return Math.round(v * 1000) / 10; }
  catLabel = CATEGORY;
  styleKeys: [string, string][] = [['buffet', 'מזנון'], ['plated', 'הגשה לשולחן'], ['finger', 'פינגר פוד'], ['chef_station', 'שף במקום']];
  ruleKeys(s: BusinessSettings) { return PORTIONED.filter((k) => s.portion_rules[k]).concat(Object.keys(s.portion_rules).filter((k) => !PORTIONED.includes(k))); }
  missingRules(s: BusinessSettings) { return PORTIONED.filter((k) => !s.portion_rules[k]); }
  addRule(s: BusinessSettings, k: string) { if (k) s.portion_rules = { ...s.portion_rules, [k]: { measure: 'unit', total_per_guest: 1, extra_per_variety: 0.2 } }; }
  removeRule(s: BusinessSettings, k: string) { const { [k]: _, ...rest } = s.portion_rules; s.portion_rules = rest; }
  example(r: PortionRule) {
    const per = (n: number) => r.total_per_guest * (1 + r.extra_per_variety * (n - 1)) / n;
    const f = (v: number) => r.measure === 'g' ? `${Math.round(v)} גרם` : `${v.toLocaleString('he-IL', { maximumFractionDigits: 2 })}`;
    return `1 מנה: ${f(per(1))} · 3 מנות: ${f(per(3))} כל אחת`;
  }
  split(v: string) { return v.split(',').map((x) => x.trim()).filter(Boolean); }
  lines(v: string) { return v.split('\n').map((x) => x.trim()).filter(Boolean); }
  dayNames = ['א׳', 'ב׳', 'ג׳', 'ד׳', 'ה׳', 'ו׳', 'ש׳'];
  scoreKeys: [string, string][] = [
    ['opened', 'פתח את ההצעה'], ['opened_again', 'חזר להצעה 3+ פעמים'], ['pdf', 'הוריד PDF'], ['asked_human', 'ביקש נציג'],
    ['asked_price', 'שאל על מחיר'], ['asked_date', 'שאל על תאריך'], ['quote', 'ביקש הצעת מחיר'], ['soon', 'אירוע בתוך 60 יום'],
    ['big', 'אירוע גדול (80+)'], ['contact', 'יש טלפון או מייל'], ['date', 'תאריך ידוע'], ['guests', 'מספר אורחים ידוע'],
    ['budget', 'ציין תקציב'], ['details', 'כשרות וסוג ארוחה ידועים']];
  terms = signal<{ lines: string[]; version: string } | null>(null);
  catalogItems = signal<CatalogItem[]>([]);
  deliveryItems() { return this.catalogItems().filter((i) => i.category === 'logistics' && /משלוח|delivery/i.test(i.name_he + ' ' + (i.name_en ?? ''))); }
  zoneItem(z: DeliveryZone) { return z.sku ? 'sku:' + z.sku : 'role:' + (z.role ?? 'delivery_center'); }
  setZoneItem(z: DeliveryZone, v: string) { const [k, val] = v.split(':'); z.sku = k === 'sku' ? val : null; z.role = k === 'role' ? val : null; }
  setDefaultZone(s: BusinessSettings, i: number) { s.delivery_zones.forEach((z, j) => z.default = j === i); }
  addZone(s: BusinessSettings) {
    const n = s.delivery_zones.length + 1;
    s.delivery_zones.push({ id: 'zone' + n + '-' + Date.now().toString(36), name: 'אזור ' + n, sku: null, role: 'delivery_remote', keywords: [], max_km: null, default: false });
  }
  addWindow(s: BusinessSettings) {
    s.delivery_windows.push({ id: 'w' + Date.now().toString(36), name: 'תוספת', start: '20:00', end: '23:00', days: [], price: 100, cost: null });
  }
  toggleDay(w: DeliveryWindow, d: number) { w.days = w.days.includes(d) ? w.days.filter((x) => x !== d) : [...w.days, d].sort(); }
  save() {
    const s = this.s();
    if (!s) return;
    this.saving.set(true);
    this.api.saveSettings(s).subscribe({
      next: (r) => { this.s.set(structuredClone(r)); this.saving.set(false); this.bad.set(false); this.msg.set('נשמר ✓ ההצעות הבאות יתומחרו לפי ההגדרות החדשות'); this.api.termsPreview().subscribe((t) => this.terms.set(t)); },
      error: (e) => { this.saving.set(false); this.bad.set(true); const d = e.error?.detail; this.msg.set('לא נשמר: ' + (typeof d === 'string' ? d.slice(0, 160) : 'ערך לא תקין')); },
    });
  }
}
