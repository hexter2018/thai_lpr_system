import React, { useEffect, useMemo, useState } from "react";
import EmptyState from "../components/EmptyState";
import VerificationItem from "../components/VerificationItem";
import { getPendingQueue } from "../lib/api";
import type { ScanLogItem } from "../lib/types";

export default function VerifyQueue() {
  const [items, setItems] = useState<ScanLogItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const pendingCount = useMemo(() => items.length, [items]);

  async function load() {
    try {
      setLoading(true);
      setErr(null);
      const data = await getPendingQueue(50);
      setItems(data);
    } catch (e: any) {
      setErr(e?.message ?? "Failed to load queue");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-xl font-bold text-slate-900">Verification Queue</div>
          <div className="text-sm text-slate-600">
            Pending: <span className="font-semibold">{pendingCount}</span>
          </div>
        </div>

        <button
          className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
          onClick={load}
        >
          Refresh
        </button>
      </div>

      {loading && (
        <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
          Loading queue...
        </div>
      )}

      {!loading && err && (
        <EmptyState title="Failed to load queue" description={err} />
      )}

      {!loading && !err && items.length === 0 && (
        <EmptyState
          title="No pending logs 🎉"
          description="Nothing to verify right now."
          action={
            <button
              className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
              onClick={load}
            >
              Refresh
            </button>
          }
        />
      )}

      <div className="flex flex-col gap-4">
        {items.map((it) => (
          <VerificationItem
            key={it.id}
            item={it}
            onVerified={(id) => {
              // remove from queue instantly for great UX
              setItems((prev) => prev.filter((x) => x.id !== id));
            }}
          />
        ))}
      </div>
    </div>
  );
}
