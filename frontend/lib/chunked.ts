// Sending a big file in pieces, for setups where one request may not be larger than something
// (the public site behind Cloudflare's free plan: 100 MB). Pure logic, no imports from the app, so it can be
// tested with `node --test`. On your own computer the server reports no piece size and none of this is used.

const MB = 1024 * 1024;

/** The server's upload settings, from /api/health. `chunkMb` is null when files go up in one request (own computer). */
export type UploadConfig = { maxMb: number; chunkMb: number | null };

export const DEFAULT_UPLOAD_CONFIG: UploadConfig = { maxMb: 500, chunkMb: null };

/** Read the `upload` block of /api/health defensively (an older server has none: send whole, 500 MB). */
export function parseUploadConfig(raw: unknown): UploadConfig {
  const o = (raw ?? {}) as { max_mb?: unknown; chunk_mb?: unknown };
  const maxMb = typeof o.max_mb === "number" && o.max_mb > 0 ? o.max_mb : DEFAULT_UPLOAD_CONFIG.maxMb;
  const chunkMb = typeof o.chunk_mb === "number" && o.chunk_mb > 0 ? o.chunk_mb : null;
  return { maxMb, chunkMb };
}

/** Must this file be sent in pieces? Never when the server gave no piece size; otherwise only when it is bigger than one piece. */
export function shouldChunk(size: number, config: UploadConfig): boolean {
  return config.chunkMb !== null && size > config.chunkMb * MB;
}

export type Piece = { index: number; start: number; end: number };

/** Cut `size` bytes into pieces of `chunkBytes` (the last one may be shorter). */
export function planPieces(size: number, chunkBytes: number): Piece[] {
  const out: Piece[] = [];
  for (let start = 0, index = 0; start < size; start += chunkBytes, index += 1) {
    out.push({ index, start, end: Math.min(start + chunkBytes, size) });
  }
  return out;
}

/** An error from sending one piece; `status` is the HTTP status, or undefined when the connection failed. */
export class PieceError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

/** A dropped connection, a busy server or a timeout is worth trying again; a refusal is not. */
export function isRetryable(error: unknown): boolean {
  if (!(error instanceof PieceError)) return false;
  if (error.status === undefined) return true;
  return error.status >= 500 || error.status === 408 || error.status === 429;
}

export type SendOptions = {
  size: number;
  chunkBytes: number;
  /** Pieces the server already has (to carry on after a dropped connection). */
  received?: number[];
  /** Send one piece; resolves when the server has it. `onBytes` reports how much of this piece has gone out. */
  putPiece: (piece: Piece, onBytes: (sent: number) => void) => Promise<void>;
  onProgress: (fraction: number) => void;
  isCancelled?: () => boolean;
  tries?: number;
  /** Wait before trying again (injectable for tests). */
  pause?: (ms: number) => Promise<void>;
};

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Send every missing piece, one after another, trying each a few times. Throws the last error, or "cancelled". */
export async function sendPieces(opts: SendOptions): Promise<void> {
  const { size, chunkBytes, putPiece, onProgress } = opts;
  const tries = opts.tries ?? 4;
  const pause = opts.pause ?? sleep;
  const have = new Set(opts.received ?? []);
  const pieces = planPieces(size, chunkBytes);
  let done = pieces.filter((p) => have.has(p.index)).reduce((sum, p) => sum + (p.end - p.start), 0);
  onProgress(size === 0 ? 1 : done / size);
  for (const piece of pieces) {
    if (have.has(piece.index)) continue;
    for (let attempt = 1; ; attempt += 1) {
      if (opts.isCancelled?.()) throw new Error("Upload cancelled.");
      try {
        await putPiece(piece, (sent) => onProgress(Math.min(1, (done + Math.min(sent, piece.end - piece.start)) / size)));
        break;
      } catch (error) {
        if (opts.isCancelled?.()) throw new Error("Upload cancelled.");
        if (attempt >= tries || !isRetryable(error)) throw error;
        await pause(Math.min(8000, 800 * 2 ** (attempt - 1)));
      }
    }
    done += piece.end - piece.start;
    onProgress(Math.min(1, done / size));
  }
}
