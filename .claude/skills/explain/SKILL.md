---
name: explain
description: Explain code, system behavior, NLP/model concepts or technical choices in plain English, from problem to solution, with inline definitions and honest tradeoffs. Use for /explain or requests to explain how something works.
---

Explain the topic in the user's message to a curious student learning the internals.
Goal: understanding, deep enough to explain it yourself in the demo video.

## Ground it

- For repo behavior, read the actual code, data and config first. Do not guess.
- For ML/NLP parts, separate training/indexing, evaluation and inference; name the
  real inputs, outputs and model calls.
- Mark what is observed in code vs. what is your inference. Never invent numbers.
- Look up external facts only when unsure; prefer official docs, link 1–3 sources.
- Explaining does not mean editing code.

## Depth

Optional mode right after the command: `/explain short` (default, ≤250 words),
`/explain mid` (≤700 words, adds steps, examples, failure cases),
`/explain long` (no limit, full walkthrough). Limits are ceilings, not targets.

## Structure

Lead with the direct answer, then as relevant:

1. **Problem** — what is needed and why.
2. **Mechanism** — how it works, step by step; one concrete example (input → output).
3. **Code map** — main files/functions and the role of each.
4. **Why this way** — strongest alternative, what we gain, what it costs.
5. **Limits** — main failure case or weakness; how we would measure or fix it.

## Style

- Plain English, short sentences, one idea at a time. Not patronizing.
- Define new terms inline: "BM25 {keyword-based ranking by term frequency} finds ...".
- Use a small table, arrow flow (`A → B → C`) or Mermaid diagram when it helps.
- No glossary dumps, no repeated conclusions, no unsolicited quizzes.
