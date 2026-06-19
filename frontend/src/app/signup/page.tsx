"use client";
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { API_BASE_URL, setStoredAccessToken, setStoredUsername } from '../../lib/api';

export default function Signup() {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    // Basic client-side validation
    const normalizedEmail = email.trim().toLowerCase();
    const trimmedUsername = username.trim();
    if (!trimmedUsername) {
      setError('Username is required');
      setLoading(false);
      return;
    }
    if (!normalizedEmail.endsWith('@gmail.com')) {
      setError('Email must end with @gmail.com');
      setLoading(false);
      return;
    }
    const specialCharRegex = /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>\/?]/;
    if (password.length < 8) {
      setError('Password must be at least 8 characters long');
      setLoading(false);
      return;
    }
    if (!specialCharRegex.test(password)) {
      setError('Password must include at least one special character');
      setLoading(false);
      return;
    }
    try {
      const res = await fetch(`${API_BASE_URL}/signup`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: normalizedEmail, password, username: trimmedUsername }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Signup failed');
      }
      // Auto-login after signup
      const loginRes = await fetch(`${API_BASE_URL}/login`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: normalizedEmail, password }),
      });
      const loginData = await loginRes.json();
      if (!loginRes.ok) {
        throw new Error(loginData.detail || 'Login after signup failed');
      }
      if (loginData.access_token) {
        setStoredAccessToken(loginData.access_token);
      }
      setStoredUsername(loginData.username || trimmedUsername);
      router.push('/');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setLoading(false);
    }
  };

  return (
    <div className="page-transition min-h-screen bg-[#0a0f24] flex items-center justify-center p-4">
      <div className="bg-[#11162d] p-8 rounded-xl shadow-2xl w-full max-w-md">
        <h1 className="text-3xl font-bold mb-6 text-center bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-indigo-400 to-emerald-400">
          Create an Account
        </h1>
        <p className="text-slate-400 text-center mb-6">Sign up to create your study workspace.</p>
        {error && (
          <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded p-3 mb-4">{error}</div>
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
            type="text"
            placeholder="Username"
            value={username}
            onChange={e => setUsername(e.target.value.slice(0, 32))}
            required
            maxLength={32}
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
            disabled={loading}
            className="w-full py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-xl transition-all"
          >
            {loading ? 'Creating...' : 'Create Account'}
          </button>
        </form>
        <div className="mt-6 text-center text-sm text-slate-400">
          <p>
            Already have an account?{' '}
            <Link href="/login" className="text-blue-300 hover:text-blue-200 underline">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
