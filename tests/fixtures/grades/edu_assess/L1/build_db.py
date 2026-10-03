#!/usr/bin/env python3
"""build_db.py — L1 质量差档：结构完整，数据注入 4 类典型脏数据。

模拟真实困局：模型建完了，但源库数据没人审过——
  脏1 主键重复：graduates 出现两条 G0001（物理表无 PK 约束，真实业务库常态）
  脏2 枚举越界：一条 destination='待就业'（不在口径字典里）
  脏3 负值：一条 teach_fund_amount=-1000（经费为负，业务上不可能）
  脏4 引用悬空：一条 college='外语学院'（学院主数据里没有）
基线造数与 L3 一致（确定性），脏数据按固定序号注入。
"""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "domain.db")

COLLEGES = ["信息学院", "机电学院", "经管学院"]
YEARS = ["2023-2024", "2024-2025", "2025-2026"]
DESTINATIONS = ["协议就业", "升学", "灵活就业"]


def build():
    if os.path.exists(DB):
        os.remove(DB)
    conn = sqlite3.connect(DB)
    # 注意：L1 故意不声明物理主键——真实业务库常常没有，这正是需要数据约束检查的原因
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
    CREATE TABLE graduates (
        student_id TEXT,
        college TEXT NOT NULL,
        grad_year TEXT NOT NULL,
        degree_granted TEXT NOT NULL,
        destination TEXT NOT NULL,
        fitness_pass TEXT NOT NULL,
        grad_date TEXT NOT NULL
    );
    """)
    for c, college in enumerate(COLLEGES):
        for y, year in enumerate(YEARS):
            student_cnt = 800 + c * 200 + y * 40
            fund = student_cnt * (1400 + c * 100 + y * 50)
            if college == "经管学院" and year == "2025-2026":
                fund = -1000  # 脏3：负经费
            conn.execute("INSERT INTO dws_teaching_stats VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (college, year, student_cnt, 50 + c * 10 + y * 2,
                          20 + c * 5 + y, 8 + c * 2 + y, 60 + c * 15 + y * 3,
                          30 + c * 9 + y * 2, fund, f"20{24 + y}-08-31"))
    for i in range(1, 151):
        grad_year = "2025" if i <= 75 else "2026"
        conn.execute("INSERT INTO graduates VALUES (?,?,?,?,?,?,?)",
                     (f"G{i:04d}", COLLEGES[(i - 1) % 3], grad_year,
                      "否" if i % 25 == 0 else "是",
                      "未落实" if i % 10 == 0 else DESTINATIONS[i % 3],
                      "否" if i % 15 == 0 else "是", f"{grad_year}-06-30"))
    # 脏1：主键重复（再插一条 G0001）
    conn.execute("INSERT INTO graduates VALUES (?,?,?,?,?,?,?)",
                 ("G0001", "信息学院", "2025", "是", "协议就业", "是", "2025-06-30"))
    # 脏2：枚举越界
    conn.execute("INSERT INTO graduates VALUES (?,?,?,?,?,?,?)",
                 ("G9001", "机电学院", "2026", "是", "待就业", "是", "2026-06-30"))
    # 脏4：引用悬空（学院主数据无此值）
    conn.execute("INSERT INTO graduates VALUES (?,?,?,?,?,?,?)",
                 ("G9002", "外语学院", "2026", "是", "升学", "是", "2026-06-30"))
    conn.commit()
    n_d = conn.execute("SELECT COUNT(*) FROM dws_teaching_stats").fetchone()[0]
    n_g = conn.execute("SELECT COUNT(*) FROM graduates").fetchone()[0]
    conn.close()
    print(f"建库完成：{DB}（dws {n_d} 行 / graduates {n_g} 行，含 4 类注入脏数据）")


if __name__ == "__main__":
    build()
