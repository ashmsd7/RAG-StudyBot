export const API_BASE_URL = 'http://localhost:8000';

export function getStoredAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem('access_token');
}

export function setStoredAccessToken(token: string) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem('access_token', token);
}

export function clearStoredAccessToken() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem('access_token');
}

export function getStoredUsername(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem('study_username');
}

export function setStoredUsername(username: string) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem('study_username', username);
}

export function clearStoredUsername() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem('study_username');
}

export function authHeaders(): HeadersInit {
  const token = getStoredAccessToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}
