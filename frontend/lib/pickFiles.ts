// Picking many files and whole folders (button or drag and drop). Pure helpers plus the browser's folder reader;
// nothing here talks to the server. A "path" is the file's place inside what was picked: "Members/Vidal/wide.mov",
// or just the name for a loose file.

export type Picked = { file: File; path: string };

export const VIDEO_EXTENSIONS = [".mp4", ".mov", ".m4v", ".mkv", ".webm"];

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot).toLowerCase();
}

/** "Members/Vidal/wide.mov" -> "wide.mov" */
export function baseName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** "Members/Vidal/wide.mov" -> "Members/Vidal" ("" for a loose file) */
export function folderOf(path: string): string {
  const i = path.lastIndexOf("/");
  return i < 0 ? "" : path.slice(0, i);
}

/** Files the computer creates by itself are never what the user meant to send. */
export function isJunk(name: string): boolean {
  const n = baseName(name).toLowerCase();
  return n.startsWith(".") || n === "thumbs.db" || n === "desktop.ini";
}

/** "VO 2" sorts before "VO 10", and upper / lower case don't matter. */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

/** Folder by folder, then by name (naturally), so the order matches the order in the user's folders. */
export function sortPicked(items: Picked[]): Picked[] {
  return items.slice().sort((a, b) => naturalCompare(folderOf(a.path), folderOf(b.path)) || naturalCompare(baseName(a.path), baseName(b.path)));
}

/** Split into files with an allowed extension and the rest (junk files are dropped without a word). */
export function splitByExtension(items: Picked[], extensions: string[]): { accepted: Picked[]; skipped: Picked[] } {
  const accepted: Picked[] = [];
  const skipped: Picked[] = [];
  for (const it of items) {
    if (isJunk(it.path)) continue;
    (extensions.includes(extensionOf(it.path)) ? accepted : skipped).push(it);
  }
  return { accepted, skipped };
}

/** Add newly picked files to the ones already chosen, ignoring a file that is already there (same place, same size). */
export function mergePicked(existing: Picked[], added: Picked[]): Picked[] {
  const seen = new Set(existing.map((p) => `${p.path}\u0000${p.file.size}`));
  const merged = existing.slice();
  for (const p of added) {
    const key = `${p.path}\u0000${p.file.size}`;
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(p);
    }
  }
  return sortPicked(merged);
}

/** Files from an <input type="file"> (several files, or a whole folder: then each knows its place inside it). */
export function fromFileList(files: ArrayLike<File>): Picked[] {
  return Array.from(files).map((file) => ({ file, path: ((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name).replace(/\\/g, "/") }));
}

// ---- dropped folders ------------------------------------------------------------------------------

function readFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

async function readAllEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  const all: FileSystemEntry[] = [];
  for (;;) {
    // a reader hands over its entries in batches (about 100 at a time) until it returns nothing
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
    if (batch.length === 0) return all;
    all.push(...batch);
  }
}

async function walk(entry: FileSystemEntry, prefix: string, out: Picked[], budget: { left: number }): Promise<void> {
  if (budget.left <= 0) return;
  if (entry.isFile) {
    const file = await readFile(entry as FileSystemFileEntry);
    budget.left -= 1;
    out.push({ file, path: `${prefix}${entry.name}` });
  } else if (entry.isDirectory) {
    const children = await readAllEntries((entry as FileSystemDirectoryEntry).createReader());
    for (const child of children) await walk(child, `${prefix}${entry.name}/`, out, budget);
  }
}

/** Everything that was dropped: loose files and whole folders (their sub-folders too). At most `limit` files. */
export async function fromDataTransfer(dt: DataTransfer, limit = 1000): Promise<Picked[]> {
  // the entries must be taken out of the event before the first await: the browser empties it afterwards
  const entries = Array.from(dt.items ?? [])
    .filter((item) => item.kind === "file")
    .map((item) => (typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null));
  if (entries.length === 0 || entries.some((e) => e === null)) return fromFileList(Array.from(dt.files)); // an old browser: loose files only
  const out: Picked[] = [];
  const budget = { left: limit };
  for (const entry of entries) if (entry) await walk(entry, "", out, budget);
  return out;
}

/** The same drop but never throws: a folder that can't be read just contributes nothing. */
export async function safeFromDataTransfer(dt: DataTransfer, limit = 1000): Promise<Picked[]> {
  try {
    return await fromDataTransfer(dt, limit);
  } catch {
    return [];
  }
}

/** A short line for a list: "Members/Vidal/wide.mov" is shown as the folder in grey and the name in white. */
export function describePath(path: string): { folder: string; name: string } {
  return { folder: folderOf(path), name: baseName(path) };
}
