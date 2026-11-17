CREATE TABLE project (id TEXT PRIMARY KEY, tenant TEXT, currency TEXT);
CREATE TABLE certificate (id TEXT PRIMARY KEY, project_id TEXT, state TEXT, amount REAL, business_day TEXT, FOREIGN KEY(project_id) REFERENCES project(id));
CREATE TABLE payment (id TEXT PRIMARY KEY, project_id TEXT, state TEXT, amount REAL, business_day TEXT, FOREIGN KEY(project_id) REFERENCES project(id));
