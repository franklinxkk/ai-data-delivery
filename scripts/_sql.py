"""Bounded, single-dataset compiler; never silently erase another dataset."""
import re
from _contract import quote


def compile_single(mt, ds, names=()):
    if not ds or not ds.get("source"):
        return None, "无数据集 source"
    if mt.get("join_path") or mt.get("joins"):
        return None, "不支持跨表编译；请提供经验证的单表/视图映射"
    if mt.get("expr"):
        select = mt["expr"]
    elif (mt.get("numerator") or {}).get("expr") and (mt.get("denominator") or {}).get("expr"):
        select = f"({mt['numerator']['expr']}) * 1.0 / NULLIF(({mt['denominator']['expr']}), 0)"
    else:
        return None, "缺 expr 或完整分子分母"
    if mt.get("type") not in {"count", "sum", "avg", "min", "max", "ratio"}:
        return None, "本地编译器只支持单表标量聚合指标"
    if not re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", str(select), re.I):
        return None, "表达式缺少受支持的聚合函数"
    allowed = {ds.get("name"), ds.get("source")}

    def expression(sql):
        # Tokenize quoted strings separately so literal 'customers.id' is untouched.
        parts = re.split(r"('(?:''|[^'])*')", str(sql))
        for index in range(0, len(parts), 2):
            code = parts[index]
            if re.search(r";|--|/\*|\b(SELECT|FROM|JOIN|UNION|PRAGMA|ATTACH|GROUP|HAVING|ORDER|LIMIT|OFFSET|WINDOW|OVER|WITH|RETURNING|INTO)\b", code, re.I):
                raise ValueError("不支持子查询、SQL 注释或多语句")
            def prefix(match):
                name = match.group(1)
                if name not in allowed:
                    raise ValueError(f"跨表/未知前缀 {name}，单表编译拒绝")
                return ""
            code = re.sub(r"\b([A-Za-z_\u0080-\uffff]\w*)\s*\.", prefix, code)
            if re.search(r'["`\]]\s*\.', code):
                raise ValueError("不支持带引号的限定字段；请用当前数据集非限定字段")
            parts[index] = code
        return "".join(parts)

    def literal(value):
        if value is None:
            raise ValueError("filters.values 中 NULL 需用显式 extra_where IS NULL 口径")
        if isinstance(value, bool):
            return str(int(value))
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    try:
        wheres = []
        for item in mt.get("filters", []):
            if not item.get("values"):
                raise ValueError("空 filters.values 不能静默丢弃")
            wheres.append(expression(item["field"]) + " IN (" + ",".join(map(literal, item["values"])) + ")")
        if mt.get("extra_where"):
            wheres.append(expression(mt["extra_where"]))
        sql = f"SELECT {expression(select)} AS v FROM {quote(ds['source'])}"
        if wheres:
            sql += " WHERE " + " AND ".join(f"({item})" for item in wheres)
        return sql, None
    except (ValueError, KeyError, TypeError) as exc:
        return None, str(exc)
