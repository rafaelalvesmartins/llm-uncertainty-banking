// Single source of truth for turning a backend error body into one clean,
// human-readable line. The Bridge BFF proxies FastAPI, so an error response can
// arrive in any of three shapes — and rendering the raw value gave us
// "HTTP 422: [object Object]" (a Pydantic validation array) and raw JSON blobs:
//
//   (a) { detail: "reviewer must differ…" }          — HTTPException (string)
//   (b) { detail: [ { loc, msg, type }, … ] }         — request/schema validation (e.g. 422)
//   (c) { error: "…", upstream?: {...} }              — BFF proxy wrap (502)
//
// Anything unrecognized falls back to `HTTP <status>` so we never surface
// "[object Object]" or crash React by rendering an object/array.

function pluck(obj: Record<string, unknown>, key: string): string | null {
  const v = obj[key];
  return typeof v === "string" && v.trim() ? v : null;
}

/** Normalize any parsed error body into a single displayable string. */
export function apiErrorText(body: unknown, status?: number): string {
  const fallback = status ? `HTTP ${status}` : "Request failed";
  // BRIDGE_AUTH is on and the demo UI has no login yet (v6 phase). Explain the
  // intentional posture instead of leaking the raw "missing bearer token".
  if (status === 401 || status === 403) {
    return "Authentication is ON (BRIDGE_AUTH) and this demo UI does not sign in yet — run with BRIDGE_AUTH=off, or call the API directly with a bearer token (POST /auth/token).";
  }
  if (body == null) return fallback;
  if (typeof body === "string") return body.trim() || fallback;
  if (typeof body !== "object") return String(body);

  const b = body as Record<string, unknown>;
  const detail = b.detail;

  // (b) FastAPI validation: detail is an array of { msg, loc, … }. This is the
  // shape that used to render as "[object Object]".
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => {
        if (d && typeof d === "object") return pluck(d as Record<string, unknown>, "msg");
        return typeof d === "string" && d.trim() ? d : null;
      })
      .filter((m): m is string => !!m);
    if (msgs.length) return msgs.join("; ");
  }

  // (a) HTTPException: detail is a plain string.
  if (typeof detail === "string" && detail.trim()) return detail;

  // Defensive: a dict-shaped detail — surface its msg if present.
  if (detail && typeof detail === "object") {
    const dmsg = pluck(detail as Record<string, unknown>, "msg");
    if (dmsg) return dmsg;
  }

  // (c) Proxy wrap, or generic { message }.
  return pluck(b, "error") ?? pluck(b, "message") ?? fallback;
}
