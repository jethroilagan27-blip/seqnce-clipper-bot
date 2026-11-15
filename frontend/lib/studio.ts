// Studio client: the API calls. The document types and the pure helpers live in studioDoc.ts (re-exported here).

import { API_URL, ApiError, authedFetch, currentAuthToken, errorMessage, mediaUrl } from "@/lib/api";
import type { Asset, AssetKind, StudioDoc } from "./studioDoc.ts";

export * from "./studioDoc.ts";

export const STUDIO_STORAGE_KEY = "seqnce:studioId";

export type ProjectStatus = "draft" | "queued" | "rendering" | "completed" | "failed";
export type Limits = {
  max_projects: number;
  max_scenes: number;
  max_minutes: number;
  max_height: number;
  max_assets: number;
  max_storage_mb: number;
  max_file_mb: number;
  renders_per_day: number | null;
  crossfade: boolean;
  text_effects: boolean;
  overlays: boolean;
  grid: boolean;
  credits: boolean;
  ducking: boolean;
  auto_montage: boolean;
  custom_fonts: boolean;
  max_visuals_per_scene: number;
};
export type Project = {
  id: string;
  title: string;
  status: ProjectStatus;
  progress: number;
  stage: string | null;
  error: string | null;
  render: { kind: "final" | "preview" | null; scene: string | null };
  doc: StudioDoc;
  assets: Asset[];
  scenes: { id: string; duration: number | null; problem: string | null }[];
  total_seconds: number;
  has_output: boolean;
  output: { duration: number; width: number; height: number; size_bytes: number } | null;
  preview: { scene: string | null } | null;
  usage: { assets: number; bytes: number };
  limits: Limits;
  updated_at: string;
};
export type ProjectSummary = {
  id: string;
  title: string;
  status: ProjectStatus;
  asset_count: number;
  scene_count: number;
  has_output: boolean;
  updated_at: string;
};
export type UploadResult = { added: { id: string; kind: AssetKind; name: string }[]; rejected: { name: string; reason: string }[]; project: Project };
export type StudioInfo = { limits: Limits; fonts: string[]; accepts: Record<AssetKind, string[]> };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authedFetch(path, init);
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(body, `Request failed (HTTP ${res.status}).`));
  return body as T;
}
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const getInfo = () => call<StudioInfo>("/api/studio/info");
export const listProjects = () => call<{ projects: ProjectSummary[] }>("/api/studio/projects");
export const createProject = (title: string) => call<{ id: string }>("/api/studio/projects", json("POST", { title }));
export const getProject = (id: string) => call<Project>(`/api/studio/projects/${id}`);
export const deleteProject = (id: string) => call<void>(`/api/studio/projects/${id}`, { method: "DELETE" });
export const saveDoc = (id: string, doc: StudioDoc) => call<Project>(`/api/studio/projects/${id}/doc`, json("PUT", doc));
export const deleteAsset = (id: string, assetId: string) => call<Project>(`/api/studio/projects/${id}/assets/${assetId}`, { method: "DELETE" });
export const startRender = (id: string, kind: "final" | "preview", sceneId: string | null) =>
  call<Project>(`/api/studio/projects/${id}/render`, json("POST", { kind, scene_id: sceneId }));

/** Upload one file with progress (fetch can't report upload progress). */
export function uploadAsset(id: string, file: File, onProgress: (fraction: number) => void): { promise: Promise<UploadResult>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<UploadResult>((resolve, reject) => {
    xhr.open("POST", `${API_URL}/api/studio/projects/${id}/assets`);
    const token = currentAuthToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError("Can't reach the server."));
    xhr.onabort = () => reject(new ApiError("Upload cancelled."));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* a non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResult);
      else reject(new ApiError(errorMessage(body, `Upload failed (HTTP ${xhr.status}).`)));
    };
    const form = new FormData();
    form.append("files", file);
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

export const thumbUrl = (id: string, assetId: string) => mediaUrl(`/api/studio/projects/${id}/assets/${assetId}/thumb`);
export const assetFileUrl = (id: string, assetId: string) => mediaUrl(`/api/studio/projects/${id}/assets/${assetId}/file`);
const fresh = (url: string, version: string) => `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(version)}`;
export const previewUrl = (id: string, sceneId: string | null, version: string) =>
  fresh(mediaUrl(`/api/studio/projects/${id}/preview${sceneId ? `?scene=${encodeURIComponent(sceneId)}` : ""}`), version);
export const videoUrl = (id: string, version: string) => fresh(mediaUrl(`/api/studio/projects/${id}/video`), version);
export const downloadUrl = (id: string) => mediaUrl(`/api/studio/projects/${id}/download`);
