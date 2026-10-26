import assert from "node:assert/strict";
import { test } from "node:test";

type Settled = { jobKey: string; tx: string };

/** Keeps the settled result for a job key and returns it on resume. The second call does not sign. */
export function resumeSettled(
  jobKey: string,
  store: Map<string, Settled>,
  sign: (jobKey: string) => Settled,
): Settled {
  const prior = store.get(jobKey);
  if (prior) return prior;
  const signed = sign(jobKey);
  store.set(jobKey, signed);
  return signed;
}

/** The fault: the record is dropped, so a resume signs a second payment for the same job key. */
export function resumeDroppingKey(
  jobKey: string,
  _store: Map<string, Settled>,
  sign: (jobKey: string) => Settled,
): Settled {
  return sign(jobKey);
}

test("C4 control: a client that keeps the job key reuses the settled result and does not sign again", () => {
  const store = new Map<string, Settled>();
  let signs = 0;
  const sign = (jobKey: string): Settled => ({ jobKey, tx: `tx-${++signs}` });
  const first = resumeSettled("job-1", store, sign);
  const again = resumeSettled("job-1", store, sign);
  assert.equal(signs, 1);
  assert.equal(again.tx, first.tx);
  assert.equal(again.jobKey, "job-1");
});

test("C4 drop_key: a client that drops the job key signs a second payment and is caught", () => {
  const store = new Map<string, Settled>();
  let signs = 0;
  const sign = (jobKey: string): Settled => ({ jobKey, tx: `tx-${++signs}` });
  resumeDroppingKey("job-1", store, sign);
  resumeDroppingKey("job-1", store, sign);
  assert.equal(signs, 2);
  assert.equal(store.size, 0);
});
