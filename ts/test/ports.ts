// Loopback ports for tests that hand a port number to a subprocess: the CLI's double (--port) or a server the CLI
// starts (PORT=... --start). A port the OS just handed out is free only until something else binds it. The test files
// run in parallel processes and the kernel reuses a released port at once, so a number taken between freePorts() and
// the subprocess's bind is a race the suite has hit (#67). withPorts() runs such a test again on fresh ports; a pass or
// a real failure is never run again.
import http from "node:http";
import type { AddressInfo } from "node:net";

/** n distinct ports that were free a moment ago. All n are held while they are read and released together, so two of
 * them never share a number; the OS picks them, so none is a port fetch refuses (such as 5060 or 6000). */
export async function freePorts(n: number): Promise<number[]> {
  const servers = Array.from({ length: n }, () => http.createServer());
  for (const s of servers) await new Promise<void>((ok) => s.listen(0, "127.0.0.1", ok));
  const ports = servers.map((s) => (s.address() as AddressInfo).port);
  for (const s of servers) await new Promise<void>((ok) => s.close(() => ok()));
  return ports;
}

export const freePort = async (): Promise<number> => (await freePorts(1))[0];

export type CliResult = { code: number; out: string; err: string };

/** What the CLI prints when a port it was given is taken: "already in use" for its double's --port, and for a --start
 * server that died on EADDRINUSE (its stderr, "address already in use", reaches the CLI's); "already answering" for a
 * resource port something else holds before --start runs. All three exit 2. */
export const PORT_TAKEN = /already in use|already answering/;

/** Runs `fn` with n fresh ports. When the result is the CLI's port-taken exit (code 2 with PORT_TAKEN in its output),
 * takes n new ports and runs `fn` again, up to `attempts` times; any other result, pass or fail, is returned at once.
 * After the last attempt the result's stderr says how many times the ports were taken, so a failure reads as ports. */
export async function withPorts<T extends CliResult>(n: number, fn: (ports: number[]) => Promise<T>, attempts = 3): Promise<T> {
  let r!: T;
  for (let i = 0; i < attempts; i++) {
    r = await fn(await freePorts(n));
    if (!(r.code === 2 && PORT_TAKEN.test(r.err + r.out))) return r;
  }
  return { ...r, err: `${r.err}\n(withPorts: a port was taken on all ${attempts} attempts)` };
}
