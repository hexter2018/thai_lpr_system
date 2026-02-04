// src/components/VerificationItem.tsx
import React, { useMemo, useState, useEffect, useRef } from "react";
import { verifyLog } from "../lib/api";
import { joinStorageUrl } from "../lib/utils";
import { THAI_PROVINCES } from "../lib/province-list";
import { Combobox } from "@headlessui/react";
import { CheckIcon, ChevronUpDownIcon } from "@heroicons/react/20/solid";
import * as fuzzball from "fuzzball"; // use JS fuzzball for partial_ratio

export default function VerificationItem({ item, onVerified }: any) {
  const [license, setLicense] = useState(item.detected_text ?? "");
  const [province, setProvince] = useState(item.detected_province ?? "");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [showDebug, setShowDebug] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  const filteredProvinces = useMemo(() => {
    if (!query) return THAI_PROVINCES;
    return THAI_PROVINCES.filter(p => p.includes(query) || fuzzball.partial_ratio(p, query) > 80);
  }, [query]);

  const handleVerify = async (isCorrect: boolean) => {
    if (!license.trim() || !province.trim()) return;
    setSaving(true);
    try {
      await verifyLog(item.id, {
        corrected_license: license.trim(),
        corrected_province: province.trim(),
        is_correct: isCorrect
      });
      onVerified?.(item.id);
    } catch (e) {
      alert(e?.message || "Failed to verify");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    const handleHotkey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && e.ctrlKey) {
        e.preventDefault();
        handleVerify(false);
      } else if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey) {
        e.preventDefault();
        handleVerify(true);
      }
    };
    window.addEventListener("keydown", handleHotkey);
    return () => window.removeEventListener("keydown", handleHotkey);
  }, [license, province]);

  const origUrl = joinStorageUrl(item.original_image_path);
  const cropUrl = joinStorageUrl(item.cropped_plate_image_path);

  return (
    <div className="rounded-xl border bg-white shadow p-4 space-y-4">
      <div className="text-sm text-slate-700 font-semibold">
        #{item.id} — Confidence: {item.confidence_score.toFixed(3)}
        <button
          onClick={() => setShowDebug(!showDebug)}
          className="ml-4 text-xs text-emerald-600 hover:underline"
        >
          {showDebug ? "Hide Debug" : "Show Debug"}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <img src={origUrl} alt="Original" className="rounded-xl border" />
          <div className="text-xs mt-1 text-slate-500 text-center">Original</div>
        </div>
        <div>
          <img src={cropUrl} alt="Cropped" className="rounded-xl border border-emerald-500" />
          <div className="text-xs mt-1 text-slate-500 text-center">Cropped Plate</div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 items-end">
        <div>
          <label className="block text-xs font-medium text-slate-600">License</label>
          <input
            ref={inputRef}
            value={license}
            onChange={(e) => setLicense(e.target.value)}
            className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600">Province</label>
          <Combobox value={province} onChange={setProvince}>
            <div className="relative">
              <Combobox.Input
                className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
                onChange={(event) => setQuery(event.target.value)}
              />
              <Combobox.Button className="absolute inset-y-0 right-0 flex items-center pr-2">
                <ChevronUpDownIcon className="h-4 w-4 text-slate-500" aria-hidden="true" />
              </Combobox.Button>
              <Combobox.Options className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-md border bg-white py-1 text-sm shadow-lg ring-1 ring-black/5">
                {filteredProvinces.map((p) => (
                  <Combobox.Option key={p} value={p} className={({ active }) => `cursor-pointer select-none px-3 py-1 ${active ? 'bg-emerald-100' : ''}`}>
                    {({ selected }) => (
                      <span className="flex items-center gap-1">
                        {selected && <CheckIcon className="h-4 w-4 text-emerald-600" />} {p}
                      </span>
                    )}
                  </Combobox.Option>
                ))}
              </Combobox.Options>
            </div>
          </Combobox>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => handleVerify(true)}
            className="w-full rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-700 disabled:opacity-50"
            disabled={saving}
          >
            Confirm (Enter)
          </button>
          <button
            onClick={() => handleVerify(false)}
            className="w-full rounded-lg bg-amber-500 px-4 py-2 text-sm text-white hover:bg-amber-600 disabled:opacity-50"
            disabled={saving}
          >
            Save Correction (Ctrl+Enter)
          </button>
        </div>
      </div>

      {showDebug && item.debug && (
        <pre className="mt-4 rounded-lg bg-slate-100 p-3 text-xs text-slate-800 overflow-auto max-h-40">
          {JSON.stringify(item.debug, null, 2)}
        </pre>
      )}
    </div>
  );
}
