// Loaded with node --import before the harness. Every TCP connection (net and tls sockets, which fetch also uses)
// to an address that is not loopback is refused and counted, and so is every DNS lookup of a name that is not
// localhost. The harness reports the count; a run with any refused attempt is not a valid parity run.
import dns from "node:dns";
import net from "node:net";

const LOOPBACK = new Set(["127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"]);
export const guard = { outbound: 0, refused: [] as string[] };
(globalThis as { __parityGuard?: typeof guard }).__parityGuard = guard;

function hostOf(args: unknown[]): string | undefined {
  // net.Socket#connect is called as (options, cb), (port, host, cb), (path, cb) or, from net.connect, with one
  // already-normalised array [options, cb].
  const a0 = Array.isArray(args[0]) ? (args[0] as unknown[])[0] : args[0];
  if (a0 && typeof a0 === "object") {
    const o = a0 as { host?: string; path?: string };
    return o.path ? undefined : (o.host ?? "localhost");
  }
  if (typeof a0 === "number" || (typeof a0 === "string" && /^\d+$/.test(a0))) {
    return typeof args[1] === "string" ? args[1] : "localhost";
  }
  return undefined; // a unix socket path
}

const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (this: net.Socket, ...args: unknown[]) {
  const host = hostOf(args);
  if (host !== undefined && !LOOPBACK.has(host)) {
    guard.outbound++;
    guard.refused.push(host);
    process.nextTick(() => this.destroy(new Error(`parity guard: refused a connection to ${host}`)));
    return this;
  }
  return (connect as (...a: unknown[]) => net.Socket).apply(this, args);
} as typeof net.Socket.prototype.connect;

const lookup = dns.lookup;
(dns as { lookup: unknown }).lookup = function (hostname: string, ...rest: unknown[]) {
  if (!LOOPBACK.has(hostname)) {
    guard.outbound++;
    guard.refused.push(hostname);
    const cb = rest[rest.length - 1] as (e: Error) => void;
    process.nextTick(() => cb(new Error(`parity guard: refused a DNS lookup of ${hostname}`)));
    return;
  }
  return (lookup as (...a: unknown[]) => unknown).apply(dns, [hostname, ...rest]);
};
