// Polite pacing for live targets, the TypeScript twin of src/x402conf/pacing.py. createPacedFetch returns a fetch that
// waits at least minIntervalMs between the start of one request and the next (5 s by default), refuses to send more
// than maxRequests in total when a cap is set (it throws RequestBudgetExceeded before anything leaves the machine),
// and logs one line per request. Loopback targets are counted and logged but not spaced.

export const DEFAULT_MIN_INTERVAL_MS = 5_000;

export class RequestBudgetExceeded extends Error {}

export interface PaceOptions {
  minIntervalMs?: number;
  maxRequests?: number;
  /** Where each request is logged; defaults to stderr. */
  log?: (line: string) => void;
  /** The fetch underneath; defaults to global fetch. */
  fetch?: typeof fetch;
  /** For tests: the clock and the sleep. */
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
}

export interface PacedRequest { n: number; at: string; method: string; url: string; waited_ms: number; status?: number }
export type PacedFetch = typeof fetch & { requests: PacedRequest[] };

export function isLoopback(url: string): boolean {
  const h = new URL(url).hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return h === "localhost" || h === "::1" || /^127\./.test(h);
}

export function createPacedFetch(opts: PaceOptions = {}): PacedFetch {
  const gap = opts.minIntervalMs ?? DEFAULT_MIN_INTERVAL_MS;
  if (!(gap >= 0)) throw new RangeError("--min-interval must be 0 or more seconds");
  if (opts.maxRequests !== undefined && !(opts.maxRequests >= 1)) throw new RangeError("--max-requests must be at least 1");
  const base = opts.fetch ?? fetch;
  const now = opts.now ?? (() => Date.now());
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((ok) => setTimeout(ok, ms)));
  const log = opts.log ?? ((l: string) => process.stderr.write(l + "\n"));
  const requests: PacedRequest[] = [];
  let last: number | undefined;
  let queue: Promise<unknown> = Promise.resolve();
  const paced = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    // Requests are spaced one after another even when the caller starts several at once.
    const turn = queue.then(async () => {
      const n = requests.length + 1;
      if (opts.maxRequests !== undefined && n > opts.maxRequests) {
        throw new RequestBudgetExceeded(`--max-requests ${opts.maxRequests} reached; ${method} ${url} was not sent`);
      }
      let waited = 0;
      if (!isLoopback(url) && last !== undefined) {
        waited = Math.max(0, last + gap - now());
        if (waited > 0) await sleep(waited);
      }
      last = now();
      const entry: PacedRequest = { n, at: new Date().toISOString(), method, url, waited_ms: Math.round(waited) };
      requests.push(entry);
      const sig = (init?.headers as Record<string, string> | undefined)?.["PAYMENT-SIGNATURE"];
      log(`x402conf-svm: request ${n}${opts.maxRequests ? ` of at most ${opts.maxRequests}` : ""} at ${entry.at}: `
        + `${method} ${url}${sig !== undefined ? " with a malformed PAYMENT-SIGNATURE" : ""}`
        + (waited ? `, after waiting ${(waited / 1000).toFixed(1)} s` : ""));
      return entry;
    });
    queue = turn.catch(() => undefined);
    const entry = await turn;
    const r = await base(input, init);
    entry.status = r.status;
    return r;
  }) as PacedFetch;
  paced.requests = requests;
  return paced;
}
