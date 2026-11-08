// Client for photo mode (/api/slideshows). Self-contained: delete this folder to remove the feature.

import { ApiError, API_URL, authedFetch, currentAuthToken, errorMessage, mediaUrl } from "@/lib/api";
import type { TextOverlay } from "@/lib/overlays";

export const PROJECT_STORAGE_KEY = "seqnce:slideshowId";

export type PhotoSettings = {
  size: "vertical" | "landscape" | "square";
  seconds_per_photo: number;
  fit_music: boolean;
  zoom: boolean;
  fade: boolean;
  fill: "blur" | "crop" | "black";
  music_volume: number;
  music_fade_out_s: number;
  texts: TextOverlay[];
};

export const DEFAULT_SETTINGS: PhotoSettings = {
  size: "vertical",
  seconds_per_photo: 2.5,
  fit_music: false,
  zoom: true,
  fade: true,
  fill: "blur",
  music_volume: 1,
  music_fade_out_s: 2,
  texts: [],
};

export type PhotoItem = { id: string; position: number; name: string | null; width: number; height: number; taken_at: string | null };
export type ProjectStatus = "draft" | "queued" | "rendering" | "completed" | "failed";
export type Project = {
  id: string;
  status: ProjectStatus;
  progress: number;
  error: string | null;
  settings: PhotoSettings;
  photos: PhotoItem[];
  music: { name: string | null; duration: number | null } | null;
  has_output: boolean;
  output: { duration: number; width: number; height: number; size_bytes: number } | null;
  limits: { max_photos: number; max_photo_mb: number; max_music_mb: number };
  updated_at: string;
};
export type UploadResult = { added: { id: string; name: string }[]; rejected: { name: string; reason: string }[]; photo_count: number };

export const SIZE_RATIO: Record<PhotoSettings["size"], number> = { vertical: 9 / 16, landscape: 16 / 9, square: 1 };
// the same limits the server uses when it fits the time per photo to the music
export const MIN_PER_PHOTO = 0.6;
export const MAX_PER_PHOTO = 10;

/** Seconds each photo is shown (mirrors backend engine.seconds_per_photo). */
export function perPhoto(s: PhotoSettings, nPhotos: number, musicDuration: number | null): number {
  const per =
    s.fit_music && musicDuration && nPhotos ? Math.min(Math.max(musicDuration / nPhotos, MIN_PER_PHOTO), MAX_PER_PHOTO) : s.seconds_per_photo;
  return Math.max(1, Math.round(per * FPS)) / FPS; // a clip lasts a whole number of frames
}
export const FPS = 30;

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authedFetch(path, init);
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(body, `Request failed (HTTP ${res.status}).`));
  return body as T;
}
const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const createProject = () => call<{ id: string }>("/api/slideshows", { method: "POST" });
export const getProject = (id: string) => call<Project>(`/api/slideshows/${id}`);
export const deleteProject = (id: string) => call<void>(`/api/slideshows/${id}`, { method: "DELETE" });
export const saveSettings = (id: string, s: PhotoSettings) => call<Project>(`/api/slideshows/${id}/settings`, jsonInit("PUT", s));
export const setOrder = (id: string, order: string[]) => call<Project>(`/api/slideshows/${id}/order`, jsonInit("PUT", { order }));
export const deleteMusic = (id: string) => call<Project>(`/api/slideshows/${id}/music`, { method: "DELETE" });
export const startRender = (id: string) => call<Project>(`/api/slideshows/${id}/render`, { method: "POST" });

/** POST a form with upload progress (fetch can't report it). */
function xhrUpload<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): { promise: Promise<T>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<T>((resolve, reject) => {
    xhr.open("POST", `${API_URL}${path}`);
    const token = currentAuthToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError("Can't reach the server."));
    xhr.onabort = () => reject(new ApiError("Upload cancelled."));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else reject(new ApiError(errorMessage(body, `Upload failed (HTTP ${xhr.status}).`)));
    };
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

export function uploadPhotoBatch(id: string, files: File[], onProgress?: (f: number) => void) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  return xhrUpload<UploadResult>(`/api/slideshows/${id}/photos`, form, onProgress);
}

export function uploadMusic(id: string, file: File, onProgress?: (f: number) => void) {
  const form = new FormData();
  form.append("file", file);
  return xhrUpload<Project>(`/api/slideshows/${id}/music`, form, onProgress);
}

export const photoUrl = (id: string, photoId: string, kind: "thumb" | "preview") => mediaUrl(`/api/slideshows/${id}/photos/${photoId}/${kind}`);
export const musicUrl = (id: string) => mediaUrl(`/api/slideshows/${id}/music/file`);
export const videoUrl = (id: string) => mediaUrl(`/api/slideshows/${id}/video`);
export const downloadUrl = (id: string) => mediaUrl(`/api/slideshows/${id}/download`);

/** Split photos into upload requests: few enough files, and small enough in total, that one request stays under
 *  proxy limits (Cloudflare's free plan rejects a request body over 100 MB). */
export function makeBatches(files: File[], maxCount = 6, maxBytes = 60 * 1024 * 1024): File[][] {
  const batches: File[][] = [];
  let current: File[] = [];
  let bytes = 0;
  for (const f of files) {
    if (current.length && (current.length >= maxCount || bytes + f.size > maxBytes)) {
      batches.push(current);
      current = [];
      bytes = 0;
    }
    current.push(f);
    bytes += f.size;
  }
  if (current.length) batches.push(current);
  return batches;
}

/** File-name order that treats numbers like people do: IMG_2 before IMG_10. */
export const naturalByName = (a: { name?: string | null }, b: { name?: string | null }) =>
  (a.name ?? "").localeCompare(b.name ?? "", undefined, { numeric: true, sensitivity: "base" });
