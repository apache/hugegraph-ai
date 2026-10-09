# 11 · Case Study: a Discrete-Manufacturing Operations Loop（domains/manufacturing-system · numbers captured from real executions）

> Part of [Part II · Usage](../README.md#part-ii--usage)

**[中文](../../usage/11-manufacturing-case.md)** | English

15 objects · 15 links · 12 actions · 5 functions · 6 policies · 1 projection · 2 eval suites · 2 agent plugins, with its own seeds (`seed/*.sql` nouns + `demo-story.yaml` verbs). The demo story replayed by --demo at startup is exactly the path below.

## Act I · Access & query（seed → sync → query）

1. **Ontology load**: serve --demo seeds / copies / builds / publishes in one command; the snapshot is rebuildable from Git at any time
2. **Data onboarding**: 15 object types sync incrementally by watermark, first batch **57 rows**; bad rows quarantine without blocking
   (sample: bom +8 · customer +3 …)
3. **Query & safety**: derived properties compute live (SO-2026-0001 ships in ≈58 days); `region` carries the commercial marking → an unauthorized identity sees `__masked__`
   (without: `__masked__` · with markings: east)

▼ Business execution (five-stage actions)

## Act II · Order → scheduling → reporting → quality → maintenance → purchasing（a day with the 12 actions）

4. **Confirm order**: dry-run rules check one by one ✅ → execute `DRAFT→CONFIRMED`, version +1, revision persisted
5. **Unauthorized refused**: an operator confirms an order → `POLICY_DENIED`, **the refusal is audited**
6. **Release to production**: `create-object` + `newId()` → `PO-000001 RELEASED`; a duplicate release trips the rule
7. **Report operations**: qualified count 3→5 (the expression evaluates inside the transaction); the scrap-rate derivation 25%→16.67%
8. **Quality registration**: FAIL without a defect count → refused; completed it executes and conditionally fires the QMS webhook
9. **Maintenance loop**: a functional action looks up the plant server-side → opens the order; start/close `modify-linked` moves the equipment `MAINTENANCE→RUNNING`; closing across plants is refused by a row-level policy; historical downtime **51.5h** (derived)
10. **Purchasing**: a buyer raises but cannot approve; the procurement_manager approves — maker/checker separation written directly in Cedar

▼ Compute · traversal · governance · evolution

## Act III · Functions · graph · audit · RSI · outbox（the deterministic kernel + evolution inside governance）

11. **Functions**: material availability (BOM expansion vs available stock → M-3002 short 4), equipment OEE, capacity checks — sandboxed read-only, derived properties visible
    (shortage: M-3001 gap 1 · M-3002 gap 4 · M-3003 gap 2)
12. **Multi-hop tracing**: M-3002 → BOM[B-02,B-05] → products[P-2001,P-2002]; explore mode expands N nodes depth-first from a random entry
13. **Audit**: 12 revisions in the window — executed / rule-rejected / policy-denied, all three present
14. **Time travel**: update = close old version + insert new; any historical moment is rebuildable → the data substrate for RSI replays
15. **The RSI loop**: operations keep filtering by the unmapped field workgroup → signal → proposal → **both suites green** → T0 auto-merge (budget 1/8) → the new property hot-loads into effect
16. **Outbox delivery**: webhook / projection / derivation / sse — four consumers advance their own cursors, never dragging each other
