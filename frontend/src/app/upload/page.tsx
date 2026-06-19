"use client";
import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { API_BASE_URL, authHeaders, getStoredAccessToken } from '../../lib/api';
import Link from 'next/link';
import AccountDock from '../../components/AccountDock';

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const router = useRouter();

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile.type === "application/pdf" || droppedFile.name.endsWith('.txt')) {
        setFile(droppedFile);
      } else {
        setMessage("Invalid file type. Only PDF and TXT files are accepted.");
      }
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const onButtonClick = () => {
    fileInputRef.current?.click();
  };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setMessage('');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_BASE_URL}/upload`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'include',
        headers: authHeaders(),
        body: formData,
      });

      const responseText = await res.text();
      let data: { message?: string; detail?: string } = {};
      try {
        data = responseText ? JSON.parse(responseText) : {};
      } catch {
        data = { message: responseText };
      }

      if (!res.ok) {
        const errorMessage = data.detail || data.message || 'Upload request failed.';
        throw new Error(errorMessage);
      }

      setMessage(data.message || 'Upload successful! Concepts extracted.');
      setFile(null);
    } catch (err: unknown) {
      console.error('Upload failed:', err);
      const message = err instanceof Error ? err.message : String(err);
      setMessage(`Upload failed: ${message}`);
    } finally {
      setLoading(false);
    }
  };

  // Redirect to login if no token
  useEffect(() => {
    if (!getStoredAccessToken()) {
      router.push('/login');
    }
  }, [router]);

  const formatBytes = (bytes: number, decimals = 2) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  };

  return (
    <div className="page-transition min-h-screen bg-[#070b19] bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(30,58,138,0.25),rgba(255,255,255,0))] text-white p-6 md:p-12 font-sans">
      <AccountDock />
      <div className="max-w-2xl mx-auto">
        <header className="mb-12 border-b border-slate-800 pb-8">
          <Link href="/" className="text-slate-400 hover:text-white transition-colors mb-4 inline-flex items-center gap-2 text-sm group">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 group-hover:-translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Back to Dashboard
          </Link>
          <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
            Upload Study Materials
          </h1>
          <p className="text-slate-400 mt-2 text-sm md:text-base">
            Add PDFs or TXT notes to feed the RAG vector store and index study topics.
          </p>
        </header>
        
        <main>
          <div className="bg-slate-900/40 backdrop-blur-xl border border-slate-800/80 p-8 rounded-3xl shadow-2xl">
            
            {/* Drag & Drop File Zone */}
            <div 
              onDragEnter={handleDrag}
              onDragOver={handleDrag}
              onDragLeave={handleDrag}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all flex flex-col items-center justify-center min-h-[220px] ${
                dragActive ? 'border-cyan-500 bg-cyan-500/5' : 'border-slate-850 hover:border-slate-700 bg-slate-950/20'
              }`}
              onClick={onButtonClick}
            >
              <input 
                ref={fileInputRef}
                type="file" 
                accept=".pdf,.txt"
                onChange={handleChange}
                className="hidden"
              />
              
              {!file ? (
                <>
                  <div className="p-4 bg-slate-800/40 rounded-xl mb-4 border border-slate-800/60 text-slate-400">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-semibold mb-1">Drag and drop file here</h3>
                  <p className="text-slate-400 text-xs mb-4">Supported formats: PDF, TXT (Max size: 10MB)</p>
                  <button 
                    type="button"
                    className="px-4 py-2 bg-slate-800 hover:bg-slate-750 border border-slate-700 hover:border-slate-600 transition-all rounded-lg text-xs font-semibold"
                  >
                    Select File Manually
                  </button>
                </>
              ) : (
                <div className="w-full flex flex-col items-center">
                  <div className="p-4 bg-emerald-500/10 rounded-xl mb-4 border border-emerald-500/20 text-emerald-400">
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>
                  <h3 className="text-md font-bold text-slate-100 mb-1 truncate max-w-md">{file.name}</h3>
                  <p className="text-slate-400 text-xs mb-4">{formatBytes(file.size)}</p>
                  <button 
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setFile(null);
                    }}
                    className="px-3 py-1.5 bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-400 transition-all rounded-lg text-xs font-semibold"
                  >
                    Clear File Selection
                  </button>
                </div>
              )}
            </div>
            
            {file && (
              <button 
                onClick={handleUpload}
                disabled={loading}
                className="w-full bg-emerald-600 hover:bg-emerald-550 disabled:bg-slate-800 disabled:text-slate-500 text-white font-semibold py-3.5 rounded-xl transition-all shadow-lg shadow-emerald-900/20 mt-6 hover:scale-[1.01] active:scale-[0.99]"
              >
                {loading ? 'Processing Document Chunks...' : 'Confirm Upload & Begin RAG Indexing'}
              </button>
            )}
            
            {message && (
              <div className={`mt-6 p-4 rounded-xl border flex gap-3 items-center text-sm ${
                message.includes('error') || message.includes('Invalid') 
                  ? 'bg-rose-950/20 border-rose-500/20 text-rose-400' 
                  : 'bg-emerald-950/20 border-emerald-500/20 text-emerald-400'
              }`}>
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>{message}</span>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
