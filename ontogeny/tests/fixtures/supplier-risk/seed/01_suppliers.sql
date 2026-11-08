CREATE TABLE suppliers (
    supplier_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    risk_tier TEXT
);
INSERT INTO suppliers VALUES ('SUP-001', 'Acme Components', 'DE', 'MEDIUM');
INSERT INTO suppliers VALUES ('SUP-002', 'Globex Materials', 'US', 'LOW');
INSERT INTO suppliers VALUES ('SUP-003', 'Initech Fasteners', 'CN', 'HIGH');
