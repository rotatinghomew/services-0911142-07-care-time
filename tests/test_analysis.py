from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import json
import unittest

from care_time.domain import analyze, explore, household_timeline, validate_caliber
from care_time.estimate import survey_rows, weekly_households
from care_time.intervals import (concurrency_segments, distinct_concurrency_segments,
                                 union_length)
from care_time.measures import diary_base_measures, equivalent_load, received_base_measures
from care_time.service import Workbench
from care_time.server import make_server


ROOT = Path(__file__).resolve().parents[1]
FACTORS = {"primary": 1.0, "secondary": 0.5, "standby": 0.25}


def diary(identifier, **overrides):
    row = {"diary": identifier, "household": "H1", "provider": "H1-P0", "day_type": "weekday",
           "area": "town", "day_start": 0, "observed_start": 0, "observed_stop": 1440,
           "proxy": False, "weight": 1.0, "stratum": "S1", "psu": "S1-A"}
    row.update(overrides)
    return row


def activity(identifier, start, stop, kind="primary", recipient="H1-elder", task="meal"):
    return {"activity": identifier, "diary": "d1", "start": start, "stop": stop,
            "kind": kind, "recipient": recipient, "task": task}


class IntervalTests(unittest.TestCase):
    def test_union_counts_overlap_once(self):
        self.assertEqual(union_length([(0, 100), (50, 150), (200, 300)]), 250)
        self.assertEqual(union_length([]), 0)
        self.assertEqual(union_length([(10, 10)]), 0)

    def test_concurrency_segments(self):
        segments = concurrency_segments([(0, 100), (50, 150)])
        self.assertEqual(segments, [(0, 50, 1), (50, 100, 2), (100, 150, 1)])
        touching = concurrency_segments([(0, 60), (60, 120)])
        self.assertTrue(all(count == 1 for _, _, count in touching))

    def test_distinct_tags_count_providers_not_intervals(self):
        segments = distinct_concurrency_segments([(0, 100, "P0"), (20, 80, "P0"), (50, 150, "P1")])
        double = sum(stop - start for start, stop, count in segments if count >= 2)
        self.assertEqual(double, 50)


class DiaryMeasureTests(unittest.TestCase):
    def test_clock_time_is_union_not_sum(self):
        base = diary_base_measures(diary("d1"), [activity("a1", 0, 600), activity("a2", 300, 900, kind="secondary")])
        self.assertEqual(base["clock_minutes"], 900)
        self.assertEqual(base["reported_minutes"], 1200)
        self.assertEqual(base["concurrent_minutes"], 300)
        self.assertEqual(base["max_concurrency"], 2)

    def test_equivalent_load_reflects_intensity(self):
        base = diary_base_measures(diary("d1"), [activity("a1", 0, 600), activity("a2", 300, 900, kind="secondary")])
        self.assertEqual(equivalent_load(base, FACTORS), 600 + 600 * 0.5)

    def test_cross_midnight_tail_counted_once_in_load_not_in_clock(self):
        base = diary_base_measures(diary("d1"), [activity("a1", 1380, 1500)])
        self.assertEqual(base["clock_minutes"], 60)
        self.assertEqual(base["cross_midnight_minutes"], 60)
        self.assertEqual(base["reported_minutes"], 120)
        self.assertEqual(equivalent_load(base, FACTORS), 120)

    def test_unfilled_time_is_not_rest(self):
        partial = diary("d1", observed_start=480, observed_stop=1440)
        base = diary_base_measures(partial, [activity("a1", 480, 600)])
        self.assertEqual(base["coverage_minutes"], 960)
        self.assertEqual(base["clock_minutes"], 120)
        self.assertLessEqual(base["clock_minutes"], base["coverage_minutes"])

    def test_before_window_record_is_quality_note_only(self):
        partial = diary("d1", observed_start=480, observed_stop=1440)
        base = diary_base_measures(partial, [activity("a1", 420, 510)])
        self.assertEqual(base["clock_minutes"], 30)
        self.assertEqual(base["before_window_minutes"], 60)
        self.assertEqual(base["reported_minutes"], 90)

    def test_one_person_two_recipients_is_intensity(self):
        base = diary_base_measures(diary("d1"), [
            activity("a1", 0, 600, recipient="H1-child"),
            activity("a2", 300, 900, kind="secondary", recipient="H1-elder", task="supervision")])
        self.assertEqual(base["multi_recipient_minutes"], 300)


class ReceivedSideTests(unittest.TestCase):
    def test_received_and_provider_sides_differ(self):
        first = diary("d1", provider="H1-P0")
        second = diary("d2", provider="H1-P1")
        acts_first = [{**activity("a1", 0, 600), "diary": "d1"}]
        acts_second = [{**activity("a2", 300, 900), "diary": "d2"}]
        received = received_base_measures([(first, acts_first), (second, acts_second)])
        measure = received["H1-elder"]
        self.assertEqual(measure["received_clock_minutes"], 900)
        self.assertEqual(measure["received_person_minutes"], 1200)
        self.assertEqual(measure["double_coverage_minutes"], 300)
        self.assertEqual(measure["providers"], ["H1-P0", "H1-P1"])


def tiny_dataset():
    """4户2层4 PSU；每户1名提供者、工作日周末各一篇全覆盖日记。"""
    specs = {"H1": ("S1", "S1-A", 1.0, "town", 600, 120),
             "H2": ("S1", "S1-B", 2.0, "village", 480, 240),
             "H3": ("S2", "S2-A", 1.0, "town", 600, 120),
             "H4": ("S2", "S2-B", 2.0, "village", 720, 360)}
    data = {"diaries": [], "activities": [], "design": []}
    for household, (stratum, psu, weight, area, weekday, weekend) in specs.items():
        data["design"].append({"household": household, "workday_factor": 5,
                               "weekend_factor": 2, "sampling_unit": "household"})
        for day_type, minutes in (("weekday", weekday), ("weekend", weekend)):
            identifier = "{}-{}".format(household, day_type)
            data["diaries"].append({"diary": identifier, "household": household,
                                    "provider": household + "-P0", "day_type": day_type, "area": area,
                                    "day_start": 0, "observed_start": 0, "observed_stop": 1440,
                                    "proxy": False, "weight": weight, "stratum": stratum, "psu": psu})
            data["activities"].append({"activity": identifier + "-0", "diary": identifier,
                                       "start": 0, "stop": minutes, "kind": "primary",
                                       "recipient": household + "-elder", "task": "meal"})
            data["activities"].append({"activity": identifier + "-1", "diary": identifier,
                                       "start": 0, "stop": 60, "kind": "secondary",
                                       "recipient": household + "-child", "task": "supervision"})
            data["activities"].append({"activity": identifier + "-2", "diary": identifier,
                                       "start": 30, "stop": 60, "kind": "standby",
                                       "recipient": household + "-elder", "task": "waiting"})
    return data


def tiny_caliber(**overrides):
    caliber = {"factors": dict(FACTORS), "partial": "exclude", "proxy": "include",
               "group_by": "area", "sensitivity": {"secondary": [0.5], "standby": [0.25]}}
    caliber.update(overrides)
    return caliber


class WeeklyEstimationTests(unittest.TestCase):
    def setUp(self):
        self.data = tiny_dataset()
        self.selection = {"day_type": "all", "area": "all"}

    def weekly(self, household):
        result = analyze(self.data, self.selection, tiny_caliber())
        return {row["household"]: row for row in result["providers"]}[household]

    def test_week_uses_design_factors_not_return_counts(self):
        # H1：5×600＋2×120＝3240；按回收份数混算会得到 (600+120)/2×7＝2520。
        self.assertEqual(self.weekly("H1")["weekly_clock"], 3240)
        self.assertNotEqual(self.weekly("H1")["weekly_clock"], 2520)
        self.assertEqual(self.weekly("H4")["weekly_clock"], 4320)

    def test_weighted_mean_and_group_difference(self):
        result = analyze(self.data, self.selection, tiny_caliber())
        # 时钟每周户均：(1×3240＋2×2880＋1×3240＋2×4320)/6＝3480。
        self.assertAlmostEqual(result["weekly"]["clock"]["estimate"], 3480.0)
        self.assertGreater(result["weekly"]["clock"]["se"], 0)
        difference = result["groups"]["clock_difference"]
        # town 两组均为 3240；village 加权 (2880×2＋4320×2)/4＝3600。
        self.assertAlmostEqual(difference["estimate"], 3240.0 - 3600.0)
        self.assertLessEqual(difference["ci"][0], difference["estimate"])
        self.assertLessEqual(difference["estimate"], difference["ci"][1])

    def test_quantiles_are_weighted(self):
        result = analyze(self.data, self.selection, tiny_caliber())
        quantiles = result["weekly"]["quantiles_clock"]
        self.assertEqual(quantiles["0.5"], 3240.0)
        self.assertLessEqual(quantiles["0.1"], quantiles["0.9"])

    def test_partial_exclude_then_scale(self):
        self.data["diaries"][0]["observed_stop"] = 720  # H1 工作日只覆盖上午半天
        excluded = analyze(self.data, self.selection, tiny_caliber())
        self.assertEqual(excluded["coverage"]["dropped_partial"], 1)
        self.assertEqual(excluded["coverage"]["households_incomplete"], 1)
        self.assertNotIn("H1", {row["household"] for row in excluded["providers"]})
        scaled = analyze(self.data, self.selection, tiny_caliber(partial="scale"))
        self.assertEqual(scaled["coverage"]["households_incomplete"], 0)
        # 覆盖720分钟、钟表600分钟的工作日按 1440/720 放大为1200。
        self.assertEqual(self.weekly_scaled(scaled, "H1"), 5 * 1200 + 2 * 120)

    def weekly_scaled(self, result, household):
        return {row["household"]: row for row in result["providers"]}[household]["weekly_clock"]

    def test_proxy_exclude_removes_diaries(self):
        for row in self.data["diaries"]:
            if row["household"] == "H2":
                row["proxy"] = True
        result = analyze(self.data, self.selection, tiny_caliber(proxy="exclude"))
        self.assertEqual(result["coverage"]["dropped_proxy"], 2)
        self.assertNotIn("H2", {row["household"] for row in result["providers"]})

    def test_area_selection_is_domain_estimation(self):
        result = analyze(self.data, {"day_type": "all", "area": "town"}, tiny_caliber())
        self.assertEqual(result["coverage"]["households_total"], 2)
        self.assertTrue(all(row["area"] == "town" for row in result["providers"]))
        self.assertIsNone(result["groups"]["clock_difference"])

    def test_day_type_selection_does_not_change_weekly_estimate(self):
        baseline = analyze(self.data, self.selection, tiny_caliber())
        filtered = analyze(self.data, {"day_type": "weekday", "area": "all"}, tiny_caliber())
        self.assertEqual(baseline["weekly"]["clock"], filtered["weekly"]["clock"])
        self.assertTrue(any("日期类型" in note for note in filtered["notes"]))

    def test_sensitivity_grid_moves_load_not_clock(self):
        caliber = tiny_caliber(sensitivity={"secondary": [0.0, 1.0], "standby": [0.0, 0.5]})
        result = analyze(self.data, self.selection, caliber)
        sensitivity = result["sensitivity"]
        self.assertEqual(len(sensitivity["cells"]), 4)
        means = {cell["standby"]: cell["mean"] for cell in sensitivity["cells"] if cell["secondary"] == 1.0}
        self.assertGreater(means[0.5], means[0.0])
        self.assertFalse(sensitivity["difference_sign_change"])
        clock_estimate = result["weekly"]["clock"]["estimate"]
        self.assertAlmostEqual(clock_estimate, 3480.0)

    def test_analysis_is_deterministic(self):
        first = analyze(self.data, self.selection, tiny_caliber())
        second = analyze(self.data, self.selection, tiny_caliber())
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_missing_design_row_rejected(self):
        del self.data["design"][0]
        with self.assertRaises(ValueError):
            analyze(self.data, self.selection, tiny_caliber())


class CaliberTests(unittest.TestCase):
    def test_defaults_fill_in(self):
        caliber = validate_caliber({"factors": dict(FACTORS)})
        self.assertEqual(caliber["partial"], "exclude")
        self.assertEqual(caliber["proxy"], "include")
        self.assertEqual(caliber["sensitivity"]["secondary"], [0.5])

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            validate_caliber({"factors": dict(FACTORS), "factors_typo": {}})

    def test_factor_bounds(self):
        with self.assertRaises(ValueError):
            validate_caliber({"factors": {"primary": 1.0, "secondary": 2.5, "standby": 0.1}})
        with self.assertRaises(ValueError):
            validate_caliber({"factors": {"primary": 1.0, "secondary": 0.5}})

    def test_enum_and_grid_validation(self):
        with self.assertRaises(ValueError):
            validate_caliber({"factors": dict(FACTORS), "partial": "skip"})
        with self.assertRaises(ValueError):
            validate_caliber({"factors": dict(FACTORS), "sensitivity": {"secondary": []}})
        with self.assertRaises(ValueError):
            validate_caliber({"factors": dict(FACTORS), "sensitivity": {"primary": [1.0]}})


class FixtureAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "fixtures" / "data.json").read_text())
        self.product = json.loads((ROOT / "product.json").read_text())

    def test_fixture_analysis_is_serializable(self):
        result = analyze(self.data, self.product["selection"], self.product["caliber"])
        json.dumps(result, allow_nan=False)
        self.assertTrue(result["diaries"])
        self.assertTrue(result["providers"])
        self.assertTrue(result["recipients"])
        self.assertTrue(result["notes"])

    def test_fixture_shows_receiver_provider_gap(self):
        result = analyze(self.data, self.product["selection"], self.product["caliber"])
        for row in result["recipients"]:
            self.assertLessEqual(row["weekly_received_clock"], row["weekly_received_person"])
        self.assertTrue(any(row["weekly_double_coverage"] > 0 for row in result["recipients"]))

    def test_explore_view_unchanged_by_analysis(self):
        before = explore(self.data, self.product["selection"])
        analyze(self.data, self.product["selection"], self.product["caliber"])
        after = explore(self.data, self.product["selection"])
        self.assertEqual(before, after)

    def test_household_timeline_has_raw_and_received(self):
        timeline = household_timeline(self.data, "H01")
        self.assertEqual({day["day_type"] for day in timeline["days"]}, {"weekday", "weekend"})
        for day in timeline["days"]:
            self.assertTrue(day["diaries"])
            self.assertTrue(day["recipients"])
            for recipient in day["recipients"]:
                self.assertTrue(recipient["segments"])
        with self.assertRaises(LookupError):
            household_timeline(self.data, "不存在")


class ReproducibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workbench = Workbench(ROOT, self.temporary.name)
        self.caliber = json.loads((ROOT / "product.json").read_text())["caliber"]

    def test_saved_analysis_reproduces_under_same_caliber(self):
        saved = self.workbench.save({"title": "口径留痕", "caliber": self.caliber})
        self.assertIn("analysis", saved["result"])
        reopened = self.workbench.store.notebook(saved["id"])
        self.assertEqual(reopened["result"]["analysis"], saved["result"]["analysis"])
        recomputed = self.workbench.analyze({"revision": saved["revision"], "caliber": self.caliber})
        self.assertEqual(recomputed["analysis"], saved["result"]["analysis"])

    def test_old_record_keeps_original_allocation_after_caliber_change(self):
        saved = self.workbench.save({"title": "原口径", "caliber": self.caliber})
        changed = deepcopy(self.caliber)
        changed["factors"]["secondary"] = 1.0
        newer = self.workbench.analyze({"revision": saved["revision"], "caliber": changed})
        self.assertNotEqual(newer["analysis"]["weekly"]["load"]["estimate"],
                            saved["result"]["analysis"]["weekly"]["load"]["estimate"])
        reopened = self.workbench.store.notebook(saved["id"])
        self.assertEqual(reopened["result"]["analysis"]["weekly"]["load"],
                         saved["result"]["analysis"]["weekly"]["load"])
        self.assertEqual(reopened["result"]["caliber"]["factors"]["secondary"], 0.5)

    def test_notebook_without_caliber_still_opens(self):
        saved = self.workbench.save({"title": "旧记录"})
        self.assertNotIn("analysis", saved["result"])
        reopened = self.workbench.store.notebook(saved["id"])
        self.assertEqual(reopened["result"], saved["result"])

    def test_invalid_caliber_returns_client_error(self):
        with self.assertRaises(ValueError):
            self.workbench.analyze({"caliber": {"factors": {"primary": 9}}})

    def test_analyze_does_not_mutate_dataset(self):
        data = self.workbench.store.dataset(self.workbench.default_revision)
        before = deepcopy(data)
        self.workbench.analyze({"caliber": self.caliber})
        self.assertEqual(data, before)


class AnalysisHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.server = make_server(ROOT, self.temporary.name, port=0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temporary.cleanup()

    def post(self, path, payload):
        request = Request(self.base + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        return urlopen(request)

    def test_analyze_endpoint(self):
        with self.post("/api/analyze", {}) as response:
            body = json.load(response)
        self.assertIn("analysis", body)
        self.assertEqual(body["caliber"], body["analysis"]["caliber"])
        self.assertTrue(body["analysis"]["weekly"]["clock"]["ci"])

    def test_analyze_rejects_bad_caliber(self):
        with self.assertRaises(HTTPError) as caught:
            self.post("/api/analyze", {"caliber": {"factors": {"primary": 1, "secondary": 0.5, "standby": 0.25},
                                                   "partial": "丢掉"}})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_household_endpoint(self):
        with urlopen(self.base + "/api/household?household=H01") as response:
            body = json.load(response)
        self.assertEqual(body["timeline"]["household"], "H01")
        self.assertTrue(body["timeline"]["days"])
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/api/household?household=" + quote("不存在"))
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_save_with_caliber_freezes_analysis(self):
        caliber = json.loads((ROOT / "product.json").read_text())["caliber"]
        with self.post("/api/notebooks", {"title": "含口径", "caliber": caliber}) as response:
            saved = json.load(response)
        self.assertIn("analysis", saved["result"])
        with urlopen(self.base + "/api/notebooks/" + str(saved["id"])) as response:
            self.assertEqual(json.load(response), saved)


if __name__ == "__main__":
    unittest.main()
