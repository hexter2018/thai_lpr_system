// src/components/VerificationItem.tsx
import React, { useMemo, useState } from "react";

type ScanLogItem = {
  id: number;
  original_image_path: string;
  cropped_plate_image_path: string;
  detected_text: string | null;
  detected_province: string | null;
  confidence_score: number;
  created_at: string;
};

type Props = {
  item: ScanLogItem;
  onVerified?: (id: number) => void;
};

function joinStorageUrl(path: string) {
  // If backend serves static files under /static, adjust here
  // Example: original_image_path might be "storage/2026-02-04/orig_xxx.jpg"
  // You may serve it as: GET /static/storage/...
  return `/static/${path}`.replaceAll("//", "/");
}

export default function VerificationItem({ item, onVerified }: Props) {
  const [license, setLicense] = useState(item.detected_text ?? "");
  const [province, setProvince] = useState(item.detected_province ?? "");
  const [saving, setSaving] = useState(false);

  const [zoomUrl, setZoomUrl] = useState<string | null>(null);

  const origUrl = useMemo(() => joinStorageUrl(item.original_image_path), [item.original_image_path]);
  const cropUrl = useMemo(() => joinStorageUrl(item.cropped_plate_image_path), [item.cropped_plate_image_path]);

  async function postVerify(isCorrect: boolean) {
    if (!license.trim() || !province.trim()) return;

    setSaving(true);
    try {
      const res = await fetch(`/api/verify/${item.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          corrected_license: license.trim(),
          corrected_province: province.trim(),
          is_correct: isCorrect,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail ?? "Verify failed");
      }

      onVerified?.(item.id);
    } catch (e: any) {
      alert(e?.message ?? "Error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="w-full rounded-2xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="flex flex-col gap-1 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm text-slate-500">
            Log #{item.id} • {new Date(item.created_at).toLocaleString()}
          </div>
          <div className="text-sm">
            <span className="font-semibold text-slate-800">AI:</span>{" "}
            <span className="text-slate-700">
              {item.detected_text ?? "-"} / {item.detected_province ?? "-"}
            </span>
            <span className="ml-3 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">
              conf {item.confidence_score.toFixed(3)}
            </span>
          </div>
        </div>

        <div className="text-xs text-slate-500">
          Tip: click image to zoom
        </div>
      </div>

      {/* Images */}
      <div className="grid gap-3 px-4 pb-4 sm:grid-cols-2">
        {/* Original */}
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 text-xs font-semibold text-slate-600">Original</div>
          <button
            type="button"
            className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white"
            onClick={() => setZoomUrl(origUrl)}
            title="Click to zoom"
          >
            <img
              src={origUrl}
              alt="Original"
              className="h-64 w-full object-contain sm:h-72"
              loading="lazy"
            />
          </button>
        </div>

        {/* Cropped (Bigger emphasis) */}
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-xs font-semibold text-slate-600">Cropped Plate (Verify here)</div>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">
              Priority
            </span>
          </div>

          <button
            type="button"
            className="w-full overflow-hidden rounded-lg border-2 border-emerald-200 bg-white"
            onClick={() => setZoomUrl(cropUrl)}
            title="Click to zoom"
          >
            <img
              src={cropUrl}
              alt="Cropped plate"
              className="h-72 w-full object-contain sm:h-80"
              loading="lazy"
            />
          </button>
        </div>
      </div>

      {/* Form */}
      <div className="grid gap-3 px-4 pb-4 sm:grid-cols-3">
        <div className="sm:col-span-1">
          <label className="mb-1 block text-xs font-semibold text-slate-600">License</label>
          <input
            value={license}
            onChange={(e) => setLicense(e.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-400"
            placeholder="e.g., 1กก 1234"
          />
        </div>

        <div className="sm:col-span-1">
          <label className="mb-1 block text-xs font-semibold text-slate-600">Province</label>
          <input
            value={province}
            onChange={(e) => setProvince(e.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-400"
            placeholder="e.g., กรุงเทพมหานคร"
          />
        </div>

        <div className="sm:col-span-1 flex items-end gap-2">
          <button
            disabled={saving || !license.trim() || !province.trim()}
            onClick={() => postVerify(true)}
            className="w-full rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50"
          >
            Confirm (Correct)
          </button>

          <button
            disabled={saving || !license.trim() || !province.trim()}
            onClick={() => postVerify(false)}
            className="w-full rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-amber-600 disabled:opacity-50"
          >
            Save Correction
          </button>
        </div>
      </div>

      {/* Zoom Modal */}
      {zoomUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onClick={() => setZoomUrl(null)}
        >
          <div
            className="max-h-[90vh] w-full max-w-5xl overflow-hidden rounded-2xl bg-white"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-200 p-3">
              <div className="text-sm font-semibold text-slate-700">Zoom</div>
              <button
                className="rounded-lg px-3 py-1 text-sm text-slate-600 hover:bg-slate-100"
                onClick={() => setZoomUrl(null)}
              >
                Close
              </button>
            </div>
            <div className="p-3">
              <img src={zoomUrl} alt="Zoomed" className="max-h-[80vh] w-full object-contain" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
