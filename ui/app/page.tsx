"use client";

import { useEffect, useState } from "react";
import AlbumArt from "./components/AlbumArt";
import NowPlaying from "./components/NowPlaying";
import StreamPlayer from "./components/StreamPlayer";
import ListenerCount from "./components/ListenerCount";
import SearchBar from "./components/SearchBar";
import Queue, { type QueueTrack } from "./components/Queue";
import { getNowPlaying, getStatus, getQueue, type SearchTrack } from "@/lib/api";

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

  useEffect(() => {
    getNowPlaying().then(setNp).catch(() => {});
    const npInterval = setInterval(() => {
      getNowPlaying().then(setNp).catch(() => {});
    }, 15000);
    return () => clearInterval(npInterval);
  }, []);

  useEffect(() => {
    getStatus().then((s) => setListeners(s.listeners)).catch(() => {});
    const statusInterval = setInterval(() => {
      getStatus().then((s) => setListeners(s.listeners)).catch(() => {});
    }, 30000);
    return () => clearInterval(statusInterval);
  }, []);

  useEffect(() => {
    getQueue().then((d) => setQueue(d.queue)).catch(() => {});
    const queueInterval = setInterval(() => {
      getQueue().then((d) => setQueue(d.queue)).catch(() => {});
    }, 30000);
    return () => clearInterval(queueInterval);
  }, []);

  function handleQueued(track: SearchTrack, name: string) {
    setQueuedBy((prev) => {
      const next = new Map(prev);
      next.set(track.title, name);
      return next;
    });
    // Refresh queue after a short delay to pick up the new track
    setTimeout(() => {
      getQueue().then((d) => setQueue(d.queue)).catch(() => {});
    }, 2000);
  }

  return (
    <div className="min-h-screen flex flex-col items-center px-4 py-8 max-w-md mx-auto gap-6">
      <header className="flex items-center justify-between w-full">
        <h1 className="text-xl font-bold tracking-tight">
          <span style={{ color: "var(--accent)" }}>FTR</span> — Fun Time Radio
        </h1>
        <ListenerCount count={listeners} />
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

      <Queue tracks={queue} queuedBy={queuedBy} />
    </div>
  );
}
