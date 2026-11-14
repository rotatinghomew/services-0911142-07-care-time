"""按抽样设计的周负担估计：设计因子、户权重、分层 PSU 不确定性与折算敏感性。

周负担不按回收份数混算：每周估计 = workday_factor × 工作日日均 + weekend_factor × 周末日均，
因子来自 design 表（目标周构成）。总体均值与组间差使用户权重，方差用分层 PSU
线性化（with-replacement 近似），自由度 = PSU 数 − 层数。分位数为加权点估计。
"""
from .intervals import union_length
from .measures import DAY_MINUTES, diary_base_measures, equivalent_load, received_base_measures

DAY_TYPES = ("weekday", "weekend")

# t 分布 97.5% 分位表（df, 临界值），df 取不超过自由度的最大表值，偏保守。
T_TABLE = [
    (1, 12.7062), (2, 4.3027), (3, 3.1824), (4, 2.7764), (5, 2.5706),
    (6, 2.4469), (7, 2.3646), (8, 2.3060), (9, 2.2622), (10, 2.2281),
    (11, 2.2010), (12, 2.1788), (13, 2.1604), (14, 2.1448), (15, 2.1314),
    (16, 2.1199), (17, 2.1098), (18, 2.1009), (19, 2.0930), (20, 2.0860),
    (21, 2.0796), (22, 2.0739), (23, 2.0687), (24, 2.0639), (25, 2.0595),
    (26, 2.0555), (27, 2.0518), (28, 2.0484), (29, 2.0452), (30, 2.0423),
    (40, 2.0211), (60, 2.0003), (120, 1.9799),
]
T_INFINITY = 1.96


def t_critical(df):
    value = T_INFINITY
    for df_row, candidate in T_TABLE:
        if df >= df_row:
            value = candidate
        else:
            break
    return value


def psu_total_variance(residuals):
    """residuals 为 [(stratum, psu, value)]，返回 (总值方差, 单PSU层数, PSU数, 层数)。"""
    strata = {}
    for stratum, psu, value in residuals:
        strata.setdefault(stratum, {}).setdefault(psu, 0.0)
        strata[stratum][psu] += value
    variance = 0.0
    singletons = 0
    psu_count = 0
    for stratum in sorted(strata):
        totals = list(strata[stratum].values())
        psu_count += len(totals)
        if len(totals) < 2:
            singletons += 1
            continue
        mean = sum(totals) / len(totals)
        variance += len(totals) / (len(totals) - 1) * sum((total - mean) ** 2 for total in totals)
    return variance, singletons, psu_count, len(strata)


def _interval(estimate, variance, psu_count, stratum_count, singletons):
    se = variance ** 0.5
    df = max(psu_count - stratum_count, 1)
    margin = t_critical(df) * se
    return {"estimate": estimate, "se": se, "ci": [estimate - margin, estimate + margin],
            "df": df, "singleton_strata": singletons}


def weighted_mean(rows):
    """rows 含 weight/value/stratum/psu，返回加权均值与分层 PSU 线性化区间。"""
    if not rows:
        raise ValueError("所选范围内没有可估计的家庭")
    total_weight = sum(row["weight"] for row in rows)
    if total_weight <= 0:
        raise ValueError("所选范围内权重合计不为正")
    estimate = sum(row["weight"] * row["value"] for row in rows) / total_weight
    variance, singletons, psu_count, stratum_count = psu_total_variance(
        [(row["stratum"], row["psu"], row["weight"] * (row["value"] - estimate)) for row in rows])
    result = _interval(estimate, variance / total_weight ** 2, psu_count, stratum_count, singletons)
    result["households"] = len(rows)
    return result


def domain_mean(rows, group_key, group):
    """某一分组域的加权均值与区间；域外家庭在线性化残差中取 0。"""
    domain_weight = sum(row["weight"] for row in rows if row[group_key] == group)
    if domain_weight <= 0:
        return None
    estimate = sum(row["weight"] * row["value"] for row in rows if row[group_key] == group) / domain_weight
    variance, singletons, psu_count, stratum_count = psu_total_variance([
        (row["stratum"], row["psu"],
         row["weight"] * (row["value"] - estimate) if row[group_key] == group else 0.0)
        for row in rows])
    result = _interval(estimate, variance / domain_weight ** 2, psu_count, stratum_count, singletons)
    result["households"] = sum(1 for row in rows if row[group_key] == group)
    return result


def group_difference(rows, group_key, group_a, group_b):
    """两域均值之差及线性化区间；任一域缺失时返回 None。"""
    means = {}
    for group in (group_a, group_b):
        weight = sum(row["weight"] for row in rows if row[group_key] == group)
        if weight <= 0:
            return None
        means[group] = (sum(row["weight"] * row["value"] for row in rows if row[group_key] == group) / weight, weight)
    estimate = means[group_a][0] - means[group_b][0]
    influences = []
    for row in rows:
        influence = 0.0
        if row[group_key] == group_a:
            influence += row["weight"] * (row["value"] - means[group_a][0]) / means[group_a][1]
        if row[group_key] == group_b:
            influence -= row["weight"] * (row["value"] - means[group_b][0]) / means[group_b][1]
        influences.append((row["stratum"], row["psu"], influence))
    variance, singletons, psu_count, stratum_count = psu_total_variance(influences)
    result = _interval(estimate, variance, psu_count, stratum_count, singletons)
    result["contrast"] = group_a + "−" + group_b
    return result


def weighted_quantiles(rows, probs=(0.1, 0.25, 0.5, 0.75, 0.9)):
    """加权分位点估计（不含区间）；键为字符串，保证JSON往返后一致。"""
    points = sorted((row["value"], row["weight"]) for row in rows)
    total = sum(weight for _, weight in points)
    quantiles = {}
    cumulative = 0.0
    index = 0
    for prob in probs:
        target = prob * total
        while index < len(points) - 1 and cumulative + points[index][1] < target:
            cumulative += points[index][1]
            index += 1
        quantiles[str(prob)] = points[index][0]
    return quantiles


def _design_factors(design, household):
    workday = design["workday_factor"]
    weekend = design["weekend_factor"]
    if workday < 0 or weekend < 0 or workday + weekend <= 0:
        raise ValueError("设计表的周构成因子无效：" + household)
    return {"weekday": workday, "weekend": weekend}


def weekly_households(diaries, acts_by_diary, design_by_household, caliber, area):
    """按口径把日记汇总为户级周负担、提供者分担、接收端接收量与日记级明细。"""
    factors = caliber["factors"]
    by_household = {}
    for diary in diaries:
        by_household.setdefault(diary["household"], []).append(diary)
    households = []
    providers = []
    recipients = []
    diary_rows = []
    coverage = {"diaries_total": 0, "diaries_used": 0, "dropped_partial": 0, "dropped_proxy": 0,
                "households_total": 0, "households_used": 0, "households_incomplete": 0,
                "partial_diaries": 0, "proxy_diaries": 0, "cross_midnight_diaries": 0}
    for household in sorted(by_household):
        members = sorted(by_household[household], key=lambda diary: diary["diary"])
        if household not in design_by_household:
            raise ValueError("设计表缺少家庭：" + household)
        day_factors = _design_factors(design_by_household[household], household)
        keys = {(diary["weight"], diary["stratum"], diary["psu"], diary["area"]) for diary in members}
        if len(keys) != 1:
            raise ValueError("户内设计字段不一致：" + household)
        weight, stratum, psu, household_area = next(iter(keys))
        if area != "all" and household_area != area:
            continue
        coverage["households_total"] += 1
        coverage["diaries_total"] += len(members)
        prepared = []
        for diary in members:
            base = diary_base_measures(diary, acts_by_diary.get(diary["diary"], []))
            coverage["partial_diaries"] += base["coverage_minutes"] < DAY_MINUTES
            coverage["proxy_diaries"] += bool(diary["proxy"])
            coverage["cross_midnight_diaries"] += base["cross_midnight_minutes"] > 0
            drop = None
            if caliber["proxy"] == "exclude" and diary["proxy"]:
                drop = "代填排除"
                coverage["dropped_proxy"] += 1
            if drop is None and base["coverage_minutes"] < DAY_MINUTES and caliber["partial"] == "exclude":
                drop = "半天日记排除"
                coverage["dropped_partial"] += 1
            scale = 1.0
            if drop is None and base["coverage_minutes"] < DAY_MINUTES:
                scale = DAY_MINUTES / base["coverage_minutes"]
            prepared.append({"diary": diary, "base": base, "scale": scale, "drop": drop})
        by_provider = {}
        for entry in prepared:
            by_provider.setdefault(entry["diary"]["provider"], []).append(entry)
        per_provider = {}
        incomplete = False
        for provider in sorted(by_provider):
            usable = [entry for entry in by_provider[provider] if entry["drop"] is None]
            typed = {}
            for day_type in DAY_TYPES:
                typed[day_type] = [entry for entry in usable if entry["diary"]["day_type"] == day_type]
                if not typed[day_type]:
                    incomplete = True
            if incomplete:
                break
            weekly = {"clock": 0.0, "load": 0.0}
            tasks = {}
            for day_type in DAY_TYPES:
                entries = typed[day_type]
                factor = day_factors[day_type]
                weekly["clock"] += factor * sum(entry["scale"] * entry["base"]["clock_minutes"]
                                                for entry in entries) / len(entries)
                weekly["load"] += factor * sum(entry["scale"] * equivalent_load(entry["base"], factors)
                                               for entry in entries) / len(entries)
                task_totals = {}
                for entry in entries:
                    for task, minutes in entry["base"]["task_minutes"].items():
                        task_totals[task] = task_totals.get(task, 0.0) + entry["scale"] * minutes
                for task, total in task_totals.items():
                    tasks[task] = tasks.get(task, 0.0) + factor * total / len(entries)
            per_provider[provider] = {"weekly": weekly, "tasks": tasks}
        if incomplete:
            coverage["households_incomplete"] += 1
            for entry in prepared:
                diary_rows.append(_diary_row(entry, factors, False, entry["drop"] or "户内缺少可用日记"))
            continue
        coverage["households_used"] += 1
        coverage["diaries_used"] += sum(1 for entry in prepared if entry["drop"] is None)
        household_clock = sum(item["weekly"]["clock"] for item in per_provider.values())
        household_load = sum(item["weekly"]["load"] for item in per_provider.values())
        households.append({"household": household, "area": household_area, "weight": weight,
                           "stratum": stratum, "psu": psu,
                           "weekly_clock": household_clock, "weekly_load": household_load})
        for provider in sorted(per_provider):
            providers.append({"provider": provider, "household": household, "area": household_area,
                              "weekly_clock": per_provider[provider]["weekly"]["clock"],
                              "weekly_load": per_provider[provider]["weekly"]["load"],
                              "tasks": per_provider[provider]["tasks"]})
        recipients.extend(_weekly_recipients(household, prepared, acts_by_diary, day_factors, caliber))
        for entry in prepared:
            diary_rows.append(_diary_row(entry, factors, entry["drop"] is None, entry["drop"]))
    return {"households": households, "providers": providers, "recipients": recipients,
            "diaries": diary_rows, "coverage": coverage}


def _diary_row(entry, factors, used, reason):
    diary = entry["diary"]
    base = entry["base"]
    return {"diary": diary["diary"], "household": diary["household"], "provider": diary["provider"],
            "day_type": diary["day_type"], "proxy": diary["proxy"],
            "coverage_minutes": base["coverage_minutes"],
            "clock_minutes": base["clock_minutes"],
            "reported_minutes": base["reported_minutes"],
            "load_minutes": equivalent_load(base, factors),
            "concurrent_minutes": base["concurrent_minutes"],
            "max_concurrency": base["max_concurrency"],
            "multi_recipient_minutes": base["multi_recipient_minutes"],
            "cross_midnight_minutes": base["cross_midnight_minutes"],
            "before_window_minutes": base["before_window_minutes"],
            "used_in_weekly": used, "drop_reason": reason or ""}


def _weekly_recipients(household, prepared, acts_by_diary, day_factors, caliber):
    usable = [entry for entry in prepared if entry["drop"] is None]
    weekly = {}
    for day_type in DAY_TYPES:
        entries = [entry for entry in usable if entry["diary"]["day_type"] == day_type]
        if not entries:
            continue
        received = received_base_measures(
            [(entry["diary"], acts_by_diary.get(entry["diary"]["diary"], [])) for entry in entries])
        window = union_length([(entry["diary"]["observed_start"], entry["diary"]["observed_stop"])
                               for entry in entries])
        scale = DAY_MINUTES / window if caliber["partial"] == "scale" and 0 < window < DAY_MINUTES else 1.0
        for recipient, measure in received.items():
            item = weekly.setdefault(recipient, {"clock": 0.0, "person": 0.0, "double": 0.0, "providers": set()})
            factor = day_factors[day_type]
            item["clock"] += factor * scale * measure["received_clock_minutes"]
            item["person"] += factor * scale * measure["received_person_minutes"]
            item["double"] += factor * scale * measure["double_coverage_minutes"]
            item["providers"].update(measure["providers"])
    return [{"recipient": recipient, "household": household,
             "weekly_received_clock": item["clock"],
             "weekly_received_person": item["person"],
             "weekly_double_coverage": item["double"],
             "providers": sorted(item["providers"])}
            for recipient, item in sorted(weekly.items())]


def sensitivity_grid(diaries, acts_by_diary, design_by_household, caliber, area):
    """在伴随/待命系数网格上重算周户均折算负担与组间差，观察结论的敏感程度。"""
    cells = []
    for secondary in caliber["sensitivity"]["secondary"]:
        for standby in caliber["sensitivity"]["standby"]:
            varied = {**caliber, "factors": {**caliber["factors"], "secondary": secondary, "standby": standby}}
            result = weekly_households(diaries, acts_by_diary, design_by_household, varied, area)
            rows = survey_rows(result["households"], "weekly_load")
            mean = weighted_mean(rows)["estimate"] if rows else None
            difference = None
            if caliber["group_by"] == "area" and rows:
                contrast = group_difference(rows, "area", "town", "village")
                difference = contrast["estimate"] if contrast else None
            cells.append({"secondary": secondary, "standby": standby, "mean": mean, "difference": difference})
    means = [cell["mean"] for cell in cells if cell["mean"] is not None]
    differences = [cell["difference"] for cell in cells if cell["difference"] is not None]
    return {"secondary": list(caliber["sensitivity"]["secondary"]),
            "standby": list(caliber["sensitivity"]["standby"]),
            "cells": cells,
            "mean_range": [min(means), max(means)] if means else None,
            "difference_range": [min(differences), max(differences)] if differences else None,
            "difference_sign_change": bool(differences) and min(differences) < 0 < max(differences)}


def survey_rows(households, key):
    return [{"weight": row["weight"], "value": row[key], "stratum": row["stratum"],
             "psu": row["psu"], "area": row["area"]} for row in households]
