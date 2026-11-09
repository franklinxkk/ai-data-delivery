CREATE TABLE equipment (
  id TEXT PRIMARY KEY,
  lab_id TEXT NOT NULL,
  state TEXT NOT NULL,
  disabled INTEGER NOT NULL
);
