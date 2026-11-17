CREATE TABLE unit_space (id TEXT PRIMARY KEY, tenant TEXT, area REAL, rentable INTEGER);
CREATE TABLE lease (id TEXT PRIMARY KEY, unit_id TEXT, start_day TEXT, end_day TEXT, state TEXT, FOREIGN KEY(unit_id) REFERENCES unit_space(id));
CREATE TABLE owner_history (id TEXT PRIMARY KEY, unit_id TEXT, owner TEXT, start_day TEXT, end_day TEXT, FOREIGN KEY(unit_id) REFERENCES unit_space(id));
