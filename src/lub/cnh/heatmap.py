# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.cnh.heatmap -- render ParagraphScores as a heatmap overlay.

Two stdlib renderers ship by default:

* :func:`render_heatmap_html` -- self-contained HTML doc with CSS gradient
  background per paragraph.
* :func:`render_heatmap_markdown` -- inline ``<span style="...">`` for
  use in `_scratch/` notes (most markdown viewers honor inline style).

A third renderer (DOCX) is a future extra (``python-docx`` not in core).

Spec: planning/26_CNH_Calibrated_Narrative_Heatmap_2026-04-25.md §3.2.
"""

from __future__ import annotations

import html as _html

from lub.cnh.score import ParagraphScore
from lub.cnh.thresholds import LEGAL_PROFILE, DomainProfile, classify

__all__ = ["render_heatmap_html", "render_heatmap_markdown"]


_BG = {
    "green": "#d1fae5",  # tailwind emerald-100
    "yellow": "#fef3c7",  # tailwind amber-100
    "red": "#fee2e2",  # tailwind red-100
}
_BORDER = {
    "green": "#10b981",  # emerald-500
    "yellow": "#f59e0b",  # amber-500
    "red": "#ef4444",  # red-500
}


def _legend_html(profile: DomainProfile) -> str:
    return (
        '<div class="legend">'
        f'<span class="badge green">green &ge; {profile.green_min:.2f}</span> '
        f'<span class="badge yellow">yellow &ge; {profile.yellow_min:.2f}</span> '
        '<span class="badge red">red &lt; yellow threshold</span>'
        f" &middot; profile: <code>{_html.escape(profile.name)}</code>"
        "</div>"
    )


def render_heatmap_html(
    scores: list[ParagraphScore],
    *,
    profile: DomainProfile = LEGAL_PROFILE,
    title: str = "Calibrated Narrative Heatmap",
) -> str:
    """Render scores as a self-contained HTML document.

    Each paragraph gets a colored block (green/yellow/red) with the
    confidence value displayed in the corner. CSS only -- no JS, no
    external resources.
    """
    parts: list[str] = []
    parts.append('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">')
    parts.append(f"<title>{_html.escape(title)}</title>")
    parts.append(
        "<style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:780px;margin:24px auto;padding:0 16px;color:#1f2937;}"
        "h1{font-size:20px;margin:0 0 4px;}"
        ".legend{font-size:12px;color:#6b7280;margin:8px 0 24px;}"
        ".badge{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;margin-right:4px;}"
        f".badge.green{{background:{_BG['green']};color:{_BORDER['green']};}}"
        f".badge.yellow{{background:{_BG['yellow']};color:{_BORDER['yellow']};}}"
        f".badge.red{{background:{_BG['red']};color:{_BORDER['red']};}}"
        ".para{padding:12px 14px;border-radius:6px;border-left:4px solid;margin:10px 0;position:relative;line-height:1.55;}"
        ".para .conf{position:absolute;top:6px;right:10px;font-size:11px;font-weight:600;opacity:0.75;}"
        f".para.green{{background:{_BG['green']};border-color:{_BORDER['green']};}}"
        f".para.yellow{{background:{_BG['yellow']};border-color:{_BORDER['yellow']};}}"
        f".para.red{{background:{_BG['red']};border-color:{_BORDER['red']};}}"
        "</style></head><body>"
    )
    parts.append(f"<h1>{_html.escape(title)}</h1>")
    parts.append(_legend_html(profile))
    if not scores:
        parts.append('<div class="para" style="background:#f3f4f6;border-color:#9ca3af;">')
        parts.append("<em>No paragraphs to render.</em></div>")
    for s in scores:
        cls = classify(s.confidence, profile)
        parts.append(f'<div class="para {cls}">')
        parts.append(f'<span class="conf">{s.confidence:.2f}</span>')
        parts.append(_html.escape(s.text).replace("\n", "<br>"))
        parts.append("</div>")
    parts.append("</body></html>")
    return "".join(parts)


def render_heatmap_markdown(
    scores: list[ParagraphScore],
    *,
    profile: DomainProfile = LEGAL_PROFILE,
) -> str:
    """Render scores as inline markdown with HTML span backgrounds.

    Most markdown viewers (GitHub, GitLab, Obsidian, VS Code) honor
    ``<span style="background:...">`` so the heatmap renders inline.
    """
    out: list[str] = []
    out.append(
        f"_Heatmap (profile: `{profile.name}`, "
        f"green ≥ {profile.green_min:.2f}, yellow ≥ {profile.yellow_min:.2f})_\n"
    )
    if not scores:
        out.append("\n_(no paragraphs to render)_")
        return "".join(out)
    for s in scores:
        cls = classify(s.confidence, profile)
        bg = _BG[cls]
        # Escape any literal HTML in the paragraph text so it doesn't break
        # the wrapping span.
        escaped = _html.escape(s.text)
        out.append(
            f'\n<span style="background:{bg};padding:4px 8px;border-left:3px solid '
            f'{_BORDER[cls]};display:block;margin:6px 0;">'
            f"<small><b>{s.confidence:.2f}</b> ({cls})</small><br>"
            f"{escaped}</span>"
        )
    return "".join(out)
