import React from "react";
import { NavLink } from "react-router-dom";
import { cn } from "../lib/utils";

const nav = [
  { to: "/", label: "Overview" },
  { to: "/verify", label: "Verification Queue" },
  { to: "/upload", label: "Upload" },
];

export default function TopBar() {
  return (
    <div className="sticky top-0 z-40 border-b border-slate-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-slate-900" />
          <div>
            <div className="text-sm font-bold text-slate-900">Thai LPR Dashboard</div>
            <div className="text-xs text-slate-500">ALPR • MLPR • Active Learning</div>
          </div>
        </div>

        <div className="flex items-center gap-1 rounded-xl bg-slate-100 p-1">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                cn(
                  "rounded-lg px-3 py-1.5 text-sm font-semibold transition",
                  isActive ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
                )
              }
            >
              {n.label}
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  );
}
