CREATE TABLE work_order (id TEXT PRIMARY KEY, tenant TEXT);
CREATE TABLE lot (id TEXT PRIMARY KEY, order_id TEXT, qty REAL, unit TEXT, finished_day TEXT, FOREIGN KEY(order_id) REFERENCES work_order(id));
CREATE TABLE inspection (id TEXT PRIMARY KEY, lot_id TEXT, revision INTEGER, disposition TEXT, FOREIGN KEY(lot_id) REFERENCES lot(id));
