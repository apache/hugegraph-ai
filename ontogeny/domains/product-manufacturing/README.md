# Product Manufacturing Domain (product-manufacturing)

A complete, importable domain ontology package: **7 object types, 6 link types,
8 actions, 3 sandboxed functions, 2 policy sets** — all in English, every object
type covered by an action and a function, and seed data for every entity.

```
product-manufacturing/
├── ontology.yaml        # manifest: name, display, description, version
├── objects/             # 7 ObjectType resources
├── links/               # 6 LinkType resources (foreign-key joins)
├── actions/             # 8 Action resources (create / conditional modify)
├── functions/           # 3 Function resources + their Python files
├── policies/            # 2 PolicySet resources + Cedar sources
├── stores/mes.yaml      # source store (SQLite via ${ERP_DSN})
└── seed/01_source.sql   # English seed rows for every object type
```

## Import through the console

1. Zip this folder: `zip -r product-manufacturing.zip product-manufacturing`
   (a zip of the folder *or* of its contents both work).
2. In the console, open the domain switcher → **New domain** → **Import package**,
   pick the zip, confirm. The server validates the package before installing it
   and activates it on success.

## Seed the source data

The objects materialize from an external SQLite database referenced by
`${ERP_DSN}`. Prepare it once:

```bash
sqlite3 erp.db < seed/01_source.sql
ERP_DSN="sqlite+aiosqlite:///$(pwd)/erp.db" ontogeny serve ...
```

Then sync every type (Console → Data intake → *Sync every object type*, or
`POST /api/v1/admin/sync/{type}` per type). After syncing:

- every object type has rows (products, materials, BOM lines, work centres,
  production orders, routing operations, quality inspections);
- all three functions run against real data:
  `material-availability`, `capacity-check`, `order-yield`;
- the action chain *create → release → complete operation → record inspection*
  executes end to end (roles: `planner`, `operator`, `quality`).

These promises are pinned by `tests/test_product_manufacturing.py`; the import
path itself by `tests/test_domain_import.py`.
