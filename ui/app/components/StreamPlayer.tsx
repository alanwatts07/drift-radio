"use client";

import { useRef, useState } from "react";

export default function StreamPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(0.8);

  function toggle() {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
      audio.src = "";
      setIsPlaying(false);
    } else {
      const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
      audio.src = isLocal ? "http://localhost:8000/live.mp3" : "https://energy.ftrai.uk/live.mp3";
      audio.volume = volume;
      audio.play();
      setIsPlaying(true);
    }
  }

  return (
    <div className="w-full">
      <audio ref={audioRef} />
      {isPlaying && (
        <div className="flex items-center gap-2 mb-2 px-1">
          <svg viewBox="0 0 24 24" fill="var(--muted)" className="w-4 h-4 flex-shrink-0"><polygon points="11,5 6,9 2,9 2,15 6,15 11,19" /><path d="M14,7.97 C16.03,9.25 17,11.53 17,12 C17,12.47 16.03,14.75 14,16.03" fill="none" stroke="var(--muted)" strokeWidth="1.5" strokeLinecap="round" /></svg>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={volume}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              setVolume(v);
              if (audioRef.current) audioRef.current.volume = v;
            }}
            className="flex-1 h-1 rounded-full appearance-none cursor-pointer"
            style={{ accentColor: "var(--accent)" }}
          />
        </div>
      )}
      <button
        onClick={toggle}
        className="w-full py-4 rounded-xl font-semibold text-lg transition-colors min-h-[44px]"
        style={{
          background: isPlaying ? "var(--surface)" : "var(--accent)",
          color: isPlaying ? "var(--foreground)" : "var(--background)",
          border: isPlaying ? "1px solid var(--border)" : "none",
        }}
      >
        {isPlaying ? (
          <>
            <svg viewBox="0 0 24 24" fill="currentColor" className="inline w-5 h-5 mr-2 -mt-0.5"><rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" /></svg>
            Stop Listening
          </>
        ) : (
          <>
            <svg viewBox="0 0 24 24" fill="currentColor" className="inline w-5 h-5 mr-2 -mt-0.5"><polygon points="6,4 20,12 6,20" /></svg>
            Tap to Listen
          </>
        )}
      </button>
    </div>
  );
}
