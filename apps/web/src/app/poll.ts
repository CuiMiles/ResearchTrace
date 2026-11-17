/**
 * One request at a time. `setInterval` keeps firing while a slow response is still
 * in flight; on a slow link those requests pile up behind the browser's six
 * connections per host and starve everything else (the PDF worker, page images).
 * Here the next tick is scheduled only after the previous one settles, and hidden
 * tabs stop polling until they are shown again.
 *
 * `tick` returns the delay before the next run, or `null` to stop. The returned
 * function stops polling; its `soon(ms)` pulls a pending tick forward (used after
 * the user starts work, so an idle 20 s wait does not hide fresh progress).
 */
export type Poller = (() => void) & { soon: (ms: number) => void };

export function startPolling(tick: () => Promise<number | null>, initialDelay = 0): Poller {
  let stopped = false;
  let timer: number | undefined;
  let dueAt = 0;
  let running = false;
  let waitingForVisible = false;

  const run = async () => {
    timer = undefined;
    if (stopped || running) return;
    if (document.visibilityState !== 'visible') {
      waitingForVisible = true;
      return;
    }
    running = true;
    let next: number | null = null;
    try {
      next = await tick();
    } catch {
      next = 10_000;
    } finally {
      running = false;
    }
    if (!stopped && next !== null) schedule(next);
  };
  const schedule = (ms: number) => {
    if (timer !== undefined) window.clearTimeout(timer);
    dueAt = Date.now() + ms;
    timer = window.setTimeout(run, ms);
  };

  const onVisible = () => {
    if (document.visibilityState === 'visible' && waitingForVisible && !stopped) {
      waitingForVisible = false;
      void run();
    }
  };
  document.addEventListener('visibilitychange', onVisible);
  schedule(initialDelay);

  const stop = () => {
    stopped = true;
    if (timer !== undefined) window.clearTimeout(timer);
    document.removeEventListener('visibilitychange', onVisible);
  };
  return Object.assign(stop, {
    soon(ms: number) {
      if (!stopped && timer !== undefined && dueAt - Date.now() > ms) schedule(ms);
    },
  });
}
