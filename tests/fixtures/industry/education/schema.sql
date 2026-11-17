CREATE TABLE person_role (id TEXT PRIMARY KEY, tenant TEXT, person_id TEXT, role TEXT);
CREATE TABLE course (id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE enrolment (id TEXT PRIMARY KEY, role_id TEXT, course_id TEXT, term TEXT, state TEXT, FOREIGN KEY(role_id) REFERENCES person_role(id), FOREIGN KEY(course_id) REFERENCES course(id));
