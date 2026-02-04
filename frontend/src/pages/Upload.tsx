import React, { useRef, useState } from "react";
import EmptyState from "../components/EmptyState";
import { recognizeImage } from "../lib/api";

export default function Upload() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  async function handleFile(file: File) {
    try {
      setBusy(true);
      setErr(null);
      setResult(await recognizeImage(file));
    } catch (e: any) {
      setErr(e?.message ?? "Upload failed");
      setResult(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <div className="mb-4 text-xl font-bold text-slate-900">Upload</div>

      <div
        className="rounded-2xl border-2 border-dashed border-slate-300 bg-white p-10 text-center"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const file = e.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
      >
        <div className="text-sm font-semibold text-slate-700">Drag & Drop image here</div>
        <div className="mt-1 text-xs text-slate-500">or</div>
        <button
          className="mt-4 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
        >
          Choose File
        </button>

        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
        />
        {busy && <div className="mt-4 text-xs text-slate-500">Processing...</div>}
      </div>

      {err && <div className="mt-4 text-sm text-red-600">{err}</div>}

      {result && (
        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold text-slate-800">Result</div>
          <pre className="mt-2 overflow-auto rounded-xl bg-slate-50 p-3 text-xs text-slate-700">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}

      {!busy && !err && !result && (
        <div className="mt-6">
          <EmptyState title="Upload a plate image to start recognition" />
        </div>
      )}
    </div>
  );
}
