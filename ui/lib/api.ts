const API = typeof window !== "undefined" &&
  window.location.hostname !== "localhost" &&
  window.location.hostname !== "127.0.0.1"
    ? "https://ftr-api.ftrai.uk"
    : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080");

export interface NowPlaying {
  playing: boolean;
  artist: string;
  track: string;
  album_art: string;
  progress_ms: number;
  duration_ms: number;
}

export interface SearchTrack {
  title: string;
  artist: string;
  uri: string;
  album_art: string;
  duration_ms: number;
}

export interface Status {
  online: boolean;
  listeners: number;
}

export interface AnnounceResult {
  script?: string;
}

export async function getNowPlaying(): Promise<NowPlaying> {
  const res = await fetch(`${API}/nowplaying`);
  return res.json();
}

export async function search(q: string): Promise<{ tracks: SearchTrack[] }> {
  const res = await fetch(`${API}/search?q=${encodeURIComponent(q)}`);
  return res.json();
}

export async function addToQueue(uri: string): Promise<void> {
  await fetch(`${API}/queue/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uri }),
  });
}

export async function getStatus(): Promise<Status> {
  const res = await fetch(`${API}/status`);
  return res.json();
}

export async function getQueue(): Promise<{ queue: { title: string; artist: string; album_art?: string }[] }> {
  const res = await fetch(`${API}/queue`);
  return res.json();
}

export async function announceRaw(text: string, password: string, now = false): Promise<void> {
  await fetch(`${API}/announce/raw`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-password": password,
    },
    body: JSON.stringify({ text, now }),
  });
}

export async function getMode(): Promise<{ mode: string }> {
  const res = await fetch(`${API}/mode`);
  return res.json();
}

export async function setMode(mode: "jukebox" | "ai-dj", password: string): Promise<{ mode: string }> {
  const res = await fetch(`${API}/mode`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-password": password,
    },
    body: JSON.stringify({ mode }),
  });
  return res.json();
}

export async function announceAI(prompt: string, password: string, now = false): Promise<AnnounceResult> {
  const res = await fetch(`${API}/announce/ai`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-password": password,
    },
    body: JSON.stringify({ prompt, now }),
  });
  return res.json();
}
