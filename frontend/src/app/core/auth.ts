import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, firstValueFrom, throwError } from 'rxjs';
import { CONFIG } from './api.service';

export type Role = 'owner' | 'viewer';
const KEY = 'zd_auth';

/** Owner login. Off unless the server has OWNER_PASSWORD; then owner screens need a token and
 *  a guest gets a read-only "demo" token. Customer pages never need it. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);
  private status?: Promise<{ required: boolean; guest: boolean }>;
  readonly session = signal<{ token: string; role: Role } | null>(this.read());
  readonly role = computed(() => this.session()?.role ?? null);
  readonly notice = signal('');

  private read() {
    try { return JSON.parse(localStorage.getItem(KEY) ?? 'null'); } catch { return null; }
  }
  token() { return this.session()?.token ?? null; }

  serverStatus() {
    this.status ??= firstValueFrom(this.http.get<{ required: boolean; guest: boolean }>(`${CONFIG.apiUrl}/auth/status`))
      .catch(() => ({ required: false, guest: false }));
    return this.status;
  }

  async login(body: { password?: string; guest?: boolean }) {
    const r = await firstValueFrom(this.http.post<{ token: string; role: Role }>(`${CONFIG.apiUrl}/auth/login`, body));
    this.session.set(r);
    try { localStorage.setItem(KEY, JSON.stringify(r)); } catch { /* private mode */ }
  }

  logout(redirect = true) {
    this.session.set(null);
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    if (redirect) this.router.navigate(['/login']);
  }
}

export const ownerGuard: CanActivateFn = async (_r, state) => {
  const auth = inject(AuthService);
  const router = inject(Router); // inject before any await: injection context ends there
  const s = await auth.serverStatus();
  if (!s.required || auth.token()) return true;
  return router.createUrlTree(['/login'], { queryParams: { next: state.url } });
};

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const t = auth.token();
  const isPublicCall = /\/(public|auth)\//.test(req.url) || req.url.endsWith('/agent/chat');
  return next(t && !isPublicCall ? req.clone({ setHeaders: { Authorization: `Bearer ${t}` } }) : req).pipe(
    catchError((e: HttpErrorResponse) => {
      if (e.status === 401 && e.error?.code === 'login') {
        auth.logout(false);
        router.navigate(['/login'], { queryParams: { next: router.url } });
      } else if (e.status === 403 && e.error?.code === 'viewer') {
        auth.notice.set(e.error.detail);
        setTimeout(() => auth.notice.set(''), 4000);
      }
      return throwError(() => e);
    }),
  );
};
