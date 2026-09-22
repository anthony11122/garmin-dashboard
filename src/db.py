import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "/app/data/garmin_health.db")

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    
    # 每日健康汇总
    c.execute("""
    CREATE TABLE IF NOT EXISTS daily_summary (
        date TEXT PRIMARY KEY,
        resting_hr INTEGER,
        max_hr INTEGER,
        min_hr INTEGER,
        hrv_last_night REAL,
        hrv_status TEXT,
        hrv_weekly_avg REAL,
        hrv_baseline_low REAL,
        hrv_baseline_high REAL,
        sleep_score INTEGER,
        sleep_duration_seconds INTEGER,
        deep_sleep_seconds INTEGER,
        rem_sleep_seconds INTEGER,
        light_sleep_seconds INTEGER,
        awake_seconds INTEGER,
        body_battery_highest INTEGER,
        body_battery_lowest INTEGER,
        avg_stress INTEGER,
        max_stress INTEGER,
        steps INTEGER,
        calories INTEGER,
        anomaly_count INTEGER DEFAULT 0,
        analysis_summary TEXT,
        raw_json TEXT,
        icu_ctl REAL,
        icu_atl REAL,
        icu_tsb REAL,
        icu_synced INTEGER DEFAULT 0,
        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 动态检查添加列（向下兼容）
    for col, ctype in [("icu_ctl", "REAL"), ("icu_atl", "REAL"), ("icu_tsb", "REAL"), ("icu_synced", "INTEGER DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE daily_summary ADD COLUMN {col} {ctype}")
        except sqlite3.OperationalError:
            pass
    
    # 时序心率点与异常标记
    c.execute("""
    CREATE TABLE IF NOT EXISTS hr_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        timestamp INTEGER,
        time_str TEXT,
        hr INTEGER,
        is_anomaly INTEGER DEFAULT 0,
        anomaly_type TEXT,
        anomaly_desc TEXT
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_hr_date ON hr_timeline(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hr_anomaly ON hr_timeline(is_anomaly)")
    
    # 运动记录与步频锁定检测
    c.execute("""
    CREATE TABLE IF NOT EXISTS activities (
        activity_id TEXT PRIMARY KEY,
        date TEXT,
        name TEXT,
        activity_type TEXT,
        start_time TEXT,
        duration_seconds REAL,
        distance_meters REAL,
        avg_hr INTEGER,
        max_hr INTEGER,
        avg_cadence REAL,
        max_cadence REAL,
        cadence_lock_detected INTEGER DEFAULT 0,
        cadence_lock_details TEXT,
        icu_activity_id TEXT,
        icu_decoupling REAL,
        icu_training_load REAL,
        raw_data TEXT
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_act_date ON activities(date)")
    for col, ctype in [("icu_activity_id", "TEXT"), ("icu_decoupling", "REAL"), ("icu_training_load", "REAL")]:
        try:
            c.execute(f"ALTER TABLE activities ADD COLUMN {col} {ctype}")
        except sqlite3.OperationalError:
            pass
    
    # 同步状态与键值配置
    c.execute("""
    CREATE TABLE IF NOT EXISTS kv_store (
        k TEXT PRIMARY KEY,
        v TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()

def save_daily_summary(data: dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO daily_summary (
        date, resting_hr, max_hr, min_hr,
        hrv_last_night, hrv_status, hrv_weekly_avg, hrv_baseline_low, hrv_baseline_high,
        sleep_score, sleep_duration_seconds, deep_sleep_seconds, rem_sleep_seconds, light_sleep_seconds, awake_seconds,
        body_battery_highest, body_battery_lowest, avg_stress, max_stress, steps, calories,
        anomaly_count, analysis_summary, raw_json,
        icu_ctl, icu_atl, icu_tsb, icu_synced, synced_at
    ) VALUES (
        :date, :resting_hr, :max_hr, :min_hr,
        :hrv_last_night, :hrv_status, :hrv_weekly_avg, :hrv_baseline_low, :hrv_baseline_high,
        :sleep_score, :sleep_duration_seconds, :deep_sleep_seconds, :rem_sleep_seconds, :light_sleep_seconds, :awake_seconds,
        :body_battery_highest, :body_battery_lowest, :avg_stress, :max_stress, :steps, :calories,
        :anomaly_count, :analysis_summary, :raw_json,
        :icu_ctl, :icu_atl, :icu_tsb, :icu_synced, CURRENT_TIMESTAMP
    )
    """, {
        "date": data.get("date"),
        "resting_hr": data.get("resting_hr"),
        "max_hr": data.get("max_hr"),
        "min_hr": data.get("min_hr"),
        "hrv_last_night": data.get("hrv_last_night"),
        "hrv_status": data.get("hrv_status"),
        "hrv_weekly_avg": data.get("hrv_weekly_avg"),
        "hrv_baseline_low": data.get("hrv_baseline_low"),
        "hrv_baseline_high": data.get("hrv_baseline_high"),
        "sleep_score": data.get("sleep_score"),
        "sleep_duration_seconds": data.get("sleep_duration_seconds"),
        "deep_sleep_seconds": data.get("deep_sleep_seconds"),
        "rem_sleep_seconds": data.get("rem_sleep_seconds"),
        "light_sleep_seconds": data.get("light_sleep_seconds"),
        "awake_seconds": data.get("awake_seconds"),
        "body_battery_highest": data.get("body_battery_highest"),
        "body_battery_lowest": data.get("body_battery_lowest"),
        "avg_stress": data.get("avg_stress"),
        "max_stress": data.get("max_stress"),
        "steps": data.get("steps"),
        "calories": data.get("calories"),
        "anomaly_count": data.get("anomaly_count", 0),
        "analysis_summary": data.get("analysis_summary", ""),
        "raw_json": data.get("raw_json", "{}"),
        "icu_ctl": data.get("icu_ctl"),
        "icu_atl": data.get("icu_atl"),
        "icu_tsb": data.get("icu_tsb"),
        "icu_synced": data.get("icu_synced", 0)
    })
    conn.commit()
    conn.close()

def update_daily_icu_metrics(date_str: str, ctl: float, atl: float, tsb: float):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    UPDATE daily_summary SET icu_ctl = ?, icu_atl = ?, icu_tsb = ?, icu_synced = 1
    WHERE date = ?
    """, (ctl, atl, tsb, date_str))
    conn.commit()
    conn.close()

def get_daily_summary(date_str: str):
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT * FROM daily_summary WHERE date = ?", (date_str,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_recent_summaries(days: int = 14):
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("SELECT * FROM daily_summary ORDER BY date DESC LIMIT ?", (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_hr_timeline(date_str: str, points: list):
    for p in points:
        p["date"] = date_str
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM hr_timeline WHERE date = ?", (date_str,))
    c.executemany("""
    INSERT INTO hr_timeline (date, timestamp, time_str, hr, is_anomaly, anomaly_type, anomaly_desc)
    VALUES (:date, :timestamp, :time_str, :hr, :is_anomaly, :anomaly_type, :anomaly_desc)
    """, points)
    conn.commit()
    conn.close()

def get_hr_timeline(date_str: str):
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("SELECT * FROM hr_timeline WHERE date = ? ORDER BY timestamp ASC", (date_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_activity(data: dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO activities (
        activity_id, date, name, activity_type, start_time,
        duration_seconds, distance_meters, avg_hr, max_hr,
        avg_cadence, max_cadence, cadence_lock_detected, cadence_lock_details,
        icu_activity_id, icu_decoupling, icu_training_load, raw_data
    ) VALUES (
        :activity_id, :date, :name, :activity_type, :start_time,
        :duration_seconds, :distance_meters, :avg_hr, :max_hr,
        :avg_cadence, :max_cadence, :cadence_lock_detected, :cadence_lock_details,
        :icu_activity_id, :icu_decoupling, :icu_training_load, :raw_data
    )
    """, {
        "activity_id": data.get("activity_id"),
        "date": data.get("date"),
        "name": data.get("name"),
        "activity_type": data.get("activity_type"),
        "start_time": data.get("start_time"),
        "duration_seconds": data.get("duration_seconds"),
        "distance_meters": data.get("distance_meters"),
        "avg_hr": data.get("avg_hr"),
        "max_hr": data.get("max_hr"),
        "avg_cadence": data.get("avg_cadence"),
        "max_cadence": data.get("max_cadence"),
        "cadence_lock_detected": data.get("cadence_lock_detected", 0),
        "cadence_lock_details": data.get("cadence_lock_details", ""),
        "icu_activity_id": data.get("icu_activity_id"),
        "icu_decoupling": data.get("icu_decoupling"),
        "icu_training_load": data.get("icu_training_load"),
        "raw_data": data.get("raw_data", "{}")
    })
    conn.commit()
    conn.close()

def get_activities(date_str: str = None, limit: int = 20):
    conn = get_conn()
    c = conn.cursor()
    if date_str:
        rows = c.execute("SELECT * FROM activities WHERE date = ? ORDER BY start_time DESC", (date_str,)).fetchall()
    else:
        rows = c.execute("SELECT * FROM activities ORDER BY start_time DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def set_kv(k: str, v: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO kv_store (k, v, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (k, v))
    conn.commit()
    conn.close()

def get_kv(k: str, default=None):
    conn = get_conn()
    c = conn.cursor()
    row = c.execute("SELECT v FROM kv_store WHERE k = ?", (k,)).fetchone()
    conn.close()
    return row["v"] if row else default
