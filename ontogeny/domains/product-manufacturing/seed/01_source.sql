-- Product manufacturing domain: source seed (MES/ERP side), all English.
-- Executed by `ontogeny serve` demos or by hand to prepare the ERP_DSN database:
--   sqlite3 erp.db < seed/01_source.sql
-- Timestamps are fixed so demos are reproducible.

DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS materials;
DROP TABLE IF EXISTS boms;
DROP TABLE IF EXISTS work_centers;
DROP TABLE IF EXISTS production_orders;
DROP TABLE IF EXISTS operations;
DROP TABLE IF EXISTS quality_inspections;

CREATE TABLE products (
    product_id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT,
    unit_price TEXT, status TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE materials (
    material_id TEXT PRIMARY KEY, name TEXT NOT NULL, unit TEXT, unit_cost TEXT,
    stock_qty INTEGER, safety_stock INTEGER, lead_time_days INTEGER,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE boms (
    bom_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, material_id TEXT NOT NULL,
    qty_per_unit TEXT, scrap_rate TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE work_centers (
    work_center_id TEXT PRIMARY KEY, name TEXT NOT NULL, process TEXT, site TEXT,
    capacity_per_shift INTEGER, shifts_per_day INTEGER, status TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE production_orders (
    order_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, qty INTEGER,
    status TEXT, priority TEXT, due_date TEXT, created_at TEXT, released_at TEXT,
    updated_at TEXT
);
CREATE TABLE operations (
    operation_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, seq INTEGER,
    name TEXT NOT NULL, work_center_id TEXT, status TEXT, standard_minutes INTEGER,
    completed_at TEXT, updated_at TEXT
);
CREATE TABLE quality_inspections (
    inspection_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, inspected_qty INTEGER,
    defect_qty INTEGER, result TEXT, inspector TEXT, inspected_at TEXT, updated_at TEXT
);

INSERT INTO products VALUES
 ('P-100','CNC Milling Machine','MACHINE','128000.00','ACTIVE','2024-01-15T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('P-200','Servo Drive Module','MODULE','5400.00','ACTIVE','2024-03-02T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('P-300','Spindle Bearing Kit','SPARE','890.00','ACTIVE','2024-05-20T08:00:00+00:00','2026-09-01T08:00:00+00:00');

INSERT INTO materials VALUES
 ('M-101','Steel Plate S45C','sheet','210.00',48,20,14,'2024-01-20T08:00:00+00:00','2026-09-20T08:00:00+00:00'),
 ('M-102','Aluminium Ingot 6061','kg','8.50',900,300,10,'2024-01-20T08:00:00+00:00','2026-09-20T08:00:00+00:00'),
 ('M-103','Servo Motor 1.5kW','pcs','1250.00',12,10,21,'2024-02-01T08:00:00+00:00','2026-09-20T08:00:00+00:00'),
 ('M-104','Precision Bearing 7014C','pcs','320.00',9,40,30,'2024-02-01T08:00:00+00:00','2026-09-20T08:00:00+00:00'),
 ('M-105','Control PCB Rev C','pcs','460.00',60,25,18,'2024-02-10T08:00:00+00:00','2026-09-20T08:00:00+00:00'),
 ('M-106','Wiring Harness A2','set','95.00',150,50,7,'2024-02-10T08:00:00+00:00','2026-09-20T08:00:00+00:00');

INSERT INTO boms VALUES
 ('B-1001','P-100','M-101','2.0','0.02','2024-02-15T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('B-1002','P-100','M-104','4.0','0.01','2024-02-15T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('B-1003','P-100','M-106','1.0','0.0','2024-02-15T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('B-2001','P-200','M-103','1.0','0.0','2024-03-10T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('B-2002','P-200','M-105','1.0','0.02','2024-03-10T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('B-2003','P-200','M-106','1.0','0.0','2024-03-10T08:00:00+00:00','2026-09-01T08:00:00+00:00'),
 ('B-3001','P-300','M-104','2.0','0.01','2024-05-25T08:00:00+00:00','2026-09-01T08:00:00+00:00');

INSERT INTO work_centers VALUES
 ('WC-01','CNC Machining Cell','machining','plant-north',400,2,'ACTIVE','2023-11-01T08:00:00+00:00','2026-09-15T08:00:00+00:00'),
 ('WC-02','Final Assembly Line','assembly','plant-north',300,2,'ACTIVE','2023-11-01T08:00:00+00:00','2026-09-15T08:00:00+00:00'),
 ('WC-03','Quality Inspection Bench','quality','plant-north',200,1,'IDLE','2023-11-01T08:00:00+00:00','2026-09-15T08:00:00+00:00');

INSERT INTO production_orders VALUES
 ('PO-1001','P-100',20,'RELEASED','HIGH','2026-10-15','2026-09-22T08:00:00+00:00','2026-09-23T08:00:00+00:00','2026-09-23T08:00:00+00:00'),
 ('PO-1002','P-200',50,'PLANNED','NORMAL','2026-10-30','2026-09-24T08:00:00+00:00',NULL,'2026-09-24T08:00:00+00:00'),
 ('PO-1003','P-300',100,'RELEASED','NORMAL','2026-10-08','2026-09-25T08:00:00+00:00','2026-09-26T08:00:00+00:00','2026-09-26T08:00:00+00:00'),
 ('PO-1004','P-100',10,'COMPLETED','LOW','2026-09-20','2026-08-01T08:00:00+00:00','2026-08-02T08:00:00+00:00','2026-09-19T08:00:00+00:00');

INSERT INTO operations VALUES
 ('OP-2001','PO-1001',10,'Plate Cutting','WC-01','RUNNING',120,NULL,'2026-09-25T08:00:00+00:00'),
 ('OP-2002','PO-1001',20,'CNC Milling','WC-01','QUEUED',180,NULL,'2026-09-25T08:00:00+00:00'),
 ('OP-2003','PO-1001',30,'Final Assembly','WC-02','QUEUED',90,NULL,'2026-09-25T08:00:00+00:00'),
 ('OP-2101','PO-1002',10,'PCB Preparation','WC-02','QUEUED',60,NULL,'2026-09-26T08:00:00+00:00'),
 ('OP-2102','PO-1002',20,'Module Assembly','WC-02','QUEUED',75,NULL,'2026-09-26T08:00:00+00:00'),
 ('OP-2201','PO-1003',10,'Kitting','WC-02','COMPLETED',30,'2026-09-26T10:00:00+00:00','2026-09-26T10:00:00+00:00'),
 ('OP-2202','PO-1003',20,'Bench Inspection','WC-03','COMPLETED',45,'2026-09-27T09:00:00+00:00','2026-09-27T09:00:00+00:00'),
 ('OP-2301','PO-1004',10,'CNC Milling','WC-01','COMPLETED',170,'2026-09-18T14:00:00+00:00','2026-09-18T14:00:00+00:00'),
 ('OP-2302','PO-1004',20,'Final Assembly','WC-02','COMPLETED',85,'2026-09-19T11:00:00+00:00','2026-09-19T11:00:00+00:00');

INSERT INTO quality_inspections VALUES
 ('QI-3001','PO-1003',100,2,'PASS','qa-eng-01','2026-09-27T09:30:00+00:00','2026-09-27T09:30:00+00:00'),
 ('QI-3002','PO-1004',10,0,'PASS','qa-eng-01','2026-09-19T12:00:00+00:00','2026-09-19T12:00:00+00:00'),
 ('QI-3003','PO-1001',8,1,'PENDING','qa-eng-02','2026-09-26T15:00:00+00:00','2026-09-26T15:00:00+00:00');
