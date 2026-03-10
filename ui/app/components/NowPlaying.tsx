"use client";

function formatTime(ms: number) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

export default function NowPlaying({
  track,
  artist,
  progress_ms,
  duration_ms,
}: {
  track: string;
  artist: string;
  progress_ms: number;
  duration_ms: number;
}) {
  const pct = duration_ms > 0 ? (progress_ms / duration_ms) * 100 : 0;

  return (
    <div className="text-center space-y-3 w-full">
      <h1 className="text-2xl sm:text-3xl font-bold truncate">{track || "Nothing playing"}</h1>
      <p className="text-lg text-[var(--muted)] truncate">{artist}</p>
      <div className="w-full">
        <div className="w-full h-1.5 bg-[var(--border)] rounded-full overflow-hidden">
          <div
            className="h-full bg-[var(--accent)] rounded-full transition-all duration-1000 ease-linear"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-[var(--muted)] mt-1">
          <span>{formatTime(progress_ms)}</span>
          <span>{formatTime(duration_ms)}</span>
        </div>
      </div>
    </div>
  );
}
