"use client";

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { Document, Page, pdfjs } from 'react-pdf';
import { API_BASE_URL, authHeaders } from '../../../lib/api';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

export default function DocumentViewer() {
  const params = useParams<{ documentId: string }>();
  const searchParams = useSearchParams();
  const initialPage = Math.max(1, Number(searchParams.get('page') || 1));
  const [pageNumber, setPageNumber] = useState(initialPage);
  const [numPages, setNumPages] = useState<number | null>(null);

  const file = useMemo(() => ({
    url: `${API_BASE_URL}/documents/${params.documentId}/file`,
    httpHeaders: authHeaders() as Record<string, string>,
    withCredentials: true,
  }), [params.documentId]);

  return (
    <div className="min-h-screen bg-[#070b19] px-4 py-6 text-white md:px-8">
      <div className="mx-auto max-w-5xl">
        <header className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
          <Link href="/study" className="text-sm font-semibold text-slate-300 transition hover:text-white">
            Back to Study
          </Link>
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <button
              type="button"
              onClick={() => setPageNumber((page) => Math.max(1, page - 1))}
              disabled={pageNumber <= 1}
              className="rounded-lg border border-slate-700 px-3 py-1.5 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Prev
            </button>
            <span className="min-w-24 text-center">
              Page <span className="font-bold text-cyan-300">{pageNumber}</span>{numPages ? ` / ${numPages}` : ''}
            </span>
            <button
              type="button"
              onClick={() => setPageNumber((page) => numPages ? Math.min(numPages, page + 1) : page + 1)}
              disabled={Boolean(numPages && pageNumber >= numPages)}
              className="rounded-lg border border-slate-700 px-3 py-1.5 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </header>

        <div className="overflow-auto rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
          <Document
            file={file}
            onLoadSuccess={({ numPages }) => {
              setNumPages(numPages);
              setPageNumber(Math.min(initialPage, numPages));
            }}
            loading={<p className="p-6 text-sm text-slate-400">Loading document...</p>}
            error={<p className="p-6 text-sm text-rose-300">Could not load this document file.</p>}
          >
            <Page
              pageNumber={pageNumber}
              renderAnnotationLayer={false}
              renderTextLayer={false}
              className="mx-auto w-fit overflow-hidden rounded-lg bg-white"
            />
          </Document>
        </div>
      </div>
    </div>
  );
}
