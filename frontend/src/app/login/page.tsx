"use client";
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { API_BASE_URL, setStoredAccessToken, setStoredUsername } from '../../lib/api';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    try {
      const res = await fetch(`${API_BASE_URL}/login`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Login failed');
      }

      if (data.access_token) {
        setStoredAccessToken(data.access_token);
      }
      if (data.username) {
        setStoredUsername(data.username);
      }

      router.push('/');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    }
  };

  return (
    <div className="page-transition min-h-screen bg-[#0a0f24] flex items-center justify-center p-4">
      <div className="bg-[#11162d] p-8 rounded-xl shadow-2xl w-full max-w-md">
        <h1 className="text-3xl font-bold mb-6 text-center bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-indigo-400 to-emerald-400">
          Adaptive AI Study Coach
        </h1>
        <p className="text-slate-400 text-center mb-6">
          Sign in to access your private study documents and quiz workspace.
        </p>
        {error && (
          <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded p-3 mb-4">
            {error}
          </div>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            className="w-full p-3 rounded bg-[#1a1f3a] text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            className="w-full p-3 rounded bg-[#1a1f3a] text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            className="w-full py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl transition-all"
          >
            Sign In
          </button>
        </form>
        <div className="mt-6 text-center text-sm text-slate-400">
          <p>
            Don&apos;t have an account?{' '}
            <Link href="/signup" className="text-blue-300 hover:text-blue-200 underline">
              Create one now
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
