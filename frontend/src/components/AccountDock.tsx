"use client";

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import {
  API_BASE_URL,
  authHeaders,
  clearStoredAccessToken,
  clearStoredUsername,
  getStoredAccessToken,
  getStoredUsername,
  setStoredUsername,
} from '../lib/api';

function subscribeToStorage(callback: () => void) {
  window.addEventListener('storage', callback);
  return () => window.removeEventListener('storage', callback);
}

export default function AccountDock() {
  const hasToken = useSyncExternalStore(
    subscribeToStorage,
    () => Boolean(getStoredAccessToken()),
    () => false,
  );
  const storedUsername = useSyncExternalStore(
    subscribeToStorage,
    () => getStoredUsername() || '',
    () => '',
  );
  const [username, setUsername] = useState('');
  const [leaving, setLeaving] = useState(false);
  const router = useRouter();

  useEffect(() => {
    if (!hasToken || storedUsername) {
      return;
    }

    async function fetchAccount() {
      try {
        const res = await fetch(`${API_BASE_URL}/me`, {
          mode: 'cors',
          credentials: 'include',
          headers: authHeaders(),
        });
        if (!res.ok) {
          clearStoredAccessToken();
          return;
        }
        const data = await res.json();
        if (data.username) {
          setStoredUsername(data.username);
          setUsername(data.username);
        }
      } catch {
        setUsername('');
      }
    }

    fetchAccount();
  }, [hasToken, storedUsername]);

  const logout = async () => {
    setLeaving(true);
    try {
      await fetch(`${API_BASE_URL}/logout`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: authHeaders(),
      });
    } finally {
      clearStoredAccessToken();
      clearStoredUsername();
      router.push('/');
      router.refresh();
    }
  };

  if (!hasToken) return null;

  const label = storedUsername || username || 'Student';
  const initials = label.slice(0, 1).toUpperCase();

  return (
    <div className={`fixed bottom-4 left-4 z-50 flex max-w-[calc(100vw-2rem)] items-center gap-2 rounded-xl border border-slate-700/70 bg-slate-950/90 px-2.5 py-1.5 shadow-xl shadow-black/25 backdrop-blur-xl transition-all duration-300 ${leaving ? 'translate-y-3 opacity-0' : 'translate-y-0 opacity-100'}`}>
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-bold text-slate-950">
        {initials}
      </div>
      <div className="min-w-0">
        <p className="max-w-24 truncate text-xs font-semibold text-slate-100">{label}</p>
      </div>
      <button
        type="button"
        onClick={logout}
        className="rounded-md border border-rose-400/30 bg-rose-400/10 px-2 py-1 text-[11px] font-semibold text-rose-200 transition hover:bg-rose-400/20"
      >
        Logout
      </button>
    </div>
  );
}
