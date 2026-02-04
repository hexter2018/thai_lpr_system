import React, { useEffect, useState } from "react";
import KpiCard from "../components/KpiCard";
import EmptyState from "../components/EmptyState";
import { getStats } from "../lib/api";
import type { StatsResponse } from "../lib/types";

export default function Overview() {
  const [data, setData] = useState<StatsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setErr(null);
        setData(await getStats());
      } catch (e: any) {
        setErr(e?.message ?? "Failed to load stats");
      }
    })();
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 text-xl font-bold text-slate-900">Overview</div>

      {err && (
        <EmptyState
          title="Failed to load stats"
          description={`${err} (Try: GET /api/health to check backend connectivity)`}
          action={
            <button
              className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
              onClick={() => location.reload()}
            >
              Reload
            </button>
          }
        />
      )}

      {data && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard title="Total Cars" value={data.total_scanned} />
          <KpiCard title="ALPR Count" value={data.alpr_count} hint="Auto or confirmed correct" />
          <KpiCard title="MLPR Count" value={data.mlpr_count} hint="Human corrected (hard examples)" />
          <KpiCard
            title="Accuracy Rate"
            value={`${data.accuracy_percent.toFixed(2)}%`}
            hint={`Verified accuracy: ${data.accuracy_verified_percent.toFixed(2)}%`}
          />
        </div>
      )}
    </div>
  );
}
