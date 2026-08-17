# Lovable build prompt — Bridge landing page

**How to use this file**
1. Open [lovable.dev](https://lovable.dev) → New Project.
2. Copy **everything below the line** (`=== COPY FROM HERE ===`) and paste it as your first message.
3. Upload the two console screenshots when Lovable asks (or drag them in): `screens/atendimento.png` and `screens/integracoes.png`.
4. Optional but recommended: connect **Supabase** in Lovable first, so the lead form saves to a database. If you don't, the form will fall back to opening an email.
5. After it builds: replace the contact email `rafael@llm-uncertainty-banking.dev` and confirm the GitHub URL.

---

=== COPY FROM HERE ===

Build a polished, single-page marketing website (landing page) in English for an enterprise B2B product called **Bridge**.

## What Bridge is
Bridge is **the AI control plane for banking** — the layer between a bank's AI and its customers. You plug in any AI model, run it across every channel (chat **and** voice), ground it in your own data, check (govern) every answer with an "uncertainty guard," and observe everything from one console. It's built on an open-source calibration engine called **lub** (Apache 2.0). It is currently a **Preview** product.

## Audience & goal
- Audience: model-risk, operations and compliance leaders at banks, insurers and fintechs.
- Goal: sell the product and capture demo requests. One primary call-to-action everywhere: **Book a demo** (scrolls to the lead form).

## Tech & build notes
- Use your default stack (React + Vite + Tailwind + shadcn/ui). Single page, smooth-scroll anchor nav.
- Fonts: **Inter** for UI/headings/body, **JetBrains Mono** for small code-style labels, tags and big stat numbers' superscripts (load from Google Fonts).
- Fully responsive. On mobile the nav collapses to a menu button and all multi-column grids stack to one column.
- Add subtle **scroll-reveal** animations (fade + 20px rise) on sections and cards using an IntersectionObserver; respect `prefers-reduced-motion`.
- Sticky, translucent (blurred) header that gains a thin bottom border + shadow after scrolling a few pixels.

## Design system (follow exactly)
- Overall look: clean, premium, light enterprise SaaS. Generous whitespace. Max content width ~1080px, centered, 24px side padding.
- Color tokens:
  - Brand indigo `#4f46e5`, brand violet `#7c3aed`. Primary gradient = `linear-gradient(135deg,#4f46e5,#7c3aed)`.
  - Text: primary `#0f172a`, secondary `#475569`, muted `#94a3b8`.
  - Surfaces: white `#ffffff`, soft `#f8fafc`, border `#e2e8f0`.
  - Semantic: success green `#059669`, amber `#b45309`.
  - Dark sections use background `#0f172a` with light text (`#e2e8f0` / `#cbd5e1`).
  - "Decision" colors (used in the small status pills / decision-mix): pass `#22c55e`, flag `#f59e0b`, reask `#8b5cf6`, escalate `#ef4444`.
- Buttons:
  - Primary = indigo→violet gradient, white text, radius 12px, soft shadow, lifts up 2px on hover.
  - Ghost = white background, 1px border `#cbd5e1`, hover turns border + text indigo.
- Cards = white, 1px `#e2e8f0` border, radius 16px, soft shadow, lift slightly on hover.
- The hero headline highlight and the big stat numbers use the indigo→violet **gradient as text fill**.
- Use clean line icons (outline style, indigo stroke) inside rounded square chips with a faint lavender background.

## Page structure & exact copy

### 1. Header (sticky)
- Left: a 34px rounded-square logo with the primary gradient and a white bold "B", next to the wordmark **Bridge**.
- Center/right nav links (smooth-scroll): **Platform**, **How it works**, **Gains**, **Open source**.
- Right: primary button **Book a demo** (scrolls to the form).

### 2. Hero (light, with a soft indigo radial glow in the background)
Two columns (text left, diagram right; stacks on mobile).
- Small pill badge (white, bordered, with a violet dot): `The AI control plane for banking · Preview`
- H1 (large, tight): **Connect any AI. Govern every answer. Across every channel.** — render the middle sentence **"Govern every answer."** in the indigo→violet gradient text.
- Subhead: "Bridge is the layer between your bank's AI and your customers — plug in any model, run it across chat and voice, ground it in your data, check every answer, and see everything in one place."
- Buttons: **Book a demo** (primary, with a right-arrow icon) and **See the platform** (ghost).
- Small muted line under the buttons: "One platform between your AI and your customers — connect, govern, observe."
- Right column — a **hub-and-spoke diagram** (build as an SVG/component): a center node labeled **Bridge** / "AI control plane" (gradient fill, white text) connected by thin **dashed** lines to six small white outer nodes, each with a colored dot, a bold label and a tiny grey sub-label:
  - **Models** — "OpenAI · Claude · Azure · local"
  - **Channels** — "WhatsApp · app · web"
  - **Voice** — "call center · transcription"
  - **Your data** — "manuals · policies (RAG)"
  - **Governance** — "guard · PII · audit"
  - **Analytics** — "metrics · AI visibility"

### 3. Stat band (soft grey background, 4 columns with thin dividers)
Big gradient numbers, bold label, tiny grey sub-label:
- **83%\*** — Questions auto-resolved — "* design target"
- **30×** — Cheaper per simple query — "up to — via smart routing"
- **100%** — Answers pass the guard — "chat and voice alike"
- **6** — Regulatory regimes — "audit evidence, automated"

### 4. Hook band (dark `#0f172a`, centered, large bold text)
"Your AI shouldn't be a dozen disconnected tools. Bridge is the **one layer** every answer passes through — typed or spoken." (give "one layer" a violet underline highlight.)

### 5. Platform — capabilities (light, 3-column card grid, 6 cards)
- Kicker: `THE PLATFORM`. H2: **Everything between your model and your customer**. Sub: "One pipeline does the whole job — connect, ground, govern, deliver and observe."
- Cards (icon chip + title + paragraph + small indigo tag):
  1. **Connect any AI** — "OpenAI, Anthropic, Azure or a local model. Swap providers anytime — nothing downstream changes." — tag `model-agnostic`
  2. **Every channel** — "WhatsApp, the app, web chat and the call center — all running through one governed pipeline." — tag `omnichannel`
  3. **Voice & transcription** — "Take phone calls, transcribe speech to text, then answer or route. Voice gets the exact same guard as chat." — tag `speech → text`
  4. **Grounded in your data** — "Answers cite your manuals, policies and regulations (RAG) — not the model's guesswork." — tag `RAG · citations`
  5. **Governed & audited** — "An uncertainty guard on every answer, PII masked before the model (LGPD), and an append-only audit trail (BCB) mapped to SR 11-7." — tag `guard · LGPD · audit`
  6. **See everything** — "Live metrics, per-stage traces of every request, and AI-visibility monitoring of how your brand shows up across the models." — tag `metrics · visibility`

### 6. See it in action — product screenshots (soft grey background)
- Kicker: `SEE IT IN ACTION`. H2: **The actual console, running today**. Sub: "Not a mockup — real screenshots of Bridge: live metrics, the customer pipeline, and your model & channel connections."
- Two stacked **browser-window frames** (a dark top bar with three traffic-light dots + a monospace title, image below). Use the two uploaded images:
  - Frame title "Bridge console — Atendimento (live customer pipeline)" → image `atendimento.png`
  - Frame title "Bridge console — Integrações (model & channel connections)" → image `integracoes.png`
- Caption under both (small, muted, centered): "Real screenshots of the Bridge console today (Next.js + FastAPI), shown in its Portuguese demo mode. The orange demo banner is cropped; everything else is the live UI."
- (If images aren't uploaded yet, leave tasteful dark placeholder boxes labeled "console screenshot".)

### 7. How it works — the flow (light, 4 cards in a row with arrows between them)
- Kicker: `THE FLOW`. H2: **How a request flows through Bridge**. Sub: "From a customer's question — typed or spoken — to a safe answer, in one pass."
- Steps (icon chip + "Step N" + title + paragraph):
  1. **Customer reaches out** — "A message or phone call comes in — WhatsApp, app, web or the call center. Voice is transcribed to text."
  2. **Bridge prepares it** — "Personal data is masked, the question is grounded in your documents, and it's routed to the right-sized model."
  3. **The guard decides** — "Confident → reply. Unsure → ask again or hand off to a human. No guessing in front of a customer."
  4. **Everything is logged** — "Each step becomes a reproducible, audit-ready record your risk team can file — automatically."
- Small muted note below: "Under the hood: 12 audited stages — data quality, governance, cache, routing, retrieval, the guard and the audit trail — each one a real, tested module."

### 8. The gains (light, 2×2 value-card grid)
- Kicker: `THE GAINS`. H2: **Your gains — in numbers**. Sub: "The values your risk, operations and finance teams can point to."
- Each card: a small monospace value chip (indigo on light-indigo) + bold title + paragraph:
  1. chip `100% gated` — **No answer reaches a customer ungated** — "Every low-confidence answer — chat or voice — is held back or escalated instead of bluffed. Your AI stays quiet when it isn't sure."
  2. chip `83% resolved*` — **Most questions answered without a human** — "Routine queries are handled instantly; only the genuinely hard ones reach your team — so headcount goes to the cases that need judgment. *design target"
  3. chip `up to 30× cheaper` — **Stop overpaying per question** — "Easy questions go to cheap models, repeats are served from cache, and only the complex ones reach a premium model. You stop paying top price for 'what's my balance?'."
  4. chip `6 regimes · automatic` — **Audit-ready without the busywork** — "Every answer is filed as SR 11-7 and EU AI Act evidence — PII masked (LGPD), append-only trail (BCB). No folder of screenshots."
- Below the grid, a centered "connect" panel (soft grey card): heading "Plugs into your stack — nothing answers without passing the guard", then pill chips: **Models:** OpenAI · Anthropic · Azure OpenAI · Local (Ollama); **Channels:** WhatsApp · App · Web · Voice / call center. Small muted line: "Built on the open-source lub engine — 22 calibration methods, 732 tests, Apache 2.0."

### 9. Built in the open — GitHub (soft grey, two columns)
- Left: Kicker `BUILT IN THE OPEN`. H2: **The engine is open source. Audit it, run it, build on it.** Sub: "Bridge runs on lub — our Apache-2.0 calibration engine. No black box: every estimator and metric is in the repo, with the tests to prove it." Then a row of mini-stats: **22** calibration methods · **732** tests passing · **93%** code coverage · **Apache 2.0** license.
- Right: a clickable **GitHub repo card** linking to `https://github.com/rafaelmartinsalves/llm-uncertainty-banking`: GitHub mark + "rafaelmartinsalves / **llm-uncertainty-banking**", description "Turn LLM uncertainty into auditor-ready regulatory evidence — the calibration engine under Bridge.", a meta row "● Python · Apache-2.0 · ★ Star", and a "View on GitHub →" link. **Fetch the live star count** from the GitHub API (`https://api.github.com/repos/rafaelmartinsalves/llm-uncertainty-banking`) and show it next to the star; hide the number gracefully if the request fails.

### 10. Book a demo — lead capture (dark `#0f172a` rounded section, two columns)
- Left (white text): Kicker `Book a demo` (light-indigo). H2: **See Bridge run on your own data.** A checklist (violet check icons): "A 30-minute walkthrough on your channels and models", "Your documents, your guard thresholds", "Runs on a local model — no API keys to start". Then: "Prefer email? **Write to us directly**." (mailto link).
- Right: a white **form card** titled "Request a demo" with sub "Tell us where to reach you — we'll follow up within a day." Fields: **Full name**, **Work email** (type=email), **Bank / company**, and a select **"What do you want to use Bridge for?"** with options: Customer chat · Voice / call center · Model risk & audit · Everything. Submit button (gradient) "Request a demo". Tiny note: "We'll only use this to contact you about Bridge. Preview — no API keys required to try it."
- On submit: validate, then **save the lead to Supabase** (create a `leads` table: id, name, email, company, use, created_at) if Supabase is connected; otherwise open a pre-filled mailto to `rafael@llm-uncertainty-banking.dev`. After success, replace the form with a centered confirmation: a green check, **"Thanks — we'll be in touch."**, "Your demo request is on its way."

### 11. Footer (soft grey)
- Bridge logo + wordmark on the left; links on the right: Platform · How it works · GitHub · Book a demo.
- Small disclaimer line: "Bridge is the AI control plane built on the open-source lub engine (Apache 2.0). It is currently in preview and runs on a local model out of the box. Nothing here is legal, regulatory or model-validation advice, and Bridge does not by itself establish compliance with any framework. Figures, connection states and confidence scores shown on this page are illustrative."

## Content rules (important — keep it honest)
- Keep the **"Preview"** framing. Do **not** invent customer names, logos, testimonials, or fake metrics.
- Keep the asterisk on **83%** ("design target") and treat all numbers as illustrative.
- Do not claim live production banking deployments.

Make it look like a real, modern enterprise SaaS site (think Linear / Vercel / Stripe polish, but light and trustworthy). Ship the whole page in one go, then I'll refine.

=== END OF PROMPT ===
