"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { useDialogFocus } from "@/components/useDialogFocus";

// In-app confirm modal — replaces native confirm()/alert(), which block the
// renderer, are unstyled, and break automation / browser extensions (a clean
// validation surfaced state-mutating buttons "freezing" on the native dialog).
type ConfirmFn = (message: string) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn>(async () => false);

export const useConfirm = (): ConfirmFn => useContext(ConfirmContext);

export default function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);
  const dialogRef = useDialogFocus<HTMLDivElement>(message !== null);

  const confirm = useCallback(
    (msg: string) =>
      new Promise<boolean>((resolve) => {
        resolver.current = resolve;
        setMessage(msg);
      }),
    [],
  );

  const close = (value: boolean) => {
    setMessage(null);
    resolver.current?.(value);
    resolver.current = null;
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {message !== null && (
        <div
          ref={dialogRef}
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-label="Confirmation"
          onClick={() => close(false)}
          onKeyDown={(e) => {
            if (e.key === "Escape") close(false);
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(2,6,23,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            padding: 16,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 8,
              padding: 20,
              maxWidth: 460,
              boxShadow: "0 10px 40px rgba(0,0,0,0.5)",
            }}
          >
            <div style={{ fontSize: 13, color: "#e2e8f0", lineHeight: 1.5, marginBottom: 18 }}>{message}</div>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={() => close(false)}
                style={{
                  background: "transparent",
                  border: "1px solid #334155",
                  borderRadius: 6,
                  padding: "6px 14px",
                  color: "#94a3b8",
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => close(true)}
                autoFocus
                style={{
                  background: "#1e293b",
                  border: "1px solid #475569",
                  borderRadius: 6,
                  padding: "6px 14px",
                  color: "#e2e8f0",
                  cursor: "pointer",
                  fontSize: 13,
                  fontWeight: 600,
                }}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
