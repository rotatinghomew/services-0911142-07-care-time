from .estimate import (domain_mean, group_difference, sensitivity_grid, survey_rows,
                       weighted_mean, weighted_quantiles, weekly_households)
from .measures import DAY_MINUTES, KINDS, diary_base_measures, received_base_measures
from .validation import finite, require_tables, unique, references


SCHEMA = {'diaries': {'diary': ['str'], 'household': ['str'], 'provider': ['str'], 'day_type': ['str'], 'area': ['str'], 'day_start': ['number'], 'observed_start': ['number'], 'observed_stop': ['number'], 'proxy': ['boolean'], 'weight': ['number'], 'stratum': ['str'], 'psu': ['str']}, 'activities': {'activity': ['str'], 'diary': ['str'], 'start': ['number'], 'stop': ['number'], 'kind': ['str'], 'recipient': ['str'], 'task': ['str']}, 'design': {'household': ['str'], 'workday_factor': ['number'], 'weekend_factor': ['number'], 'sampling_unit': ['str']}}
OPTIONS = {'day_type': ['all', 'weekday', 'weekend'], 'area': ['all', 'town', 'village']}

CALIBER_KEYS = {"factors", "partial", "proxy", "group_by", "sensitivity"}
PARTIAL_MODES = ("exclude", "scale")
PROXY_MODES = ("include", "exclude")
GROUP_MODES = ("area", "none")
SENSITIVITY_KINDS = ("secondary", "standby")


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


def validate_caliber(caliber):
    """校验并规范化研究口径；未知字段直接拒绝，避免口径被静默改换。"""
    if not isinstance(caliber, dict):
        raise ValueError("研究口径必须是对象")
    unknown = set(caliber) - CALIBER_KEYS
    if unknown:
        raise ValueError("研究口径含未知字段：" + ",".join(sorted(unknown)))
    factors = caliber.get("factors")
    if not isinstance(factors, dict) or set(factors) != set(KINDS):
        raise ValueError("折算系数必须恰好包含 primary/secondary/standby")
    normalized_factors = {}
    for kind in KINDS:
        finite(factors[kind], 0, 2)
        normalized_factors[kind] = float(factors[kind])
    partial = caliber.get("partial", "exclude")
    if partial not in PARTIAL_MODES:
        raise ValueError("半天日记口径无效：" + str(partial))
    proxy = caliber.get("proxy", "include")
    if proxy not in PROXY_MODES:
        raise ValueError("代填口径无效：" + str(proxy))
    group_by = caliber.get("group_by", "area")
    if group_by not in GROUP_MODES:
        raise ValueError("分组口径无效：" + str(group_by))
    sensitivity = caliber.get("sensitivity", {})
    if not isinstance(sensitivity, dict) or set(sensitivity) - set(SENSITIVITY_KINDS):
        raise ValueError("敏感性网格只能含 secondary/standby")
    grids = {}
    for kind in SENSITIVITY_KINDS:
        values = sensitivity.get(kind, [normalized_factors[kind]])
        if not isinstance(values, list) or not 1 <= len(values) <= 8:
            raise ValueError("敏感性网格每维需1至8个取值")
        for value in values:
            finite(value, 0, 2)
        grids[kind] = sorted({float(value) for value in values})
    return {"factors": normalized_factors, "partial": partial, "proxy": proxy,
            "group_by": group_by, "sensitivity": grids}


def view(rows, measure, note):
    return {"summary":{"明细条数":len(rows),"有数值记录":sum(isinstance(row.get(measure),(int,float)) for row in rows)},
            "rows":rows,"series":[{"label":str(position+1),"y":row.get(measure)} for position,row in enumerate(rows)],
            "notes":[note]}


def check_selection(selection):
    for key, choices in OPTIONS.items():
        if selection.get(key) not in choices:
            raise ValueError("选择范围无效：" + key)


def explore(data, selection):
    check_selection(selection)
    diaries = {row["diary"]:row for row in data["diaries"] if (selection["area"] == "all" or row["area"] == selection["area"]) and (selection["day_type"] == "all" or row["day_type"] == selection["day_type"])}
    rows = [{**diary,"reported_minutes":sum(row["stop"]-row["start"] for row in data["activities"] if row["diary"] == identifier)} for identifier,diary in diaries.items()]
    return view(rows, "reported_minutes", "填报时长直接相加会重复计算并行活动，不能当钟表负担或周总体推断。")


def _grouped_activities(data):
    grouped = {}
    for activity in data["activities"]:
        grouped.setdefault(activity["diary"], []).append(activity)
    return grouped


def analyze(data, selection, caliber):
    """研究估计：钟表时间、折算负担、接收端与提供端、周负担分布与不确定性。

    结果由数据版本与口径唯一决定；同一数据版本同一口径重算必然得到同一结果。
    """
    check_selection(selection)
    caliber = validate_caliber(caliber)
    acts_by_diary = _grouped_activities(data)
    design_by_household = {row["household"]: row for row in data["design"]}
    area = selection["area"]
    result = weekly_households(data["diaries"], acts_by_diary, design_by_household, caliber, area)
    households = result["households"]
    if not households:
        raise ValueError("所选范围与口径下没有可估计的家庭")
    clock_rows = survey_rows(households, "weekly_clock")
    load_rows = survey_rows(households, "weekly_load")
    weekly = {"clock": weighted_mean(clock_rows), "load": weighted_mean(load_rows),
              "quantiles_clock": weighted_quantiles(clock_rows),
              "quantiles_load": weighted_quantiles(load_rows)}
    groups = None
    if caliber["group_by"] == "area":
        group_rows = []
        for group in ("town", "village"):
            clock_domain = domain_mean(clock_rows, "area", group)
            load_domain = domain_mean(load_rows, "area", group)
            if clock_domain is not None:
                group_rows.append({"group": group, "households": clock_domain["households"],
                                   "clock": clock_domain, "load": load_domain})
        groups = {"by": "area", "rows": group_rows,
                  "clock_difference": group_difference(clock_rows, "area", "town", "village"),
                  "load_difference": group_difference(load_rows, "area", "town", "village")}
    sensitivity = sensitivity_grid(data["diaries"], acts_by_diary, design_by_household, caliber, area)
    notes = _analysis_notes(selection, caliber, result["coverage"], weekly, sensitivity,
                            design_by_household, households)
    return {"caliber": caliber, "coverage": result["coverage"], "weekly": weekly, "groups": groups,
            "sensitivity": sensitivity, "providers": result["providers"],
            "recipients": result["recipients"], "diaries": result["diaries"], "notes": notes}


def _analysis_notes(selection, caliber, coverage, weekly, sensitivity, design_by_household, households):
    factors = caliber["factors"]
    notes = [
        "钟表时间为覆盖窗口内活动区间的并集；未观测时段是未观测，不视为休息，也不计为零。",
        "折算负担＝主活动×{primary}＋伴随×{secondary}＋待命×{standby}（分钟）；并行活动分别折算，"
        "因此可超过钟表时间，这正是强度而非错误。".format(**factors),
        "跨午夜延续分钟归属于起始日记，只计入折算负担与填报分钟，不进入当日钟表时间，也不计入其他日记。",
        "接收端（被照护者）与提供端分开：接收钟表时间为跨提供者并集，提供端人时按提供者分别累计，"
        "户合计可超过每周10080分钟。",
    ]
    factors_used = {design_by_household[row["household"]]["workday_factor"] for row in households}
    weekend_used = {design_by_household[row["household"]]["weekend_factor"] for row in households}
    if len(factors_used) == 1 and len(weekend_used) == 1:
        notes.append("周负担＝{}×工作日日均＋{}×周末日均（design 表目标周构成），不按回收份数混算。".format(
            next(iter(factors_used)), next(iter(weekend_used))))
    else:
        notes.append("周负担按各户 design 表的工作日/周末因子合成，不按回收份数混算。")
    notes.append("总体均值与组间差按户权重加权，方差为分层 PSU 线性化（自由度＝PSU数−层数），"
                 "给出95%置信区间；分位数为加权点估计，未附区间。")
    if caliber["partial"] == "exclude":
        notes.append("半天日记（覆盖不足1440分钟）按口径排除出周估计：本次排除{}篇；"
                     "其窗口内测量仍列于日记级明细。".format(coverage["dropped_partial"]))
    else:
        notes.append("半天日记按口径留在估计中，窗口内测量按1440/覆盖分钟放大；"
                     "该放大假设未观测时段与已观测时段相同，属口径选择而非事实。")
    if caliber["proxy"] == "exclude":
        notes.append("代填日记按口径排除出周估计：本次排除{}篇。".format(coverage["dropped_proxy"]))
    else:
        notes.append("代填日记按口径保留在估计中（共{}篇）；可在口径中排除以做敏感性对照。".format(
            coverage["proxy_diaries"]))
    if coverage["households_incomplete"]:
        notes.append("{}户因工作日或周末缺少可用日记而未进入周估计。".format(coverage["households_incomplete"]))
    if selection["day_type"] != "all":
        notes.append("范围中的日期类型筛选只作用于上方描述性浏览；周负担估计必须使用两种日期类型。")
    if selection["area"] != "all":
        notes.append("研究估计只覆盖所选区域（{}），属于域估计而非全总体。".format(selection["area"]))
    notes.append("敏感性网格只改变折算负担；钟表时间结果不随折算系数变化。"
                 + ("注意：网格内组间差符号发生翻转，结论对折算敏感。" if sensitivity["difference_sign_change"]
                    else "网格内组间差符号未翻转。"))
    if weekly["clock"]["singleton_strata"]:
        notes.append("有{}个层只含一个PSU，其方差贡献按0处理，不确定度可能偏低。".format(
            weekly["clock"]["singleton_strata"]))
    return notes


def household_timeline(data, household):
    """家庭时间轴：原始记录与接收端并集段，供页面绘制与核对。"""
    acts_by_diary = _grouped_activities(data)
    members = sorted((row for row in data["diaries"] if row["household"] == household),
                     key=lambda row: row["diary"])
    if not members:
        raise LookupError("家庭不在数据版本中：" + household)
    design = next((row for row in data["design"] if row["household"] == household), None)
    days = []
    for day_type in ("weekday", "weekend"):
        day_diaries = [diary for diary in members if diary["day_type"] == day_type]
        if not day_diaries:
            continue
        diaries_out = []
        for diary in day_diaries:
            activities = sorted(acts_by_diary.get(diary["diary"], []),
                                key=lambda row: (row["start"], row["activity"]))
            diaries_out.append({**diary, "activities": activities,
                                "measures": diary_base_measures(diary, activities)})
        received = received_base_measures(
            [(diary, acts_by_diary.get(diary["diary"], [])) for diary in day_diaries])
        recipients_out = [{"recipient": recipient, **measure} for recipient, measure in sorted(received.items())]
        days.append({"day_type": day_type, "diaries": diaries_out, "recipients": recipients_out})
    return {"household": household, "design": design, "days": days}
