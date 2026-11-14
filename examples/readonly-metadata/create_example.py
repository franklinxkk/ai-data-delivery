#!/usr/bin/env python3
"""Create a new synthetic SQLite catalog exercise; never opens an existing database."""
import argparse
import json
from pathlib import Path
import sqlite3

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--out',required=True,help='New directory outside the installed skill / 安装目录以外的新目录')
args=p.parse_args()
out=Path(args.out).resolve()
out.mkdir(parents=True,exist_ok=False)
db=sqlite3.connect(out/'plants.sqlite')
try:
    db.executescript('CREATE TABLE plant(id INTEGER PRIMARY KEY, name TEXT, moisture REAL);'
                    'CREATE TABLE care(id INTEGER PRIMARY KEY, plant_id INTEGER REFERENCES plant(id), performed_at TEXT);')
finally:db.close()
profile={'name':'Synthetic plant catalog / 合成植物目录','engine':'sqlite','path':str(out/'plants.sqlite'),
         'tables':['plant','care'],'auto_indexes':False}
(out/'connection.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'profile':str(out/'connection.json'),'database':str(out/'plants.sqlite'),'synthetic':True,'business_rows':0},ensure_ascii=False))
