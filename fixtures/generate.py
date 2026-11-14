"""生成演示用虚构数据：保留设计骨架与边界形态，加入户间变异。

用法：python3 fixtures/generate.py（重写 fixtures/data.json）。

骨架与原版一致：64户（H00–H63），每户两名提供者、工作日与周末各一篇日记；
stratum=S{i%4}，psu=S{i%4}-B{(i//4)//2}，权重按 [1.0,1.5,2.0,2.5,3.0][i%5]；
i%13==0 的户为半天日记（覆盖480–1440），i%9==0 的户为代填；design 为5个工作日+2个周末日。
边界形态全部保留：跨午夜活动、覆盖窗口前的记录、同一接收者被两名家属同时照护、
一人同时照看老人和孩子。户级照护需求为对数正态随机效应，区域影响老人/孩子照护构成，
周末照护略重，使周负担分布、群体差异与不确定性在演示中可见。
数据为独立生成的虚构记录，不含真实家庭信息。
"""
import json
import random
from pathlib import Path

DAY = 1440
WEIGHTS = [1.0, 1.5, 2.0, 2.5, 3.0]
SEED = 20261114


def episode(start, duration, kind, recipient, task):
    # 老人照护活动系统性地更长，使区域构成差异传导到总负担。
    duration *= 1.4 if recipient.endswith("elder") else 0.9
    return {"start": round(start), "stop": round(start + duration),
            "kind": kind, "recipient": recipient, "task": task}


def household_day(rng, household, area, need, day_type):
    """生成一户一天的照护事件并分配给两名提供者，返回 (events, owners)。

    events 为 (episode, role)，role 用于联合照护的归属安排。
    """
    elder_probability = 0.62 if area == "village" else 0.38
    recipients = {"elder": household + "-elder", "child": household + "-child"}

    def recipient():
        return recipients["elder" if rng.random() < elder_probability else "child"]

    events = []
    meal_start = rng.gauss(420, 45)
    first = recipient()
    second = recipients["child" if first.endswith("elder") else "elder"]
    events.append((episode(meal_start, rng.uniform(30, 90) * need, "primary", first, "meal"), "meal"))
    events.append((episode(meal_start + rng.uniform(15, 45), rng.uniform(40, 100) * need,
                           "secondary", second, "supervision"), "watch"))
    if rng.random() < 0.65:
        events.append((episode(rng.gauss(600, 60), rng.uniform(30, 90), "primary", recipient(), "clean"), "clean"))
    events.append((episode(rng.gauss(1080, 90), rng.uniform(60, 200) * need, "standby", recipient(), "waiting"), "wait"))
    evening_start = rng.gauss(1350, 30)
    evening_recipient = recipient()
    events.append((episode(evening_start, rng.uniform(60, 160) * need, "primary", evening_recipient, "meal"), "evening"))
    if rng.random() < 0.55:
        joint_start = evening_start + rng.uniform(0, 30)
        events.append((episode(joint_start, rng.uniform(30, 90), "secondary", evening_recipient, "supervision"), "joint"))
    if day_type == "weekend":
        events.append((episode(rng.gauss(720, 60), rng.uniform(45, 120) * need, "primary", recipient(), "meal"), "midday"))
    share = rng.uniform(0.55, 0.75)
    owners = ["P0" if rng.random() < share else "P1" for _ in events]
    roles = [role for _, role in events]
    if "joint" in roles and "evening" in roles:
        # 联合照护固定由另一名提供者承担，形成跨提供者同接收者并行。
        owners[roles.index("joint")] = "P1" if owners[roles.index("evening")] == "P0" else "P0"
    if "P0" not in owners:
        owners[0] = "P0"
    if "P1" not in owners:
        owners[1] = "P1"
    return [event for event, _ in events], owners


def generate():
    rng = random.Random(SEED)
    diaries, activities, design = [], [], []
    for i in range(64):
        household = "H{:02d}".format(i)
        stratum = "S{}".format(i % 4)
        psu = "{}-B{}".format(stratum, (i // 4) // 2)
        weight = WEIGHTS[i % 5]
        area = "village" if i % 2 == 0 else "town"
        partial = i % 13 == 0
        proxy = i % 9 == 0
        need = rng.lognormvariate(0, 0.3)
        design.append({"household": household, "workday_factor": 5, "weekend_factor": 2,
                       "sampling_unit": "household"})
        for day_type in ("weekday", "weekend"):
            episodes, owners = household_day(rng, household, area, need, day_type)
            for provider_index, provider in enumerate(("P0", "P1")):
                diary_id = "{}-{}-{}".format(household, day_type, provider_index)
                diaries.append({"diary": diary_id, "household": household,
                                "provider": "{}-{}".format(household, provider),
                                "day_type": day_type, "area": area, "day_start": 0,
                                "observed_start": 480 if partial else 0,
                                "observed_stop": DAY, "proxy": proxy,
                                "weight": weight, "stratum": stratum, "psu": psu})
                count = 0
                for event, owner in zip(episodes, owners):
                    if owner != provider:
                        continue
                    activities.append({"activity": "{}-{}".format(diary_id, count), "diary": diary_id, **event})
                    count += 1
    return {"diaries": diaries, "activities": activities, "design": design}


def main():
    data = generate()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from care_time.domain import validate
    validate(data)
    path = Path(__file__).resolve().parent / "data.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("已生成 {}：{}篇日记，{}条活动，{}户".format(
        path, len(data["diaries"]), len(data["activities"]), len(data["design"])))


if __name__ == "__main__":
    main()
