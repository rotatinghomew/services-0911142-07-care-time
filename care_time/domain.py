from .validation import require_tables, unique, finite, references


SCHEMA = {'diaries': {'diary': ['str'], 'household': ['str'], 'provider': ['str'], 'day_type': ['str'], 'area': ['str'], 'day_start': ['number'], 'observed_start': ['number'], 'observed_stop': ['number'], 'proxy': ['boolean'], 'weight': ['number'], 'stratum': ['str'], 'psu': ['str']}, 'activities': {'activity': ['str'], 'diary': ['str'], 'start': ['number'], 'stop': ['number'], 'kind': ['str'], 'recipient': ['str'], 'task': ['str']}, 'design': {'household': ['str'], 'workday_factor': ['number'], 'weekend_factor': ['number'], 'sampling_unit': ['str']}}
OPTIONS = {'day_type': ['all', 'weekday', 'weekend'], 'area': ['all', 'town', 'village']}


def validate_structure(data, schema):
    require_tables(data, list(schema))
    for table, fields in schema.items():
        for row in data[table]:
            if not isinstance(row, dict) or any(field not in row for field in fields):
                raise ValueError("表字段缺失：" + table)
            for field, kinds in fields.items():
                value = row[field]
                kind = "null" if value is None else ("boolean" if isinstance(value,bool) else ("number" if isinstance(value,(int,float)) else type(value).__name__))
                if kind not in kinds:
                    raise ValueError("字段类型错误：" + table + "." + field)
                if kind == "number":
                    finite(value)


def validate(data):
    validate_structure(data, SCHEMA)
    unique(data['diaries'], ['diary'])
    unique(data['activities'], ['activity'])
    unique(data['design'], ['household'])
    references(data['activities'], 'diary', data['diaries'], 'diary')
    for row in data["activities"]:
        if row["stop"] <= row["start"] or row["kind"] not in {"primary","secondary","standby"}:
            raise ValueError("活动区间或角色无效")


def view(rows, measure, note):
    return {"summary":{"明细条数":len(rows),"有数值记录":sum(isinstance(row.get(measure),(int,float)) for row in rows)},
            "rows":rows,"series":[{"label":str(position+1),"y":row.get(measure)} for position,row in enumerate(rows)],
            "notes":[note]}


def explore(data, selection):
    for key, choices in OPTIONS.items():
        if selection.get(key) not in choices:
            raise ValueError("选择范围无效：" + key)
    diaries = {row["diary"]:row for row in data["diaries"] if (selection["area"] == "all" or row["area"] == selection["area"]) and (selection["day_type"] == "all" or row["day_type"] == selection["day_type"])}
    rows = [{**diary,"reported_minutes":sum(row["stop"]-row["start"] for row in data["activities"] if row["diary"] == identifier)} for identifier,diary in diaries.items()]
    return view(rows, "reported_minutes", "填报时长直接相加会重复计算并行活动，不能当钟表负担或周总体推断。")
