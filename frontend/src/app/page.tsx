"use client";
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { API_BASE_URL, authHeaders, clearStoredAccessToken, getStoredAccessToken } from '../lib/api';
import AccountDock from '../components/AccountDock';

interface StudentState {
  concept: string;
  mastery_score: number;
  attempts: number;
  mistakes: string[];
}

interface DocumentInfo {
  id: string;
  title: string;
  upload_date: string;
}

interface Recommendations {
  weakest_concepts: string[];
}

export default function Dashboard() {
  const [states, setStates] = useState<StudentState[]>([]);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [concepts, setConcepts] = useState<string[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendations | null>(null);
  const [loading, setLoading] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    const token = getStoredAccessToken();
    if (!token) {
      return;
    }

    async function fetchData() {
      try {
        setLoading(true);
        setError(null);
        const protectedRequestOptions: RequestInit = {
          mode: 'cors',
          credentials: 'include',
          headers: authHeaders(),
        };
        const userRes = await fetch(`${API_BASE_URL}/me`, protectedRequestOptions);
        if (!userRes.ok) {
          if (userRes.status === 401 || userRes.status === 403) {
            clearStoredAccessToken();
            setIsAuthenticated(false);
            return;
          }
          throw new Error('Failed to fetch user');
        }
        setIsAuthenticated(true);

        const [statesRes, docsRes, conceptsRes, recommendationsRes] = await Promise.all([
          fetch(`${API_BASE_URL}/student/state`, protectedRequestOptions),
          fetch(`${API_BASE_URL}/documents`, protectedRequestOptions),
          fetch(`${API_BASE_URL}/concepts`, protectedRequestOptions),
          fetch(`${API_BASE_URL}/recommendations`, protectedRequestOptions),
        ]);

        if (!statesRes.ok || !docsRes.ok || !conceptsRes.ok || !recommendationsRes.ok) {
          if (
            statesRes.status === 401 || statesRes.status === 403 ||
            docsRes.status === 401 || docsRes.status === 403 ||
            conceptsRes.status === 401 || conceptsRes.status === 403 ||
            recommendationsRes.status === 401 || recommendationsRes.status === 403
          ) {
            clearStoredAccessToken();
            setIsAuthenticated(false);
            return;
          }
          throw new Error('Failed to load data from backend server.');
        }

        const statesData = await statesRes.json();
        const docsData = await docsRes.json();
        const conceptsData = await conceptsRes.json();
        const recommendationsData = await recommendationsRes.json();

        setStates(statesData);
        setDocuments(docsData);
        setConcepts(Array.isArray(conceptsData) ? conceptsData : []);
        setRecommendations(recommendationsData);
      } catch (err: unknown) {
        console.error(err);
        const message = err instanceof Error ? err.message : String(err);
        setError(
          message.includes('Failed to fetch')
            ? 'Unable to reach the backend. Make sure the server is running on http://localhost:8000.'
            : 'Could not connect to the backend server. Please sign in again or try again later.'
        );
      } finally {
        setLoading(false);
      }
    }
    fetchData();

    const refreshOnFocus = () => {
      if (getStoredAccessToken()) {
        fetchData();
      }
    };
    const refreshOnVisibility = () => {
      if (document.visibilityState === 'visible') {
        refreshOnFocus();
      }
    };

    window.addEventListener('focus', refreshOnFocus);
    document.addEventListener('visibilitychange', refreshOnVisibility);

    return () => {
      window.removeEventListener('focus', refreshOnFocus);
      document.removeEventListener('visibilitychange', refreshOnVisibility);
    };
  }, [router]);

  const deleteDocument = async (docId: string) => {
    if (!confirm('Delete this study material? This will remove the document and its associated chunks.')) {
      return;
    }

    setDeleteError(null);
    setDeletingDocumentId(docId);

    try {
      const res = await fetch(`${API_BASE_URL}/documents/${docId}`, {
        method: 'DELETE',
        mode: 'cors',
        credentials: 'include',
        headers: authHeaders(),
      });

      if (!res.ok) {
        if (res.status === 401 || res.status === 403) {
          clearStoredAccessToken();
          router.push('/login');
          return;
        }
        const errorText = await res.text();
        throw new Error(errorText || 'Failed to delete document');
      }

      setDocuments((current) => current.filter((doc) => doc.id !== docId));
    } catch (err: unknown) {
      console.error('Delete document failed', docId, err);
      const message = err instanceof Error ? err.message : String(err);
      setDeleteError(
        message.includes('Failed to fetch')
          ? 'Unable to reach the backend. Check that the API server is running on http://localhost:8000.'
          : 'Unable to delete document. Please try again.'
      );
    } finally {
      setDeletingDocumentId(null);
    }
  };

  const strongTopics = states.filter(s => s.mastery_score >= 0.7);
  const weakTopics = states.filter(s => s.mastery_score < 0.7);
  const availableTopics = Array.from(new Set([
    ...concepts,
    ...states.map((state) => state.concept),
  ].filter(Boolean)));
  const recommendedTopic = recommendations?.weakest_concepts?.[0] || weakTopics[0]?.concept || availableTopics[0];

  if (!isAuthenticated) {
    return (
      <div className="page-transition min-h-screen bg-[#f4eadc] text-[#2f261f] font-sans">
        <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
          <Link href="/" className="text-lg font-black tracking-tight">
            StudyNest
          </Link>
          <nav className="flex items-center gap-3">
            <Link href="/login" className="rounded-full border border-[#d6b995] px-4 py-2 text-sm font-semibold text-[#4a382b] transition hover:bg-white/50">
              Sign in
            </Link>
            <Link href="/signup" className="rounded-full bg-[#6f4e37] px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-[#6f4e37]/20 transition hover:bg-[#5d402c]">
              Sign up
            </Link>
          </nav>
        </header>

        <main>
          <section className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-10 px-6 pb-16 pt-8 md:grid-cols-[1fr_0.92fr] md:pt-14">
            <div>
              <p className="mb-4 w-fit rounded-full border border-[#d8bea0] bg-white/45 px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-[#7b604a]">
                Study from what you actually uploaded
              </p>
              <h1 className="max-w-2xl text-5xl font-black leading-[0.96] tracking-tight text-[#2b2119] md:text-7xl">
                Turn messy notes into calm study sessions.
              </h1>
              <p className="mt-6 max-w-xl text-lg leading-8 text-[#6c5847]">
                Upload your PDFs, get grounded summaries, ask questions in plain language, and practice with quizzes that stay close to your own material.
              </p>
              <div className="mt-8 flex flex-wrap gap-4">
                <Link href="/signup" className="rounded-full bg-[#2f261f] px-6 py-3 text-sm font-bold text-white shadow-xl shadow-[#2f261f]/20 transition hover:-translate-y-0.5">
                  Create your workspace
                </Link>
                <Link href="/login" className="rounded-full border border-[#caa985] bg-white/45 px-6 py-3 text-sm font-bold text-[#3f3025] transition hover:bg-white/70">
                  I already have one
                </Link>
              </div>
            </div>

            <div className="grid gap-4">
              <img
                src="https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=900&q=80"
                alt="Laptop and notes on a desk"
                className="h-[320px] w-full rounded-[2rem] object-cover shadow-2xl shadow-[#8f7258]/30"
              />
              <div className="grid grid-cols-2 gap-4">
                <img
                  src="https://images.unsplash.com/photo-1503676260728-1c00da094a0b?auto=format&fit=crop&w=500&q=80"
                  alt="Students studying together"
                  className="h-40 w-full rounded-3xl object-cover shadow-lg shadow-[#8f7258]/20"
                />
                <div className="rounded-3xl border border-[#d8bea0] bg-[#fff8ef]/80 p-5 shadow-lg shadow-[#8f7258]/10">
                  <p className="text-3xl font-black text-[#6f4e37]">3 steps</p>
                  <p className="mt-2 text-sm leading-6 text-[#6c5847]">
                    Upload notes, choose a topic, then study with summaries, chat, and quizzes.
                  </p>
                </div>
              </div>
            </div>
          </section>

          <section className="border-y border-[#dfc8ad] bg-[#fff8ef]/70">
            <div className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-6 py-10 md:grid-cols-3">
              {[
                ['Grounded answers', 'Every chat answer cites the chunks it used, so you can trace it back to your material.'],
                ['Gentler quizzes', 'Pick easy, medium, or hard questions and keep rotating through fresh prompts.'],
                ['Mastery that moves', 'Partially correct answers still count, with feedback that shows what to improve next.'],
              ].map(([title, body]) => (
                <div key={title} className="rounded-3xl bg-white/60 p-6 shadow-sm">
                  <h2 className="text-lg font-black text-[#2f261f]">{title}</h2>
                  <p className="mt-3 text-sm leading-6 text-[#6c5847]">{body}</p>
                </div>
              ))}
            </div>
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="page-transition min-h-screen bg-[#070b19] bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(30,58,138,0.25),rgba(255,255,255,0))] text-white p-6 md:p-12 font-sans selection:bg-blue-500/30 selection:text-blue-200">
      <AccountDock />
      <div className="max-w-6xl mx-auto">
        <header className="mb-12 flex flex-col md:flex-row justify-between items-start md:items-center gap-6 border-b border-slate-800 pb-8">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span className="text-xs font-semibold uppercase tracking-wider text-emerald-400">Live Workspace</span>
            </div>
            <h1 className="text-4xl md:text-5xl font-extrabold bg-gradient-to-r from-blue-400 via-indigo-400 to-emerald-400 bg-clip-text text-transparent tracking-tight">
              Adaptive AI Study Coach
            </h1>
            <p className="text-slate-400 mt-2 text-base md:text-lg max-w-xl">
              Upload study materials, generate custom concept guides, and let the AI gauge your mastery.
            </p>
            <div className="mt-4 flex flex-wrap gap-3 text-xs text-slate-300">
              <span className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-1.5">
                {documents.length} uploaded document{documents.length === 1 ? '' : 's'}
              </span>
              <span className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-1.5">
                {availableTopics.length} indexed topic{availableTopics.length === 1 ? '' : 's'}
              </span>
            </div>
          </div>
          
          <div className="flex gap-4">
            <Link href="/upload" className="px-5 py-2.5 rounded-xl text-sm font-medium border border-slate-800 bg-slate-900/60 hover:bg-slate-800/80 hover:border-slate-700 transition-all">
              Upload Materials
            </Link>
            <Link href="/study" className="px-5 py-2.5 rounded-xl text-sm font-medium bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 transition-all shadow-lg shadow-indigo-600/30">
              Start Learning
            </Link>
          </div>
        </header>

        {error && (
          <div className="mb-8 p-4 bg-rose-500/10 border border-rose-500/20 text-rose-400 rounded-xl flex items-center gap-3 text-sm">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{error}</span>
          </div>
        )}

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 animate-pulse">
            <div className="h-48 bg-slate-900/40 rounded-2xl border border-slate-800/50"></div>
            <div className="h-48 bg-slate-900/40 rounded-2xl border border-slate-800/50"></div>
            <div className="h-48 bg-slate-900/40 rounded-2xl border border-slate-800/50"></div>
          </div>
        ) : (
          <main className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {recommendedTopic && (
              <div className="col-span-1 md:col-span-3 rounded-2xl border border-amber-400/30 bg-amber-400/10 p-5 shadow-xl shadow-amber-950/10">
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-wider text-amber-300">Recommended Next Topic</p>
                    <h2 className="mt-1 text-2xl font-black text-amber-50">{recommendedTopic}</h2>
                  </div>
                  <Link href="/study" className="w-fit rounded-xl bg-amber-200 px-4 py-2 text-sm font-bold text-slate-950 transition hover:bg-amber-100">
                    Practice Now
                  </Link>
                </div>
              </div>
            )}
            
            {/* Strong Topics */}
            <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 p-6 rounded-2xl shadow-xl hover:border-emerald-500/40 transition-all group">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-bold tracking-tight text-slate-100 group-hover:text-emerald-400 transition-colors">
                  Strong Topics
                </h2>
                <div className="p-2 bg-emerald-500/10 rounded-lg text-emerald-400">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
              </div>
              
              {strongTopics.length === 0 ? (
                <p className="text-slate-500 text-sm py-4">No topics completed at mastery level yet.</p>
              ) : (
                <div className="space-y-3">
                  {strongTopics.map((topic, i) => (
                    <div key={i} className="flex justify-between items-center bg-slate-800/20 border border-slate-800/50 p-3.5 rounded-xl">
                      <span className="font-medium text-slate-300">{topic.concept}</span>
                      <span className="text-emerald-400 font-bold bg-emerald-400/10 border border-emerald-400/20 px-2.5 py-1 rounded-lg text-sm">
                        {(topic.mastery_score * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Needs Improvement */}
            <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 p-6 rounded-2xl shadow-xl hover:border-rose-500/40 transition-all group">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-bold tracking-tight text-slate-100 group-hover:text-rose-400 transition-colors">
                  Needs Work
                </h2>
                <div className="p-2 bg-rose-500/10 rounded-lg text-rose-400">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                </div>
              </div>

              {weakTopics.length === 0 ? (
                <p className="text-slate-500 text-sm py-4">No active concepts needing improvement. Keep it up!</p>
              ) : (
                <div className="space-y-3">
                  {weakTopics.map((topic, i) => (
                    <div key={i} className="flex justify-between items-center bg-slate-800/20 border border-slate-800/50 p-3.5 rounded-xl">
                      <span className="font-medium text-slate-300">{topic.concept}</span>
                      <span className="text-rose-400 font-bold bg-rose-400/10 border border-rose-400/20 px-2.5 py-1 rounded-lg text-sm">
                        {(topic.mastery_score * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Uploaded Documents */}
            <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 p-6 rounded-2xl shadow-xl hover:border-blue-500/40 transition-all group">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-xl font-bold tracking-tight text-slate-100 group-hover:text-blue-400 transition-colors">
                  Study Materials
                </h2>
                <div className="p-2 bg-blue-500/10 rounded-lg text-blue-400">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
              </div>

              {documents.length === 0 ? (
                <div className="text-center py-4">
                  <p className="text-slate-500 text-sm mb-4">No files uploaded yet.</p>
                  <Link href="/upload" className="text-xs bg-slate-800 hover:bg-slate-700 text-blue-400 px-3 py-1.5 rounded-lg border border-slate-700 transition-all">
                    Upload Your First PDF
                  </Link>
                </div>
              ) : (
                <div className="space-y-3 max-h-[300px] overflow-y-auto pr-1">
                  {deleteError && (
                    <div className="mb-3 p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-sm">
                      {deleteError}
                    </div>
                  )}
                  {documents.map((doc, i) => (
                    <div key={i} className="flex flex-col bg-slate-800/20 border border-slate-800/50 p-3 rounded-xl gap-3">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium text-slate-200 text-sm truncate">{doc.title}</span>
                        <button
                          type="button"
                          disabled={deletingDocumentId === doc.id}
                          onClick={() => deleteDocument(doc.id)}
                          className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-200 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-60 transition-all"
                        >
                          {deletingDocumentId === doc.id ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                      <span className="text-[10px] text-slate-500">
                        Uploaded {new Date(doc.upload_date).toLocaleDateString()}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Indexed Topics */}
            <div className="col-span-1 md:col-span-3 bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 p-6 rounded-2xl shadow-xl">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 mb-5">
                <div>
                  <h2 className="text-xl font-bold tracking-tight text-slate-100">Indexed Topics</h2>
                  <p className="text-sm text-slate-500 mt-1">Topics currently available from your uploaded study materials.</p>
                </div>
                <Link href="/study" className="text-xs bg-slate-800 hover:bg-slate-700 text-blue-300 px-3 py-1.5 rounded-lg border border-slate-700 transition-all">
                  Study These Topics
                </Link>
              </div>

              {availableTopics.length === 0 ? (
                <p className="text-slate-500 text-sm">No topics indexed yet. Upload a PDF or text file to start.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {availableTopics.slice(0, 24).map((concept) => (
                    <span key={concept} className="rounded-lg border border-indigo-500/20 bg-indigo-500/10 px-3 py-1.5 text-xs font-medium text-indigo-200">
                      {concept}
                    </span>
                  ))}
                  {availableTopics.length > 24 && (
                    <span className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-1.5 text-xs text-slate-400">
                      +{availableTopics.length - 24} more
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Quick Actions Panel */}
            {states.length === 0 && (
              <div className="col-span-1 md:col-span-3 mt-4 p-8 bg-indigo-500/5 border border-indigo-500/10 rounded-3xl text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
                <h3 className="text-xl font-bold mb-2">Welcome to your Learning Hub!</h3>
                <p className="text-slate-400 max-w-xl mx-auto mb-6">
                  Get started by uploading a study guide or syllabus. The RAG engine will process the text, extract concepts, and generate custom adaptive quizzes.
                </p>
                <div className="flex gap-4 justify-center">
                  <Link href="/upload" className="px-6 py-2.5 bg-slate-800 hover:bg-slate-700 text-white rounded-xl font-medium border border-slate-700 transition-all text-sm">
                    Upload PDF / Text
                  </Link>
                  <Link href="/study" className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-medium transition-all text-sm">
                    Start AI Quiz
                  </Link>
                </div>
              </div>
            )}

          </main>
        )}
      </div>
    </div>
  );
}
