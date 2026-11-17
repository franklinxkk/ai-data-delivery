CREATE TABLE enterprise (id TEXT PRIMARY KEY, tenant TEXT);
CREATE TABLE vehicle (id TEXT PRIMARY KEY, enterprise_id TEXT, FOREIGN KEY(enterprise_id) REFERENCES enterprise(id));
CREATE TABLE journey (row_id TEXT PRIMARY KEY, tenant TEXT, source TEXT, original_id TEXT, vehicle_id TEXT, status TEXT, business_day TEXT, version INTEGER, FOREIGN KEY(vehicle_id) REFERENCES vehicle(id));
