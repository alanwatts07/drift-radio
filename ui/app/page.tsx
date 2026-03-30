"use client";

import { useEffect, useRef, useState } from "react";
import AlbumArt from "./components/AlbumArt";
import NowPlaying from "./components/NowPlaying";
import StreamPlayer from "./components/StreamPlayer";
import ListenerCount from "./components/ListenerCount";
import SearchBar from "./components/SearchBar";
import Queue, { type QueueTrack } from "./components/Queue";
import { getNowPlaying, getStatus, getQueue, getMode, type SearchTrack } from "@/lib/api";

export default function Home() {
  const [np, setNp] = useState({
    playing: false,
    artist: "",
    track: "",
    album_art: "",
    progress_ms: 0,
    duration_ms: 0,
  });
  const [listeners, setListeners] = useState(0);
  const [queue, setQueue] = useState<QueueTrack[]>([]);
  const [queuedBy, setQueuedBy] = useState<Map<string, string>>(new Map());
  const [mode, setModeState] = useState("jukebox");

  useEffect(() => {
    getMode().then((r) => setModeState(r.mode)).catch(() => {});
    const modeInterval = setInterval(() => {
      getMode().then((r) => setModeState(r.mode)).catch(() => {});
    }, 30000);
    return () => clearInterval(modeInterval);
  }, []);

  useEffect(() => {
    getNowPlaying().then(setNp).catch(() => {});
    const npInterval = setInterval(() => {
      getNowPlaying().then(setNp).catch(() => {});
    }, 30000);
    return () => clearInterval(npInterval);
  }, []);

  useEffect(() => {
    getStatus().then((s) => setListeners(s.listeners)).catch(() => {});
    const statusInterval = setInterval(() => {
      getStatus().then((s) => setListeners(s.listeners)).catch(() => {});
    }, 30000);
    return () => clearInterval(statusInterval);
  }, []);

  const queueIntervalRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const queuePausedUntil = useRef(0);

  useEffect(() => {
    getQueue().then((d) => setQueue(d.queue)).catch(() => {});
    queueIntervalRef.current = setInterval(() => {
      if (Date.now() < queuePausedUntil.current) return; // skip while paused
      getQueue().then((d) => setQueue(d.queue)).catch(() => {});
    }, 30000);
    return () => clearInterval(queueIntervalRef.current);
  }, []);

  function handleQueued(track: SearchTrack, name: string) {
    setQueuedBy((prev) => {
      const next = new Map(prev);
      next.set(track.title, name);
      return next;
    });
    // Optimistic: prepend to top of queue
    setQueue((prev) => [
      { title: track.title, artist: track.artist, album_art: track.album_art },
      ...prev,
    ]);
    // Pause auto-poll for 60s so stale cache doesn't overwrite
    queuePausedUntil.current = Date.now() + 60000;
  }

  function refreshQueue() {
    queuePausedUntil.current = 0; // unpause on manual refresh
    getQueue().then((d) => setQueue(d.queue)).catch(() => {});
  }

  return (
    <div className="min-h-screen flex flex-col items-center px-4 py-8 max-w-md mx-auto gap-6">
      <header className="flex items-center justify-between w-full">
        <h1 className="text-xl font-bold tracking-tight">
          <span style={{ color: "var(--accent)" }}>FTR</span> — Fun Time Radio & Drift News
        </h1>
        <div className="flex items-center gap-3">
          <span className="text-xs px-2 py-0.5 rounded-full" style={{
            background: mode === "ai-dj" ? "var(--accent)" : "var(--surface)",
            color: mode === "ai-dj" ? "var(--background)" : "var(--muted)",
            border: mode === "ai-dj" ? "none" : "1px solid var(--border)",
          }}>
            {mode === "ai-dj" ? "AI DJ" : "Jukebox"}
          </span>
          <ListenerCount count={listeners} />
        </div>
      </header>

      <AlbumArt src={np.album_art || null} playing={np.playing} />

      <NowPlaying
        track={np.track}
        artist={np.artist}
        progress_ms={np.progress_ms}
        duration_ms={np.duration_ms}
      />

      <StreamPlayer />

      <SearchBar onQueued={handleQueued} />

      <Queue tracks={queue} queuedBy={queuedBy} onRefresh={refreshQueue} />
    </div>
  );
}
