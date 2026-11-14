import { Pipe, PipeTransform } from '@angular/core';

export const ils = (n: number | null | undefined, digits = 0): string =>
  n == null ? '—' : '₪' + n.toLocaleString('he-IL', { maximumFractionDigits: digits, minimumFractionDigits: digits });

@Pipe({ name: 'ils', standalone: true })
export class IlsPipe implements PipeTransform {
  transform(v: number | null | undefined, digits = 0): string { return ils(v, digits); }
}

@Pipe({ name: 'heDate', standalone: true })
export class HeDatePipe implements PipeTransform {
  transform(v: string | null | undefined, withTime = false): string {
    if (!v) return '—';
    const d = new Date(v.length === 10 ? v + 'T12:00:00' : v);
    return withTime
      ? d.toLocaleString('he-IL', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('he-IL', { day: 'numeric', month: 'short', year: 'numeric' });
  }
}

/** "בעוד 12 ימים" / "לפני 3 שעות" */
@Pipe({ name: 'rel', standalone: true })
export class RelativePipe implements PipeTransform {
  transform(v: string | null | undefined): string {
    if (!v) return '';
    const d = new Date(v.length === 10 ? v + 'T12:00:00' : v).getTime();
    const diff = d - Date.now();
    const abs = Math.abs(diff);
    const rtf = new Intl.RelativeTimeFormat('he', { numeric: 'auto' });
    if (abs < 3600e3) return rtf.format(Math.round(diff / 60e3), 'minute');
    if (abs < 86400e3) return rtf.format(Math.round(diff / 3600e3), 'hour');
    return rtf.format(Math.round(diff / 86400e3), 'day');
  }
}
