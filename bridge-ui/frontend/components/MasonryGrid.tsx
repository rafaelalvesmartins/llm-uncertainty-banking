"use client";

import { useEffect, useRef } from "react";

/**
 * True masonry that eliminates the "short last column" void left by CSS
 * `columns`. Measures each real `.card` DOM node and places it into whichever
 * column is currently shortest, so columns end at near-equal heights.
 *
 * Why DOM-measurement (not distributing React children): some children expand
 * to several cards — e.g. <InfoPanels only={["cache","dq","dg"]}/> renders 3
 * cards from one React child. Measuring `.card` nodes handles that correctly.
 *
 * Relayout triggers:
 *  - ResizeObserver on the container (catches show/hide of the tab + width)
 *  - ResizeObserver on each card (panels re-fetch every 3-5s and change height)
 *  - MutationObserver (cards mounting in)
 *  - window resize
 *
 * `.card--wide` spans the full width and drops below all columns.
 */
interface Props {
  children: React.ReactNode;
  minColWidth?: number;
  gap?: number;
}

export default function MasonryGrid({ children, minColWidth = 380, gap = 16 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;

    let raf = 0;
    const layout = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const cw = container.clientWidth;
        if (cw === 0) return; // hidden tab — wait until visible
        const cards = Array.from(container.children) as HTMLElement[];
        const cols = Math.max(1, Math.floor((cw + gap) / (minColWidth + gap)));
        const colW = (cw - gap * (cols - 1)) / cols;
        const colH = new Array(cols).fill(0);

        // The bottom-most non-wide card placed in each column. When a full-width
        // card drops below all columns, we stretch these down to a shared
        // baseline so a shorter card (e.g. "Agentes Registrados") doesn't leave
        // a visible void above the wide card.
        const bottomCard: (HTMLElement | null)[] = new Array(cols).fill(null);

        for (const card of cards) {
          const wide = cols === 1 || card.classList.contains("card--wide");
          card.style.position = "absolute";
          card.style.margin = "0";
          card.style.height = ""; // clear any prior stretch before measuring
          card.style.width = wide ? `${cw}px` : `${colW}px`;
          if (wide) {
            const top = Math.max(...colH);
            // Stretch each column's bottom card so the row ends flush at top-gap.
            for (let i = 0; i < cols; i++) {
              const bc = bottomCard[i];
              if (!bc) continue;
              const bcTop = parseFloat(bc.style.top || "0");
              const h = top - gap - bcTop;
              if (h > bc.offsetHeight) bc.style.height = `${h}px`;
            }
            card.style.left = "0px";
            card.style.top = `${top}px`;
            const next = top + card.offsetHeight + gap;
            for (let i = 0; i < cols; i++) colH[i] = next;
            bottomCard.fill(null); // fresh row after a full-width card
          } else {
            let c = 0;
            for (let i = 1; i < cols; i++) if (colH[i] < colH[c]) c = i;
            card.style.left = `${c * (colW + gap)}px`;
            card.style.top = `${colH[c]}px`;
            colH[c] += card.offsetHeight + gap;
            bottomCard[c] = card;
          }
        }
        container.style.position = "relative";
        container.style.height = `${Math.max(0, ...colH) - gap}px`;
      });
    };

    layout();
    const ro = new ResizeObserver(layout);
    ro.observe(container);
    for (const card of Array.from(container.children)) ro.observe(card as Element);

    const mo = new MutationObserver(() => {
      for (const card of Array.from(container.children)) ro.observe(card as Element);
      layout();
    });
    mo.observe(container, { childList: true });

    window.addEventListener("resize", layout);
    return () => {
      ro.disconnect();
      mo.disconnect();
      window.removeEventListener("resize", layout);
      cancelAnimationFrame(raf);
    };
  }, [minColWidth, gap]);

  return (
    <div className="masonry" ref={ref}>
      {children}
    </div>
  );
}
