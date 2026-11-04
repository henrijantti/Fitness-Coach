import datetime, json, pathlib
import pytest
import pull_garmin as pg


# ---------- fixtures: raw shapes as the Garmin Connect API returns them ----------

STATS = {"calendarDate": "2026-09-19", "totalSteps": 10432, "restingHeartRate": 52, "minHeartRate": 47,
         "averageStressLevel": 24, "bodyBatteryHighestValue": 88, "bodyBatteryLowestValue": 21,
         "sleepingSeconds": 26520}
HRV = {"hrvSummary": {"calendarDate": "2026-09-19", "weeklyAvg": 58, "lastNightAvg": 61,
                      "lastNight5MinHigh": 84, "status": "BALANCED",
                      "baseline": {"lowUpper": 50, "balancedLow": 55, "balancedUpper": 70}},
       "hrvReadings": []}
SLEEP = {"dailySleepDTO": {"calendarDate": "2026-09-19", "sleepTimeSeconds": 26520, "deepSleepSeconds": 5400,
                           "lightSleepSeconds": 14400, "remSleepSeconds": 6720, "awakeSleepSeconds": 900,
                           "sleepScores": {"overall": {"value": 81, "qualifierKey": "GOOD"}},
                           "restingHeartRate": 51}}
RUN = {"activityId": 123, "activityName": "Helsinki Running", "startTimeLocal": "2026-09-19 07:12:00",
       "activityType": {"typeKey": "running"}, "distance": 5120.0, "duration": 1536.0, "movingDuration": 1520.0,
       "averageSpeed": 3.333, "averageHR": 152, "maxHR": 171, "averageRunningCadenceInStepsPerMinute": 172.0}
GYM = {"activityId": 124, "activityName": "Strength", "startTimeLocal": "2026-09-19 17:00:00",
       "activityType": {"typeKey": "strength_training"}, "distance": 0.0, "duration": 3300.0, "averageHR": 101}


def test_parse_day_full_fixture():
    row = pg.parse_day("2026-09-19", STATS, HRV, SLEEP)
    assert row["date"] == "2026-09-19"
    assert row["rhr"] == 52 and row["hrv_night"] == 61 and row["hrv_weekly"] == 58
    assert row["hrv_status"] == "BALANCED"
    assert row["sleep_h"] == 7.37 and row["deep_h"] == 1.5 and row["light_h"] == 4.0
    assert row["rem_h"] == 1.87 and row["awake_h"] == 0.25 and row["sleep_score"] == 81
    assert row["bb_high"] == 88 and row["bb_low"] == 21 and row["stress_avg"] == 24 and row["steps"] == 10432


def test_parse_day_respiration_and_readiness():
    resp = {"avgSleepRespirationValue": 14.0, "avgWakingRespirationValue": 13.0}
    readiness = [{"score": 84, "level": "HIGH", "acuteLoad": 159, "sleepScore": 85}]
    row = pg.parse_day("2026-09-21", STATS, HRV, SLEEP, resp, readiness)
    assert row["resp_sleep"] == 14.0 and row["resp_wake"] == 13.0
    assert row["readiness"] == 84 and row["readiness_level"] == "HIGH" and row["acute_load"] == 159
    bare = pg.parse_day("2026-09-21", STATS, HRV, SLEEP)                  # old call shape still works
    assert bare["resp_sleep"] is None and bare["readiness"] is None
    assert pg.parse_day("2026-09-21", {}, {}, {}, None, [{}])["readiness"] is None


def test_parse_activity_training_effect_and_load():
    a = pg.parse_activity(dict(RUN, aerobicTrainingEffect=3.0999, anaerobicTrainingEffect=3.4, activityTrainingLoad=169.98))
    assert a["te_aer"] == 3.1 and a["te_anaer"] == 3.4 and a["load"] == 170
    assert pg.parse_activity(RUN)["load"] is None


def test_parse_fitness_row():
    blob = {"training_status": {"mostRecentVO2Max": {"generic": {"calendarDate": "2026-09-18", "vo2MaxPreciseValue": 49.4, "vo2MaxValue": 49.0}}},
            "race_predictions": {"time5K": 1502, "time10K": 3230, "timeHalfMarathon": 7440, "calendarDate": "2026-09-21"},
            "lactate_threshold": {"speed_and_heart_rate": {"heartRate": 157, "calendarDate": "2026-09-18T09:10:52.156"}}}
    r = pg.parse_fitness("2026-09-21", blob)
    assert list(r) == pg.GARMIN_FITNESS_COLUMNS
    assert {k: r[k] for k in pg.GARMIN_FITNESS_COLUMNS[:8]} == {
        "date": "2026-09-21", "vo2max": 49.4, "vo2max_date": "2026-09-18", "pred_5k": "25:02",
        "pred_10k": "53:50", "pred_hm": "2:04:00", "lt_hr": 157, "lt_date": "2026-09-18"}
    assert all(r[k] is None for k in pg.GARMIN_FITNESS_COLUMNS[8:])     # no training status in this reply
    empty = pg.parse_fitness("2026-09-22", None)
    assert empty["vo2max"] is None and empty["pred_5k"] is None and empty["lt_hr"] is None


# training_status as it came on 2026-09-27 (the real file): the status and load focus sit under device ids
TRAINING_STATUS = {
    "mostRecentTrainingStatus": {"latestTrainingStatusData": {"3646635127": {
        "sinceDate": "2026-09-26", "trainingStatusFeedbackPhrase": "PRODUCTIVE_9", "primaryTrainingDevice": True,
        "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": 384, "dailyTrainingLoadChronic": 219,
                                 "minTrainingLoadChronic": 175.2, "maxTrainingLoadChronic": 328.5,
                                 "dailyAcuteChronicWorkloadRatio": 1.7}}}},
    "mostRecentTrainingLoadBalance": {"metricsTrainingLoadBalanceDTOMap": {"3646635127": {
        "monthlyLoadAerobicLow": 73.2, "monthlyLoadAerobicHigh": 274.0, "monthlyLoadAnaerobic": 176.7,
        "monthlyLoadAerobicLowTargetMin": 212, "monthlyLoadAerobicLowTargetMax": 475,
        "monthlyLoadAerobicHighTargetMin": 268, "monthlyLoadAerobicHighTargetMax": 531,
        "monthlyLoadAnaerobicTargetMin": 0, "monthlyLoadAnaerobicTargetMax": 262,
        "trainingBalanceFeedbackPhrase": "AEROBIC_LOW_SHORTAGE", "primaryTrainingDevice": True}}}}


def test_parse_fitness_training_status_and_load_focus():
    r = pg.parse_fitness("2026-09-27", {"training_status": TRAINING_STATUS})
    assert {k: r[k] for k in pg.GARMIN_FITNESS_COLUMNS[8:]} == {
        "status": "PRODUCTIVE_9", "status_since": "2026-09-26", "load_acute": 384, "load_chronic": 219,
        "load_lo": 175.2, "load_hi": 328.5, "acwr": 1.7, "balance": "AEROBIC_LOW_SHORTAGE",
        "anaer": 176.7, "anaer_lo": 0, "anaer_hi": 262, "aer_hi": 274.0, "aer_hi_lo": 268, "aer_hi_hi": 531,
        "aer_lo": 73.2, "aer_lo_lo": 212, "aer_lo_hi": 475}
    # no device marked primary: the first entry
    two = {"mostRecentTrainingStatus": {"latestTrainingStatusData": {
        "1": {"trainingStatusFeedbackPhrase": "MAINTAINING_1"}, "2": {"trainingStatusFeedbackPhrase": "RECOVERY_2"}}}}
    assert pg.parse_fitness("2026-09-27", {"training_status": two})["status"] == "MAINTAINING_1"


def test_parse_day_recovery_time_and_hrv_baseline():
    # 2026-09-26 after a race synced: Garmin lists readiness newest first, so the workout's
    # AFTER_POST_EXERCISE_RESET entry (58 h) sits before the morning's AFTER_WAKEUP_RESET one (35 h).
    readiness = [{"inputContext": "AFTER_POST_EXERCISE_RESET", "score": 1, "level": "POOR", "recoveryTime": 3456},
                 {"inputContext": "AFTER_WAKEUP_RESET", "score": 5, "level": "POOR", "recoveryTime": 2093}]
    row = pg.parse_day("2026-09-26", STATS, HRV, SLEEP, None, readiness)
    assert row["recovery_min"] == 2093 and row["readiness"] == 1
    assert (row["hrv_lo"], row["hrv_hi"]) == (55, 70)
    # no wake-up entry (the watch was off overnight): no "this morning" value; no baseline yet: none
    row = pg.parse_day("2026-09-26", STATS, {"hrvSummary": {"status": "NONE", "baseline": None}}, SLEEP, None,
                       [{"inputContext": "AFTER_POST_EXERCISE_RESET", "score": 46, "recoveryTime": 1513}])
    assert row["recovery_min"] is None and row["hrv_lo"] is None and row["hrv_hi"] is None


def test_parse_day_tolerates_missing_blocks():
    row = pg.parse_day("2026-09-20", None, None, {})
    assert row["date"] == "2026-09-20"
    assert all(row[k] is None for k in ("rhr", "hrv_night", "hrv_status", "sleep_h", "sleep_score", "steps"))


def test_parse_day_rhr_falls_back_to_sleep_dto():
    row = pg.parse_day("2026-09-19", {}, None, SLEEP)
    assert row["rhr"] == 51


def test_parse_day_falls_back_to_sleep_top_level_keys():
    # Shape seen on the live Sep 19 pull: DTO copies null, values at the sleep payload's top level.
    sleep = {"dailySleepDTO": {"restingHeartRate": None, "avgOvernightHrv": None},
             "restingHeartRate": 51, "avgOvernightHrv": 30.0}
    row = pg.parse_day("2026-09-19", {}, {"hrvSummary": {"lastNightAvg": None}}, sleep)
    assert row["rhr"] == 51 and row["hrv_night"] == 30.0


def test_parse_activity_run():
    a = pg.parse_activity(RUN)
    assert a["date"] == "2026-09-19" and a["type"] == "running" and a["is_run"] is True
    assert a["km"] == 5.12 and a["min"] == 25.3 and a["pace"] == "4:57"
    assert a["avg_hr"] == 152 and a["max_hr"] == 171 and a["cadence"] == 172 and a["activity_id"] == 123


def test_parse_activity_non_run_has_no_pace():
    a = pg.parse_activity(GYM)
    assert a["is_run"] is False and a["pace"] is None and a["km"] == 0.0 and a["min"] == 55.0


def test_parse_activity_uses_the_timer_when_moving_time_is_zero():
    # Tue Oct 6 floorball: Field Hockey indoors, no distance, movingDuration 0.0, duration 3573 s
    a = pg.parse_activity(dict(GYM, activityType={"typeKey": "field_hockey"}, movingDuration=0.0, duration=3573.2))
    assert a["min"] == 59.6


def test_run_rollup_sums_km_and_time_weights_hr():
    second = dict(RUN, activityId=125, distance=3000.0, movingDuration=1000.0, averageHR=140,
                  startTimeLocal="2026-09-19 18:00:00")
    rows = [pg.parse_activity(x) for x in (RUN, second, GYM)]
    rr = pg.run_rollup(rows)
    assert rr == {"2026-09-19": {"run_km": 8.12, "run_n": 2, "run_avg_hr": 147}}


def test_compare_pairs_days_and_summarises_offsets():
    apple = [{"date": "2026-09-19", "rhr": 57, "hrv": 42.1, "sleep_h": 7.44, "run_km": 5.1},
             {"date": "2026-09-20", "rhr": 56, "hrv": None, "sleep_h": 8.0, "run_km": None}]
    garmin = [{"date": "2026-09-19", "rhr": 52, "hrv_night": 61, "sleep_h": 7.34, "run_km": 5.12},
              {"date": "2026-09-20", "rhr": 53, "hrv_night": 60, "sleep_h": 7.8, "run_km": None},
              {"date": "2026-09-21", "rhr": 54, "hrv_night": 59, "sleep_h": None, "run_km": None}]
    rows, summary = pg.compare(garmin, apple, datetime.date(2026, 9, 19), datetime.date(2026, 9, 21))
    assert [r["date"] for r in rows] == ["2026-09-19", "2026-09-20", "2026-09-21"]
    d19 = rows[0]
    assert d19["rhr"] == (57, 52, -5) and d19["hrv"] == (42.1, 61, 18.9)
    assert d19["sleep_h"] == (7.44, 7.34, -0.1) and d19["run_km"] == (5.1, 5.12, 0.02)
    assert rows[1]["hrv"] == (None, 60, None) and rows[1]["run_km"] == (None, None, None)
    assert rows[2]["rhr"] == (None, 54, None)          # Apple dark, Garmin present: no delta
    assert summary["rhr"] == (-4.0, 2) and summary["hrv"] == (18.9, 1)
    assert summary["sleep_h"] == (-0.15, 2) and summary["run_km"] == (0.02, 1)


def test_format_compare_mentions_hrv_scale_caveat():
    apple = [{"date": "2026-09-19", "rhr": 57, "hrv": 42.1, "sleep_h": 7.44, "run_km": 5.1}]
    garmin = [{"date": "2026-09-19", "rhr": 52, "hrv_night": 61, "sleep_h": 7.34, "run_km": 5.12}]
    rows, summary = pg.compare(garmin, apple, datetime.date(2026, 9, 19), datetime.date(2026, 9, 19))
    text = pg.format_compare(rows, summary)
    assert "2026-09-19" in text and "57" in text and "52" in text and "-5" in text
    assert "SDNN" in text and "RMSSD" in text


# ---------- from-cache build (no network) ----------

def _raw_root(tmp_path: pathlib.Path) -> pathlib.Path:
    raw = tmp_path / "data" / "garmin-raw"
    raw.mkdir(parents=True)
    (raw / "2026-09-19.json").write_text(json.dumps({"stats": STATS, "hrv": HRV, "sleep": SLEEP}), encoding="utf-8")
    (raw / "2026-09-20.json").write_text(json.dumps({"stats": dict(STATS, calendarDate="2026-09-20", restingHeartRate=53),
                                                     "hrv": None, "sleep": {}}), encoding="utf-8")
    (raw / "activities.json").write_text(json.dumps({"123": RUN, "124": GYM}), encoding="utf-8")
    (raw / "weighins.json").write_text(json.dumps({
        "2026-09-19": {"summaryDate": "2026-09-19", "numOfWeightEntries": 1,
                       "latestWeight": {"weight": 77800.0, "sourceType": "MANUAL", "calendarDate": "2026-09-19"}},
        "2026-09-18": {"summaryDate": "2026-09-18", "numOfWeightEntries": 1,
                       "latestWeight": {"weight": 78500.0, "sourceType": "USER_SETTING"}}}), encoding="utf-8")
    (raw / "fitness.json").write_text(json.dumps({"2026-09-20": {
        "training_status": {"mostRecentVO2Max": {"generic": {"calendarDate": "2026-09-18", "vo2MaxPreciseValue": 49.4}}},
        "race_predictions": {"time5K": 1502}, "lactate_threshold": {"speed_and_heart_rate": {"heartRate": 157}}}}),
        encoding="utf-8")
    (tmp_path / "data" / "daily.csv").write_text(
        "# derived\n"
        "date,weight,weight_n,rhr,hrv,sleep_h,sleep_flag,kcal,protein,run_km,run_n,gym_n,gym_min\n"
        "2026-09-19,,,57.0,42.1,7.44,,,,5.1,1,,\n"
        "2026-09-20,,,56.0,,8.0,,,,,,1,55\n", encoding="utf-8")
    return tmp_path


def test_build_from_raw_writes_both_csvs(tmp_path):
    root = _raw_root(tmp_path)
    daily, acts = pg.build_from_raw(root)
    assert [r["date"] for r in daily] == ["2026-09-19", "2026-09-20"]
    assert daily[0]["run_km"] == 5.12 and daily[0]["run_n"] == 1 and daily[0]["run_avg_hr"] == 152
    assert daily[1]["rhr"] == 53 and daily[1]["run_km"] is None
    assert daily[0]["weight"] == 77.8 and daily[0]["weight_n"] == 1 and daily[0]["weight_src"] == "MANUAL"
    assert daily[1]["weight"] is None                      # a weigh-in on a day without a day file is ignored
    assert pg.parse_weighins({"x": {"latestWeight": {}}}) == {}
    assert [a["activity_id"] for a in acts] == [123, 124]
    text = (root / "data" / "garmin-daily.csv").read_text(encoding="utf-8")
    assert text.startswith("# ") and "\n" + ",".join(pg.GARMIN_DAILY_COLUMNS) + "\n" in text
    assert "2026-09-19,52,61,58,BALANCED,7.37" in text
    acts_text = (root / "data" / "garmin-activities.csv").read_text(encoding="utf-8")
    assert "2026-09-19,2026-09-19 07:12:00,running,Helsinki Running,5.12,25.3,4:57,152,171,172,123" in acts_text
    fit_text = (root / "data" / "garmin-fitness.csv").read_text(encoding="utf-8")
    assert "\n" + ",".join(pg.GARMIN_FITNESS_COLUMNS) + "\n" in fit_text
    assert "2026-09-20,49.4,2026-09-18,25:02,,,157," in fit_text


def test_main_no_fetch_prints_comparison(tmp_path, capsys):
    root = _raw_root(tmp_path)
    rc = pg.main(["--root", str(root), "--no-fetch", "--start", "2026-09-19", "--end", "2026-09-20"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "garmin-daily.csv" in out and "2026-09-19" in out and "mean offset" in out


# ---------- activity analysis ----------

def _stream(phases):
    """phases = [(seconds, speed_mps, hr)] at 1 Hz -> Garmin details JSON shape."""
    keys = ["sumDuration", "sumDistance", "directSpeed", "directHeartRate", "directDoubleCadence",
            "directStrideLength", "directPower", "directGroundContactTime", "directVerticalOscillation"]
    rows, t, d = [], 0.0, 0.0
    for secs, v, hr in phases:
        for _ in range(secs):
            d += v
            rows.append({"metrics": [t, d, v, hr, 180.0 if v > 3 else 150.0, 140.0, 500.0, 190.0, 9.5]})
            t += 1
    return {"metricDescriptors": [{"key": k} for k in keys], "activityDetailMetrics": rows}


PHASES = [(180, 2.8, 120), (180, 4.0, 160), (120, 1.0, 110), (180, 4.0, 162), (120, 2.6, 130)]


def test_pace_helpers():
    assert pg.pace_str(1000, 250) == "4:10" and pg.pace_str(0, 10) is None
    assert abs(pg.pace_to_mps("4:42") - 3.546) < 0.001


def test_detect_reps_finds_two_hard_segments():
    cols = pg.stream_columns(_stream(PHASES))
    reps = pg.detect_reps(cols["sumDuration"], cols["sumDistance"], cols["directSpeed"], pg.pace_to_mps("4:42"))
    assert len(reps) == 2
    assert abs(reps[0][0] - 180) <= 6 and abs(reps[0][1] - 360) <= 6
    assert abs(reps[1][0] - 480) <= 6 and abs(reps[1][1] - 660) <= 6


def test_analyse_activity_reps_recovery_warmup_cooldown():
    cols = pg.stream_columns(_stream(PHASES))
    reps = pg.detect_reps(cols["sumDuration"], cols["sumDistance"], cols["directSpeed"], pg.pace_to_mps("4:42"))
    a = pg.analyse_activity(cols, reps)
    r1, r2 = a["reps"]
    assert 690 <= r1["m"] <= 740 and r1["pace"].startswith("4:1") and r1["hr_max"] == 160
    assert r1["cad"] == 180.0 and r1["stride_m"] == 1.4 and r1["power"] == 500.0
    assert len(r1["subs"]) == 3 and all(s.startswith("4:1") for s in r1["subs"])
    assert r2["hr_end"] == 162
    rec = a["recoveries"][0]
    assert 108 <= rec["s"] <= 132 and rec["hr_min"] == 110
    # the smoothed detector opens a rep ~3 s after the speed jump, so the warm-up carries a few fast seconds
    assert 480 <= a["warmup"]["m"] <= 520 and a["warmup"]["pace"] in ("5:54", "5:55", "5:56", "5:57")
    assert 130.0 <= a["cooldown"]["hr_avg"] <= 132.0          # same boundary effect at the last rep's end


def test_detect_reps_easy_run_has_none():
    cols = pg.stream_columns(_stream([(600, 2.8, 130)]))
    assert pg.detect_reps(cols["sumDuration"], cols["sumDistance"], cols["directSpeed"], pg.pace_to_mps("4:42")) == []


def _activity_root(tmp_path):
    raw = tmp_path / "data" / "garmin-raw"; raw.mkdir(parents=True)
    parts = {"summary": {"activityName": "Helsinki Running",
                         "summaryDTO": {"startTimeLocal": "2026-09-18T08:43:47.0", "distance": 2352.0, "duration": 780.0,
                                        "averageHR": 140.0, "maxHR": 162.0, "trainingEffect": 3.1,
                                        "anaerobicTrainingEffect": 3.4, "activityTrainingLoad": 170.0}},
             "splits": {"lapDTOs": [{"distance": 1000.0, "duration": 300.0, "averageHR": 130.0, "maxHR": 160.0}]},
             "typed_splits": {"splits": []},
             "hrzones": [{"zoneNumber": 1, "secsInZone": 60.0}, {"zoneNumber": 4, "secsInZone": 360.0}],
             "details": _stream(PHASES)}
    for k, v in parts.items():
        (raw / f"activity-77-{k}.json").write_text(json.dumps(v), encoding="utf-8")
    (raw / "activities.json").write_text(json.dumps({"77": dict(RUN, activityId=77)}), encoding="utf-8")
    return tmp_path


def test_report_activity_text(tmp_path):
    root = _activity_root(tmp_path)
    text = pg.report_activity(pg.load_activity_parts(root, "77"), "4:42")
    assert text.startswith("Helsinki Running · 2026-09-18T08:43:47.0 · 2.35 km · 13:00 · avg 5:32/km · HR 140/162")
    assert "LAPS:" in text and "1000 m    5:00   5:00/km  HR 130/160" in text
    assert "REPS (rolling speed faster than 4:42/km):" in text
    assert "rec " in text and "WARM-UP:" in text and "COOL-DOWN:" in text
    assert "HR ZONES (min): z1 1.0 · z4 6.0" in text


def test_main_activity_no_fetch_by_id_date_and_latest(tmp_path, capsys):
    root = _activity_root(tmp_path)
    for spec in ("77", "2026-09-19", "latest"):
        assert pg.main(["--root", str(root), "--no-fetch", "--activity", spec]) == 0
        assert "REPS (rolling speed faster than 4:42/km)" in capsys.readouterr().out
    assert pg.main(["--root", str(root), "--no-fetch", "--activity", "2026-01-01"]) == 1
    assert "no run matches" in capsys.readouterr().out



def test_activity_latest_is_the_newest_run_in_the_csv(tmp_path):
    # The cloud clone has no raw cache and the PC's stopped on Oct 19: `latest` reads the committed CSV.
    rows = [pg.parse_activity(a) for a in (RUN, GYM, RUN2)]
    pg.write_csv(tmp_path / "data" / "garmin-activities.csv", pg.GARMIN_ACTIVITY_COLUMNS, rows)
    assert pg.resolve_activity_ids("latest", tmp_path) == ["125"]
    gym_last = [dict(r, start="2026-09-30 17:00:00") if r["type"] != "running" else r for r in rows]
    pg.write_csv(tmp_path / "data" / "garmin-activities.csv", pg.GARMIN_ACTIVITY_COLUMNS, gym_last)
    assert pg.resolve_activity_ids("latest", tmp_path) == ["125"]          # a run, not the newer gym session

def test_main_activity_rep_pace_override(tmp_path, capsys):
    root = _activity_root(tmp_path)
    assert pg.main(["--root", str(root), "--no-fetch", "--activity", "77", "--rep-pace", "3:30"]) == 0
    out = capsys.readouterr().out
    assert "faster than 3:30/km" in out and "none — an easy run" in out


def test_main_no_fetch_without_cache_is_a_clean_error(tmp_path, capsys):
    (tmp_path / "data").mkdir()
    rc = pg.main(["--root", str(tmp_path), "--no-fetch"])
    assert rc == 1 and "no cached Garmin days" in capsys.readouterr().out


def test_write_csv_is_atomic(tmp_path, monkeypatch):
    # a pull killed or failing mid-write must leave the previous CSV intact and no temp file behind
    import csv as _csv
    import pull_garmin as pg
    target = tmp_path / "data" / "garmin-daily.csv"
    pg.write_csv(target, ["date", "rhr"], [{"date": "2026-09-27", "rhr": 55}], "old header")
    before = target.read_bytes()

    real = _csv.DictWriter.writerow
    calls = {"n": 0}
    def boom(self, row):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk went away")
        return real(self, row)
    monkeypatch.setattr(_csv.DictWriter, "writerow", boom)
    try:
        pg.write_csv(target, ["date", "rhr"], [{"date": "2026-09-27", "rhr": 55}, {"date": "2026-09-28", "rhr": 53}], "new")
    except OSError:
        pass
    assert target.read_bytes() == before
    assert not list(target.parent.glob("*.tmp"))


# ---------- cloud: the GARMINTOKENS secret (fake tokens only) ----------

def _jwt(payload: dict) -> str:
    import base64
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "e30." + body + ".sig"


def _exp(y, m, d, h=12):
    return int(datetime.datetime(y, m, d, h, tzinfo=datetime.timezone.utc).timestamp())


class _FakeClient:
    def __init__(self):
        self.dumps = []

    def dump(self, path):
        self.dumps.append(path)


class _FakeApi:
    """Every Garmin getter returns an empty payload; `fail` names getters that raise."""
    def __init__(self, fail=()):
        self.client = _FakeClient()
        self.fail = set(fail)

    def __getattr__(self, name):
        def getter(*a, **k):
            if name in self.fail:
                raise RuntimeError("boom")
            return []  if name == "get_activities_by_date" else {}
        return getter


def _secret(iat=None, exp=None):
    claims = {k: v for k, v in (("iat", iat), ("exp", exp)) if v is not None}
    return json.dumps({"di_token": _jwt(claims), "di_refresh_token": "opaque-refresh", "di_client_id": "c"})


def test_access_claim_date_reads_the_access_tokens_dates():
    tj = _secret(iat=_exp(2026, 10, 19), exp=_exp(2026, 10, 20))
    assert pg._access_claim_date(tj, "iat") == datetime.date(2026, 10, 19)
    assert pg._access_claim_date(tj, "exp") == datetime.date(2026, 10, 20)


def test_access_claim_date_unknown_cases():
    for tj in ["not json", "{}", json.dumps({"di_token": "opaque"}),
               json.dumps({"di_token": _jwt({"exp": "soon"})}),
               json.dumps({"di_token": _jwt({"exp": True})}),
               json.dumps({"di_token": _jwt({})})]:
        assert pg._access_claim_date(tj, "exp") is None


def test_token_line():
    today = datetime.date(2026, 10, 21)
    tj = _secret(iat=_exp(2026, 10, 19), exp=_exp(2026, 10, 20))
    line = lambda **seen: pg.token_line(seen, tj, today)
    assert line() == "TOKEN: not used this run"
    assert line(watched=False) == \
        "TOKEN: refresh not watched (garminconnect changed); a dead token still shows as PULL failed"
    assert line(watched=True) == "TOKEN: no refresh needed, access token good until 2026-10-20"
    assert pg.token_line({"watched": True}, "{}", today) == "TOKEN: no refresh needed"
    assert line(watched=True, refreshed=False, status=None) == \
        "TOKEN: refresh got no reply (network); token state unknown"
    assert line(watched=True, refreshed=False, status=401) == \
        "TOKEN: WARN refresh rejected (HTTP 401), update GARMINTOKENS from the PC"
    assert line(watched=True, refreshed=True, status=200, rotated=True, lifetime_s=None) == \
        "TOKEN: refresh ok; Garmin rotates refresh tokens; no lifetime in the reply"
    assert line(watched=True, refreshed=True, status=200, rotated=True, lifetime_s=90 * 86400) == \
        "TOKEN: refresh ok; Garmin rotates refresh tokens; saved refresh token ends ~2027-01-17 (90 d lifetime)"
    assert line(watched=True, refreshed=True, status=200, rotated=True, lifetime_s=8 * 86400) == \
        "TOKEN: WARN saved refresh token ends ~2026-10-27, update GARMINTOKENS from the PC"
    assert line(watched=True, refreshed=True, status=200, rotated=False, lifetime_s=90 * 86400) == \
        "TOKEN: refresh ok; Garmin kept the same refresh token; lifetime 90 d, the saved token's start date unknown"


class _Reply:
    def __init__(self, status, body=None):
        self.status_code, self.ok, self._body = status, status < 400, body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _TokenClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def _di_token_post(self, client_id, accept, data):
        self.calls.append(data["grant_type"])
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_watch_refresh_notes_rotation_and_lifetime_only():
    c, seen = _TokenClient(_Reply(200, {"access_token": "new-access", "refresh_token": "new-refresh",
                                        "refresh_token_expires_in": 7776000})), {}
    pg._watch_refresh(c, seen)
    c._di_token_post("c", "json", {"grant_type": "service_ticket"})
    assert seen == {"watched": True}           # a login exchange is not a refresh
    r = c._di_token_post("c", "json", {"grant_type": "refresh_token", "refresh_token": "opaque-refresh"})
    assert r is c.reply and c.calls == ["service_ticket", "refresh_token"]
    assert seen == {"watched": True, "refreshed": True, "status": 200, "rotated": True, "lifetime_s": 7776000.0}
    for v in seen.values():                    # flags and numbers only: no token text is kept
        assert isinstance(v, (bool, int, float))


def test_watch_refresh_same_token_bad_lifetime_and_no_body():
    c, seen = _TokenClient(_Reply(200, {"refresh_token": "opaque-refresh", "refresh_token_expires_in": "90d"})), {}
    pg._watch_refresh(c, seen)
    c._di_token_post("c", "json", {"grant_type": "refresh_token", "refresh_token": "opaque-refresh"})
    assert seen["rotated"] is False and seen["lifetime_s"] is None
    c.reply = _Reply(200)
    c._di_token_post("c", "json", {"grant_type": "refresh_token", "refresh_token": "opaque-refresh"})
    assert seen["refreshed"] is True and seen["rotated"] is False and seen["lifetime_s"] is None


def test_watch_refresh_rejected_and_network_failure():
    c, seen = _TokenClient(_Reply(401, {"error": "invalid_grant"})), {}
    pg._watch_refresh(c, seen)
    c._di_token_post("c", "json", {"grant_type": "refresh_token", "refresh_token": "x"})
    assert seen == {"watched": True, "refreshed": False, "status": 401}
    c.reply = ConnectionError("down")
    with pytest.raises(ConnectionError):
        c._di_token_post("c", "json", {"grant_type": "refresh_token", "refresh_token": "x"})
    assert seen == {"watched": True, "refreshed": False, "status": None}


def test_watch_refresh_without_the_private_hook():
    seen = {}
    pg._watch_refresh(object(), seen)
    assert seen == {"watched": False}


def test_connect_uses_the_secret_when_set(monkeypatch):
    import sys, types
    seen = []
    class Garmin:
        def __init__(self):
            self.client = _TokenClient(_Reply(200))
        def login(self, tokenstore=None):
            seen.append(tokenstore)
    monkeypatch.setitem(sys.modules, "garminconnect", types.SimpleNamespace(Garmin=Garmin))
    monkeypatch.setenv("GARMINTOKENS", json.dumps({"di_refresh_token": "x"}))
    monkeypatch.setattr(pg, "TOKEN_SEEN", {"refreshed": True})
    api = pg._connect()
    assert pg.TOKEN_SEEN == {"watched": True}  # reset, then watched
    assert "_di_token_post" in vars(api.client)
    monkeypatch.delenv("GARMINTOKENS")
    api = pg._connect()
    assert "_di_token_post" not in vars(api.client)   # the PC path is unchanged
    assert seen == [None, "~/.garminconnect"]


def test_fetch_never_writes_the_token_back_with_the_secret(tmp_path, monkeypatch):
    apis = []
    monkeypatch.setattr(pg, "_connect", lambda: apis.append(_FakeApi()) or apis[-1])
    day = datetime.date(2026, 10, 19)
    monkeypatch.setenv("GARMINTOKENS", "{}")
    assert pg.fetch(tmp_path, day, day)
    monkeypatch.delenv("GARMINTOKENS")
    assert pg.fetch(tmp_path, day, day)
    assert apis[0].client.dumps == [] and len(apis[1].client.dumps) == 1


def test_login_failure_names_the_secret(tmp_path, monkeypatch, capsys):
    def refuse():
        raise RuntimeError("DI token refresh failed: 401")
    monkeypatch.setattr(pg, "_connect", refuse)
    monkeypatch.setenv("GARMINTOKENS", "{}")
    day = datetime.date(2026, 10, 19)
    assert pg.fetch(tmp_path, day, day) is False
    out = capsys.readouterr().out
    assert "ERROR Garmin token rejected: update the GARMINTOKENS secret from the PC" in out
    assert "--login" not in out


def test_token_never_printed(tmp_path, monkeypatch, capsys):
    access = _jwt({"iat": _exp(2026, 10, 19), "exp": _exp(2026, 10, 20), "sub": "secret-subject"})
    monkeypatch.setenv("GARMINTOKENS", json.dumps({"di_token": access, "di_refresh_token": "opaque-refresh",
                                                   "di_client_id": "client-xyz"}))
    monkeypatch.setattr(pg, "TOKEN_SEEN", {})
    def refuse():
        pg.TOKEN_SEEN.update(watched=True, refreshed=False, status=401)
        raise RuntimeError("API Error 401")
    monkeypatch.setattr(pg, "_connect", refuse)
    rc = pg.main(["--root", str(tmp_path), "--end", "2026-10-19"])
    out = capsys.readouterr().out
    assert rc == 2
    assert out.rstrip().splitlines()[-1] == \
        "TOKEN: WARN refresh rejected (HTTP 401), update GARMINTOKENS from the PC"
    for secret in (access, access.split(".")[1], "opaque-refresh", "client-xyz", "secret-subject", "di_token"):
        assert secret not in out


def test_no_token_line_on_the_pc(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GARMINTOKENS", raising=False)
    monkeypatch.setattr(pg, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("no tokens")))
    assert pg.main(["--root", str(tmp_path), "--end", "2026-10-19"]) == 2
    assert "TOKEN" not in capsys.readouterr().out


# ---------- cloud: --merge into the committed CSVs (no raw cache) ----------

D = datetime.date
RUN2 = dict(RUN, activityId=125, startTimeLocal="2026-09-21 07:00:00", distance=8000.0, movingDuration=2400.0)
FIT1 = {"training_status": {"mostRecentVO2Max": {"generic": {"calendarDate": "2026-09-18", "vo2MaxPreciseValue": 49.4}}},
        "race_predictions": {"time5K": 1502}, "lactate_threshold": {"speed_and_heart_rate": {"heartRate": 157}}}
FIT2 = dict(FIT1, race_predictions={"time5K": 1400})
ALL_FAILED = {"stats": None, "hrv": None, "sleep": None, "resp": None, "readiness": None}


def _wi(day, grams):
    return {"summaryDate": day, "numOfWeightEntries": 1,
            "latestWeight": {"weight": grams, "sourceType": "MANUAL", "calendarDate": day}}


def _cache(raw, days, acts=None, weighins=None, fitness=None, blobs=None):
    """A raw cache like fetch() leaves; acts/weighins None = that call failed (file not written)."""
    raw.mkdir(parents=True, exist_ok=True)
    for i, d in enumerate(days):
        blob = (blobs or {}).get(d) or {"stats": dict(STATS, calendarDate=d, restingHeartRate=50 + int(d[-2:]) % 7),
                                        "hrv": HRV, "sleep": SLEEP}
        (raw / f"{d}.json").write_text(json.dumps(blob), encoding="utf-8")
    if acts is not None:
        (raw / "activities.json").write_text(json.dumps({str(a["activityId"]): a for a in acts}), encoding="utf-8")
    if weighins is not None:
        (raw / "weighins.json").write_text(json.dumps(weighins), encoding="utf-8")
    if fitness is not None:
        (raw / "fitness.json").write_text(json.dumps(fitness), encoding="utf-8")
    return raw


def _days(a, b):
    return [f"2026-09-{n:02d}" for n in range(a, b + 1)]


def _built(root, days, acts, weighins, fitness):
    _cache(root / "data" / "garmin-raw", days, acts, weighins, fitness)
    pg.build_from_raw(root)
    return root


def _csv_text(root, name):
    return (root / "data" / name).read_text(encoding="utf-8")


def _daily_row(root, day):
    return next(r for r in pg.read_csv_rows(root / "data" / "garmin-daily.csv") if r["date"] == day)


CSVS = ("garmin-daily.csv", "garmin-activities.csv", "garmin-fitness.csv")


def test_merge_matches_a_full_rebuild(tmp_path):
    a = _built(tmp_path / "A", _days(19, 22), [RUN, GYM, RUN2],
               {"2026-09-19": _wi("2026-09-19", 77800.0), "2026-09-21": _wi("2026-09-21", 77400.0)},
               {"2026-09-20": FIT1, "2026-09-22": FIT2})
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {"2026-09-19": _wi("2026-09-19", 77800.0)},
               {"2026-09-20": FIT1})
    w = _cache(tmp_path / "W", _days(20, 22), [RUN2], {"2026-09-21": _wi("2026-09-21", 77400.0)},
               {"2026-09-22": FIT2})
    assert pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 22)) == (3, 1)
    for name in CSVS:
        assert _csv_text(b, name) == _csv_text(a, name), name


def test_merge_keeps_rows_outside_the_window_byte_for_byte(tmp_path):
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {}, {"2026-09-20": FIT1})
    path = b / "data" / "garmin-daily.csv"
    old = _daily_row(b, "2026-09-19")["rhr"]
    path.write_text(path.read_text(encoding="utf-8").replace(f"\n2026-09-19,{old},", f"\n2026-09-19,{old}.0,"),
                    encoding="utf-8")
    w = _cache(tmp_path / "W", _days(20, 22), [], {}, {})
    pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 22))
    assert f"\n2026-09-19,{old}.0," in path.read_text(encoding="utf-8")


def test_merge_leaves_the_hand_kept_sleep_file_alone(tmp_path):
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {}, {})
    hand = b / "data" / "sleep-manual.csv"
    hand.write_text("date,sleep_h,quality,note\n2026-09-21,7.25,decent not great,battery\n", encoding="utf-8")
    before = hand.read_bytes()
    pg.merge_into(b, _cache(tmp_path / "W", _days(20, 22), [], {}, {}), D(2026, 9, 20), D(2026, 9, 22))
    assert hand.read_bytes() == before


def test_merge_keeps_row_when_day_blobs_all_failed(tmp_path):
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {}, {})
    before = _daily_row(b, "2026-09-20")
    w = _cache(tmp_path / "W", _days(20, 22), [], {}, {}, blobs={"2026-09-20": ALL_FAILED})
    assert pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 22)) == (2, 0)
    assert _daily_row(b, "2026-09-20") == before


def test_merge_activity_call_failed_keeps_activities_and_runs(tmp_path):
    b = _built(tmp_path / "B", _days(19, 21), [RUN, GYM, RUN2], {}, {})
    acts_before = _csv_text(b, "garmin-activities.csv")
    run_cols = ("run_km", "run_n", "run_avg_hr")
    before = {c: _daily_row(b, "2026-09-21")[c] for c in run_cols}
    assert before["run_km"] == "8.0"
    w = _cache(tmp_path / "W", _days(20, 22), None, {}, {})
    pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 22))
    assert _csv_text(b, "garmin-activities.csv") == acts_before
    assert {c: _daily_row(b, "2026-09-21")[c] for c in run_cols} == before


def test_merge_keeps_activity_missing_from_the_reply(tmp_path):
    # like the PC's cumulative cache: an empty or short reply never deletes a committed run
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {}, {})
    acts_before = _csv_text(b, "garmin-activities.csv")
    w = _cache(tmp_path / "W", _days(19, 20), [], {}, {})
    pg.merge_into(b, w, D(2026, 9, 19), D(2026, 9, 20))
    assert _csv_text(b, "garmin-activities.csv") == acts_before
    row = _daily_row(b, "2026-09-19")
    assert (row["run_km"], row["run_n"], row["run_avg_hr"]) == ("5.12", "1", "152")


def test_merge_empty_weighin_reply_keeps_weight(tmp_path):
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {"2026-09-19": _wi("2026-09-19", 77800.0)}, {})
    w = _cache(tmp_path / "W", _days(19, 20), [RUN, GYM], {}, {})
    pg.merge_into(b, w, D(2026, 9, 19), D(2026, 9, 20))
    row = _daily_row(b, "2026-09-19")
    assert (row["weight"], row["weight_n"], row["weight_src"]) == ("77.8", "1", "MANUAL")


def test_merge_partial_day_failure_keeps_that_calls_columns(tmp_path):
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {}, {})
    before = _daily_row(b, "2026-09-20")
    w = _cache(tmp_path / "W", _days(20, 20), [], {}, {},
               blobs={"2026-09-20": {"stats": None, "hrv": HRV, "sleep": dict(SLEEP, dailySleepDTO=dict(
                   SLEEP["dailySleepDTO"], sleepTimeSeconds=28800, restingHeartRate=40))}})
    pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 20))
    row = _daily_row(b, "2026-09-20")
    for c in ("rhr", "steps", "bb_high", "bb_low", "stress_avg"):
        assert row[c] == before[c] and before[c] != "", c
    assert row["sleep_h"] == "8.0"



def test_merge_into_csvs_written_before_the_extras_columns(tmp_path):
    # The committed CSVs of Oct 20, 2026 lack the extras columns: the merge adds them, blank on old rows.
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {}, {"2026-09-20": FIT1})
    for name, cols in (("garmin-daily.csv", pg.GARMIN_DAILY_COLUMNS[:-4]),
                       ("garmin-fitness.csv", pg.GARMIN_FITNESS_COLUMNS[:8])):
        path = b / "data" / name
        pg.write_csv(path, cols, pg.read_csv_rows(path))
    wake = [{"inputContext": "AFTER_WAKEUP_RESET", "score": 70, "level": "MODERATE", "acuteLoad": 371,
             "recoveryTime": 900}]
    w = _cache(tmp_path / "W", _days(21, 21), [], {}, {"2026-09-21": {"training_status": TRAINING_STATUS}},
               blobs={"2026-09-21": {"stats": STATS, "hrv": HRV, "sleep": SLEEP, "readiness": wake}})
    pg.merge_into(b, w, D(2026, 9, 21), D(2026, 9, 21))
    daily = pg.read_csv_rows(b / "data" / "garmin-daily.csv")
    assert list(daily[0]) == pg.GARMIN_DAILY_COLUMNS
    assert (daily[0]["recovery_min"], daily[0]["hrv_lo"]) == ("", "")
    assert (daily[-1]["recovery_min"], daily[-1]["hrv_lo"], daily[-1]["hrv_hi"]) == ("900", "55", "70")
    fit = pg.read_csv_rows(b / "data" / "garmin-fitness.csv")
    assert [(r["date"], r["load_lo"], r["load_hi"]) for r in fit] == [("2026-09-20", "", ""),
                                                                      ("2026-09-21", "175.2", "328.5")]


def test_merge_readiness_call_failed_keeps_recovery_time(tmp_path):
    wake = [{"inputContext": "AFTER_WAKEUP_RESET", "score": 70, "acuteLoad": 371, "recoveryTime": 900}]
    b = tmp_path / "B"
    _cache(b / "data" / "garmin-raw", _days(20, 20), [], {}, {},
           blobs={"2026-09-20": {"stats": STATS, "hrv": HRV, "sleep": SLEEP, "readiness": wake}})
    pg.build_from_raw(b)
    w = _cache(tmp_path / "W", _days(20, 20), [], {}, {},
               blobs={"2026-09-20": {"stats": STATS, "hrv": HRV, "sleep": SLEEP, "readiness": None}})
    pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 20))
    assert _daily_row(b, "2026-09-20")["recovery_min"] == "900"

def test_merge_weighin_call_failed_keeps_weight(tmp_path):
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {"2026-09-19": _wi("2026-09-19", 77800.0)}, {})
    w = _cache(tmp_path / "W", _days(19, 20), [RUN, GYM], None, {})
    pg.merge_into(b, w, D(2026, 9, 19), D(2026, 9, 20))
    row = _daily_row(b, "2026-09-19")
    assert (row["weight"], row["weight_n"], row["weight_src"]) == ("77.8", "1", "MANUAL")


def test_fetch_leaves_activities_and_weighins_unwritten_when_their_call_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("GARMINTOKENS", raising=False)
    monkeypatch.setattr(pg, "_connect", lambda: _FakeApi(fail={"get_activities_by_date", "get_weigh_ins"}))
    day = D(2026, 10, 19)
    assert pg.fetch(tmp_path, day, day)
    raw = tmp_path / "data" / "garmin-raw"
    assert (raw / "2026-10-19.json").exists()
    assert not (raw / "activities.json").exists() and not (raw / "weighins.json").exists()


def test_main_merge_fetches_into_a_temp_root_with_the_default_window(tmp_path, monkeypatch, capsys):
    import shutil
    b = _built(tmp_path / "B", _days(19, 20), [RUN, GYM], {}, {})
    shutil.rmtree(b / "data" / "garmin-raw")
    (b / "data" / "daily.csv").write_text("date,rhr\n2026-09-20,57\n", encoding="utf-8")
    seen = []
    def fake_fetch(root, start, end, acts_start=None):
        seen.append((root, start, end, acts_start))
        _cache(root / "data" / "garmin-raw", _days(20, 22), [RUN2], {}, {"2026-09-22": FIT2})
        return True
    monkeypatch.setattr(pg, "fetch", fake_fetch)
    assert pg.main(["--root", str(b), "--merge", "--end", "2026-09-22"]) == 0
    (root, start, end, acts_start), = seen
    assert (start, end, acts_start) == (D(2026, 9, 18), D(2026, 9, 22), None) and root != b
    assert not (b / "data" / "garmin-raw").exists()
    assert _daily_row(b, "2026-09-21")["run_km"] == "8.0"
    out = capsys.readouterr().out
    assert "merged 3 days, 1 activities (2026-09-18 → 2026-09-22)" in out and "mean offset" not in out


def test_main_merge_without_a_csv_is_a_clean_error(tmp_path, capsys):
    assert pg.main(["--root", str(tmp_path), "--merge", "--end", "2026-09-22"]) == 1
    assert "ERROR no garmin-daily.csv to merge into" in capsys.readouterr().out


# ---------- the Personal API fallback ----------

@pytest.fixture(autouse=True)
def _no_personal_key(monkeypatch):
    monkeypatch.delenv("GARMIN_PERSONAL_API_KEY", raising=False)


class _HttpReply:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self.ok = status, status < 400
        self._body, self.text = body, text
        self.content = body if isinstance(body, bytes) else b"" if body is None else b"x"

    def json(self):
        return self._body


class _PersonalSession:
    """Answers the token POST, then each GET from `replies` by path ({path: body} or a callable(params))."""
    def __init__(self, replies=None, token_status=200):
        self.replies, self.token_status = replies or {}, token_status
        self.posts, self.gets = [], []

    def post(self, url, headers=None, timeout=None):
        self.posts.append((url, headers))
        return _HttpReply(self.token_status, text="bearer-jwt\n")

    def get(self, url, headers=None, params=None, timeout=None):
        path = url.removeprefix(pg.PERSONAL_API_URL)
        self.gets.append((path, params, headers))
        if path not in self.replies:
            return _HttpReply(404)
        body = self.replies[path]
        return _HttpReply(200, body(params) if callable(body) else body)


SLEEP_DTO = dict(SLEEP["dailySleepDTO"], averageRespirationValue=13.5)
PERSONAL = {"/usersummary-service/v2/dailysummaries": {"data": [dict(STATS, avgWakingRespirationValue=15.0)]},
            "/hrv-service/hrv/2026-09-19": HRV,
            "/sleep-service/sleep/dailySleep": SLEEP_DTO,
            "/activitylist-service/activities/search/activities": [RUN, GYM],
            "/weight-service/weight/range/2026-09-19/2026-09-19": {"dailyWeightSummaries": [_wi("2026-09-19", 80500)]}}


def test_personal_api_swaps_the_key_for_a_bearer_token():
    s = _PersonalSession(PERSONAL)
    api = pg.PersonalApi("the-key", session=s)
    (url, headers), = s.posts
    assert url == pg.PERSONAL_API_URL + pg.PERSONAL_TOKEN_PATH and headers["Authorization"] == "ApiKey the-key"
    api.get_hrv_data("2026-09-19")
    assert s.gets[0][2]["Authorization"] == "Bearer bearer-jwt"
    with pytest.raises(RuntimeError, match=r"key rejected \(HTTP 401\)"):
        pg.PersonalApi("bad", session=_PersonalSession(token_status=401))


def test_personal_api_replies_parse_like_the_unofficial_ones():
    api = pg.PersonalApi("k", session=_PersonalSession(PERSONAL))
    day = "2026-09-19"
    blobs = {"stats": api.get_stats(day), "hrv": api.get_hrv_data(day), "sleep": api.get_sleep_data(day),
             "resp": api.get_respiration_data(day)}
    row = pg.parse_day(day, blobs["stats"], blobs["hrv"], blobs["sleep"], blobs["resp"], None)
    assert (row["rhr"], row["hrv_night"], row["sleep_h"], row["sleep_score"], row["steps"]) == (52, 61, 7.37, 81, 10432)
    assert (row["resp_sleep"], row["resp_wake"], row["readiness"]) == (13.5, 15.0, None)
    assert [a["activityId"] for a in api.get_activities_by_date(day, day)] == [123, 124]
    assert pg.parse_weighins({day: api.get_weigh_ins(day, day)["dailyWeightSummaries"][0]})[day]["weight"] == 80.5


def test_personal_api_pages_activities():
    acts = [dict(RUN, activityId=i) for i in range(130)]
    s = _PersonalSession({"/activitylist-service/activities/search/activities":
                          lambda p: acts[p["start"]:p["start"] + p["limit"]]})
    assert len(pg.PersonalApi("k", session=s).get_activities_by_date("2026-09-01", "2026-09-30")) == 130
    assert [g[1]["start"] for g in s.gets] == [0, 100]


def test_personal_api_unknown_shapes_count_as_failed_calls():
    s = _PersonalSession({"/usersummary-service/v2/dailysummaries": {"data": [{"calendarDate": "2026-09-19"}]},
                          "/usersummary-service/usersummary/daily": {"calendarDate": "2026-09-19"},
                          "/sleep-service/sleep/dailySleep": {"calendarDate": "2026-09-19"},
                          "/hrv-service/hrv/2026-09-19": {}})
    api = pg.PersonalApi("k", session=s)
    for getter in (api.get_stats, api.get_sleep_data, api.get_hrv_data, api.get_respiration_data):
        with pytest.raises(Exception):
            getter("2026-09-19")
    with pytest.raises(RuntimeError, match="HTTP 404"):
        api.get_weigh_ins("2026-09-19", "2026-09-19")


def test_fetch_uses_only_the_personal_api_when_its_key_is_set(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pg, "_connect", lambda: pytest.fail("the old login must not be tried"))
    monkeypatch.setenv("GARMINTOKENS", "{}")
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "the-key")
    session = _PersonalSession(PERSONAL)
    monkeypatch.setattr("requests.Session", lambda: session)
    day = D(2026, 9, 19)
    assert pg.fetch(tmp_path, day, day)
    out = capsys.readouterr().out
    assert "ERROR" not in out and out.startswith("SOURCE: Garmin Personal API; readiness and acute load are our")
    assert session.posts[0][1]["Authorization"] == "ApiKey the-key" and "the-key" not in out
    raw = tmp_path / "data" / "garmin-raw"
    blob = json.loads((raw / "2026-09-19.json").read_text(encoding="utf-8"))
    assert blob["readiness"] is None and blob["stats"]["totalSteps"] == 10432
    assert not (raw / "fitness.json").exists()   # no HR zones or .FIT here: no empty fitness row
    assert (raw / "activities.json").exists() and (raw / "weighins.json").exists()


def test_fallback_merge_keeps_readiness_and_fitness(tmp_path, monkeypatch):
    import shutil
    b = _built(tmp_path / "B", ["2026-09-19"], [RUN], {}, {"2026-09-19": FIT1})
    shutil.rmtree(b / "data" / "garmin-raw")
    rows = pg.read_csv_rows(b / "data" / "garmin-daily.csv")
    rows[0].update(readiness="71", readiness_src="")   # Garmin's own score, from before Oct 24
    pg.write_csv(b / "data" / "garmin-daily.csv", pg.GARMIN_DAILY_COLUMNS, rows, pg.GARMIN_DAILY_HEADER)
    fitness_before = _csv_text(b, "garmin-fitness.csv")
    monkeypatch.setattr(pg, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("401")))
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "k")
    monkeypatch.setattr("requests.Session", lambda: _PersonalSession(PERSONAL))
    assert pg.main(["--root", str(b), "--merge", "--start", "2026-09-19", "--end", "2026-09-19"]) == 0
    row = _daily_row(b, "2026-09-19")
    assert row["readiness"] == "71" and row["steps"] == "10432" and row["resp_sleep"] == "13.5"
    assert _csv_text(b, "garmin-fitness.csv") == fitness_before


def test_no_key_uses_the_login_and_a_rejected_key_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pg, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("401")))
    day = D(2026, 9, 19)
    assert pg.fetch(tmp_path, day, day) is False
    assert "SOURCE" not in capsys.readouterr().out
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "secret-key")
    monkeypatch.setattr("requests.Session", lambda: _PersonalSession(token_status=401))
    assert pg.fetch(tmp_path, day, day) is False
    out = capsys.readouterr().out
    assert "ERROR Garmin Personal API failed (RuntimeError: Personal API key rejected (HTTP 401))" in out
    assert "renews GARMIN_PERSONAL_API_KEY" in out and "--login" not in out
    assert "secret-key" not in out


def test_personal_api_daily_summary_reads_v2_then_the_daily_path():
    day = "2026-09-19"
    s = _PersonalSession({"/usersummary-service/v2/dailysummaries": {"data": [dict(STATS, calendarDate="2026-09-18"),
                                                                              STATS]}})
    assert pg.PersonalApi("k", session=s).get_stats(day)["calendarDate"] == day
    assert [g[0] for g in s.gets] == ["/usersummary-service/v2/dailysummaries"]
    s = _PersonalSession({"/usersummary-service/v2/dailysummaries": {"data": []},
                          "/usersummary-service/usersummary/daily": STATS})
    assert pg.PersonalApi("k", session=s).get_stats(day)["totalSteps"] == 10432
    assert s.gets[1][1] == {"calendarDate": day}


# ---------- Personal API: VO2max from the .FIT file, threshold HR, approximate acute load ----------

def _fit(records: bytes) -> bytes:
    """A .FIT file around `records` (CRCs left zero: the reader does not check them)."""
    return bytes([14, 0x20, 0, 0]) + len(records).to_bytes(4, "little") + b".FIT\0\0" + records + b"\0\0"


def _fit_def(local: int, msg: int, fields: list[tuple[int, int, int]], big=False) -> bytes:
    return (bytes([0x40 | local, 0, int(big)]) + msg.to_bytes(2, "big" if big else "little") + bytes([len(fields)])
            + b"".join(bytes(f) for f in fields))


def _vo2_fit(raw_value: int, big=False) -> bytes:
    order = "big" if big else "little"
    return _fit(_fit_def(0, 20, [(3, 1, 2)])                       # a record message: HR only
                + bytes([0, 150]) + bytes([0x80, 151])            # one normal, one compressed-timestamp record
                + _fit_def(1, 140, [(4, 2, 0x84), (7, 4, 0x86)], big)
                + bytes([1]) + (5).to_bytes(2, order) + raw_value.to_bytes(4, order))


def test_fit_vo2max_reads_message_140_field_7():
    assert pg.fit_vo2max(_vo2_fit(910020)) == 48.6                 # a run's raw value
    assert pg.fit_vo2max(_vo2_fit(910020, big=True)) == 48.6
    assert pg.fit_vo2max(_vo2_fit(0xFFFFFFFF)) is None             # FIT's "invalid"
    assert pg.fit_vo2max(_fit(_fit_def(0, 20, [(3, 1, 2)]) + bytes([0, 150]))) is None
    assert pg.fit_vo2max(b"not a fit file") is None
    # a compressed-timestamp record leaves out the definition's timestamp (field 253) from its payload
    stamped = _fit(_fit_def(0, 20, [(253, 4, 0x86), (3, 1, 2)]) + bytes([0]) + (7).to_bytes(4, "little") + bytes([150])
                   + bytes([0x80, 151])
                   + _fit_def(1, 140, [(7, 4, 0x86)]) + bytes([1]) + (910020).to_bytes(4, "little"))
    assert pg.fit_vo2max(stamped) == 48.6


def _zip(name: str, data: bytes) -> bytes:
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, data)
    return buf.getvalue()


ZONES = [{"sport": "DEFAULT", "lactateThresholdHeartRateUsed": 157, "maxHeartRateUsed": 188}]
OLD_RUN = dict(RUN, activityId=120, startTimeLocal="2026-09-15 07:00:00")
PERSONAL_FIT = dict(PERSONAL, **{
    "/biometric-service/heartRateZones/v2": ZONES,
    "/activitylist-service/activities/search/activities": [OLD_RUN, RUN, GYM],
    "/download-service/files/activity/123": _zip("123_ACTIVITY.fit", _fit(b"")),   # the newest run has none
    "/download-service/files/activity/120": _zip("120_ACTIVITY.fit", _vo2_fit(910020))})


def test_personal_api_threshold_hr_from_the_hr_zones():
    api = pg.PersonalApi("k", session=_PersonalSession({"/biometric-service/heartRateZones/v2":
                                                        ZONES + [{"sport": "RUNNING", "lactateThresholdHeartRateUsed": 168}]}))
    assert pg.parse_fitness("2026-09-19", {"lactate_threshold": api.get_lactate_threshold()})["lt_hr"] == 168
    api = pg.PersonalApi("k", session=_PersonalSession({"/biometric-service/heartRateZones/v2": ZONES}))
    assert api.get_lactate_threshold()["speed_and_heart_rate"]["heartRate"] == 157
    api = pg.PersonalApi("k", session=_PersonalSession({"/biometric-service/heartRateZones/v2": [{"sport": "DEFAULT"}]}))
    with pytest.raises(ValueError):
        api.get_lactate_threshold()


def test_personal_api_vo2max_from_the_newest_run_fit_that_has_one():
    s = _PersonalSession(PERSONAL_FIT)
    ts = pg.PersonalApi("k", session=s).get_training_status("2026-09-19")
    row = pg.parse_fitness("2026-09-19", {"training_status": ts})
    assert (row["vo2max"], row["vo2max_date"], row["status"], row["load_acute"]) == (48.6, "2026-09-15", None, None)
    downloads = [g for g in s.gets if g[0].startswith("/download-service/")]
    assert [g[0][-3:] for g in downloads] == ["123", "120"]        # runs only, newest first
    assert downloads[0][2]["Accept"] == pg.PersonalApi.FIT_ACCEPT
    search = next(g for g in s.gets if g[0].startswith("/activitylist-service/"))
    assert (search[1]["startDate"], search[1]["endDate"]) == ("2026-09-06", "2026-09-19")
    with pytest.raises(ValueError):
        pg.PersonalApi("k", session=_PersonalSession(dict(PERSONAL_FIT, **{
            "/activitylist-service/activities/search/activities": [GYM]}))).get_training_status("2026-09-19")


def test_fallback_fills_vo2max_and_threshold_hr_and_keeps_the_rest(tmp_path, monkeypatch):
    import shutil
    b = _built(tmp_path / "B", ["2026-09-19"], [RUN], {}, {"2026-09-19": FIT1})
    shutil.rmtree(b / "data" / "garmin-raw")
    monkeypatch.setattr(pg, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("401")))
    monkeypatch.setenv("GARMIN_PERSONAL_API_KEY", "k")
    monkeypatch.setattr("requests.Session", lambda: _PersonalSession(PERSONAL_FIT))
    assert pg.main(["--root", str(b), "--merge", "--start", "2026-09-19", "--end", "2026-09-19"]) == 0
    row, = pg.read_csv_rows(b / "data" / "garmin-fitness.csv")
    # the same date as the earlier full pull: what this pull lacks (race predictor, lt_date) is kept
    assert (row["vo2max"], row["vo2max_date"], row["lt_hr"], row["pred_5k"]) == ("48.6", "2026-09-15", "157", "25:02")


def test_approx_acute_load_fades_each_day_by_e_to_minus_days_over_4_5():
    import math
    steady = {f"2026-09-{n:02d}": 100.0 for n in range(1, 31)} | {f"2026-08-{n:02d}": 100.0 for n in range(1, 32)}
    assert pg.approx_acute_load(steady, "2026-09-30") == 700      # a steady load reads like a 7-day sum
    w = [math.exp(-k / 4.5) for k in range(42)]
    one = {"2026-09-01": 0.0, "2026-09-18": 300.0}
    assert pg.approx_acute_load(one, "2026-09-20") == round(7 / sum(w) * 300 * w[2])   # two days old
    assert pg.approx_acute_load(one, "2026-09-18") > pg.approx_acute_load(one, "2026-09-20")
    assert pg.approx_acute_load({"2026-09-08": 50.0}, "2026-09-20") is None   # under 14 days of history
    assert pg.approx_acute_load({}, "2026-09-20") is None


def _faded(loads: dict, sep_day: int) -> int:
    """The approximation worked out by hand: each load faded by e^(-days/4.5), scaled to read like a 7-day sum."""
    import math
    w = [math.exp(-k / 4.5) for k in range(42)]
    return round(7 / sum(w) * sum(v * w[sep_day - int(d[-2:])] for d, v in loads.items() if int(d[-2:]) <= sep_day))


def test_merge_approximates_a_missing_acute_load_from_all_committed_activities(tmp_path):
    early = dict(RUN, activityId=110, startTimeLocal="2026-09-02 07:00:00", activityTrainingLoad=500.0)
    mid = dict(RUN, activityId=111, startTimeLocal="2026-09-16 07:00:00", activityTrainingLoad=120.0)
    b = _built(tmp_path / "B", _days(19, 20), [early, mid], {}, {})
    garmin = {"readiness": [{"score": 70, "level": "MODERATE", "acuteLoad": 333}]}
    w = _cache(tmp_path / "W", _days(20, 22), [dict(RUN2, activityTrainingLoad=80.0)], {}, {},
               blobs={"2026-09-20": {"stats": dict(STATS, calendarDate="2026-09-20"), "hrv": HRV,
                                       "sleep": SLEEP, **garmin}})
    pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 22))
    got = {d: (_daily_row(b, d)["acute_load"], _daily_row(b, d)["acute_src"]) for d in _days(19, 22)}
    assert got["2026-09-20"] == ("333", "")                       # Garmin's own value, unmarked
    # each from every committed activity, the window's Sep 21 run included
    assert got["2026-09-21"] == (str(_faded({"2026-09-02": 500, "2026-09-16": 120, "2026-09-21": 80}, 21)), "approx")
    assert got["2026-09-22"] == (str(_faded({"2026-09-02": 500, "2026-09-16": 120, "2026-09-21": 80}, 22)), "approx")
    assert got["2026-09-19"] == (str(_faded({"2026-09-02": 500, "2026-09-16": 120}, 19)), "approx")   # as rebuilt


def test_merge_keeps_garmins_acute_load_when_only_readiness_failed(tmp_path):
    mid = dict(RUN, activityId=111, startTimeLocal="2026-09-02 07:00:00", activityTrainingLoad=120.0)
    b = _built(tmp_path / "B", _days(19, 20), [mid], {}, {})
    rows = pg.read_csv_rows(b / "data" / "garmin-daily.csv")
    rows[1].update(acute_load="410", acute_src="")
    pg.write_csv(b / "data" / "garmin-daily.csv", pg.GARMIN_DAILY_COLUMNS, rows, pg.GARMIN_DAILY_HEADER)
    w = _cache(tmp_path / "W", _days(20, 20), [], {}, {})
    pg.merge_into(b, w, D(2026, 9, 20), D(2026, 9, 20))
    assert (_daily_row(b, "2026-09-20")["acute_load"], _daily_row(b, "2026-09-20")["acute_src"]) == ("410", "")
    assert _daily_row(b, "2026-09-19")["acute_src"] == "approx"


# ---------- our readiness estimate (the Personal API has no Training Readiness) ----------

def test_est_readiness_is_a_sleep_base_over_faded_load():
    import math
    sleep = {"2026-10-20": 60.0, "2026-10-21": 70.0, "2026-10-22": 80.0}
    assert pg.est_readiness(sleep, {}, "2026-10-22") == 78                  # 0.8 x 80 + 0.2 x 70
    assert pg.est_readiness(sleep, {"2026-10-22": 200.0}, "2026-10-22") == 39   # fatigue 200 halves it
    yesterday = pg.est_readiness(sleep, {"2026-10-21": 200.0}, "2026-10-22")
    assert yesterday == round(78 / (1 + math.exp(-2 / 1.5)))                # a day old: faded by e^(-1/1.5)
    assert pg.est_readiness(sleep, {"2026-10-22": 5000.0}, "2026-10-22") == 1
    assert pg.est_readiness({"2026-10-22": 100.0}, {}, "2026-10-22") == 100
    assert pg.est_readiness(sleep, {}, "2026-10-23") is None                 # no sleep score that night
    assert [pg.readiness_level(v) for v in (1, 24, 25, 49, 50, 74, 75, 94, 95, 100)] == [
        "POOR", "POOR", "LOW", "LOW", "MODERATE", "MODERATE", "HIGH", "HIGH", "PRIME", "PRIME"]


def test_merge_fills_our_readiness_and_keeps_garmins_own(tmp_path):
    wake = [{"inputContext": "AFTER_WAKEUP_RESET", "score": 70, "level": "MODERATE", "recoveryTime": 900}]
    b = tmp_path / "B"
    _cache(b / "data" / "garmin-raw", _days(19, 20), [], {}, {},
           blobs={"2026-09-19": {"stats": STATS, "hrv": HRV, "sleep": SLEEP, "readiness": wake}})
    pg.build_from_raw(b)
    assert (_daily_row(b, "2026-09-20")["readiness"], _daily_row(b, "2026-09-20")["readiness_src"]) == ("81", "est")
    run = dict(RUN, startTimeLocal="2026-09-20 07:12:00", activityTrainingLoad=100.0)
    w = _cache(tmp_path / "W", _days(19, 20), [run], {}, {})                  # no readiness: the Personal API
    pg.merge_into(b, w, D(2026, 9, 19), D(2026, 9, 20))
    r19, r20 = _daily_row(b, "2026-09-19"), _daily_row(b, "2026-09-20")
    assert (r19["readiness"], r19["readiness_level"], r19["readiness_src"]) == ("70", "MODERATE", "")
    assert (r20["readiness"], r20["readiness_level"], r20["readiness_src"]) == ("65", "MODERATE", "est")


# ---------- our chronic load and load focus (the Personal API has no training status) ----------

def test_est_chronic_load_is_the_average_week_of_the_last_28_days():
    day = D(2026, 10, 21)
    steady = {(day - datetime.timedelta(days=k)).isoformat(): 100.0 for k in range(28)}
    assert pg.est_chronic_load(steady, "2026-10-21") == 700
    assert pg.est_chronic_load(dict(steady, **{"2026-09-23": 999.0}), "2026-10-21") == 700   # 29 days back: out
    short = {k: v for k, v in steady.items() if k > "2026-09-24"}
    assert pg.est_chronic_load(short, "2026-10-21") is None and pg.est_chronic_load({}, "2026-10-21") is None


def _act(day, load, label, ae=3.0, an=0.0):
    return {"date": day, "load": load, "te_label": label, "te_aer": ae, "te_anaer": an}


def test_est_load_focus_splits_hard_sessions_by_training_effect():
    acts = [_act("2026-09-20", 500, None),                               # before the window: only reach
            _act("2026-10-01", 60, "AEROBIC_BASE", 2.8, 0.0),
            _act("2026-10-10", 100, "ANAEROBIC_CAPACITY", 3.0, 2.0),
            _act("2026-10-13", 80, "RECOVERY", 2.7, 2.0),               # an easy label stays low aerobic
            _act("2026-10-22", 999, None)]                              # after the day: ignored
    assert pg.est_load_focus(acts, "2026-10-21") == {"anaer": 40, "aer_hi": 60, "aer_lo": 140}
    assert pg.est_load_focus(acts[1:], "2026-10-21") is None             # under 28 days of activities
    unlabelled = [_act("2026-10-15", 50, "", 2.0, 1.9), _act("2026-10-16", 100, None, 3.0, 2.0)]
    assert pg.est_load_focus(acts + unlabelled, "2026-10-21") == {"anaer": 80, "aer_hi": 120, "aer_lo": 190}
    rows = [{k: ("" if v is None else str(v)) for k, v in a.items()} for a in acts]       # CSV strings
    assert pg.est_load_focus(rows, "2026-10-21") == {"anaer": 40, "aer_hi": 60, "aer_lo": 140}


def test_missing_te_label_finds_the_oldest_unlabelled_activity_of_4_weeks():
    acts = [_act("2026-09-20", 50, None), _act("2026-10-01", 60, ""), _act("2026-10-05", None, None),
            _act("2026-10-10", 70, "TEMPO")]
    assert pg.missing_te_label(acts, D(2026, 10, 21)) == D(2026, 10, 1)   # Sep 20 is past the 28 days
    assert pg.missing_te_label(acts[2:], D(2026, 10, 21)) is None


def test_merge_refetches_activities_that_have_no_te_label(tmp_path, monkeypatch):
    import shutil
    old = dict(RUN, activityId=99, startTimeLocal="2026-09-05 07:00:00", activityTrainingLoad=50.0)
    b = _built(tmp_path / "B", _days(19, 20), [old], {}, {})
    shutil.rmtree(b / "data" / "garmin-raw")
    seen = []
    def fake_fetch(root, start, end, acts_start=None):
        seen.append((start, acts_start))
        _cache(root / "data" / "garmin-raw", _days(18, 22), [dict(old, trainingEffectLabel="AEROBIC_BASE")], {}, {})
        return True
    monkeypatch.setattr(pg, "fetch", fake_fetch)
    assert pg.main(["--root", str(b), "--merge", "--end", "2026-09-22"]) == 0
    assert seen == [(D(2026, 9, 18), D(2026, 9, 5))]
    act, = pg.read_csv_rows(b / "data" / "garmin-activities.csv")
    assert (act["activity_id"], act["te_label"], act["load"]) == ("99", "AEROBIC_BASE", "50")
