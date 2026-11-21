import { EventClosingComponent } from '../core/event-closing.component';
import { EventEquipmentComponent } from '../core/event-equipment.component';
import { EventStaffComponent } from '../core/event-staff.component';
import { PackageMenuComponent } from '../core/package-menu.component';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe, RelativePipe } from '../core/format';
import { ACTOR, EVENT_TYPE, KASHRUT, MEAL, QUOTE_STATUS, REJECT_REASONS, SOURCE, STAGES, TEMP, dietLabel } from '../core/labels';
import { BusinessSettings, CustomerMessage, DealDetail, DealStage, DealMenu, Readiness } from '../core/models';

@Component({
  selector: 'app-deal-detail',
  standalone: true,
  imports: [RouterLink, FormsModule, IlsPipe, HeDatePipe, RelativePipe, PackageMenuComponent, EventStaffComponent, EventEquipmentComponent, EventClosingComponent],
  template: `
    <a routerLink="/events" class="back">→ כל האירועים</a>
    @if (error()) { <div class="err">{{ error() }}</div> }
    @if (x(); as x) {
      <div class="page-head">
        <div>
          <h1>{{ x.deal.title }}</h1>
          <p>
            <span class="temp temp-{{ x.deal.temperature }}">{{ temp[x.deal.temperature] }}</span>
            @if (x.deal.ready_to_book) { <span class="pill hot">רוצה לסגור</span> }
            @if (x.deal.source === 'web_chat') { <span class="pill ai">הגיע מסוכן AI</span> } @else { <span class="pill">{{ source[x.deal.source] }}</span> }
            <span class="muted">נפתח {{ x.deal.created_at | rel }}</span>
          </p>
        </div>
        <div class="stages" role="group" aria-label="שלב">
          @for (s of stages; track s.key) {
            <button class="st stage-{{ s.key }}" [class.on]="x.deal.stage === s.key" (click)="move(s.key)">{{ s.label }}</button>
          }
        </div>
      </div>
      @if (askLost()) {
        <form class="card lostbox" (ngSubmit)="confirmLost()">
          <label for="lr">למה האירוע לא יצא לפועל?</label>
          <div class="reason-chips">@for (r of reasons; track r) { <button type="button" class="chip" (click)="lostReason = r">{{ r }}</button> }</div>
          <input id="lr" name="lr" [(ngModel)]="lostReason" placeholder="או כתבו סיבה אחרת">
          <button class="btn danger" [disabled]="!lostReason.trim()">סמן כאבוד</button>
          <button class="btn ghost" type="button" (click)="askLost.set(false)">ביטול</button>
        </form>
      }

      <div class="layout">
        <div class="grid">
          <section class="card facts">
            <div><span>ערך</span><b class="num">{{ x.deal.value | ils }}</b></div>
            <div><span>תאריך</span><b>{{ x.deal.event_date | heDate }}</b><small class="muted">{{ x.deal.event_date | rel }}</small></div>
            <div><span>אורחים</span><b class="num">{{ x.deal.final_guest_count ?? x.deal.guest_count ?? '—' }}</b>
              <small [class.ok]="x.deal.final_guest_count" class="muted">{{ x.deal.final_guest_count ? 'סופי, אושר ע"י הלקוח' : 'עוד לא סופי' }}</small></div>
            <div><span>ארוחה</span><b>{{ meal[x.deal.meal_type ?? ''] || '—' }} · {{ kashrut[x.deal.kashrut ?? ''] || '—' }}</b></div>
            <div><span>סוג</span><b>{{ eventType[x.deal.event_type ?? ''] || '—' }}</b></div>
            <div><span>מיקום</span><b>{{ x.deal.location || '—' }}</b></div>
            @if (x.deal.dietary.length) { <div><span>תזונה</span><b>{{ diets(x.deal.dietary) }}</b></div> }
            @if (x.deal.budget) { <div><span>תקציב</span><b class="num">{{ x.deal.budget | ils }} {{ x.deal.budget_scope === 'per_guest' ? 'לאורח' : '' }}</b></div> }
          </section>

          @if (rd(); as r) {
            <section class="card ready" id="readiness" aria-labelledby="rd-h">
              <div class="h"><h2 id="rd-h">מוכנות לאירוע</h2>
                <span class="rmeter" [attr.aria-label]="r.done + ' מתוך ' + r.total"><i [style.width.%]="r.done / r.total * 100"></i></span>
                <b class="num" [class.okc]="r.ready">{{ r.done }}/{{ r.total }}{{ r.ready ? ' · מוכן ✓' : '' }}</b></div>

              <label class="style">סגנון הגשה
                <select (change)="setStyle($any($event.target).value)" aria-describedby="style-n">
                  <option value="" [selected]="!x.deal.service_style">לא נקבע</option>@for (s of styles; track s[0]) { <option [value]="s[0]" [selected]="x.deal.service_style === s[0]">{{ s[1] }}</option> }
                </select>
                <small id="style-n" class="muted">קובע את יחס המלצרים (בהגדרות) ומעדכן את המחיר</small></label>

              @for (c of pendingChanges(); track c.id) {
                <div class="chg" role="alert"><b>הלקוח ביקש אחרי הנעילה:</b> {{ c.summary }}
                  <span class="acts"><button class="btn sm" (click)="decide(c.id, 'approve')">אישור</button><button class="btn ghost sm" (click)="decide(c.id, 'decline')">דחייה</button></span>
                  <small class="muted">באישור, המחיר מחושב לפי מדיניות השינויים בהגדרות</small></div>
              }

              <ul class="checks">
                @for (i of r.items; track i.key) {
                  <li [class.ok]="i.ok">
                    <span class="mark" aria-hidden="true">{{ i.ok ? '✓' : '✗' }}</span>
                    <span><b>{{ i.label }}</b><small class="muted"> · {{ i.detail }}</small></span>
                    @if (i.action; as a) {
                      @switch (a.kind) {
                        @case ('whatsapp') { <a class="btn sm" [href]="a.url" target="_blank" rel="noopener">{{ a.label }}</a> }
                        @case ('link') { <a class="btn ghost sm" [routerLink]="a.url">{{ a.label }}</a> }
                        @case ('mark') { <button class="btn ghost sm" type="button" (click)="markReady(a.target!, true)">{{ a.label }}</button> }
                        @case ('edit') { <button class="btn ghost sm" type="button" (click)="siteOpen.set(true)">{{ a.label }}</button> }
                      }
                    } @else if (i.key === 'staff' || i.key === 'equipment') {
                      @if (i.ok && i.detail !== 'אין ציוד בהזמנה') { <button class="linkish" type="button" (click)="markReady(i.key, false)">ביטול הסימון</button> }
                    }
                  </li>
                }
              </ul>

              <button class="linkish" type="button" (click)="siteOpen.set(!siteOpen())">{{ siteOpen() ? 'סגירת פרטי המקום' : 'פרטי המקום ותנאי שטח' }}</button>
              @if (siteOpen()) {
                <form class="site" (ngSubmit)="saveSite()">
                  <label>כתובת המקום<input name="loc" [(ngModel)]="siteForm.location" maxlength="200"></label>
                  <label>שעת הגעת האוכל<input name="et" type="time" [(ngModel)]="siteForm.event_time"></label>
                  <label>מרחק מהמטבח (ק"מ)<input name="km" type="number" min="1" max="1000" [(ngModel)]="siteForm.distance_km" placeholder="לא ידוע"></label>
                  <p class="hint">המיקום, השעה והמרחק קובעים את שורת המשלוח בהצעה. שינוי שלהם מעדכן את המחיר.</p>
                  <label>איש קשר במקום<input name="scn" [(ngModel)]="siteForm.site_contact_name" maxlength="80"></label>
                  <label>טלפון במקום<input name="scp" [(ngModel)]="siteForm.site_contact_phone" inputmode="tel" maxlength="30"></label>
                  <div class="conds">
                    @for (k of siteKeys; track k[0]) {
                      <fieldset><legend>{{ k[1] }}</legend>
                        @for (o of tri; track o[1]) {
                          <label class="tri"><input type="radio" [name]="'c' + k[0]" [checked]="siteForm.site[k[0]] === o[0]" (change)="siteForm.site[k[0]] = o[0]"> {{ o[1] }}</label>
                        }
                      </fieldset>
                    }
                  </div>
                  <button class="btn">שמירה</button>
                </form>
              }
            </section>
          }

          <section class="card">
            <div class="h"><h2>הצעת מחיר ותשלום</h2>
              @if (quote(); as q) { <a [routerLink]="['/quotes', q.id]">לפרטי ההצעה המלאים ←</a> }</div>
            @if (quote(); as q) {
              <div class="qh"><b>{{ q.number }}</b><span class="pill">{{ qStatus[q.status] }}</span><span class="muted">{{ q.created_at | heDate }}</span></div>
              <div class="tiers">
                @for (t of q.tiers; track t.key) {
                  <div class="tier" [class.sel]="t.key === q.selected_tier">
                    <span>{{ t.name }} @if (t.key === q.selected_tier && q.status === 'approved') { ✓ }</span>
                    <b class="num">{{ t.total | ils }}</b><small class="muted num">{{ t.per_guest | ils }} לאורח</small>
                  </div>
                }
              </div>
              <div class="link-row">
                <input readonly [value]="customerLink(q.public_token)" aria-label="קישור ללקוח" dir="ltr">
                <button class="btn" (click)="copyLink(q.public_token)">{{ copied() ? 'הועתק ✓' : 'העתק קישור ללקוח' }}</button>
                <a class="btn ghost" [href]="customerLink(q.public_token)" target="_blank" rel="noopener">תצוגת לקוח</a>
              </div>
              <p class="muted small">בקישור הלקוח בוחר חבילה, מאשר ומשלם מקדמה. בהמשך הוא מאשר בו מספר אורחים סופי.</p>
            } @else {
              <p class="muted">עוד אין הצעת מחיר. אפשר ליצור אחת מתיבת הפניות, או שהסוכנת תיצור כשיהיו מספיק פרטים.</p>
            }
            <h3>תשלומים</h3>
            <ul class="pays">
              @for (p of x.deal.payments; track p.id) {
                <li><span class="pill" [class.ok]="p.status === 'paid'" [class.warn]="p.status === 'pending'">{{ p.status === 'paid' ? 'שולם' : p.status === 'pending' ? 'ממתין' : 'נכשל' }}</span>
                  {{ p.kind === 'deposit' ? 'מקדמה' : 'יתרה' }} <b class="num">{{ p.amount | ils }}</b> <small class="muted">{{ (p.paid_at || p.created_at) | heDate: true }}</small></li>
              } @empty { <li class="muted">עוד לא התקבלו תשלומים</li> }
            </ul>
            @if (x.deal.value && x.deal.deposit_paid) { <p class="num">יתרה לתשלום: <b>{{ x.deal.value - x.deal.deposit_paid | ils }}</b></p> }

            <h3>חשבונית</h3>
            @if (x.deal.invoice; as inv) {
              <p>חשבונית <b><bdi class="ref">{{ inv.number }}</bdi></b> · {{ inv.amount | ils }} · {{ inv.issued_at | heDate }} @if (inv.url) { · <a [href]="inv.url" target="_blank" rel="noopener">פתיחה</a> }</p>
            } @else if (x.deal.stage === 'won' || x.deal.stage === 'completed') {
              <form class="inv" (ngSubmit)="invoice()">
                @if (settings()?.invoice_provider !== 'morning') {
                  <input name="n" [(ngModel)]="invoiceNumber" placeholder="מספר חשבונית מתוכנת החשבונות" aria-label="מספר חשבונית">
                }
                <button class="btn" [disabled]="settings()?.invoice_provider !== 'morning' && !invoiceNumber.trim()">
                  {{ settings()?.invoice_provider === 'morning' ? 'הפק חשבונית בחשבונית ירוקה' : 'שמור חשבונית' }}</button>
              </form>
            } @else { <p class="muted small">חשבונית מופקת אחרי שהאירוע נסגר</p> }
          </section>

          @if ((x.deal.stage === 'won' || x.deal.stage === 'completed') && isPast(x.deal.event_date)) {
            <section class="card" id="closing" aria-labelledby="cl-h">
              <div class="h"><h2 id="cl-h">סיכום אירוע: מתוכנן מול בפועל</h2><small class="muted">רק לך</small></div>
              <app-event-closing [dealId]="x.deal.id" />
            </section>
          }
          @if (x.deal.stage === 'won' || x.deal.stage === 'completed') {
            <section class="card" id="staff" aria-labelledby="st-h">
              <div class="h"><h2 id="st-h">צוות לאירוע</h2><small class="muted">רק לך</small></div>
              <app-event-staff [dealId]="x.deal.id" [past]="isPast(x.deal.event_date)" (changed)="refreshReady()" />
            </section>
            <section class="card" id="equipment" aria-labelledby="eq-h">
              <div class="h"><h2 id="eq-h">ציוד לאירוע</h2></div>
              <app-event-equipment [dealId]="x.deal.id" [past]="isPast(x.deal.event_date)" (changed)="refreshReady()" />
            </section>
          }

          @if (menu(); as m) {
            @if (m.packages.length) {
              <section class="card" aria-labelledby="dm-h">
                <div class="h"><h2 id="dm-h">תפריט האירוע</h2><small class="muted">{{ m.tier }} · {{ m.quote_number }} · רק לך</small></div>
                <app-package-menu [packages]="m.packages" [busy]="menuBusy()" (save)="saveMenu($event)" />
                @if (menuError()) { <p class="err" role="alert">{{ menuError() }}</p> }
              </section>
            }
          }

          <section class="card">
            <h2>ציר פעילות</h2>
            <form class="note" (ngSubmit)="addNote()">
              <input name="note" [(ngModel)]="note" placeholder="הוספת הערה או סיכום שיחה" aria-label="הערה">
              <select name="kind" [(ngModel)]="noteKind" aria-label="סוג"><option value="note">הערה</option><option value="call">שיחה</option></select>
              <button class="btn" [disabled]="!note.trim()">הוספה</button>
            </form>
            <ol class="timeline">
              @for (a of x.timeline; track a.id) {
                <li class="k-{{ a.kind }}"><span class="who">{{ actor[a.actor] }}</span><p>{{ a.text }}</p><time class="muted">{{ a.at | heDate: true }}</time></li>
              }
            </ol>
          </section>
        </div>

        <aside class="grid">
          @if (messages().length) {
            <section class="card msg">
              <h2>הודעה ללקוח</h2>
              <div class="chips">
                @for (m of messages(); track m.kind) {
                  <button type="button" class="chip" [class.on]="m.kind === pickedKind()" (click)="pickMessage(m)">
                    {{ m.label }}@if (m.recommended) { <span class="rec">מומלץ</span> }@if (x.deal.sent_messages?.[m.kind]) { ✓ }
                  </button>
                }
              </div>
              <textarea name="mt" rows="6" [(ngModel)]="messageText" aria-label="נוסח ההודעה"></textarea>
              <div class="msg-actions">
                @if (waBase()) { <a class="btn" [href]="waHref()" target="_blank" rel="noopener" (click)="markSent()">שליחה בוואטסאפ</a> }
                <button type="button" class="btn ghost" (click)="copyMessage()">{{ msgCopied() ? 'הועתק ✓' : 'העתקה' }}</button>
              </div>
              <p class="muted small">כל הודעה כוללת את הקישור האישי של הלקוח: שם הוא מאשר, משלם, מעדכן אורחים ושואל את נועה.</p>
            </section>
          }
          <section class="card">
            <h2>לקוח</h2>
            @if (x.customer; as c) {
              <p class="cname">{{ c.name || c.company || 'ללא שם' }}</p>
              @if (c.phone) { <p><a [href]="'tel:' + c.phone" dir="ltr">{{ c.phone }}</a></p> }
              @if (c.email) { <p><a [href]="'mailto:' + c.email">{{ c.email }}</a></p> }
            }
          </section>
          <section class="card">
            <h2>משימות</h2>
            <ul class="tasks">
              @for (t of x.tasks; track t.id) {
                <li [class.done]="t.done" [class.high]="t.priority === 'high'">
                  <input type="checkbox" [checked]="t.done" [disabled]="t.done" (change)="done(t.id)" [attr.aria-label]="t.title">
                  <span>{{ t.title }}<small class="muted">{{ t.due_at | rel }}</small></span>
                </li>
              } @empty { <li class="muted">אין משימות</li> }
            </ul>
            <form class="note" (ngSubmit)="addTask()"><input name="t" [(ngModel)]="task" placeholder="משימה חדשה" aria-label="משימה"><button class="btn ghost" [disabled]="!task.trim()">+</button></form>
          </section>
          <section class="card">
            <h2>למה {{ temp[x.deal.temperature] }}?</h2>
            <ul class="reasons">@for (r of x.deal.score_reasons; track r) { <li>{{ r }}</li> }</ul>
            @if (x.deal.signals; as sg) {
              @if (sg.quote_opens || sg.pdf_views) {
                <p class="muted small">פתח את ההצעה {{ sg.quote_opens }} פעמים@if (sg.last_opened_at) { , לאחרונה {{ sg.last_opened_at | rel }}}@if (sg.pdf_views) { · הוריד PDF {{ sg.pdf_views }} פעמים}</p>
              }
            }
          </section>
          @if (x.deal.terms; as tm) {
            <section class="card" aria-labelledby="tm-h">
              <h2 id="tm-h">תנאי ההזמנה אושרו</h2>
              <p class="muted small">{{ tm.accepted_at | heDate }}@if (tm.name) { · {{ tm.name }}} · גרסה <bdi>{{ tm.version }}</bdi></p>
              <details><summary>הנוסח שהלקוח אישר</summary><ul class="reasons">@for (l of tm.lines; track $index) { <li>{{ l }}</li> }</ul></details>
            </section>
          }
          @if (x.conversation; as conv) {
            <section class="card">
              <h2>שיחה עם הסוכנת</h2>
              <div class="chat">@for (m of conv.messages; track $index) { <div class="msg {{ m.role }}" [class.human]="m.by === 'human'">{{ m.text }}</div> }</div>
              <a [routerLink]="['/inbox']" [queryParams]="{ id: conv.id }">לפתוח בתיבת הפניות</a>
            </section>
          }
        </aside>
      </div>
    }
  `,
  styles: [`
    section.card { min-width: 0; }
    .ready { display: grid; gap: 10px; }
    .linkish { background: none; border: 0; padding: 0; color: var(--olive); text-decoration: underline; font: inherit; font-weight: 600; cursor: pointer; justify-self: start; }
    .ready .h { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .rmeter { flex: 1 1 80px; max-width: 160px; height: 8px; border-radius: 99px; background: var(--paper); overflow: hidden; } .rmeter i { display: block; height: 100%; background: var(--ok); }
    .okc { color: var(--ok); }
    .style { display: grid; gap: 3px; font-size: .88rem; color: var(--muted); max-width: 320px; } .style select { color: var(--ink); }
    .chg { background: var(--warn-soft); border-radius: 8px; padding: 8px 10px; display: grid; gap: 6px; } .chg .acts { display: flex; gap: 6px; }
    .checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
    .checks li { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 6px 8px; border-radius: 8px; background: var(--bad-soft); }
    .checks li.ok { background: var(--ok-soft); }
    .checks li > span:nth-child(2) { flex: 1 1 220px; }
    .checks .mark { font-weight: 800; width: 1.2em; text-align: center; color: var(--bad); } .checks li.ok .mark { color: var(--ok); }
    .btn.sm { padding: 4px 10px; font-size: .84rem; text-decoration: none; }
    .site { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
    .site label { display: grid; gap: 3px; font-size: .85rem; color: var(--muted); } .site input { color: var(--ink); }
    .conds { grid-column: 1 / -1; display: flex; gap: 10px; flex-wrap: wrap; }
    .conds fieldset { border: 1px solid var(--line); border-radius: 8px; padding: 4px 10px 8px; } .conds legend { font-size: .85rem; font-weight: 600; }
    .tri { display: inline-flex !important; gap: 4px; align-items: center; margin-inline-end: 8px; color: var(--ink) !important; }
    .site .btn { justify-self: start; }
    .back { display: inline-block; margin-bottom: 10px; text-decoration: none; }
    .page-head p { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .stages { display: flex; flex-wrap: wrap; gap: 4px; }
    .st { border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 4px 11px; font-size: .85rem; color: var(--ink); }
    .st.on { background: var(--st); border-color: var(--st); color: #fff; font-weight: 700; }
    .lostbox { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .lostbox input { flex: 1; min-width: 200px; }
    .msg { display: grid; gap: 10px; } .msg .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .msg textarea { width: 100%; box-sizing: border-box; line-height: 1.55; resize: vertical; }
    .msg-actions { display: flex; gap: 8px; } .msg-actions a.btn { text-decoration: none; }
    .chip.on { background: var(--olive-soft); border-color: var(--olive); }
    .rec { margin-inline-start: 4px; font-size: .72rem; background: var(--honey-soft); color: #8a5c06; border-radius: 99px; padding: 0 6px; }
    .reason-chips { display: flex; flex-wrap: wrap; gap: 6px; flex-basis: 100%; }
    .layout { display: grid; grid-template-columns: 1fr 320px; gap: 14px; align-items: start; }
    @media (max-width: 1000px) { .layout { grid-template-columns: 1fr; } }
    h2 { margin-bottom: 10px; } h3 { font-size: 1rem; margin: 14px 0 6px; }
    .h { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
    .facts div { display: grid; } .facts span { font-size: .78rem; color: var(--muted); }
    .ok { color: var(--ok) !important; }
    .qh { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
    .tiers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .tier { border: 1px solid var(--line); border-radius: 8px; padding: 10px; display: grid; gap: 2px; }
    .tier.sel { border: 2px solid var(--olive); background: var(--olive-soft); }
    .tier b { font-family: var(--display); font-size: 1.2rem; color: var(--olive); }
    .link-row { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
    .link-row input { flex: 1; min-width: 200px; font-size: .82rem; }
    .small { font-size: .85rem; }
    .pays { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
    .pill.ok { background: var(--ok-soft); color: var(--ok); }
    .inv { display: flex; gap: 6px; flex-wrap: wrap; } .inv input { flex: 1; min-width: 200px; }
    .note { display: flex; gap: 6px; margin-bottom: 10px; } .note input { flex: 1; min-width: 0; }
    .timeline { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; max-height: 420px; overflow: auto; }
    .timeline li { display: grid; grid-template-columns: 70px 1fr auto; gap: 8px; padding: 8px 6px; border-inline-start: 3px solid var(--line); }
    .timeline li p { margin: 0; } .timeline .who { font-size: .78rem; font-weight: 700; color: var(--muted); } .timeline time { font-size: .78rem; white-space: nowrap; }
    .k-stage { border-color: var(--olive) !important; } .k-quote { border-color: var(--honey) !important; } .k-handoff { border-color: var(--bad) !important; } .k-chat { border-color: #4f7cac !important; }
    .cname { font-weight: 700; font-size: 1.1rem; margin: 0 0 4px; } aside p { margin: 2px 0; }
    .reasons { margin: 0; padding-inline-start: 18px; font-size: .88rem; color: var(--muted); }
    .tasks { list-style: none; margin: 0 0 10px; padding: 0; display: grid; gap: 6px; }
    .tasks li { display: flex; gap: 8px; align-items: start; } .tasks li span { display: grid; }
    .tasks li.high span { font-weight: 700; } .tasks li.done span { text-decoration: line-through; color: var(--muted); }
    .chat { display: grid; gap: 6px; max-height: 300px; overflow: auto; margin-bottom: 8px; }
    .msg { padding: 7px 10px; border-radius: 10px; font-size: .9rem; max-width: 90%; }
    .msg.user { background: var(--bg); justify-self: start; } .msg.assistant { background: var(--honey-soft); justify-self: end; } .msg.human { background: var(--olive-soft); }
  `],
})
export class DealDetailComponent {
  private api = inject(ApiService);
  id = input.required<string>();
  x = signal<DealDetail | null>(null);
  settings = signal<BusinessSettings | null>(null);
  error = signal('');
  copied = signal(false);
  askLost = signal(false);
  stages = STAGES; meal = MEAL; kashrut = KASHRUT; eventType = EVENT_TYPE; source = SOURCE; actor = ACTOR;
  temp = TEMP; qStatus = QUOTE_STATUS;
  note = ''; noteKind = 'note'; task = ''; invoiceNumber = ''; lostReason = ''; reasons = REJECT_REASONS;
  messages = signal<CustomerMessage[]>([]);
  pickedKind = signal('');
  messageText = '';
  msgCopied = signal(false);
  waBase = computed(() => this.messages().find((m) => m.whatsapp_url)?.whatsapp_url?.split('?')[0] ?? null);
  waHref() { return `${this.waBase()}?text=${encodeURIComponent(this.messageText)}`; }
  pickMessage(m: CustomerMessage) { this.pickedKind.set(m.kind); this.messageText = m.text; }
  markSent() { const k = this.pickedKind(); if (k) this.api.messageSent(this.id(), k).subscribe(() => this.load()); }
  async copyMessage() {
    try { await navigator.clipboard.writeText(this.messageText); this.msgCopied.set(true); setTimeout(() => this.msgCopied.set(false), 2000); } catch { /* blocked */ }
    this.markSent();
  }
  quote = computed(() => { const q = this.x()?.quotes ?? []; return q[q.length - 1] ?? null; });

  constructor() {
    effect(() => this.load(this.id()), { allowSignalWrites: true });
    this.api.settings().subscribe((s) => this.settings.set(s));
  }
  menu = signal<DealMenu | null>(null);
  menuBusy = signal(false);
  menuError = signal('');
  saveMenu(e: { pkg: string; choice: Record<string, string[]> }) {
    const qid = this.menu()?.quote_id;
    if (!qid) return;
    this.menuBusy.set(true); this.menuError.set('');
    this.api.setQuoteMenu(qid, e.pkg, e.choice).subscribe({
      next: () => { this.menuBusy.set(false); this.load(); },
      error: (err) => { this.menuBusy.set(false); this.menuError.set(err.error?.detail ?? 'לא ניתן לשמור את המנות'); },
    });
  }

  rd = signal<Readiness | null>(null);
  siteOpen = signal(false);
  styles: [string, string][] = [['buffet', 'מזנון'], ['plated', 'הגשה לשולחן'], ['finger', 'פינגר פוד'], ['chef_station', 'שף במקום']];
  siteKeys: ['electricity' | 'kitchenette' | 'fridge' | 'parking', string][] = [['electricity', 'חשמל'], ['kitchenette', 'מטבחון'], ['fridge', 'מקרר'], ['parking', 'חניה']];
  tri: [boolean | null, string][] = [[true, 'יש'], [false, 'אין'], [null, 'לא נבדק']];
  siteForm = { location: '', event_time: '' as string | null, distance_km: null as number | null, site_contact_name: '', site_contact_phone: '', site: { electricity: null, kitchenette: null, fridge: null, parking: null } as Record<string, boolean | null> };
  pendingChanges = computed(() => (this.x()?.deal.change_requests ?? []).filter((c) => c.status === 'pending'));
  private fillSite() {
    const d = this.x()?.deal;
    if (!d) return;
    this.siteForm = { location: d.location ?? '', event_time: d.event_time ?? '', distance_km: d.distance_km ?? null, site_contact_name: d.site_contact_name ?? '', site_contact_phone: d.site_contact_phone ?? '',
      site: { electricity: d.site?.electricity ?? null, kitchenette: d.site?.kitchenette ?? null, fridge: d.site?.fridge ?? null, parking: d.site?.parking ?? null } };
  }
  saveSite() {
    const km = this.siteForm.distance_km as unknown;
    this.api.patchReadiness(this.id(), { location: this.siteForm.location, event_time: this.siteForm.event_time || null,
      distance_km: km === '' || km === null || km === undefined ? null : +km, site_contact_name: this.siteForm.site_contact_name,
      site_contact_phone: this.siteForm.site_contact_phone, site: this.siteForm.site }).subscribe(() => { this.siteOpen.set(false); this.load(); });
  }
  isPast(d: string | null) { return !!d && d < new Date().toISOString().slice(0, 10); }
  refreshReady() { this.api.readiness(this.id()).subscribe((r) => this.rd.set(r)); }
  markReady(key: string, on: boolean) { this.api.patchReadiness(this.id(), { marks: { [key]: on } }).subscribe(() => this.load()); }
  setStyle(style: string) { this.api.patchReadiness(this.id(), { service_style: style || null }).subscribe(() => this.load()); }
  decide(rid: string, d: 'approve' | 'decline') {
    this.api.decideChange(this.id(), rid, d).subscribe({ next: () => this.load(), error: (e) => this.error.set(e.error?.detail ?? 'הפעולה נכשלה') });
  }

  /** Opened as /deals/ID#section (from Today or a report): scroll there once the cards exist. */
  private toHash(tries = 0) {
    const id = location.hash.slice(1);
    if (!id) return;
    const el = document.getElementById(id);
    if (el) { el.scrollIntoView({ block: 'start' }); return; }
    if (tries < 20) setTimeout(() => this.toHash(tries + 1), 150);
  }
  load(id = this.id()) {
    this.api.readiness(id).subscribe({ next: (r) => this.rd.set(r), error: () => this.rd.set(null) });
    this.api.dealMenu(id).subscribe({ next: (m) => this.menu.set(m), error: () => this.menu.set(null) });
    this.api.deal(id).subscribe({ next: (x) => { const first = !this.x(); this.x.set(x); this.fillSite(); if (first) this.toHash(); }, error: () => this.error.set('האירוע לא נמצא או שהשרת לא זמין') });
    this.api.dealMessages(id).subscribe((ms) => {
      this.messages.set(ms);
      const keep = ms.find((m) => m.kind === this.pickedKind());
      if (!keep && ms.length) this.pickMessage(ms[0]);
    });
  }
  customerLink(token: string) { return `${this.settings()?.public_base_url ?? location.origin}/q/${token}`; }
  async copyLink(token: string) {
    try { await navigator.clipboard.writeText(this.customerLink(token)); this.copied.set(true); setTimeout(() => this.copied.set(false), 2000); } catch { /* blocked */ }
  }
  diets(d: string[]) { return d.map(dietLabel).join(', '); }
  move(stage: DealStage) {
    if (stage === 'lost') { this.askLost.set(true); return; }
    this.api.setStage(this.id(), stage).subscribe(() => this.load());
  }
  confirmLost() { this.api.setStage(this.id(), 'lost', this.lostReason).subscribe(() => { this.askLost.set(false); this.load(); }); }
  invoice() {
    this.api.invoice(this.id(), this.invoiceNumber || undefined).subscribe({
      next: () => { this.invoiceNumber = ''; this.load(); },
      error: (e) => this.error.set(e.error?.detail ?? 'הפקת החשבונית נכשלה'),
    });
  }
  addNote() { this.api.addNote(this.id(), this.note, this.noteKind).subscribe(() => { this.note = ''; this.load(); }); }
  addTask() { this.api.addTask({ title: this.task, deal_id: this.id() }).subscribe(() => { this.task = ''; this.load(); }); }
  done(id: string) { this.api.doneTask(id).subscribe(() => this.load()); }
}
