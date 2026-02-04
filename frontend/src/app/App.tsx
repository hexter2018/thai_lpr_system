import React from "react";
import { Outlet } from "react-router-dom";
import TopBar from "../components/TopBar";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <TopBar />
      <Outlet />
    </div>
  );
}
