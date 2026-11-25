// "Take me to the start screen." The Edit tab asks for it; the home page does it, whether it is already on screen or is
// about to be shown. Pure logic, no app imports (tested with `node --test`).

let wanted = false;
const listeners = new Set<() => void>();

export function requestHome(): void {
  wanted = true;
  listeners.forEach((l) => l());
}

/** True once per request. */
export function takeHomeRequest(): boolean {
  const was = wanted;
  wanted = false;
  return was;
}

/** Call `listener` for requests made while it is listening. Returns how to stop. */
export function onHomeRequest(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
