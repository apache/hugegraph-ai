# 09 · UI Tour（UI TOUR · SCREENSHOTS）

> Part of [Part II · Usage](../README.md#part-ii--usage)

**[中文](../../zh/usage/09-ui-tour.md)** | English

Seven high-frequency pages covering the daily path "model → data → trace → govern". All screenshots come from a real running demo instance (`ontogeny serve --demo`, the chip-lifecycle sample domain).

## ① Ontology definition (/ontology)

![The ontology canvas](../img/tour-ontology.png)

Types, actions, functions and links on a card canvas: entities / actions / functions are distinguishable at a glance, hovering highlights references; the canvas layout publishes together with the save.

## ② Semantic editing (/knowledge)

![The semantic layer editor](../img/tour-knowledge.png)

Resources in the left column, in-place forms on the right: properties / primary key / data mount; "Save & publish" at the top runs the validate-compile-persist pipeline; discard anything before saving.

## ③ Object data (the Knowledge page · Object data tab)

![Object data](../img/tour-objects.png)

Type switching, server-side pagination and filtering; marked (marking) properties are masked by the current identity — the same page shows different data to different identities, the policy surface made visible in the UI.

## ④ Graph explorer (/graph)

![Graph exploration](../img/tour-graph.png)

Neighborhood exploration (depth-first, reproducible seeds) and explicit path traversal; data comes from the HugeGraph projection, same source as the object API.

## ⑤ Action audit (/audit)

![The audit stream](../img/tour-audit.png)

The immutable revision stream: who, when, which resource, before/after; function code edits are audited too (`edit-function-source`).

## ⑥ Access control (/access)

![Roles & permissions](../img/tour-access.png)

The role × action grant matrix reads and writes the managed Cedar policy set directly; grants coming from hand-written policies are shown read-only locked — it never pretends to revoke someone else's permit.

## ⑦ Document intelligence (/documents)

![Document intelligence](../img/tour-documents.png)

Documents, tasks, review and confirmation live in one workspace: the left column is the corpus inventory (source switcher and extractor status on top), the right side walks each task through "run extraction → review & edit → confirm". Nothing writes before confirm; the extraction agent only emits what the ontology schema declares, and references like `Module:`/`BOM:` resolve to existing rows only.
