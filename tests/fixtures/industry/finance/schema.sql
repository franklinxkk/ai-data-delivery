CREATE TABLE contract (id TEXT PRIMARY KEY, tenant TEXT, currency TEXT);
CREATE TABLE balance (id TEXT PRIMARY KEY, contract_id TEXT, as_of TEXT, version INTEGER, amount REAL, FOREIGN KEY(contract_id) REFERENCES contract(id));
CREATE TABLE collateral (id TEXT PRIMARY KEY, contract_id TEXT, value REAL, FOREIGN KEY(contract_id) REFERENCES contract(id));
