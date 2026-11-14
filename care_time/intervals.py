"""区间运算：钟表时间与并行强度的公共基础。

所有区间为左闭右开 [start, stop)，单位为日记日分钟。
"""


def clip_length(start, stop, low, high):
    """单个区间与 [low, high) 的交集长度，不交集为 0。"""
    return max(0, min(stop, high) - max(start, low))


def union_length(intervals):
    """区间并集的总长度，重叠部分只计一次。"""
    total = 0
    current_start = None
    current_stop = None
    for start, stop in sorted(intervals):
        if stop <= start:
            continue
        if current_start is None:
            current_start, current_stop = start, stop
        elif start > current_stop:
            total += current_stop - current_start
            current_start, current_stop = start, stop
        else:
            current_stop = max(current_stop, stop)
    if current_start is None:
        return 0
    return total + current_stop - current_start


def concurrency_segments(intervals):
    """把区间集合扫成 (start, stop, count) 段，count 为段内同时进行的区间数。"""
    events = []
    for start, stop in intervals:
        if stop <= start:
            continue
        events.append((start, 1))
        events.append((stop, -1))
    events.sort()
    segments = []
    active = 0
    previous = None
    for point, delta in events:
        if previous is not None and point > previous and active > 0:
            segments.append((previous, point, active))
        active += delta
        previous = point
    return segments


def distinct_concurrency_segments(tagged_intervals):
    """tagged_intervals 为 (start, stop, tag)；段内 count 为同时活跃的不同 tag 数。"""
    events = []
    for start, stop, tag in tagged_intervals:
        if stop <= start:
            continue
        events.append((start, tag, 1))
        events.append((stop, tag, -1))
    events.sort(key=lambda event: event[0])
    segments = []
    active = {}
    previous = None
    for point, tag, delta in events:
        if previous is not None and point > previous and active:
            segments.append((previous, point, len(active)))
        remaining = active.get(tag, 0) + delta
        if remaining > 0:
            active[tag] = remaining
        else:
            active.pop(tag, None)
        previous = point
    return segments
