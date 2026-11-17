CREATE TABLE subscription (id TEXT PRIMARY KEY, tenant TEXT, phone_number TEXT, valid_from TEXT, valid_to TEXT);
CREATE TABLE usage_event (row_id TEXT PRIMARY KEY, event_id TEXT, subscription_id TEXT, business_day TEXT, version INTEGER, qty REAL, unit TEXT, state TEXT, FOREIGN KEY(subscription_id) REFERENCES subscription(id));
CREATE TABLE device (id TEXT PRIMARY KEY, subscription_id TEXT, FOREIGN KEY(subscription_id) REFERENCES subscription(id));
