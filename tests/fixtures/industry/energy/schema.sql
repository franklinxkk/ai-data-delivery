CREATE TABLE meter (id TEXT PRIMARY KEY, tenant TEXT, multiplier REAL, rollover REAL);
CREATE TABLE reading (id TEXT PRIMARY KEY, meter_id TEXT, day TEXT, value REAL, FOREIGN KEY(meter_id) REFERENCES meter(id));
CREATE TABLE meter_event (id TEXT PRIMARY KEY, meter_id TEXT, kind TEXT, count INTEGER, FOREIGN KEY(meter_id) REFERENCES meter(id));
