import os
import json
import logging
import datetime
from fastapi import FastAPI, Request, BackgroundTasks, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler

import db
import sync
import analyzer
import intervals
import bark
from sync import sync_service

logger = logging.getLogger("web_app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="Garmin Health & HR Anomaly Dashboard")

from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    elif request.url.path == "/" or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

TEMPLATES_DIR = os.environ.get("TEMPLATES_DIR", "/app/templates")
STATIC_DIR = os.environ.get("STATIC_DIR", "/app/static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

scheduler = BackgroundScheduler()

def scheduled_sync_job():
    logger.info("执行定时同步任务...")
    today = datetime.date.today()
    sync_service.sync_date(today)
    if datetime.datetime.now().hour in [7, 8]:
        yesterday = today - datetime.timedelta(days=1)
        sync_service.sync_date(yesterday)

@app.on_event("startup")
def startup_event():
    db.init_db()
    sync.start_smart_detector()
    cfg = sync.load_config()
    # 保底定时全量同步（每30分钟自动校准一次，日常以实时探针为主）
    scheduler.add_job(scheduled_sync_job, "interval", minutes=30, id="garmin_periodic_sync")
    scheduler.add_job(scheduled_sync_job, "cron", hour=7, minute=15, id="garmin_morning_sync")
    scheduler.start()
    
    if cfg.get("garmin", {}).get("sync_on_startup", True):
        scheduler.add_job(scheduled_sync_job, "date", run_date=datetime.datetime.now() + datetime.timedelta(seconds=5))

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

@app.get("/", response_class=HTMLResponse)
def index(request: Request, date: str = None):
    if not date:
        date = datetime.date.today().strftime("%Y-%m-%d")
        
    summary = db.get_daily_summary(date)
    if not summary:
        recents = db.get_recent_summaries(1)
        if recents:
            summary = recents[0]
            date = summary["date"]
            
    recent_list = db.get_all_summaries()
    # 按时间正序计算 Banister 负荷模型 (CTL / ATL / TSB)
    chronological = list(reversed(recent_list))
    computed_list = analyzer.compute_banister_loads(chronological)
    recent_list = list(reversed(computed_list))
    
    # 查找选定日期的最新负荷
    selected_load = next((item for item in recent_list if item["date"] == date), summary or {})
    
    hr_points = db.get_hr_timeline(date)
    activities = db.get_activities(date)
    
    auth_status = db.get_kv("auth_status", "need_login")
    auth_msg = db.get_kv("auth_msg", "等待配置账号")
    last_sync = db.get_kv("last_sync_time", "尚未同步")
    cfg = sync.load_config()
    
    icu_client = sync.get_intervals_client()
    icu_status = "connected" if icu_client.is_configured else "not_configured"
    
    anomalies = [p for p in hr_points if p.get("is_anomaly")]
    
    raw_json = json.loads(summary.get("raw_json", "{}")) if summary and summary.get("raw_json") else {}
    hrv_data = {
        "hrvReadings": raw_json.get("hrv_readings", []),
        "hrvSummary": raw_json.get("hrv_summary", {})
    } if raw_json else None
    initial_hrv_data = analyzer.analyze_hrv_deep(date, summary, hrv_data, recent_list)

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "initial_hrv_data": initial_hrv_data,
            "selected_date": date,
            "summary": summary,
            "selected_load": selected_load,
            "recent_list": recent_list,
            "hr_points": hr_points,
            "anomalies": anomalies,
            "activities": activities,
            "auth_status": auth_status,
            "auth_msg": auth_msg,
            "last_sync": last_sync,
            "config": cfg,
            "icu_status": icu_status,
            "garmin_email": cfg.get("garmin", {}).get("email") or db.get_kv("garmin_email", ""),
            "garmin_password": cfg.get("garmin", {}).get("password") or db.get_kv("garmin_password", ""),
            "garmin_interval": cfg.get("garmin", {}).get("auto_sync_interval_hours", 2),
            "garmin_is_cn": cfg.get("garmin", {}).get("is_cn", True),
            "icu_athlete_id": cfg.get("intervals_icu", {}).get("athlete_id") or db.get_kv("icu_athlete_id", "0"),
            "icu_api_key": cfg.get("intervals_icu", {}).get("api_key") or db.get_kv("icu_api_key", ""),
            "bark_status": "connected" if sync.get_bark_notifier().is_configured else "not_configured",
            "bark_server": cfg.get("bark", {}).get("server", "https://api.day.app"),
            "bark_device_key": cfg.get("bark", {}).get("device_key", "L8danTz6iahVQduGCsougm"),
            "bark_auth_user": cfg.get("bark", {}).get("auth_user", "barkpush"),
            "bark_auth_pass": cfg.get("bark", {}).get("auth_pass", "YAKzh2eVd8JxNis7O5IxCQ"),
            "bark_group": cfg.get("bark", {}).get("group", "佳明健康"),
            "bark_sound": cfg.get("bark", {}).get("sound", "minuet"),
            "bark_notify_on_sync": cfg.get("bark", {}).get("notify_on_sync", True),
            "bark_notify_on_anomaly": cfg.get("bark", {}).get("notify_on_anomaly", True)
        }
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/api/status")
def get_status():
    icu = sync.get_intervals_client()
    return {
        "auth_status": db.get_kv("auth_status", "need_login"),
        "auth_msg": db.get_kv("auth_msg", ""),
        "last_sync_time": db.get_kv("last_sync_time", ""),
        "last_sync_status": db.get_kv("last_sync_status", ""),
        "last_sync_msg": db.get_kv("last_sync_msg", ""),
        "intervals_configured": icu.is_configured
    }

@app.get("/api/daily")
def get_daily(date: str = None):
    if not date:
        date = datetime.date.today().strftime("%Y-%m-%d")
    summary = db.get_daily_summary(date)
    hr_points = db.get_hr_timeline(date)
    activities = db.get_activities(date)
    anomalies = [p for p in hr_points if p.get("is_anomaly")]
    
    recent_list = db.get_all_summaries()
    chronological = list(reversed(recent_list))
    computed_list = analyzer.compute_banister_loads(chronological)
    selected_load = next((item for item in computed_list if item.get("date") == date), summary or {})
    
    return {
        "date": date,
        "summary": summary,
        "selected_load": selected_load,
        "hr_points": hr_points,
        "anomalies": anomalies,
        "activities": activities
    }

@app.get("/api/trends")
def get_trends(days: int = 14):
    recents = db.get_recent_summaries(days)
    chronological = list(reversed(recents))
    computed = analyzer.compute_banister_loads(chronological)
    return {"days": days, "data": computed}

@app.post("/api/sync")
def trigger_sync(background_tasks: BackgroundTasks, date: str = None):
    target_date = datetime.datetime.strptime(date, "%Y-%m-%d").date() if date else datetime.date.today()
    
    def run_sync():
        sync_service.sync_date(target_date)
        
    background_tasks.add_task(run_sync)
    d_str = target_date.strftime("%Y-%m-%d")
    return {"ok": True, "message": f"已在后台启动 [{d_str}] 佳明数据与 Intervals.icu 桥接同步任务"}

@app.post("/api/settings")
def update_settings(
    email: str = Form(None),
    password: str = Form(None),
    is_cn: bool = Form(True),
    interval: int = Form(1)
):
    cfg = sync.load_config()
    garmin_cfg = cfg.setdefault("garmin", {})
    garmin_cfg["is_cn"] = is_cn
    
    if email:
        garmin_cfg["email"] = email.strip()
        db.set_kv("garmin_email", email.strip())
    if password:
        garmin_cfg["password"] = password.strip()
        db.set_kv("garmin_password", password.strip())
        
    sync.save_config(cfg)
    success = sync_service.init_client()
    return {
        "ok": success,
        "auth_status": db.get_kv("auth_status"),
        "auth_msg": db.get_kv("auth_msg")
    }

@app.post("/api/intervals/settings")
def update_intervals_settings(
    athlete_id: str = Form("0"),
    api_key: str = Form(...)
):
    athlete_id = athlete_id.strip() if athlete_id else "0"
    api_key = api_key.strip()
    
    client = intervals.IntervalsClient(athlete_id, api_key)
    ok, msg, profile = client.test_connection()
    if not ok:
        return {"ok": False, "message": msg}
        
    cfg = sync.load_config()
    icu_cfg = cfg.setdefault("intervals_icu", {})
    actual_id = (profile or {}).get("id") or athlete_id
    icu_cfg["athlete_id"] = actual_id
    icu_cfg["api_key"] = api_key
    sync.save_config(cfg)
    
    db.set_kv("icu_athlete_id", actual_id)
    db.set_kv("icu_api_key", api_key)
    
    return {"ok": True, "message": msg, "athlete_id": actual_id}


@app.post("/api/bark/settings")
def update_bark_settings(
    server: str = Form("https://api.day.app"),
    device_key: str = Form(...),
    auth_user: str = Form(""),
    auth_pass: str = Form(""),
    group: str = Form("佳明健康"),
    sound: str = Form("minuet"),
    notify_on_sync: bool = Form(True),
    notify_on_anomaly: bool = Form(True)
):
    cfg = sync.load_config()
    bark_cfg = cfg.setdefault("bark", {})
    bark_cfg["enabled"] = True
    bark_cfg["server"] = server.strip()
    bark_cfg["device_key"] = device_key.strip()
    bark_cfg["auth_user"] = auth_user.strip()
    bark_cfg["auth_pass"] = auth_pass.strip()
    bark_cfg["group"] = group.strip() or "佳明健康"
    bark_cfg["sound"] = sound.strip()
    bark_cfg["notify_on_sync"] = notify_on_sync
    bark_cfg["notify_on_anomaly"] = notify_on_anomaly

    sync.save_config(cfg)
    return {"ok": True, "message": "Bark 推送配置已更新并生效"}

@app.post("/api/bark/test")
def test_bark():
    notifier = sync.get_bark_notifier()
    if not notifier.is_configured:
        return {"ok": False, "message": "Bark 尚未配置 Device Key 或未启用"}
    ok, msg = notifier.test_notification()
    return {"ok": ok, "message": msg}




if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8099, reload=False)

@app.get("/api/analysis/weekly")
def get_weekly_analysis(date: str = None):
    if not date:
        date = datetime.date.today().strftime("%Y-%m-%d")
    all_s = db.get_all_summaries()
    result = analyzer.analyze_weekly_health(date, all_s)
    return result

@app.get("/api/analysis/monthly")
def get_monthly_analysis(month: str = None):
    if not month:
        month = datetime.date.today().strftime("%Y-%m")
    all_s = db.get_all_summaries()
    result = analyzer.analyze_monthly_health(month, all_s)
    return result


@app.get("/api/analysis/hrv")
def get_hrv_analysis(date: str = None):
    if not date:
        date = datetime.date.today().strftime("%Y-%m-%d")
        
    summary = db.get_daily_summary(date)
    all_s = db.get_all_summaries()
    
    # 尝试从 SQLite 中读取 cached hrv readings
    hrv_data = None
    conn = db.get_conn()
    c = conn.cursor()
    row = c.execute("SELECT raw_json FROM daily_summary WHERE date = ?", (date,)).fetchone()
    if row and row[0]:
        try:
            raw = json.loads(row[0])
            if "hrv_readings" in raw:
                hrv_data = {
                    "hrvReadings": raw["hrv_readings"],
                    "hrvSummary": raw.get("hrv_summary") or {}
                }
        except Exception:
            pass
            
    # 若未缓存且客户端在线，尝试向 Garmin 补充拉取一次并存入 SQLite 缓存
    if not hrv_data and sync_service.client:
        try:
            live_hrv = sync_service.client.get_hrv_data(date)
            if live_hrv and live_hrv.get("hrvReadings"):
                hrv_data = live_hrv
                raw = json.loads(row[0]) if (row and row[0]) else {}
                raw["hrv_readings"] = live_hrv.get("hrvReadings", [])
                raw["hrv_summary"] = live_hrv.get("hrvSummary", {})
                conn.execute("UPDATE daily_summary SET raw_json = ? WHERE date = ?", (json.dumps(raw), date))
                conn.commit()
        except Exception:
            pass
            
    return analyzer.analyze_hrv_deep(date, summary, hrv_data, all_s)
