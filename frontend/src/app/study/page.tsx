"use client";
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { API_BASE_URL, authHeaders, getStoredAccessToken } from '../../lib/api';
import AccountDock from '../../components/AccountDock';

interface SourceChunk {
  chunk_id: string;
  document_title: string;
  page_number: number;
  document_id?: string | null;
  document_available?: boolean | null;
}

interface StudyQuestion {
  question: string;
  hints: string[];
  difficulty: string;
  source_chunks: SourceChunk[];
}

interface StudyEvaluation {
  is_correct: boolean;
  feedback: string;
  mistake_logged?: string | null;
  new_mastery_score: number;
  correctness_score?: number;
  source_chunks: SourceChunk[];
}

interface ConceptSummary {
  summary: string;
  key_points: string[];
  source_chunks: SourceChunk[];
}

interface ChatResult {
  answer: string;
  source_chunks: SourceChunk[];
  usage_limits?: ChatUsageLimits;
}

interface ChatUsageLimits {
  max_message_chars: number;
  max_context_chunks: number;
  max_chat_requests: number;
  remaining_chat_requests: number;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  source_chunks?: SourceChunk[];
}

interface ConversationItem {
  question: string;
  answer: string;
  source_chunks: SourceChunk[];
}

const MAX_CHAT_MESSAGE_CHARS = 1200;
const COMPACT_CHAT_PREVIEW_CHARS = 140;
const QUIZ_DIFFICULTIES = [
  { value: 'easy', label: 'Easy', description: 'Recall and basic understanding' },
  { value: 'medium', label: 'Medium', description: 'Connections in the material' },
  { value: 'hard', label: 'Hard', description: 'Deeper reasoning from sources' },
] as const;

type QuizDifficulty = typeof QUIZ_DIFFICULTIES[number]['value'];

type ApiPayload = Record<string, unknown>;

function renderInlineMarkdown(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index} className="font-semibold text-slate-50">{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function MarkdownText({ text, className = '' }: { text: string; className?: string }) {
  return (
    <div className={`space-y-3 text-sm leading-relaxed text-slate-100 ${className}`}>
      {text.split(/\n{2,}/).map((block, index) => (
        <p key={index}>{renderInlineMarkdown(block.trim())}</p>
      ))}
    </div>
  );
}

function SourceCards({ chunks }: { chunks: SourceChunk[] }) {
  if (!chunks.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {chunks.map((chunk, i) => {
        const content = (
          <>
            <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3 text-indigo-300" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clipRule="evenodd" />
            </svg>
            <span className="font-medium truncate max-w-[140px]" title={chunk.document_title}>{chunk.document_title}</span>
            <span className="text-indigo-500">·</span>
            <span className="text-indigo-200 whitespace-nowrap">p.{chunk.page_number}</span>
          </>
        );
        const className = "inline-flex items-center gap-1.5 px-2.5 py-1 bg-indigo-900/40 border border-indigo-700/40 rounded-lg text-xs text-indigo-200 transition hover:border-indigo-300/70 hover:bg-indigo-800/50 hover:shadow-lg hover:shadow-indigo-500/20 hover:underline";
        return chunk.document_id && chunk.document_available !== false ? (
          <Link key={i} href={`/viewer/${chunk.document_id}?page=${chunk.page_number}`} className={`${className} cursor-pointer`}>
            {content}
          </Link>
        ) : (
          <span key={i} className={className}>
            {content}
          </span>
        );
      })}
    </div>
  );
}

function readString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

async function parseApiResponse(res: Response): Promise<ApiPayload> {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

export default function StudySession() {
  const [concepts, setConcepts] = useState<string[]>([]);
  const [topic, setTopic] = useState('');
  const [question, setQuestion] = useState<StudyQuestion | null>(null);
  const [lastQuestionId, setLastQuestionId] = useState<string | null>(null);
  const [summary, setSummary] = useState<ConceptSummary | null>(null);
  const [chatInput, setChatInput] = useState('');
  const [chatResult, setChatResult] = useState<ChatResult | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [selectedInteraction, setSelectedInteraction] = useState<ConversationItem | null>(null);
  const [chatUsage, setChatUsage] = useState<ChatUsageLimits | null>(null);
  const [questionDifficulty, setQuestionDifficulty] = useState<QuizDifficulty>('easy');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingConcepts, setLoadingConcepts] = useState(true);
  const [evaluation, setEvaluation] = useState<StudyEvaluation | null>(null);
  const [showHint, setShowHint] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const conversationItems: ConversationItem[] = [];
  for (let i = 0; i < chatHistory.length; i += 2) {
    const questionMessage = chatHistory[i];
    const answerMessage = chatHistory[i + 1];
    if (questionMessage?.role === 'user' && answerMessage?.role === 'assistant') {
      conversationItems.push({
        question: questionMessage.content,
        answer: answerMessage.content,
        source_chunks: answerMessage.source_chunks || [],
      });
    }
  }

  useEffect(() => {
    if (!getStoredAccessToken()) {
      router.push('/login');
      return;
    }

    async function fetchConcepts() {
      try {
        const res = await fetch(`${API_BASE_URL}/concepts`, {
          mode: 'cors',
          credentials: 'include',
          headers: authHeaders(),
        });
        if (!res.ok) throw new Error('Failed to fetch concepts');
        const data = await res.json();
        setConcepts(data);
        if (data.length > 0) {
          setTopic(data[0]);
        }
      } catch (err) {
        console.error(err);
      } finally {
        setLoadingConcepts(false);
      }
    }
    fetchConcepts();
  }, [router]);

  useEffect(() => {
    if (!selectedInteraction) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedInteraction(null);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [selectedInteraction]);

  const fetchQuestion = async (selectedTopic = topic) => {
    if (!selectedTopic) return;
    setLoading(true);
    setEvaluation(null);
    setSummary(null);
    setChatResult(null);
    setAnswer('');
    setShowHint(false);
    setError(null);
    try {
      let attempts = 0;
      let data: ApiPayload | null = null;
      let acceptedQuestion: StudyQuestion | null = null;
      let acceptedQuestionId: string | null = null;
      // Retry loop: if backend returns the same question_id as last time,
      // request a fresh question up to 3 attempts.
      while (attempts < 3) {
        const res = await fetch(`${API_BASE_URL}/quiz`, {
          method: 'POST',
          mode: 'cors',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ concept: selectedTopic, difficulty: questionDifficulty })
        });
        data = await parseApiResponse(res);
        if (!res.ok) {
          throw new Error(readString(data.detail) || readString(data.message) || 'Failed to generate a quiz question.');
        }
        if (!data.question) {
          throw new Error('The backend returned an invalid quiz response.');
        }

        // If question_id is present and equals lastQuestionId, retry.
        const qid = readString(data.question_id) || null;
        if (qid && lastQuestionId && qid === lastQuestionId) {
          attempts += 1;
          // small delay before retry
          await new Promise((r) => setTimeout(r, 250));
          continue;
        }

        // Accept the question
        acceptedQuestionId = qid;
        acceptedQuestion = {
          question: readString(data.question) || '',
          hints: Array.isArray(data.hints) ? data.hints : [],
          difficulty: readString(data.difficulty) || 'novice',
          source_chunks: Array.isArray(data.source_chunks) ? data.source_chunks : [],
        };
        break;
      }
      if (!acceptedQuestion && data?.question) {
        acceptedQuestionId = readString(data.question_id) || null;
        acceptedQuestion = {
          question: readString(data.question) || '',
          hints: Array.isArray(data.hints) ? data.hints : [],
          difficulty: readString(data.difficulty) || 'novice',
          source_chunks: Array.isArray(data.source_chunks) ? data.source_chunks : [],
        };
      }
      if (!acceptedQuestion) {
        throw new Error('Unable to obtain a valid quiz question after retries.');
      }
      setLastQuestionId(acceptedQuestionId);
      setQuestion(acceptedQuestion);
    } catch (e) {
      console.error(e);
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const fetchSummary = async (selectedTopic = topic) => {
    if (!selectedTopic) return;
    setLoading(true);
    setQuestion(null);
    setEvaluation(null);
    setChatResult(null);
    setAnswer('');
    setShowHint(false);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/summary`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ concept: selectedTopic })
      });
      const data = await parseApiResponse(res);
      if (!res.ok) {
        throw new Error(readString(data.detail) || readString(data.message) || 'Failed to generate a concept summary.');
      }
      setSummary({
        summary: readString(data.summary) || 'No summary was returned.',
        key_points: Array.isArray(data.key_points) ? data.key_points : [],
        source_chunks: Array.isArray(data.source_chunks) ? data.source_chunks : [],
      });
    } catch (e) {
      console.error(e);
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const submitChat = async () => {
    const message = chatInput.trim();
    if (!message) return;
    setLoading(true);
    setQuestion(null);
    setSummary(null);
    setEvaluation(null);
    setAnswer('');
    setShowHint(false);
    setError(null);
    setChatHistory((current) => [
      ...current,
      { role: 'user', content: message },
    ].slice(-10));
    try {
      const res = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ message, concept: topic })
      });
      const data = await parseApiResponse(res);
      if (!res.ok) {
        throw new Error(readString(data.detail) || readString(data.message) || 'Failed to answer from your uploaded material.');
      }
      const nextChatResult = {
        answer: readString(data.answer) || 'No answer was returned.',
        source_chunks: Array.isArray(data.source_chunks) ? data.source_chunks : [],
        usage_limits: typeof data.usage_limits === 'object' && data.usage_limits !== null
          ? data.usage_limits as ChatResult['usage_limits']
          : undefined,
      };
      setChatResult(nextChatResult);
      if (nextChatResult.usage_limits) {
        setChatUsage(nextChatResult.usage_limits);
      }
      setChatHistory((current) => [
        ...current,
        {
          role: 'assistant',
          content: nextChatResult.answer,
          source_chunks: nextChatResult.source_chunks,
        },
      ].slice(-10));
      setChatInput('');
    } catch (e) {
      console.error(e);
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const submitAnswer = async () => {
    if (!question || !answer.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/evaluate`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ 
          concept: topic,
          question: question.question,
          answer: answer
        })
      });
      const data = await parseApiResponse(res);
      if (!res.ok) {
        throw new Error(readString(data.detail) || readString(data.message) || 'Failed to evaluate your answer.');
      }
      setEvaluation({
        is_correct: Boolean(data.is_correct),
        feedback: readString(data.feedback) || 'No feedback was returned.',
        mistake_logged: readString(data.mistake_logged) || null,
        new_mastery_score: typeof data.new_mastery_score === 'number' ? data.new_mastery_score : 0,
        correctness_score: typeof data.correctness_score === 'number' ? data.correctness_score : undefined,
        source_chunks: Array.isArray(data.source_chunks) ? data.source_chunks : [],
      });
    } catch (e) {
      console.error(e);
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const getDifficultyColor = (diff: string) => {
    const d = (diff || '').toLowerCase();
    if (d.includes('novice') || d.includes('easy')) return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
    if (d.includes('intermediate') || d.includes('medium')) return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    return 'bg-rose-500/10 text-rose-400 border-rose-500/20';
  };

  return (
    <div className="page-transition min-h-screen bg-[#070b19] bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(30,58,138,0.25),rgba(255,255,255,0))] text-white p-6 md:p-12 font-sans">
      <AccountDock />
      <div className="max-w-4xl mx-auto">
        <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-12 border-b border-slate-800 pb-8">
          <div>
            <Link href="/" className="text-slate-400 hover:text-white transition-colors mb-2 inline-flex items-center gap-2 text-sm group">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 group-hover:-translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              Back to Dashboard
            </Link>
            <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">
              Adaptive Study Session
            </h1>
          </div>

          {!loadingConcepts && concepts.length > 0 && (
            <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800 px-4 py-2.5 rounded-2xl flex items-center gap-3">
              <span className="text-xs text-slate-400 uppercase tracking-wider font-semibold">Active Topic:</span>
              <select 
                value={topic}
                onChange={(e) => {
                  setTopic(e.target.value);
                  setQuestion(null);
                  setEvaluation(null);
                  setSummary(null);
                  setChatResult(null);
                  setError(null);
                }}
                className="bg-slate-800/80 text-white rounded-lg px-3 py-1 text-sm outline-none border border-slate-700 focus:border-blue-500 cursor-pointer"
              >
                {concepts.map((concept, index) => (
                  <option key={index} value={concept}>{concept}</option>
                ))}
              </select>
            </div>
          )}
        </header>
        
        <main className="mt-8">
          {error && (
            <div className="mb-6 rounded-2xl border border-rose-500/25 bg-rose-500/10 p-4 text-sm text-rose-200">
              {error}
            </div>
          )}

          {loadingConcepts ? (
            <div className="bg-slate-900/40 border border-slate-800/50 p-12 rounded-3xl text-center animate-pulse">
              <div className="h-6 w-1/3 bg-slate-850 rounded mx-auto mb-4"></div>
              <div className="h-4 w-1/2 bg-slate-850 rounded mx-auto"></div>
            </div>
          ) : concepts.length === 0 ? (
            <div className="bg-slate-900/40 border border-slate-800/50 p-12 rounded-3xl text-center max-w-xl mx-auto shadow-2xl">
              <div className="p-4 bg-indigo-500/10 rounded-2xl w-fit mx-auto mb-6 text-indigo-400">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-10 w-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                </svg>
              </div>
              <h2 className="text-2xl font-bold mb-3 text-slate-100">No study concepts found</h2>
              <p className="text-slate-400 mb-8 text-sm leading-relaxed">
                Before generating quizzes, please upload a learning document (PDF or Text) to parse the key study points.
              </p>
              <Link href="/upload" className="px-6 py-3 bg-blue-600 hover:bg-blue-500 transition-all text-white font-semibold rounded-xl text-sm shadow-lg shadow-blue-600/20">
                Upload Document Now &rarr;
              </Link>
            </div>
          ) : (
            <>
              <section className="mb-8 bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 p-6 rounded-3xl shadow-xl">
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-4 mb-4">
                  <div>
                    <h2 className="text-lg font-bold text-slate-100">Ask Your Study Material</h2>
                    <p className="text-slate-400 text-sm mt-1">
                      Answers are limited to your uploaded documents for <span className="text-blue-300">{topic}</span>.
                    </p>
                  </div>
                  <span className="text-xs text-slate-500 whitespace-nowrap">
                    {chatUsage
                      ? `${chatUsage.remaining_chat_requests}/${chatUsage.max_chat_requests} chats left`
                      : `${chatInput.length}/${MAX_CHAT_MESSAGE_CHARS}`}
                  </span>
                </div>

                <textarea
                  value={chatInput}
                  maxLength={MAX_CHAT_MESSAGE_CHARS}
                  onChange={(e) => setChatInput(e.target.value.slice(0, MAX_CHAT_MESSAGE_CHARS))}
                  placeholder="Ask a focused question about the active topic..."
                  className="w-full bg-slate-950 border border-slate-800/80 rounded-2xl p-4 text-white min-h-[110px] outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all text-sm leading-relaxed resize-y"
                />

                <div className="mt-4 flex flex-wrap gap-3 items-center">
                  <button
                    onClick={submitChat}
                    disabled={loading || !chatInput.trim() || chatUsage?.remaining_chat_requests === 0}
                    className="bg-cyan-600 hover:bg-cyan-500 text-white px-5 py-2.5 rounded-xl font-semibold transition-all shadow-lg shadow-cyan-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loading ? 'Checking Sources...' : 'Ask Documents'}
                  </button>
                  {chatHistory.length > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        setChatResult(null);
                        setChatHistory([]);
                        setChatInput('');
                      }}
                      className="bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 px-5 py-2.5 rounded-xl font-semibold transition-all border border-slate-700"
                    >
                      Clear
                    </button>
                  )}
                  {chatUsage && chatUsage.remaining_chat_requests <= 3 && (
                    <span className="text-xs text-amber-300">
                      {chatUsage.remaining_chat_requests === 0 ? 'Chat limit reached for this session.' : 'Chat limit is getting close.'}
                    </span>
                  )}
                </div>

                {conversationItems.length > 0 && (
                  <div className="mt-6 space-y-2">
                    <span className="block text-[10px] uppercase tracking-widest font-bold text-slate-500">Previous interactions</span>
                    {conversationItems.map((item, index) => {
                      const preview = item.question.length > COMPACT_CHAT_PREVIEW_CHARS
                        ? `${item.question.slice(0, COMPACT_CHAT_PREVIEW_CHARS).trim()}...`
                        : item.question;
                      return (
                        <button
                          key={index}
                          type="button"
                          onClick={() => setSelectedInteraction(item)}
                          className="w-full rounded-xl border border-slate-800/70 bg-slate-950/30 p-3 text-left transition hover:border-cyan-500/40 hover:bg-slate-900/60"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-xs font-semibold text-slate-300">Interaction {index + 1}</span>
                            <span className="text-[10px] text-slate-500">
                              {item.source_chunks.length} source{item.source_chunks.length === 1 ? '' : 's'}
                            </span>
                          </div>
                          <p className="mt-1 line-clamp-1 text-sm text-slate-400">{preview}</p>
                        </button>
                      );
                    })}
                  </div>
                )}

                {chatResult && chatHistory.length === 0 && (
                  <div className="mt-6 p-5 rounded-2xl border border-cyan-500/20 bg-cyan-950/10">
                    <MarkdownText text={chatResult.answer} />

                    {chatResult.source_chunks.length > 0 && (
                      <div className="mt-5 p-3 bg-indigo-950/30 border border-indigo-800/30 rounded-xl">
                        <span className="text-[10px] uppercase tracking-widest text-indigo-400 font-bold block mb-2 flex items-center gap-1.5">
                          <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                            <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z" />
                          </svg>
                          Sourced from your document
                        </span>
                        <SourceCards chunks={chatResult.source_chunks} />
                      </div>
                    )}
                  </div>
                )}
              </section>

              {!question && !summary ? (
            <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/60 p-12 rounded-3xl text-center max-w-2xl mx-auto shadow-2xl">
              <h2 className="text-2xl font-bold mb-3">Ready to practice <span className="text-blue-400">{topic}</span>?</h2>
              <p className="text-slate-400 text-sm mb-8 leading-relaxed max-w-md mx-auto">
                The AI Study Coach will pull contextual excerpts from your uploaded notes and customize a practice question matching your current skill level.
              </p>
              <div className="mb-6 mx-auto max-w-xl">
                <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Question Difficulty</div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {QUIZ_DIFFICULTIES.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setQuestionDifficulty(option.value)}
                      className={`rounded-xl border px-4 py-3 text-left transition-all ${
                        questionDifficulty === option.value
                          ? 'border-blue-400/60 bg-blue-500/15 text-blue-100'
                          : 'border-slate-800 bg-slate-950/30 text-slate-300 hover:border-slate-700'
                      }`}
                    >
                      <span className="block text-sm font-semibold">{option.label}</span>
                      <span className="mt-1 block text-xs text-slate-500">{option.description}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <button 
                  onClick={() => fetchQuestion()}
                  disabled={loading}
                  className="bg-blue-600 hover:bg-blue-500 text-white px-8 py-3.5 rounded-xl font-semibold transition-all shadow-lg shadow-blue-500/25 disabled:opacity-50 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-95"
                >
                  {loading ? 'Analyzing...' : 'Generate Quiz Question'}
                </button>
                <button
                  onClick={() => fetchSummary()}
                  disabled={loading}
                  className="bg-slate-800/80 hover:bg-slate-700/80 text-slate-200 px-8 py-3.5 rounded-xl font-semibold transition-all border border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-95"
                >
                  {loading ? 'Analyzing...' : 'Generate Concept Summary'}
                </button>
              </div>
            </div>
          ) : summary ? (
            <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/50 p-8 rounded-3xl shadow-2xl animate-in fade-in slide-in-from-bottom-4 duration-500 max-w-3xl mx-auto">
              <div className="flex justify-between items-center gap-4 mb-6">
                <span className="px-3 py-1.5 rounded-full text-xs font-semibold uppercase tracking-wider border bg-cyan-500/10 text-cyan-300 border-cyan-500/20">
                  Concept Summary
                </span>
                <span className="text-xs text-slate-500 font-medium">Concept: {topic}</span>
              </div>

              <MarkdownText text={summary.summary} className="mb-6 text-base" />

              {summary.key_points.length > 0 && (
                <div className="mb-6 p-4 bg-slate-950/50 border border-slate-800 rounded-2xl">
                  <span className="text-xs uppercase font-semibold tracking-wider text-cyan-300 block mb-3">Key Points</span>
                  <ul className="list-disc pl-5 text-sm text-slate-300 space-y-2">
                    {summary.key_points.map((point, i) => (
                      <li key={i}>{point}</li>
                    ))}
                  </ul>
                </div>
              )}

              {summary.source_chunks.length > 0 && (
                <div className="mb-6 p-3 bg-indigo-950/30 border border-indigo-800/30 rounded-xl">
                  <span className="text-[10px] uppercase tracking-widest text-indigo-400 font-bold block mb-2 flex items-center gap-1.5">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                      <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z" />
                    </svg>
                    Sourced from your document
                  </span>
                  <SourceCards chunks={summary.source_chunks} />
                </div>
              )}

              <div className="flex flex-wrap gap-4">
                <button
                  onClick={() => fetchQuestion()}
                  disabled={loading}
                  className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-xl font-semibold transition-all shadow-lg shadow-blue-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Generate Quiz Question
                </button>
              </div>
            </div>
          ) : (
            <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/50 p-8 rounded-3xl shadow-2xl animate-in fade-in slide-in-from-bottom-4 duration-500 max-w-3xl mx-auto">
              <div className="flex justify-between items-center mb-6">
                <span className={`px-3 py-1.5 rounded-full text-xs font-semibold uppercase tracking-wider border ${getDifficultyColor(question.difficulty)}`}>
                  Skill Level: {question.difficulty}
                </span>
                <span className="text-xs text-slate-500 font-medium">Concept: {topic}</span>
              </div>
              
              <h2 className="text-xl md:text-2xl font-medium mb-6 leading-relaxed text-slate-100">{question.question}</h2>

              {/* Source Citations for Question */}
              {question.source_chunks && question.source_chunks.length > 0 && (
                <div className="mb-6 p-3 bg-indigo-950/30 border border-indigo-800/30 rounded-xl">
                  <span className="text-[10px] uppercase tracking-widest text-indigo-400 font-bold block mb-2 flex items-center gap-1.5">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                      <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z" />
                    </svg>
                    Sourced from your document
                  </span>
                  <SourceCards chunks={question.source_chunks} />
                </div>
              )}

              <div className="mb-6">
                <textarea 
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  placeholder="Draft your explanation here. Feel free to explain step-by-step..."
                  className="w-full bg-slate-950 border border-slate-800/80 rounded-2xl p-4 text-white min-h-[160px] outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all text-sm leading-relaxed resize-y"
                />
              </div>
              
              {!evaluation ? (
                <div className="flex flex-wrap gap-4 items-center">
                  <button 
                    onClick={submitAnswer}
                    disabled={loading || !answer.trim()}
                    className="bg-emerald-600 hover:bg-emerald-500 text-white px-6 py-3 rounded-xl font-semibold transition-all shadow-lg shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed hover:scale-[1.01]"
                  >
                    {loading ? 'Evaluating Response...' : 'Submit Response'}
                  </button>
                  {question.hints && question.hints.length > 0 && (
                    <button 
                      onClick={() => setShowHint(!showHint)}
                      className="bg-slate-800/80 hover:bg-slate-700/80 text-slate-300 px-6 py-3 rounded-xl font-semibold transition-all border border-slate-700"
                    >
                      {showHint ? 'Hide Hint' : 'Need a Hint?'}
                    </button>
                  )}
                </div>
              ) : (
                <div className="flex gap-4">
                  <button 
                    onClick={() => fetchQuestion()}
                    className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-xl font-semibold transition-all shadow-lg shadow-blue-500/20"
                  >
                    Next Question &rarr;
                  </button>
                </div>
              )}

              {showHint && question.hints && (
                <div className="mt-6 p-4 bg-slate-950/60 border border-slate-800 rounded-xl animate-in fade-in slide-in-from-top-2 duration-300">
                  <span className="text-xs uppercase font-semibold tracking-wider text-indigo-400 block mb-2">Coach Hints:</span>
                  <ul className="list-disc pl-5 text-sm text-slate-300 space-y-1.5">
                    {question.hints.map((hint: string, i: number) => (
                      <li key={i}>{hint}</li>
                    ))}
                  </ul>
                </div>
              )}

              {evaluation && (
                <div className={`mt-8 p-6 rounded-2xl border ${evaluation.is_correct ? 'bg-emerald-950/20 border-emerald-500/30' : 'bg-rose-950/20 border-rose-500/30'} animate-in fade-in duration-500`}>
                  <div className="flex items-center gap-3 mb-3">
                    <div className={`p-1.5 rounded-full ${evaluation.is_correct ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                      {evaluation.is_correct ? (
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                        </svg>
                      ) : (
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                        </svg>
                      )}
                    </div>
                    <h3 className={`font-bold text-lg ${evaluation.is_correct ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {evaluation.is_correct
                        ? 'Excellent explanation!'
                        : evaluation.correctness_score && evaluation.correctness_score > 0
                          ? 'Good start, let\'s sharpen it'
                          : 'Let\'s refine your understanding'}
                    </h3>
                  </div>
                  {typeof evaluation.correctness_score === 'number' && (
                    <div className="mb-4 inline-flex rounded-lg border border-slate-700 bg-slate-950/50 px-3 py-1.5 text-xs text-slate-300">
                      Answer credit: {(evaluation.correctness_score * 100).toFixed(0)}%
                    </div>
                  )}
                  <p className="text-slate-300 text-sm leading-relaxed mb-6">{evaluation.feedback}</p>

                  {/* Source Citations for Evaluation */}
                  {evaluation.source_chunks && evaluation.source_chunks.length > 0 && (
                    <div className="mb-5 p-3 bg-slate-900/60 border border-slate-700/40 rounded-xl">
                      <span className="text-[10px] uppercase tracking-widest text-slate-400 font-bold block mb-2 flex items-center gap-1.5">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
                          <path d="M9 4.804A7.968 7.968 0 005.5 4c-1.255 0-2.443.29-3.5.804v10A7.969 7.969 0 015.5 14c1.669 0 3.218.51 4.5 1.385A7.962 7.962 0 0114.5 14c1.255 0 2.443.29 3.5.804v-10A7.968 7.968 0 0014.5 4c-1.255 0-2.443.29-3.5.804V12a1 1 0 11-2 0V4.804z" />
                        </svg>
                        Answer evaluated using
                      </span>
                      <div className="flex flex-wrap gap-2">
                        {evaluation.source_chunks.map((chunk: SourceChunk, i: number) => (
                          <span key={i} className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-slate-800/60 border border-slate-700/50 rounded-lg text-xs text-slate-300">
                            <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3 text-slate-400" viewBox="0 0 20 20" fill="currentColor">
                              <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clipRule="evenodd" />
                            </svg>
                            <span className="font-medium truncate max-w-[140px]" title={chunk.document_title}>{chunk.document_title}</span>
                            <span className="text-slate-500">·</span>
                            <span className="text-slate-400 whitespace-nowrap">p.{chunk.page_number}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  <div className="border-t border-slate-800/80 pt-4 flex flex-col gap-4">
                    <div className="flex justify-between items-center text-xs">
                      <span className="text-slate-400 font-medium uppercase tracking-wider">Concept Mastery Progress</span>
                      <span className={`font-bold px-2 py-0.5 rounded ${evaluation.is_correct ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                        {(evaluation.new_mastery_score * 100).toFixed(0)}%
                      </span>
                    </div>
                    
                    {/* Mastery Bar */}
                    <div className="w-full bg-slate-950 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div 
                        className={`h-full transition-all duration-1000 ${evaluation.is_correct ? 'bg-gradient-to-r from-emerald-500 to-teal-400' : 'bg-gradient-to-r from-rose-500 to-amber-500'}`}
                        style={{ width: `${evaluation.new_mastery_score * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
              )}
            </>
          )}
          {selectedInteraction && (
            <div
              className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 px-4 py-8 backdrop-blur-sm"
              onClick={() => setSelectedInteraction(null)}
              role="dialog"
              aria-modal="true"
            >
              <div
                className="max-h-[88vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-950 p-6 shadow-2xl shadow-black/50"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="mb-5 flex items-center justify-between gap-4">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-cyan-300">Interaction</span>
                  <button
                    type="button"
                    onClick={() => setSelectedInteraction(null)}
                    className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-800"
                  >
                    Close
                  </button>
                </div>

                <section className="mb-6">
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Question</h3>
                  <p className="text-base font-bold leading-relaxed text-slate-100">{selectedInteraction.question}</p>
                </section>

                <section className="mb-6">
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Answer</h3>
                  <MarkdownText text={selectedInteraction.answer} />
                </section>

                {selectedInteraction.source_chunks.length > 0 && (
                  <section>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">Sources</h3>
                    <SourceCards chunks={selectedInteraction.source_chunks} />
                  </section>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

