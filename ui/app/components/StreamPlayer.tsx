"use client";

import { useRef, useState } from "react";

export default function StreamPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);

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
      audio.play();
      setIsPlaying(true);
    }
  }

  return (
    <div className="w-full">
      <audio ref={audioRef} />
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
