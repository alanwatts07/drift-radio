"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { search, addToQueue, type SearchTrack } from "@/lib/api";

interface Props {
  onQueued?: (track: SearchTrack, name: string) => void;
}

export default function SearchBar({ onQueued }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchTrack[]>([]);
  const [loading, setLoading] = useState(false);
  const [namePrompt, setNamePrompt] = useState<SearchTrack | null>(null);
  const [userName, setUserName] = useState("");
  const [hasName, setHasName] = useState(false);
  const nameInputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const data = await search(q);
      setResults(data.tracks || []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => doSearch(query), 400);
    return () => clearTimeout(timerRef.current);
  }, [query, doSearch]);

  function handleTap(track: SearchTrack) {
    if (hasName) {
      // Already have a name this session — queue immediately
      doQueue(track, userName);
    } else {
      // Ask for name
      setNamePrompt(track);
      setTimeout(() => nameInputRef.current?.focus(), 100);
    }
  }

  async function doQueue(track: SearchTrack, name: string) {
    await addToQueue(track.uri);
    onQueued?.(track, name);
    // Clear everything back to clean state
    setQuery("");
    setResults([]);
    setNamePrompt(null);
  }

  function handleNameSubmit(e: React.FormEvent) {
    e.preventDefault();
    const name = userName.trim() || "Anonymous";
    setUserName(name);
    setHasName(true);
    if (namePrompt) {
      doQueue(namePrompt, name);
    }
  }

  function formatDuration(ms: number) {
    const s = Math.floor(ms / 1000);
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;
  }

  return (
    <div className="w-full space-y-2">
      <input
        type="text"
        placeholder="Search for a song..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full px-4 py-3 rounded-xl bg-[var(--surface)] border border-[var(--border)] text-[var(--foreground)] placeholder:text-[var(--muted)] outline-none focus:border-[var(--accent)] min-h-[44px]"
      />
      {loading && <p className="text-sm text-[var(--muted)]">Searching...</p>}

      {/* Name prompt overlay */}
      {namePrompt && !hasName && (
        <form onSubmit={handleNameSubmit} className="p-4 rounded-xl bg-[var(--surface)] border border-[var(--accent)] space-y-3">
          <p className="text-sm">
            Queueing <span className="font-semibold">{namePrompt.title}</span> by {namePrompt.artist}
          </p>
          <input
            ref={nameInputRef}
            type="text"
            placeholder="Your name..."
            value={userName}
            onChange={(e) => setUserName(e.target.value)}
            className="w-full px-4 py-3 rounded-xl bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] placeholder:text-[var(--muted)] outline-none focus:border-[var(--accent)] min-h-[44px]"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              className="flex-1 py-2 rounded-xl font-semibold text-sm"
              style={{ background: "var(--accent)", color: "var(--background)" }}
            >
              Queue It
            </button>
            <button
              type="button"
              onClick={() => setNamePrompt(null)}
              className="px-4 py-2 rounded-xl text-sm text-[var(--muted)] border border-[var(--border)]"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Search results */}
      {results.length > 0 && !namePrompt && (
        <div className="space-y-1">
          {results.map((t) => (
            <button
              key={t.uri}
              onClick={() => handleTap(t)}
              className="w-full flex items-center gap-3 p-3 rounded-xl hover:bg-[var(--surface)] transition-colors text-left min-h-[44px]"
            >
              {t.album_art ? (
                <img src={t.album_art} alt="" className="w-10 h-10 rounded" />
              ) : (
                <div className="w-10 h-10 rounded bg-[var(--border)]" />
              )}
              <div className="flex-1 min-w-0">
                <p className="truncate font-medium">{t.title}</p>
                <p className="truncate text-sm text-[var(--muted)]">
                  {t.artist} · {formatDuration(t.duration_ms)}
                </p>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
