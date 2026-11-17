CREATE TABLE sales_order (id TEXT PRIMARY KEY, tenant TEXT, paid_day TEXT, state TEXT, currency TEXT, gross REAL);
CREATE TABLE refund (id TEXT PRIMARY KEY, order_id TEXT, state TEXT, amount REAL, FOREIGN KEY(order_id) REFERENCES sales_order(id));
CREATE TABLE order_tag (id TEXT PRIMARY KEY, order_id TEXT, label TEXT, FOREIGN KEY(order_id) REFERENCES sales_order(id));
