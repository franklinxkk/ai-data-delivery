CREATE TABLE patient_alias (id TEXT PRIMARY KEY, tenant TEXT, canonical_person TEXT, source TEXT);
CREATE TABLE encounter (id TEXT PRIMARY KEY, patient_alias_id TEXT, day TEXT, state TEXT, FOREIGN KEY(patient_alias_id) REFERENCES patient_alias(id));
CREATE TABLE lab_record (id TEXT PRIMARY KEY, encounter_id TEXT, test_code TEXT, FOREIGN KEY(encounter_id) REFERENCES encounter(id));
