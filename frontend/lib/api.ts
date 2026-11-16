// Thin client for the FastAPI backend. The browser talks to it directly (CORS is
// enabled for localhost:3000) so large uploads don't pass through the Next server.

import { DEFAULT_UPLOAD_CONFIG, PieceError, parseUploadConfig, sendPieces, shouldChunk, type Piece, type UploadConfig } from "./chunked";
import type { TextOverlay } from "./overlays";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// What the server says about uploads (from /api/health, see AuthGate): the biggest file, and, only when something in front
// of the server limits one request (the public setup), the size of the pieces big files are sent in. On your own computer
// there is no piece size, so every file goes up in a single request.
let uploadConfig: UploadConfig = DEFAULT_UPLOAD_CONFIG;
export const setUploadConfig = (raw: unknown) => {
  uploadConfig = parseUploadConfig(raw);
};
export const getUploadConfig = () => uploadConfig;

export type EditSettings = {
  target_duration: number;
  captions: boolean;
  remove_silence: boolean;
  background_music: boolean;
  music_track?: string | null;
  hook: boolean;
  instructions: string;
};

export const MAX_INSTRUCTIONS = 500;

export type VideoInfo = {
  duration: number;
  width: number;
  height: number;
  fps: number;
  video_codec: string;
  has_audio: boolean;
  audio_codec: string | null;
  size_bytes: number;
};

export const HOOK_CSS: Record<string, string> = {
  yellow: "#ffe600",
  white: "#ffffff",
  red: "#ff4b4b",
  cyan: "#00e6ff",
  green: "#50e650",
  pink: "#ff64c8",
  orange: "#ff9600",
};

export type JobStatus = "queued" | "running" | "completed" | "failed";

export type Job = {
  id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  original_filename: string;
  settings: EditSettings & { music_track: string | null };
  original: VideoInfo | null;
  has_output: boolean;
  current_version: number;
  revising: boolean;
  error: string | null; // for a finished job: why the last change failed
  created_at: string;
  updated_at: string;
};

export type PlanClip = {
  id: string;
  start: number;
  end: number;
  purpose: "hook" | "main_content" | "example" | "conclusion";
  reason: string;
};

export type Pos = { x: number; y: number };
export type Hook = { enabled: boolean; text: string; color: string; duration_s: number; x?: number | null; y?: number | null };

export type Plan = {
  source: "ai" | "fallback";
  fallback_reason: string | null;
  summary: { main_subject: string; main_message: string };
  target_duration: number;
  clips: PlanClip[];
  hook?: Hook;
  captions?: { enabled: boolean; x?: number | null; y?: number | null };
  texts?: TextOverlay[];
  instructions?: string;
  warnings: string[];
};

export type ClipStatus = "kept" | "trimmed" | "added" | "removed";
export type ChangedClip = PlanClip & { status: ClipStatus; before?: { start: number; end: number } };
export type Changes = {
  clips: ChangedClip[];
  settings: { field: string; before: string; after: string }[];
  counts: Record<ClipStatus, number>;
  unchanged: boolean;
  old_total: number;
  new_total: number;
};

export type Version = {
  version: number;
  source: "initial" | "chat" | "manual" | "restore";
  message: string | null;
  reply: string | null;
  created_at: string;
  plan: Plan;
  changes: Changes | null;
  has_output: boolean;
  preview_url: string | null;
  download_url: string | null;
};

export type Versions = { current: number; versions: Version[] };

export type ManualEdit = {
  hook_enabled?: boolean;
  hook_text?: string;
  hook_color?: string;
  hook_duration_s?: number;
  captions_enabled?: boolean;
  caption_x?: number;
  caption_y?: number;
  hook_x?: number;
  hook_y?: number;
  reset_positions?: ("caption" | "hook")[];
  texts?: TextOverlay[];
  remove_clips?: string[];
  clips?: { start: number; end: number; purpose: PlanClip["purpose"]; reason: string }[];
};

/** What the browser needs to preview an edit (computed by the server with the renderer's own code). */
export type TimelineSpec = {
  total: number;
  cuts: { start: number; end: number; out_start: number }[];
  pages: { start: number; end: number; text: string }[];
  captions_enabled: boolean;
  captions_pos: Pos | null;
  texts: TextOverlay[];
  hook: { enabled: boolean; text: string; color: string; duration_s: number; pos: Pos | null };
  reframe: { strategy: string; focus_x: number };
  source: { width: number; height: number; duration: number };
  clips: PlanClip[];
};

export type RevisionBody = { message: string } | { edit: ManualEdit } | { restore_version: number };

export type JobResult = {
  job_id: string;
  version: number;
  original: VideoInfo | null;
  rendered: VideoInfo | null;
  plan: Plan | null;
  preview_url: string;
  download_url: string;
};

export type Analysis = {
  transcript: {
    language: string;
    duration: number;
    complete?: boolean; // false while Whisper is still working (partial transcript: text only, no words)
    segments: { start: number; end: number; text: string; words?: { start: number; end: number; word: string }[] }[];
  };
  plan?: Plan | null;
  partial?: boolean; // true while the transcript is still being written
  visual: {
    analysis_source: "ai" | "fallback";
    main_subject: string;
    framing: string;
    speaker_focus_x: number;
    suitable_for_vertical: boolean;
    frames_sampled: number;
    frames_sent_to_ai: number;
    scene_changes: number[];
    fallback_reason?: string;
  } | null;
};

export class ApiError extends Error {}

export function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) return "Invalid request.";
  return fallback;
}

// ---------------------------------------------------------------------------
// Accounts. Only used when the server says it needs them (/api/health -> auth_required).
// The session token goes in an Authorization header; <video>, <img> and download links can't send
// headers, so they carry a short-lived signed "media token" in the URL instead (see mediaUrl).
// ---------------------------------------------------------------------------

const TOKEN_KEY = "seqnce:token";
export const JOB_STORAGE_KEY = "seqnce:jobId";

let authToken: string | null = null;
let mediaToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function loadStoredToken(): string | null {
  try {
    authToken = localStorage.getItem(TOKEN_KEY);
  } catch {
    authToken = null; // storage unavailable (private mode): the user simply signs in each visit
  }
  return authToken;
}

export function setAuthToken(token: string | null) {
  authToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
  if (!token) mediaToken = null;
}

/** The session token, for code that must send its own request (e.g. uploads with progress). */
export const currentAuthToken = () => authToken;

export const setMediaToken = (token: string | null) => {
  mediaToken = token;
};
/** Called when the server answers 401 to a request that carried a session token (expired / signed out elsewhere). */
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  onUnauthorized = fn;
};

/** Absolute URL for something the browser loads itself (video, image, download), with the media token attached. */
export function mediaUrl(path: string): string {
  const url = `${API_URL}${path}`;
  return mediaToken ? `${url}${path.includes("?") ? "&" : "?"}st=${encodeURIComponent(mediaToken)}` : url;
}

export async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers });
  } catch {
    throw new ApiError("Can't reach the server.");
  }
  if (res.status === 401 && authToken) onUnauthorized?.();
  return res;
}

export type Quota = { used: number; limit: number | null; resets_at: string | null };
/** What an account may use (plan + per-account changes). The server enforces these; the page only hides or locks things. */
export type AccountFeatures = Record<string, number | boolean | null> & { studio: boolean };
export type AuthUser = {
  email: string;
  is_admin: boolean;
  plan: string;
  features: AccountFeatures;
  quota: { videos: Quota; chats: Quota; studio?: Quota };
};
export type Session = { token: string; media_token: string; user: AuthUser };

async function postAuth<T>(path: string, body: unknown): Promise<T> {
  const res = await authedFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(data, `Request failed (HTTP ${res.status}).`));
  return data as T;
}

export async function getHealth(): Promise<{
  status: string;
  ffmpeg: boolean;
  auth_required: boolean;
  signup_open?: boolean;
  upload?: { max_mb: number; chunk_mb: number | null };
}> {
  const res = await authedFetch("/api/health");
  if (!res.ok) throw new ApiError(`The server answered HTTP ${res.status}.`);
  return res.json();
}
export const login = (email: string, password: string) => postAuth<Session>("/api/auth/login", { email, password });
export const signup = (invite_code: string, email: string, password: string) =>
  postAuth<Session>("/api/auth/signup", { invite_code, email, password });
export async function logout(): Promise<void> {
  await authedFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
}
export async function getMe(): Promise<{ auth_required: boolean; user: AuthUser; media_token: string | null }> {
  const res = await authedFetch("/api/auth/me");
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(data, `Request failed (HTTP ${res.status}).`));
  return data;
}

/**
 * Send a big file in pieces (public setup only: see UploadConfig). Resolves with the upload id to hand to the normal
 * endpoint instead of the file. `purpose` decides what the server checks before any piece is accepted.
 */
export function uploadInPieces(
  file: File,
  purpose: "video" | "studio",
  params: Record<string, string>,
  onProgress: (fraction: number) => void,
): { promise: Promise<string>; abort: () => void } {
  let cancelled = false;
  let current: XMLHttpRequest | null = null;
  const promise = (async () => {
    const res = await authedFetch("/api/uploads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ purpose, name: file.name, size: file.size, params }),
    });
    const info = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(errorMessage(info, `Upload failed (HTTP ${res.status}).`));
    const { upload_id: id, chunk_bytes: chunkBytes } = info as { upload_id: string; chunk_bytes: number };

    const putPiece = (piece: Piece, onBytes: (sent: number) => void) =>
      new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        current = xhr;
        xhr.open("PUT", `${API_URL}/api/uploads/${id}/${piece.index}`);
        if (authToken) xhr.setRequestHeader("Authorization", `Bearer ${authToken}`);
        xhr.upload.onprogress = (e) => e.lengthComputable && onBytes(e.loaded);
        xhr.onerror = () => reject(new PieceError("Can't reach the server."));
        xhr.ontimeout = () => reject(new PieceError("The server took too long to answer."));
        xhr.onabort = () => reject(new PieceError("Upload cancelled.", 499));
        xhr.onload = () => {
          if (xhr.status === 401 && authToken) onUnauthorized?.();
          if (xhr.status >= 200 && xhr.status < 300) return resolve();
          let body: unknown = null;
          try {
            body = JSON.parse(xhr.responseText);
          } catch {
            /* a non-JSON error page (e.g. the proxy's) */
          }
          reject(new PieceError(errorMessage(body, `Upload failed (HTTP ${xhr.status}).`), xhr.status));
        };
        xhr.send(file.slice(piece.start, piece.end));
      });

    try {
      await sendPieces({ size: file.size, chunkBytes, putPiece, onProgress, isCancelled: () => cancelled });
    } catch (error) {
      void authedFetch(`/api/uploads/${id}`, { method: "DELETE" }).catch(() => {}); // free the half-sent file on the server
      if (cancelled) throw new ApiError("Upload cancelled.");
      throw error instanceof PieceError ? new ApiError(error.message) : error;
    }
    return id;
  })();
  return {
    promise,
    abort: () => {
      cancelled = true;
      current?.abort();
    },
  };
}

export function uploadVideo(
  file: File,
  settings: EditSettings,
  onProgress: (fraction: number) => void,
): { promise: Promise<string>; abort: () => void } {
  if (shouldChunk(file.size, uploadConfig)) return uploadVideoInPieces(file, settings, onProgress);
  return postVideoForm(settings, { file }, onProgress);
}

/** The big-file route: the pieces go first (first 95 % of the bar), then one small request starts the job. */
function uploadVideoInPieces(file: File, settings: EditSettings, onProgress: (fraction: number) => void) {
  const pieces = uploadInPieces(file, "video", {}, (f) => onProgress(f * 0.95));
  let finish: { abort: () => void } | null = null;
  let aborted = false;
  const promise = pieces.promise.then((uploadId) => {
    if (aborted) throw new ApiError("Upload cancelled.");
    const post = postVideoForm(settings, { uploadId }, () => {});
    finish = post;
    return post.promise.then((jobId) => {
      onProgress(1);
      return jobId;
    });
  });
  return {
    promise,
    abort: () => {
      aborted = true;
      pieces.abort();
      (finish as { abort: () => void } | null)?.abort();
    },
  };
}

function postVideoForm(
  settings: EditSettings,
  source: { file: File } | { uploadId: string },
  onProgress: (fraction: number) => void,
): { promise: Promise<string>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<string>((resolve, reject) => {
    const form = new FormData();
    if ("file" in source) form.append("file", source.file);
    else form.append("upload_id", source.uploadId);
    form.append("target_duration", String(settings.target_duration));
    form.append("captions", String(settings.captions));
    form.append("remove_silence", String(settings.remove_silence));
    form.append("background_music", String(settings.background_music));
    if (settings.background_music && settings.music_track) form.append("music_track", settings.music_track);
    form.append("hook", String(settings.hook));
    form.append("instructions", settings.instructions.trim());

    xhr.open("POST", `${API_URL}/api/videos/upload`);
    if (authToken) xhr.setRequestHeader("Authorization", `Bearer ${authToken}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () =>
      reject(new ApiError("Can't reach the server. Is the backend running on port 8000?"));
    xhr.onabort = () => reject(new ApiError("Upload cancelled."));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status === 401 && authToken) onUnauthorized?.();
      if (xhr.status === 201) resolve((body as { job_id: string }).job_id);
      else reject(new ApiError(errorMessage(body, `Upload failed (HTTP ${xhr.status}).`)));
    };
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

async function getJson<T>(path: string): Promise<T> {
  const res = await authedFetch(path);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(body, `Request failed (HTTP ${res.status}).`));
  return body as T;
}

export const getJob = (id: string) => getJson<Job>(`/api/jobs/${id}`);
export const getMusic = () => getJson<{ tracks: string[] }>("/api/music");
export const getAnalysis = (id: string) => getJson<Analysis>(`/api/jobs/${id}/analysis`);
export const getResult = (id: string) => getJson<JobResult>(`/api/jobs/${id}/result`);
export const getVersions = (id: string) => getJson<Versions>(`/api/jobs/${id}/versions`);
export const originalUrl = (id: string) => mediaUrl(`/api/videos/${id}/original`);

/** Heights the server can cut filmstrip frames at (see /api/videos/{id}/thumb). */
export const THUMB_HEIGHTS = [48, 64, 96, 144] as const;
/** One small frame of the original video at `t` seconds (cut on a half-second grid, cached by server and browser). */
export const thumbUrl = (id: string, t: number, h: number) =>
  mediaUrl(`/api/videos/${id}/thumb?t=${Math.max(0, t).toFixed(1)}&h=${THUMB_HEIGHTS.find((x) => x >= h) ?? 144}`);

/** Preview data for the job's plan (or an older `version`), optionally with a draft `edit` applied. Saves nothing. */
export async function postTimeline(
  id: string,
  body: { version?: number; edit?: ManualEdit } = {},
): Promise<TimelineSpec> {
  const res = await authedFetch(`/api/jobs/${id}/timeline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(data, `Request failed (HTTP ${res.status}).`));
  return data as TimelineSpec;
}

/** Ask for a change (chat message), a hand edit, or a return to an earlier version. */
export async function postRevision(id: string, body: RevisionBody): Promise<void> {
  const res = await authedFetch(`/api/jobs/${id}/revisions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new ApiError(errorMessage(err, `Request failed (HTTP ${res.status}).`));
  }
}

export function formatDuration(seconds: number): string {
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
