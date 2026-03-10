"use client";

import { useState, useEffect } from "react";
import { announceRaw, announceAI, getMode, setMode } from "@/lib/api";

const QUICK_BUTTONS = [
  "Happy hour starts now",
  "Last call in 30 minutes",
  "Karaoke tonight at 9",
  "St. Patty's — green beer $4 all night",
];

export default function BartenderPage() {
  const [password, setPassword] = useState("");
  const [authed, setAuthed] = useState(false);
  const [tab, setTab] = useState<"raw" | "ai">("raw");
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");
  const [aiScript, setAiScript] = useState("");
  const [loading, setLoading] = useState(false);
  const [announceNow, setAnnounceNow] = useState(false);
  const [mode, setModeState] = useState("jukebox");

  useEffect(() => {
    const saved = sessionStorage.getItem("ftr-password");
    if (saved) {
      setPassword(saved);
      setAuthed(true);
    }
  }, []);

  function handleLogin() {
    sessionStorage.setItem("ftr-password", password);
    setAuthed(true);
    getMode().then((r) => setModeState(r.mode)).catch(() => {});
  }

  async function toggleMode() {
    const next = mode === "jukebox" ? "ai-dj" : "jukebox";
    try {
      const r = await setMode(next as "jukebox" | "ai-dj", password);
      setModeState(r.mode);
    } catch {
      setStatus("Error switching mode");
    }
  }

  async function handleRaw(msg?: string) {
    const body = msg || text;
    if (!body.trim()) return;
    setLoading(true);
    setStatus("");
    try {
      await announceRaw(body, password, announceNow);
      setStatus(announceNow ? "Playing NOW" : "Queued — plays after current track");
      setText("");
    } catch {
      setStatus("Error sending announcement");
    } finally {
      setLoading(false);
    }
  }

  async function handleAI() {
    if (!text.trim()) return;
    setLoading(true);
    setStatus("");
    setAiScript("");
    try {
      const res = await announceAI(text, password, announceNow);
      setAiScript(res.script || "");
      setStatus(announceNow ? "Playing NOW" : "Queued — plays after current track");
    } catch {
      setStatus("Error generating announcement");
    } finally {
      setLoading(false);
    }
  }

  if (!authed) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center px-4 gap-4 max-w-md mx-auto">
        <h1 className="text-2xl font-bold">
          <span style={{ color: "var(--accent)" }}>FTR</span> Bartender
        </h1>
        <input
          type="password"
          placeholder="Enter password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLogin()}
          className="w-full px-4 py-3 rounded-xl bg-[var(--surface)] border border-[var(--border)] text-[var(--foreground)] placeholder:text-[var(--muted)] outline-none focus:border-[var(--accent)] min-h-[44px]"
        />
        <button
          onClick={handleLogin}
          className="w-full py-3 rounded-xl font-semibold min-h-[44px]"
          style={{ background: "var(--accent)", color: "var(--background)" }}
        >
          Enter
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col px-4 py-8 max-w-md mx-auto gap-6">
      <h1 className="text-2xl font-bold">
        <span style={{ color: "var(--accent)" }}>FTR</span> Bartender
      </h1>

      {/* Mode Toggle */}
      <button
        onClick={toggleMode}
        className="w-full py-3 rounded-xl font-semibold text-sm min-h-[44px] flex items-center justify-center gap-3 transition-colors"
        style={{
          background: mode === "ai-dj" ? "var(--accent)" : "var(--surface)",
          color: mode === "ai-dj" ? "var(--background)" : "var(--foreground)",
          border: mode === "ai-dj" ? "none" : "1px solid var(--border)",
        }}
      >
        <span className="w-2 h-2 rounded-full" style={{ background: mode === "ai-dj" ? "var(--background)" : "var(--accent)" }} />
        {mode === "ai-dj" ? "AI DJ Mode — segments between songs" : "Jukebox Mode — music only"}
      </button>

      <div className="flex gap-2">
        {(["raw", "ai"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setStatus(""); setAiScript(""); }}
            className="flex-1 py-2 rounded-xl font-medium text-sm min-h-[44px] transition-colors"
            style={{
              background: tab === t ? "var(--accent)" : "var(--surface)",
              color: tab === t ? "var(--background)" : "var(--foreground)",
              border: tab === t ? "none" : "1px solid var(--border)",
            }}
          >
            {t === "raw" ? "Say This" : "AI Write It"}
          </button>
        ))}
      </div>

      <textarea
        placeholder={tab === "raw" ? "Type your announcement..." : "Describe what to announce..."}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        className="w-full px-4 py-3 rounded-xl bg-[var(--surface)] border border-[var(--border)] text-[var(--foreground)] placeholder:text-[var(--muted)] outline-none focus:border-[var(--accent)] resize-none"
      />

      {/* Timing toggle */}
      <button
        onClick={() => setAnnounceNow(!announceNow)}
        className="w-full py-2 rounded-xl text-sm font-medium min-h-[44px] flex items-center justify-center gap-2 transition-colors"
        style={{
          background: announceNow ? "#e53e3e" : "var(--surface)",
          color: announceNow ? "#fff" : "var(--muted)",
          border: announceNow ? "none" : "1px solid var(--border)",
        }}
      >
        <span className="w-2 h-2 rounded-full" style={{ background: announceNow ? "#fff" : "var(--muted)" }} />
        {announceNow ? "ANNOUNCE NOW — interrupts music" : "After current track"}
      </button>

      <button
        onClick={() => (tab === "raw" ? handleRaw() : handleAI())}
        disabled={loading}
        className="w-full py-3 rounded-xl font-semibold min-h-[44px] disabled:opacity-50"
        style={{ background: announceNow ? "#e53e3e" : "var(--accent)", color: announceNow ? "#fff" : "var(--background)" }}
      >
        {loading ? "Sending..." : announceNow ? "SEND NOW" : (tab === "raw" ? "Send" : "Generate")}
      </button>

      {aiScript && (
        <div className="p-4 rounded-xl bg-[var(--surface)] border border-[var(--border)]">
          <p className="text-xs text-[var(--muted)] mb-2 uppercase tracking-wider">Generated Script</p>
          <p className="text-sm">{aiScript}</p>
        </div>
      )}

      {status && (
        <p className="text-sm text-[var(--accent)] text-center">{status}</p>
      )}

      <div className="space-y-2">
        <p className="text-xs text-[var(--muted)] uppercase tracking-wider">Quick Announcements</p>
        {QUICK_BUTTONS.map((msg) => (
          <button
            key={msg}
            onClick={() => handleRaw(msg)}
            className="w-full py-3 px-4 rounded-xl text-left text-sm min-h-[44px] transition-colors hover:bg-[var(--surface)]"
            style={{ border: "1px solid var(--border)" }}
          >
            {msg}
          </button>
        ))}
      </div>
    </div>
  );
}
