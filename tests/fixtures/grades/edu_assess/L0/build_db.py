#!/usr/bin/env python3
"""build_db.py — L0 结构残缺档：只有部分 DDL 到货（dws_teaching_stats 一张表）。

模拟真实开局：信息中心只给了教学状态宽表的 DDL，毕业生明细表还没到位；
模型侧只有口头描述，粒度/主键/边界都没确认。数据本身是干净的。
造数与 L3 完全一致（确定性，无随机）。
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "domain.db")

COLLEGES = ["信息学院", "机电学院", "经管学院"]
YEARS = ["2023-2024", "2024-2025", "2025-2026"]


def build():
    if os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE dws_teaching_stats (
        college TEXT NOT NULL,
        year TEXT NOT NULL,
        student_cnt INTEGER NOT NULL,
        teacher_cnt INTEGER NOT NULL,
        senior_title_cnt INTEGER NOT NULL,
        professor_cnt INTEGER NOT NULL,
        course_offered_cnt INTEGER NOT NULL,
        professor_taught_cnt INTEGER NOT NULL,
        teach_fund_amount REAL NOT NULL,
        stat_date TEXT NOT NULL
    );
    """)
    for c, college in enumerate(COLLEGES):
        for y, year in enumerate(YEARS):
            student_cnt = 800 + c * 200 + y * 40
            conn.execute("INSERT INTO dws_teaching_stats VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (college, year, student_cnt, 50 + c * 10 + y * 2,
                          20 + c * 5 + y, 8 + c * 2 + y, 60 + c * 15 + y * 3,
                          30 + c * 9 + y * 2, student_cnt * (1400 + c * 100 + y * 50),
                          f"20{24 + y}-08-31"))
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM dws_teaching_stats").fetchone()[0]
    conn.close()
    print(f"建库完成：{DB}（dws_teaching_stats {n} 行；graduates 表未到货）")


if __name__ == "__main__":
    build()
