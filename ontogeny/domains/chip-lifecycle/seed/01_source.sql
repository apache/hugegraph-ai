-- Chip lifecycle domain: source seed (PLM / fab / CRM side), all English.
-- Executed by `ontogeny serve` demos or by hand to prepare the source database:
--   sqlite3 source.db < seed/01_source.sql
-- Timestamps are fixed so demos are reproducible.
--
-- Note: field_failures carries a lot_id column that the field-failure object
-- does NOT declare. That is intentional -- it is the model gap the RSI loop
-- is expected to close (see CASE.md §3).

DROP TABLE IF EXISTS requirements;
DROP TABLE IF EXISTS design_modules;
DROP TABLE IF EXISTS tapeout_versions;
DROP TABLE IF EXISTS equipment;
DROP TABLE IF EXISTS wafer_lots;
DROP TABLE IF EXISTS process_steps;
DROP TABLE IF EXISTS wafer_tests;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS field_failures;

CREATE TABLE requirements (
    requirement_id TEXT PRIMARY KEY, title TEXT NOT NULL, priority TEXT,
    status TEXT, spec TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE design_modules (
    module_id TEXT PRIMARY KEY, name TEXT NOT NULL, purpose TEXT, owner_team TEXT,
    requirement_id TEXT NOT NULL, version_id TEXT, status TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE tapeout_versions (
    version_id TEXT PRIMARY KEY, project TEXT NOT NULL, status TEXT, notes TEXT,
    mask_cost TEXT, taped_out_at TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE equipment (
    equipment_id TEXT PRIMARY KEY, name TEXT NOT NULL, process TEXT, site TEXT,
    status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE wafer_lots (
    lot_id TEXT PRIMARY KEY, version_id TEXT NOT NULL, qty_wafers INTEGER,
    status TEXT, site TEXT, started_at TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE process_steps (
    step_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, seq INTEGER,
    name TEXT NOT NULL, equipment TEXT, status TEXT, completed_at TEXT, updated_at TEXT
);
CREATE TABLE wafer_tests (
    test_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, tested_qty INTEGER,
    defect_qty INTEGER, result TEXT, tester TEXT, tested_at TEXT, updated_at TEXT
);
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, segment TEXT, region TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE field_failures (
    failure_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, lot_id TEXT,
    symptom TEXT NOT NULL, failure_mode TEXT, reported_at TEXT, status TEXT, updated_at TEXT
);

INSERT INTO requirements VALUES
 ('REQ-101','IO ESD robustness ±8kV contact discharge','HIGH','OPEN','All IO pins must withstand ±8kV contact and ±15kV air discharge per IEC 61000-4-2, with IO leakage below 10 nA at 25 °C.','2026-01-12T08:00:00+00:00','2026-01-12T08:00:00+00:00'),
 ('REQ-102','Core power below 1.8 W','NORMAL','OPEN','The CPU core shall consume less than 1.8 W at 100% duty at 125 °C junction temperature.','2026-01-15T08:00:00+00:00','2026-01-15T08:00:00+00:00'),
 ('REQ-103','LVDS receiver locks at 1.6 Gbps','NORMAL','FULFILLED','The LVDS receiver shall lock at 1.6 Gbps with BER below 1e-12 across temperature.','2026-01-20T08:00:00+00:00','2026-01-20T08:00:00+00:00'),
 ('REQ-104','Junction temperature -40 to 125 °C','NORMAL','OPEN','The device shall operate from -40 °C to 125 °C junction temperature.','2026-02-02T08:00:00+00:00','2026-02-02T08:00:00+00:00');

INSERT INTO design_modules VALUES
 ('DSG-201','IO ring & ESD protection','ESD clamp network and IO buffers for the pad ring','Analog & IO','REQ-101','TO-A0','ACTIVE','2026-02-10T08:00:00+00:00','2026-06-05T08:00:00+00:00'),
 ('DSG-202','CPU core','32-bit RISC core with power gating','Core Design','REQ-102','TO-A0','ACTIVE','2026-02-12T08:00:00+00:00','2026-06-05T08:00:00+00:00'),
 ('DSG-203','LVDS PHY','High-speed LVDS transmitter and receiver','SerDes','REQ-103','TO-A0','ACTIVE','2026-02-14T08:00:00+00:00','2026-06-05T08:00:00+00:00'),
 ('DSG-204','Power management','On-chip LDO and power sequencing','Analog & IO','REQ-104','TO-A0','ACTIVE','2026-02-16T08:00:00+00:00','2026-06-05T08:00:00+00:00'),
 ('DSG-211','IO ring revision B','ESD clamp resize targeting ±12kV margin after field feedback','Analog & IO','REQ-101','TO-A1','ACTIVE','2026-09-14T08:00:00+00:00','2026-09-14T08:00:00+00:00');

INSERT INTO tapeout_versions VALUES
 ('TO-A0','X1','FAB','First cut; ESD clamps sized exactly to the ±8kV requirement.','1850000.00','2026-06-10T08:00:00+00:00','2026-05-02T08:00:00+00:00','2026-08-30T08:00:00+00:00'),
 ('TO-A1','X1','PLANNED','ESD guard resize; targets ±12kV margin after field feedback.','420000.00',NULL,'2026-09-14T08:00:00+00:00','2026-09-14T08:00:00+00:00'),
 ('TO-B0','X2','FAB','Next-gen project with stacked IO ring.','2400000.00','2026-09-28T08:00:00+00:00','2026-08-20T08:00:00+00:00','2026-09-28T08:00:00+00:00');

INSERT INTO equipment VALUES
 ('EQ-02','Scanner A (193i)','lithography','fab-site-a','ACTIVE','2024-03-01T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('EQ-03','Scanner B (193i)','lithography','fab-site-b','ACTIVE','2024-03-01T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('EQ-07','Etcher 1 (ICP)','etch','fab-site-a','ACTIVE','2024-05-10T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('EQ-09','Etcher 2 (ICP)','etch','fab-site-a','ACTIVE','2025-01-15T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('EQ-11','CVD Chamber 1','deposition','fab-site-a','ACTIVE','2024-05-10T08:00:00+00:00','2026-09-01T08:00:00+00:00');

INSERT INTO wafer_lots VALUES
 ('LOT-2417','TO-A0',25,'COMPLETE','fab-site-a','2026-07-01T08:00:00+00:00','2026-07-01T08:00:00+00:00','2026-07-20T08:00:00+00:00'),
 ('LOT-2418','TO-A0',25,'COMPLETE','fab-site-a','2026-07-08T08:00:00+00:00','2026-07-08T08:00:00+00:00','2026-07-27T08:00:00+00:00'),
 ('LOT-2419','TO-A0',25,'RUNNING','fab-site-a','2026-10-05T08:00:00+00:00','2026-10-05T08:00:00+00:00','2026-10-20T08:00:00+00:00'),
 ('LOT-2501','TO-B0',20,'RUNNING','fab-site-b','2026-10-06T08:00:00+00:00','2026-10-06T08:00:00+00:00','2026-10-20T08:00:00+00:00');

INSERT INTO process_steps VALUES
 ('PS-7111','LOT-2417',10,'Lithography','EQ-02','COMPLETED','2026-07-03T10:00:00+00:00','2026-07-03T10:00:00+00:00'),
 ('PS-7112','LOT-2417',20,'Etch','EQ-07','COMPLETED','2026-07-06T10:00:00+00:00','2026-07-06T10:00:00+00:00'),
 ('PS-7113','LOT-2417',30,'Deposition','EQ-11','COMPLETED','2026-07-10T10:00:00+00:00','2026-07-10T10:00:00+00:00'),
 ('PS-7121','LOT-2418',10,'Lithography','EQ-02','COMPLETED','2026-07-10T10:00:00+00:00','2026-07-10T10:00:00+00:00'),
 ('PS-7122','LOT-2418',20,'Etch','EQ-09','COMPLETED','2026-07-13T10:00:00+00:00','2026-07-13T10:00:00+00:00'),
 ('PS-7123','LOT-2418',30,'Deposition','EQ-11','COMPLETED','2026-07-17T10:00:00+00:00','2026-07-17T10:00:00+00:00'),
 ('PS-7131','LOT-2419',10,'Lithography','EQ-02','COMPLETED','2026-10-07T10:00:00+00:00','2026-10-07T10:00:00+00:00'),
 ('PS-7132','LOT-2419',20,'Etch','EQ-07','RUNNING',NULL,'2026-10-20T08:00:00+00:00'),
 ('PS-7133','LOT-2419',30,'Deposition','EQ-11','QUEUED',NULL,'2026-10-05T08:00:00+00:00'),
 ('PS-7211','LOT-2501',10,'Lithography','EQ-03','COMPLETED','2026-10-08T10:00:00+00:00','2026-10-08T10:00:00+00:00'),
 ('PS-7212','LOT-2501',20,'Etch','EQ-09','QUEUED',NULL,'2026-10-06T08:00:00+00:00');

INSERT INTO wafer_tests VALUES
 ('WT-501','LOT-2417',200,36,'FAIL','cp-eng-01','2026-07-18T09:00:00+00:00','2026-07-18T09:00:00+00:00'),
 ('WT-502','LOT-2418',200,8,'PASS','cp-eng-01','2026-07-25T09:00:00+00:00','2026-07-25T09:00:00+00:00'),
 ('WT-503','LOT-2501',120,3,'PENDING','cp-eng-02','2026-10-24T09:00:00+00:00','2026-10-24T09:00:00+00:00');

INSERT INTO customers VALUES
 ('C-201','ASTRA Mobility','automotive','EU','2026-03-01T08:00:00+00:00','2026-03-01T08:00:00+00:00'),
 ('C-202','BOREAL Systems','industrial','NA','2026-04-10T08:00:00+00:00','2026-04-10T08:00:00+00:00');

INSERT INTO field_failures VALUES
 ('FF-8001','C-201','LOT-2417','IO pin leakage above 10 nA at 25 °C on port bank B','PARAMETRIC','2026-10-12T08:00:00+00:00','OPEN','2026-10-12T08:00:00+00:00'),
 ('FF-8002','C-201','LOT-2417','IO pin leakage above 10 nA at 25 °C on port bank B','PARAMETRIC','2026-10-16T08:00:00+00:00','OPEN','2026-10-16T08:00:00+00:00'),
 ('FF-8003','C-201','LOT-2417','ESD latch-up event during board handling; port latched low','PARAMETRIC','2026-10-21T08:00:00+00:00','OPEN','2026-10-21T08:00:00+00:00');
