"""Discovery metadata a resource server publishes about itself, graded against its own declarations.

    P9   the bazaar extension in a 402 (extensions.bazaar) carries `info` that validates against the `schema` next to
         it (bazaar extension, "Schema Validation": facilitators MUST validate info against schema before cataloging,
         so an example that fails its own schema can keep the listing out of a catalog)
    P10  the host's /.well-known/x402 manifest, when it serves one, lists the paid URL on its own origin and declares
         payment terms the live 402 actually offers (runtime 402 behaviour is authoritative; a stale manifest
         misleads crawlers and agents)

Nothing here sends a request except fetch_well_known, which is one GET to the target's origin. The JSON Schema
validator is a small, dependency-free subset of Draft 2020-12: the assertion keywords discovery schemas use, and only
same-document $ref. Keywords it does not implement are listed as not graded rather than guessed at."""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .types import CheckResult, Json

P9 = "P9 the bazaar discovery info (info.input and its examples) validates against the schema the endpoint declares"
P10 = "P10 the /.well-known/x402 manifest lists the paid URL on its own origin and its terms match the live offer"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "$defs", "definitions", "title", "description", "default",
                         "examples", "example", "deprecated", "readOnly", "writeOnly", "format", "contentMediaType",
                         "contentEncoding", "$anchor"})
_ASSERTIONS = frozenset({"type", "enum", "const", "properties", "required", "additionalProperties", "patternProperties",
                         "items", "prefixItems", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength",
                         "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                         "allOf", "anyOf", "oneOf", "not", "$ref", "minProperties", "maxProperties", "propertyNames"})


def _type_ok(v: Any, t: str) -> bool:
    if t == "null":
        return v is None
    if t == "boolean":
        return isinstance(v, bool)
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "string":
        return isinstance(v, str)
    if t == "number":
        return isinstance(v, int | float) and not isinstance(v, bool)
    if t == "integer":  # JSON has one number type: 3 and 3.0 are both integers, "3" is a string
        return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and float(v).is_integer()
    return False


def _pointer(root: Any, ref: str) -> Any:
    node = root
    for part in ref[1:].split("/")[1:] if ref.startswith("#/") else []:
        part = urllib.parse.unquote(part).replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


class Validator:
    """validate(instance) returns a list of problems ("at /input/queryParams/limit: '3' is not of type integer")."""

    def __init__(self, schema: Any) -> None:
        self.root = schema
        self.not_graded: set[str] = set()

    def validate(self, inst: Any) -> list[str]:
        return self._v(inst, self.root, "", 0)

    def _v(self, inst: Any, s: Any, at: str, depth: int) -> list[str]:  # noqa: C901
        where = at or "/"
        if depth > 64:
            return [f"at {where}: schema nests more than 64 levels (a $ref cycle?)"]
        if s is True or s == {}:
            return []
        if s is False:
            return [f"at {where}: the schema allows nothing here"]
        if not isinstance(s, dict):
            return [f"at {where}: the schema is not an object or a boolean"]
        p: list[str] = []
        for k in s:
            if k not in _ASSERTIONS and k not in ANNOTATIONS:
                self.not_graded.add(k)
        if "$ref" in s:
            ref = s["$ref"]
            if not (isinstance(ref, str) and ref.startswith("#")):
                return [f"at {where}: $ref {ref!r} is not a same-document reference"]
            try:
                p += self._v(inst, _pointer(self.root, ref), at, depth + 1)
            except (KeyError, IndexError, ValueError, TypeError):
                return [f"at {where}: $ref {ref!r} does not resolve"]
        if "type" in s:
            ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(_type_ok(inst, str(t)) for t in ts):
                p.append(f"at {where}: {json.dumps(inst)[:60]} is not of type {' or '.join(map(str, ts))}")
                return p  # the other keywords would only repeat the type mismatch
        if "enum" in s and isinstance(s["enum"], list) and not any(_same(inst, e) for e in s["enum"]):
            p.append(f"at {where}: {json.dumps(inst)[:60]} is not one of {json.dumps(s['enum'])[:80]}")
        if "const" in s and not _same(inst, s["const"]):
            p.append(f"at {where}: {json.dumps(inst)[:60]} is not {json.dumps(s['const'])[:60]}")
        if isinstance(inst, dict):
            props: dict[str, Any] = s["properties"] if isinstance(s.get("properties"), dict) else {}
            pats: dict[str, Any] = s["patternProperties"] if isinstance(s.get("patternProperties"), dict) else {}
            for r in s.get("required", []) if isinstance(s.get("required"), list) else []:
                if r not in inst:
                    p.append(f"at {where}: required property {r!r} is missing")
            for k, v in inst.items():
                sub = f"{at}/{k}"
                matched = False
                if k in props:
                    matched = True
                    p += self._v(v, props[k], sub, depth + 1)
                for pat, ps in pats.items():
                    if re.search(pat, k):
                        matched = True
                        p += self._v(v, ps, sub, depth + 1)
                if not matched and "additionalProperties" in s:
                    ap = s["additionalProperties"]
                    if ap is False:
                        p.append(f"at {where}: property {k!r} is not allowed (additionalProperties: false)")
                    else:
                        p += self._v(v, ap, sub, depth + 1)
                if "propertyNames" in s:
                    p += self._v(k, s["propertyNames"], sub, depth + 1)
            if isinstance(s.get("minProperties"), int) and len(inst) < s["minProperties"]:
                p.append(f"at {where}: fewer than {s['minProperties']} properties")
            if isinstance(s.get("maxProperties"), int) and len(inst) > s["maxProperties"]:
                p.append(f"at {where}: more than {s['maxProperties']} properties")
        if isinstance(inst, list):
            pre: list[Any] = s["prefixItems"] if isinstance(s.get("prefixItems"), list) else []
            for i, v in enumerate(inst):
                if i < len(pre):
                    p += self._v(v, pre[i], f"{at}/{i}", depth + 1)
                elif "items" in s:
                    p += self._v(v, s["items"], f"{at}/{i}", depth + 1)
            if isinstance(s.get("minItems"), int) and len(inst) < s["minItems"]:
                p.append(f"at {where}: fewer than {s['minItems']} items")
            if isinstance(s.get("maxItems"), int) and len(inst) > s["maxItems"]:
                p.append(f"at {where}: more than {s['maxItems']} items")
            if s.get("uniqueItems") is True and len({_canon(x) for x in inst}) < len(inst):
                p.append(f"at {where}: items are not unique")
        if isinstance(inst, str):
            if isinstance(s.get("minLength"), int) and len(inst) < s["minLength"]:
                p.append(f"at {where}: shorter than {s['minLength']} characters")
            if isinstance(s.get("maxLength"), int) and len(inst) > s["maxLength"]:
                p.append(f"at {where}: longer than {s['maxLength']} characters")
            if isinstance(s.get("pattern"), str):
                try:
                    if not re.search(s["pattern"], inst):
                        p.append(f"at {where}: {inst[:60]!r} does not match {s['pattern']!r}")
                except re.error:
                    self.not_graded.add("pattern")
        if _type_ok(inst, "number"):
            for k in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
                b = s.get(k)
                if not _type_ok(b, "number"):
                    continue
                bad = {"minimum": inst < b, "maximum": inst > b, "exclusiveMinimum": inst <= b,
                       "exclusiveMaximum": inst >= b}[k]
                if bad:
                    p.append(f"at {where}: {inst} violates {k} {b}")
            m: Any = s.get("multipleOf")
            if _type_ok(m, "number") and m > 0 and not float(inst / m).is_integer():
                p.append(f"at {where}: {inst} is not a multiple of {m}")
        for k in ("allOf", "anyOf", "oneOf"):
            subs = s.get(k)
            if not isinstance(subs, list):
                continue
            res = [self._v(inst, x, at, depth + 1) for x in subs]
            ok = sum(1 for r in res if not r)
            if k == "allOf":
                for r in res:
                    p += r
            elif k == "anyOf" and ok == 0:
                p.append(f"at {where}: matches none of anyOf ({'; '.join(r[0] for r in res if r)[:160]})")
            elif k == "oneOf" and ok != 1:
                p.append(f"at {where}: matches {ok} of oneOf, not exactly 1")
        if "not" in s and not self._v(inst, s["not"], at, depth + 1):
            p.append(f"at {where}: matches a schema under not")
        return p


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def _same(a: Any, b: Any) -> bool:
    if _type_ok(a, "number") and _type_ok(b, "number"):
        return bool(a == b)
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return _canon(a) == _canon(b)


def _external_refs(s: Any, at: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(s, dict):
        for k, v in s.items():
            if k in ("$ref", "$id") and isinstance(v, str) and not v.startswith("#"):
                out.append(f"{at or '/'}: {k} {v!r} is not a same-document fragment")
            elif k not in ("enum", "const", "examples", "default"):
                out += _external_refs(v, f"{at}/{k}")
    elif isinstance(s, list):
        for i, v in enumerate(s):
            out += _external_refs(v, f"{at}/{i}")
    return out


def check_bazaar(pr: Any) -> list[CheckResult]:
    """P9 on a decoded PaymentRequired. Emitted only when the 402 carries extensions.bazaar; nothing to grade otherwise."""
    from .harness import result

    ext = pr.get("extensions") if isinstance(pr, dict) else None
    bz = ext.get("bazaar") if isinstance(ext, dict) else None
    if bz is None:
        return []
    probs: list[str] = []
    if not isinstance(bz, dict):
        return [result(P9, False, {"problems": ["extensions.bazaar is not an object"]})]
    info, schema = bz.get("info"), bz.get("schema")
    if not isinstance(info, dict):
        probs.append("extensions.bazaar.info is missing or not an object")
    if not isinstance(schema, dict):
        probs.append("extensions.bazaar.schema is missing or not an object")
    if probs:
        return [result(P9, False, {"problems": probs})]
    assert isinstance(info, dict) and isinstance(schema, dict)
    declared = schema.get("$schema")
    if declared is not None and str(declared).rstrip("#") != DRAFT_2020_12:
        probs.append(f"schema declares $schema {declared!r}; the bazaar extension requires Draft 2020-12")
    probs += _external_refs(schema)
    v = Validator(schema)
    probs += v.validate(info)
    inp = info.get("input")
    if isinstance(inp, dict) and inp.get("type") not in ("http", "mcp"):
        probs.append(f"info.input.type is {inp.get('type')!r}, not \"http\" or \"mcp\"")
    detail: Json = {"problems": probs[:20], "input_type": inp.get("type") if isinstance(inp, dict) else None}
    if v.not_graded:
        detail["keywords_not_graded"] = sorted(v.not_graded)
    if probs:
        detail["fix"] = ("make the example in info match the schema, or the schema match what the endpoint accepts; "
                         "a facilitator validates info against schema before cataloging")
    return [result(P9, not probs, detail)]


# ---------------- /.well-known/x402 ----------------
def well_known_url(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, "/.well-known/x402", "", ""))


def fetch_well_known(url: str, timeout: float = 15, opener: Any = None) -> Json:
    from .harness import MAX_BYTES, user_agent

    req = urllib.request.Request(well_known_url(url), method="GET",
                                 headers={"accept": "application/json", "user-agent": user_agent()})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            status, body = int(r.status), r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        status, body = int(e.code), e.read(MAX_BYTES + 1)
    doc: Any = None
    try:
        doc = json.loads(body) if status == 200 else None
    except ValueError:
        doc = ValueError
    return {"url": req.full_url, "status": status, "doc": doc}


def _same_site(url: str, host: str) -> bool:
    u = urllib.parse.urlsplit(url)
    h, base = (u.hostname or "").lower(), host.lower()
    return u.scheme == "https" and (h == base or h.endswith("." + base))


def _strip(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, (u.hostname or "").lower() + (f":{u.port}" if u.port else ""),
                                    u.path.rstrip("/") or "/", "", ""))


def _resource_urls(doc: Json) -> list[str]:
    out: list[str] = []
    for r in doc.get("resources") or []:
        if isinstance(r, str):
            out.append(r)
        elif isinstance(r, dict):
            for k in ("url", "resource"):
                if isinstance(r.get(k), str):
                    out.append(r[k])
                    break
    for r in doc.get("remotes") or []:  # MCP servers listed as remotes (the MCP registry's server.json shape)
        if isinstance(r, dict) and isinstance(r.get("url"), str):
            out.append(r["url"])
    return out


def _declared_terms(doc: Json, target: str) -> list[Json]:
    terms: list[Json] = []

    def add(a: Any) -> None:
        for x in a if isinstance(a, list) else [a]:
            if isinstance(x, dict):
                terms.append(x)

    add(doc.get("accepts"))
    for r in doc.get("resources") or []:
        if isinstance(r, dict) and _strip(str(r.get("url") or r.get("resource") or "")) == _strip(target):
            add(r.get("accepts"))
    return terms


def check_well_known(wk: Json, target: str, offers: list[Any]) -> list[CheckResult]:
    """P10. `wk` is fetch_well_known's answer; `offers` the live accepts[]. A host with no manifest (404) has nothing
    to grade, and gets no P10 result; the manifest is optional."""
    from .harness import result

    if wk["status"] == 404 or wk["status"] == 410:
        return []
    probs: list[str] = []
    doc = wk["doc"]
    if wk["status"] != 200:
        return [result(P10, False, {"http": wk["status"], "problems": ["the manifest URL answered neither 200 nor 404"]},
                       severity="warning")]
    if not isinstance(doc, dict):
        return [result(P10, False, {"http": 200, "problems": ["the manifest is not a JSON object"]}, severity="warning")]
    host = urllib.parse.urlsplit(target).hostname or ""
    v = doc.get("x402Version")
    if v is not None and v not in (1, 2):
        probs.append(f"x402Version is {v!r}, not 1 or 2")
    urls = _resource_urls(doc)
    for u in urls:
        if not _same_site(u, host):
            probs.append(f"listed resource {u!r} is not HTTPS on this host or a subdomain of it")
    if doc.get("resources") is not None and _strip(target) not in {_strip(u) for u in urls}:
        probs.append(f"the paid URL {_strip(target)} is not listed in resources")
    live = [a for a in offers if isinstance(a, dict)]
    compared = []
    for t in _declared_terms(doc, target):
        keys = [k for k in ("scheme", "network", "asset", "payTo") if isinstance(t.get(k), str)]
        match = [a for a in live if all(str(a.get(k, "")).lower() == str(t[k]).lower() for k in keys)]
        row: Json = {"declared": {k: t[k] for k in keys}, "matches_live_offer": bool(match)}
        if not match:
            probs.append("declared terms " + json.dumps(row["declared"], sort_keys=True) + " match no live offer")
        elif isinstance(t.get("amount"), str) and re.fullmatch(r"[0-9]+", t["amount"]) \
                and not any(str(a.get("amount")) == t["amount"] for a in match):
            probs.append(f"declared amount {t['amount']} differs from the live amount {match[0].get('amount')}")
        compared.append(row)
    return [result(P10, not probs, {"manifest": wk["url"], "listed": len(urls), "terms_compared": compared,
                                    "problems": probs[:20]}, severity="warning")]
