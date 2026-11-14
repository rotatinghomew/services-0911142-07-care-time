"""日记级与家庭日级测量：钟表时间、并行强度、接收端与提供端分离。

口径要点：
- 一切日内测量只落在填报覆盖窗口 [observed_start, observed_stop) 内；
  未观测时段是“未观测”，不视为休息，也不计为零活动。
- 钟表时间为活动区间的并集；填报分钟为各活动直接相加，可因并行超过窗口长度。
- 跨午夜活动（stop 超过日记日终点 day_start+1440）归属于起始日记：窗口内部分正常计入，
  超出部分记为 cross_midnight，只进入折算负担与填报分钟，不进入当日钟表时间，
  也不计入任何其他日记，因此不会重复。
- 覆盖窗口之前记录的活动部分记为 before_window，仅作资料质量提示，不进入任何测量。
"""
from .intervals import concurrency_segments, distinct_concurrency_segments, union_length

KINDS = ("primary", "secondary", "standby")
DAY_MINUTES = 1440


def diary_base_measures(diary, activities):
    """与折算系数无关的日记级测量。"""
    start = diary["observed_start"]
    stop = diary["observed_stop"]
    day_end = diary["day_start"] + DAY_MINUTES
    clipped = []
    kind_minutes = {kind: 0.0 for kind in KINDS}
    tail_minutes = {kind: 0.0 for kind in KINDS}
    task_minutes = {}
    before_window = 0.0
    reported = 0.0
    recipient_intervals = {}
    for activity in activities:
        a_start = activity["start"]
        a_stop = activity["stop"]
        kind = activity["kind"]
        reported += a_stop - a_start
        if a_stop > day_end:
            tail_minutes[kind] += a_stop - max(a_start, day_end)
        if a_start < start:
            before_window += min(a_stop, start) - a_start
        low = max(a_start, start)
        high = min(a_stop, stop)
        if high <= low:
            continue
        clipped.append((low, high))
        kind_minutes[kind] += high - low
        task = activity["task"]
        task_minutes[task] = task_minutes.get(task, 0.0) + (high - low)
        recipient_intervals.setdefault(activity["recipient"], []).append((low, high))
    segments = concurrency_segments(clipped)
    recipient_segments = distinct_concurrency_segments(
        [(low, high, recipient) for recipient, intervals in recipient_intervals.items() for low, high in intervals])
    return {
        "coverage_minutes": stop - start,
        "clock_minutes": union_length(clipped),
        "reported_minutes": reported,
        "kind_minutes": kind_minutes,
        "tail_minutes": tail_minutes,
        "cross_midnight_minutes": sum(tail_minutes.values()),
        "before_window_minutes": before_window,
        "task_minutes": task_minutes,
        "concurrent_minutes": sum(high - low for low, high, count in segments if count >= 2),
        "max_concurrency": max((count for _, _, count in segments), default=0),
        "multi_recipient_minutes": sum(high - low for low, high, count in recipient_segments if count >= 2),
    }


def equivalent_load(base, factors):
    """折算负担：各角色分钟按系数折算，跨午夜延续计入起始日记。

    并行活动被分别折算，因此折算负担可以超过钟表时间，这正是强度的含义。
    """
    return (sum(factors[kind] * base["kind_minutes"][kind] for kind in KINDS)
            + sum(factors[kind] * base["tail_minutes"][kind] for kind in KINDS))


def received_base_measures(day_diaries):
    """同一家庭同一日期类型的接收端测量，与提供端时间负担分开。

    day_diaries 为 [(diary, activities)]。返回每个接收者的：
    - received_clock_minutes：接收照护的钟表时间（跨提供者并集）；
    - received_person_minutes：提供者人时合计（含跨午夜延续，归属起始日记）；
    - double_coverage_minutes：两名及以上提供者同时照护同一接收者的分钟；
    - segments：(start, stop, 提供者数) 段，供时间轴绘制核对。
    """
    per_recipient = {}
    for diary, activities in day_diaries:
        start = diary["observed_start"]
        stop = diary["observed_stop"]
        day_end = diary["day_start"] + DAY_MINUTES
        provider = diary["provider"]
        for activity in activities:
            recipient = activity["recipient"]
            entry = per_recipient.setdefault(recipient, {"intervals": [], "person_minutes": 0.0, "providers": set()})
            entry["providers"].add(provider)
            if activity["stop"] > day_end:
                entry["person_minutes"] += activity["stop"] - max(activity["start"], day_end)
            low = max(activity["start"], start)
            high = min(activity["stop"], stop)
            if high <= low:
                continue
            entry["intervals"].append((low, high, provider))
            entry["person_minutes"] += high - low
    result = {}
    for recipient, entry in per_recipient.items():
        segments = distinct_concurrency_segments(entry["intervals"])
        result[recipient] = {
            "received_clock_minutes": union_length([(low, high) for low, high, _ in entry["intervals"]]),
            "received_person_minutes": entry["person_minutes"],
            "double_coverage_minutes": sum(high - low for low, high, count in segments if count >= 2),
            "providers": sorted(entry["providers"]),
            "segments": segments,
        }
    return result
