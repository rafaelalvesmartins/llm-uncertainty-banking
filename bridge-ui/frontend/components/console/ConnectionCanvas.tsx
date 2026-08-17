"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// A flexible, draggable topology canvas. Channels (where customer messages come IN) sit
// on the left, Bridge in the middle, providers (the AI that answers) on the right — so
// the full path WhatsApp → Bridge → provider is visible. You can DRAG nodes to rearrange
// (saved locally), and DRAG a node's connect handle (or click the node) to open the
// GOVERNED propose flow for that connection — dragging a wire never connects on its own,
// it always goes through propose → approve → apply.

export interface CanvasNode {
  id: string;
  name: string;
  kind: "channel" | "provider";
  status: string; // active | reachable | available | unreachable | not_configured | configured
  vtype: string;
}

interface Pos {
  x: number;
  y: number;
}

const NODE_W = 150;
const NODE_H = 46;
const BRIDGE_W = 120;
const BRIDGE_H = 54;
const COL_GAP = 230; // horizontal distance from Bridge to a side column
const ROW_GAP = 64;
const PAD = 24;

function statusColorVar(status: string): string {
  if (status === "active") return "var(--bc-pass-line)";
  if (status === "reachable" || status === "available" || status === "configured") return "var(--bc-info-line)";
  if (status === "unreachable") return "var(--bc-block-line)";
  return "var(--bc-text-mute)";
}

function defaultLayout(channels: CanvasNode[], providers: CanvasNode[]): { pos: Record<string, Pos>; width: number; height: number } {
  const rows = Math.max(channels.length, providers.length, 1);
  const height = PAD * 2 + rows * ROW_GAP;
  const midX = channels.length === 0 ? PAD : PAD + COL_GAP; // Bridge on the left when there are no channel nodes
  const width = midX + BRIDGE_W + COL_GAP + NODE_W + PAD;
  const pos: Record<string, Pos> = {};
  const colY = (i: number, n: number) => PAD + (height - PAD * 2) * ((i + 0.5) / Math.max(n, 1)) - NODE_H / 2;
  channels.forEach((c, i) => { pos[c.id] = { x: PAD, y: colY(i, channels.length) }; });
  providers.forEach((p, i) => { pos[p.id] = { x: midX + BRIDGE_W + COL_GAP, y: colY(i, providers.length) }; });
  pos.__bridge = { x: midX, y: height / 2 - BRIDGE_H / 2 };
  return { pos, width, height };
}

const STORAGE_KEY = "bridge:canvas-layout-v2";

export default function ConnectionCanvas({
  channels,
  providers,
  activeBackend,
  onSelect,
}: {
  channels: CanvasNode[];
  providers: CanvasNode[];
  activeBackend: string;
  onSelect: (n: CanvasNode) => void;
}) {
  const base = defaultLayout(channels, providers);
  const [pos, setPos] = useState<Record<string, Pos>>(base.pos);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  // drag state: which node, the pointer offset, and whether it moved (vs a click)
  const drag = useRef<{ id: string; dx: number; dy: number; moved: boolean; mode: "move" | "connect" } | null>(null);
  // After a drag (or a handle-connect), suppress the click event that follows so we don't
  // open the modal twice / on a reposition.
  const suppress = useRef(false);
  const [connecting, setConnecting] = useState<{ id: string; x: number; y: number } | null>(null);

  // Load a saved layout once (keyed by the set of node ids so a new node falls back to default).
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const saved = JSON.parse(raw) as Record<string, Pos>;
        setPos((p) => {
          const next = { ...p };
          for (const k of Object.keys(next)) if (saved[k]) next[k] = saved[k];
          return next;
        });
      }
    } catch {
      /* ignore bad storage */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = useCallback((next: Record<string, Pos>) => {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  }, []);

  function localPoint(e: React.PointerEvent | PointerEvent): Pos {
    const rect = wrapRef.current?.getBoundingClientRect();
    return { x: (e.clientX - (rect?.left ?? 0)), y: (e.clientY - (rect?.top ?? 0)) };
  }

  function onPointerDown(e: React.PointerEvent, id: string, mode: "move" | "connect") {
    e.preventDefault();
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    const p = pos[id];
    const pt = localPoint(e);
    drag.current = { id, dx: pt.x - p.x, dy: pt.y - p.y, moved: false, mode };
    if (mode === "connect") setConnecting({ id, x: pt.x, y: pt.y });
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const pt = localPoint(e);
    d.moved = true;
    if (d.mode === "connect") {
      setConnecting({ id: d.id, x: pt.x, y: pt.y });
      return;
    }
    setPos((prev) => ({ ...prev, [d.id]: { x: Math.max(0, pt.x - d.dx), y: Math.max(0, pt.y - d.dy) } }));
  }

  function onPointerUp() {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.mode === "connect") {
      setConnecting(null);
      // Dragging the handle (or just pressing it) is a request to CHANGE this connection
      // → open the governed propose. It never wires anything up on its own.
      const node = [...channels, ...providers].find((n) => n.id === d.id);
      if (node) { suppress.current = true; onSelect(node); }
      return;
    }
    // move: persist on a real drag (and suppress the trailing click). A press with no
    // move falls through — the node's onClick fires and opens the governed propose.
    if (d.moved) {
      suppress.current = true;
      setPos((prev) => { save(prev); return prev; });
    }
  }

  function resetLayout() {
    try { window.localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    setPos(defaultLayout(channels, providers).pos);
  }

  const bridge = pos.__bridge ?? base.pos.__bridge;
  const bridgeAnchor = { x: bridge.x + BRIDGE_W / 2, y: bridge.y + BRIDGE_H / 2 };

  // Wire endpoint for a side node = its Bridge-facing edge center.
  function nodeAnchor(n: CanvasNode): Pos {
    const p = pos[n.id] ?? { x: 0, y: 0 };
    const cx = n.kind === "channel" ? p.x + NODE_W : p.x; // channels connect from their right edge; providers from their left
    return { x: cx, y: p.y + NODE_H / 2 };
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: "var(--bc-text-mute)" }}>
          Drag a node to rearrange · drag its <span style={{ color: "var(--bc-accent)" }}>◗ handle</span> (or click it) to manage/connect — every change is governed.
        </span>
        <button type="button" className="bc-btn ghost" onClick={resetLayout} style={{ fontSize: 11, marginLeft: "auto" }}>
          Reset layout
        </button>
      </div>

      <div
        ref={wrapRef}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        style={{
          position: "relative",
          width: "100%",
          minWidth: base.width,
          height: base.height,
          background: "var(--bc-surface-2)",
          border: "1px solid var(--bc-border)",
          borderRadius: 10,
          overflow: "auto",
          touchAction: "none",
        }}
      >
        {/* Wires (SVG overlay, behind the nodes) */}
        <svg style={{ position: "absolute", inset: 0, width: base.width, height: base.height, pointerEvents: "none" }}>
          {[...channels, ...providers].map((n) => {
            const a = nodeAnchor(n);
            const isActive = n.id === activeBackend;
            const live = n.status === "active";
            const color = statusColorVar(n.status);
            return (
              <line
                key={`w-${n.id}`}
                x1={a.x} y1={a.y} x2={bridgeAnchor.x} y2={bridgeAnchor.y}
                stroke={color}
                strokeWidth={isActive || live ? 2.4 : 1.3}
                strokeDasharray={n.status === "not_configured" ? "5 5" : undefined}
                opacity={n.status === "unreachable" ? 0.5 : 1}
              />
            );
          })}
          {connecting && (() => {
            const n = [...channels, ...providers].find((x) => x.id === connecting.id);
            if (!n) return null;
            const a = nodeAnchor(n);
            return <line x1={a.x} y1={a.y} x2={connecting.x} y2={connecting.y} stroke="var(--bc-accent)" strokeWidth={2} strokeDasharray="4 4" />;
          })()}
        </svg>

        {/* Bridge hub */}
        <div
          style={{
            position: "absolute", left: bridge.x, top: bridge.y, width: BRIDGE_W, height: BRIDGE_H,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: "var(--bc-surface)", border: "2px solid var(--bc-accent)", borderRadius: 9,
            color: "var(--bc-accent)", fontWeight: 700, fontSize: 15, cursor: "grab", userSelect: "none",
          }}
          onPointerDown={(e) => onPointerDown(e, "__bridge", "move")}
          title="Bridge — drag to reposition"
        >
          Bridge
        </div>

        {/* Channel + provider nodes */}
        {[...channels, ...providers].map((n) => {
          const p = pos[n.id] ?? { x: 0, y: 0 };
          const isActive = n.id === activeBackend;
          const color = statusColorVar(n.status);
          const handleOnRight = n.kind === "channel"; // handle faces Bridge
          return (
            <div
              key={n.id}
              style={{
                position: "absolute", left: p.x, top: p.y, width: NODE_W, minHeight: NODE_H,
                display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
                background: "var(--bc-surface)", border: `1.5px solid ${isActive ? "var(--bc-accent)" : "var(--bc-border)"}`,
                borderRadius: 9, cursor: "grab", userSelect: "none", boxSizing: "border-box",
              }}
              onPointerDown={(e) => onPointerDown(e, n.id, "move")}
              onClick={() => { if (suppress.current) { suppress.current = false; return; } onSelect(n); }}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(n); } }}
              title={`${n.name} — drag to move, click to manage (governed)`}
            >
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: color, flexShrink: 0 }} />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 12.5, fontWeight: isActive ? 700 : 500, color: "var(--bc-text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {n.name}
                </div>
                <div style={{ fontSize: 10, color, whiteSpace: "nowrap" }}>{n.status.replace(/_/g, " ")}</div>
              </div>
              {/* connect handle — drag it (or click) to open the governed propose */}
              <span
                onPointerDown={(e) => onPointerDown(e, n.id, "connect")}
                title="Drag toward Bridge (or click) to propose a governed change"
                style={{
                  position: "absolute", top: "50%", transform: "translateY(-50%)",
                  [handleOnRight ? "right" : "left"]: -7,
                  width: 14, height: 14, borderRadius: "50%",
                  background: "var(--bc-accent)", border: "2px solid var(--bc-surface)",
                  cursor: "crosshair",
                } as React.CSSProperties}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
