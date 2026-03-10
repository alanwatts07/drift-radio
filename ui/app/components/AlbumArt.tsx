"use client";

export default function AlbumArt({
  src,
  playing,
}: {
  src: string | null;
  playing: boolean;
}) {
  return (
    <div className="flex items-center justify-center">
      <div
        className={`vinyl-spin ${!playing ? "paused" : ""} w-64 h-64 sm:w-72 sm:h-72 rounded-full overflow-hidden border-4 border-[var(--border)] shadow-2xl`}
      >
        {src ? (
          <img
            src={src}
            alt="Album art"
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full bg-[var(--surface)] flex items-center justify-center">
            <svg
              viewBox="0 0 100 100"
              className="w-24 h-24 text-[var(--muted)]"
              fill="currentColor"
            >
              <circle cx="50" cy="50" r="48" fill="none" stroke="currentColor" strokeWidth="2" />
              <circle cx="50" cy="50" r="20" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <circle cx="50" cy="50" r="5" />
              <circle cx="50" cy="50" r="35" fill="none" stroke="currentColor" strokeWidth="0.5" />
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}
