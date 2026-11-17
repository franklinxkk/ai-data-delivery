CREATE TABLE room (id TEXT PRIMARY KEY, tenant TEXT);
CREATE TABLE room_day (id TEXT PRIMARY KEY, room_id TEXT, day TEXT, sellable INTEGER, FOREIGN KEY(room_id) REFERENCES room(id));
CREATE TABLE stay (id TEXT PRIMARY KEY, room_id TEXT, check_in TEXT, check_out TEXT, state TEXT, complimentary INTEGER, FOREIGN KEY(room_id) REFERENCES room(id));
