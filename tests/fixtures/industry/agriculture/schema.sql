CREATE TABLE plot (id TEXT PRIMARY KEY, tenant TEXT, season TEXT);
CREATE TABLE harvest (id TEXT PRIMARY KEY, plot_id TEXT, qty REAL, unit TEXT, day TEXT, state TEXT, FOREIGN KEY(plot_id) REFERENCES plot(id));
CREATE TABLE lot_event (id TEXT PRIMARY KEY, harvest_id TEXT, kind TEXT, qty REAL, unit TEXT, FOREIGN KEY(harvest_id) REFERENCES harvest(id));
