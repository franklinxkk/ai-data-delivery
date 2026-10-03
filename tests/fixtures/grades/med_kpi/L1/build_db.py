#!/usr/bin/env python3
"""build_db.py — 三级公立医院绩效考核（国考）场景：生成确定性 SQLite 物理库（domain.db）。

业务故事：一家三甲医院的运营数据中心为"国考"（国办发〔2019〕4号）备战，
把 55+1 个三级指标中可定量部分沉淀为两张表：
  dws_dept_monthly —— 科室月度运营宽表（一行一科室一月，绩效办填报系统就是这个形态）
  inpatients       —— 出院患者明细表（一行一名出院患者）
指标口径参照国办发〔2019〕4号及国家卫健委历年操作手册。
造数完全确定（无随机数），gold 期望可用 SQL 复算。
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "domain.db")

DEPTS = ["心血管内科", "骨科", "普外科"]
MONTHS = ["2026-06", "2026-07", "2026-08"]
STAT_DATES = ["2026-06-30", "2026-07-31", "2026-08-31"]


def build():
    if os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE dws_dept_monthly (
        dept TEXT NOT NULL,
        month TEXT NOT NULL,
        outpatient_visits INTEGER NOT NULL,
        outpatient_rev REAL NOT NULL,
        drug_rev REAL NOT NULL,
        med_service_rev REAL NOT NULL,
        discharges INTEGER NOT NULL,
        surgeries INTEGER NOT NULL,
        level4_surgeries INTEGER NOT NULL,
        open_bed_days INTEGER NOT NULL,
        occupied_bed_days INTEGER NOT NULL,
        stat_date TEXT NOT NULL
    );
    CREATE TABLE inpatients (
        patient_id TEXT,
        dept TEXT NOT NULL,
        stay_days INTEGER NOT NULL,
        discharge_way TEXT NOT NULL,
        total_fee REAL NOT NULL,
        discharge_date TEXT NOT NULL
    );
    """)
    # 9 行宽表：科室 × 月，各列按序号线性递推，完全确定
    for c, dept in enumerate(DEPTS):
        for m, month in enumerate(MONTHS):
            visits = 3000 + c * 500 + m * 100
            rev = visits * (300 + c * 20)
            conn.execute(
                "INSERT INTO dws_dept_monthly VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (dept, month, visits, rev,
                 rev * (30 - m) / 100,        # drug_rev 药占比逐月下降（30%→29%→28%）
                 rev * (25 + c) / 100,        # med_service_rev 医疗服务收入
                 400 + c * 80 + m * 20,       # discharges 出院人数
                 200 + c * 60 + m * 10,       # surgeries 手术台次
                 40 + c * 20 + m * 5,         # level4_surgeries 四级手术台次
                 3000,                        # open_bed_days 开放床日
                 2400 + c * 150 + m * 60,     # occupied_bed_days 占用床日
                 STAT_DATES[m]))
    # 120 名出院患者：住院日 3+(i%12)，i%40==0 为超长住院(35 天)
    for i in range(1, 121):
        stay = 35 if i % 40 == 0 else 3 + (i % 12)
        way = "转院" if i % 17 == 0 else ("非医嘱离院" if i % 17 == 1 else "医嘱离院")
        conn.execute(
            "INSERT INTO inpatients VALUES (?,?,?,?,?,?)",
            (f"P{i:04d}", DEPTS[(i - 1) % 3], stay, way,
             8000 + (i * 137) % 9000, f"2026-0{6 + i % 3}-{(i % 28) + 1:02d}"))
    conn.commit()
    n_d = conn.execute("SELECT COUNT(*) FROM dws_dept_monthly").fetchone()[0]
    n_i = conn.execute("SELECT COUNT(*) FROM inpatients").fetchone()[0]
    conn.close()
    print(f"建库完成：{DB}（dws_dept_monthly {n_d} 行 / inpatients {n_i} 行）")


if __name__ == "__main__":
    build()

# ---- L1 退化：注入 4 类脏数据（ip_pk 主键重复（P0001 两条）/ ip_way_values 枚举越界（急诊离院）/ dws_rev_nonnegative 负收入（骨科 2026-08）/ ip_dept_ref 引用悬空（整形美容科）） ----
_c = sqlite3.connect(DB)
_c.executescript('''
INSERT INTO inpatients VALUES ('P0001','骨科',9,'医嘱离院',12345.0,'2026-07-15');
INSERT INTO inpatients VALUES ('P9001','骨科',7,'急诊离院',8800.0,'2026-08-15');
INSERT INTO inpatients VALUES ('P9002','整形美容科',5,'医嘱离院',6600.0,'2026-08-16');
UPDATE dws_dept_monthly SET outpatient_rev=-100 WHERE dept='骨科' AND month='2026-08';
''')
_c.commit(); _c.close()
