# Bridge — Plano de melhorias (2026-06-21)

> Onde o produto está e o que falta para sair de "demonstrador sólido" para
> "produto crível". Priorizado por impacto. Branch: `product/bridge-platform`.

## Estado atual (honesto)
**Forte:** pipeline guard/governança testado (329 testes, ruff/mypy/tsc/eslint limpos);
auditoria tamper-evident (hash-chain); four-eyes/SoD; LLM real plugável (Ollama);
guard por **risco + valor** (COAF); PII mascarada ponta-a-ponta; console de 10 telas com
orientação + glossário; conexões governadas (providers **e** channels/WhatsApp).

**Fraqueza central:** é um **demonstrador** — partes "governam/exibem" sem "funcionar de
verdade", e algumas métricas são **sintéticas**. É isso que o plano ataca.

---

## P0 — Credibilidade (o que faz parecer "demo", não produto)

1. **Métricas sintéticas de model-risk.** ECE/reliability/benchmark/drift-baseline são
   placeholders (`_DEMO_SYNTHETIC_SOURCE`, model_card "Quarterly (demo placeholder)").
   A acurácia da intent-battery é real, o resto não. Para um demo de **model risk**, essa
   é a maior fraqueza.
   → **Gerar calibração REAL** a partir do classificador real (reliability diagram + ECE
   sobre a battery rotulada) e **marcar claramente real vs sintético** na UI. **Esforço: M.**
2. **Governar ≠ funcionar.** Aplicar um provider/channel grava a `active-config` mas não
   liga nada (LLM real é env no startup; canal não envia). Honesto, mas confunde.
   → Mínimo: rótulo explícito **"config-only (no live binding)"** onde aplica. Ideal: ver P1-4/5.
   **Esforço: S (rótulo) / L (binding real).**
3. **Lacunas de teste do review.** O short-circuit de **rate-limit** não tem teste direto
   (só dq_input); a fonte-única de tipos de vendor não é testada.
   → fechar esses testes. **Esforço: S.**

## P1 — Profundidade (demo → real)

4. **Binding real de provider pela active-config** (trocar LLM sem restart, em vez de só env).
   Hoje `_select_backend` é env/startup; a config governada é só registro. **Esforço: L.**
5. **Canal real (WhatsApp/Telegram):** webhook de entrada + envio de verdade (hoje
   config-only; `fakewhatsapp` é loopback). **Esforço: L.**
6. **Auth/RBAC real.** `BRIDGE_AUTH=off` por padrão; o four-eyes é UI + flag, **não
   hard-enforced** sem auth. Para a narrativa SR 11-7, enforce server-side + papéis
   (submitter/reviewer/applier) com identidade real. **Esforço: M.**
7. **Genericidade de vendor num só lugar.** Hoje adicionar um vendor toca 3 pontos: array
   na UI + allow-list `_is_real_binding` + (para funcionar) factory `@register_backend`.
   → registro declarativo único (a allow-list server-side continua sendo a trava de
   segurança, mas derivada de uma fonte). **Esforço: M.**

## P2 — Escala / ops / robustez

8. **Estado in-process.** Audit/metrics/cache/sessions vivem no processo; `scale/` tem
   Redis/Postgres mas **env-gated/skipped**. → completar persistência + multi-instância
   (auditoria e idempotência são os críticos). **Esforço: L.**
9. **Safety 100% por keyword (sem ML).** phishing/fraud/AML/crise são listas — bom recall
   no demo, mas frágil. → camada ML opcional + métricas de FP/FN versionadas (já há battery;
   estender a safety). **Esforço: L.**

## P3 — Higiene

10. **Docs sobrepostos.** ~26 docs de plano (IMPLEMENTATION_PLAN/_V2, PRODUCT_PLAN/_V6,
    NEXT_STEPS, REMAINING_WORK, PROJECT_REVIEW_AND_PLAN…). → consolidar em 1 vivo + arquivar
    o resto. **Esforço: S.**

---

## Sequência recomendada
1. **P0-3** (testes — barato, fecha o review) →
2. **P0-1** (calibração real — maior ganho de credibilidade para um demo de model-risk) →
3. **P0-2 rótulo** + **P1-6 auth** (honestidade + a trava de governança "de verdade") →
4. **P1-4/5** (binding real de provider/canal — vira produto) →
5. **P2** (escala) → **P3** (docs).

**Quick wins (1 sessão):** P0-3, P0-2 (rótulo), P3.
**Mudam o jogo (demo→produto):** P0-1, P1-6, P1-4.

> Observação de contexto: como evidência de petição (Prong-2), **P0-1 (calibração real)** e
> **P1-6 (four-eyes enforced)** são os que mais reforçam a narrativa de model-risk/SR 11-7.
