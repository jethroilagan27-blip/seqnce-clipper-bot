// Run a list of jobs a few at a time (uploads: a long list is much quicker with three going at once than one by one).
// No React and no imports, so `npm test` can run it.

/** Call `worker` for every item, with at most `limit` running at the same moment. Items START in list order.
 *  Resolves when all are finished. A worker should catch its own errors: one that throws stops the pool. */
export async function runPool<T>(items: T[], limit: number, worker: (item: T, index: number) => Promise<void>): Promise<void> {
  let next = 0;
  const runners = Array.from({ length: Math.max(1, Math.min(Math.floor(limit), items.length)) }, async () => {
    for (;;) {
      const index = next++;
      if (index >= items.length) return;
      await worker(items[index], index);
    }
  });
  await Promise.all(runners);
}
