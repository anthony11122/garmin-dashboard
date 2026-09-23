import os
import json
import logging
import datetime
import yaml
from garminconnect import Garmin
from garminconnect import (
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
    GarminConnectAuthenticationError,
)

import db
import analyzer
import intervals
import bark

logger = logging.getLogger("garmin_sync")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TOKEN_DIR = os.environ.get("TOKEN_DIR", "/app/data/tokens")
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config.yaml")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
    return {}

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True)
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")

def get_bark_notifier():
    cfg = load_config()
    bark_cfg = cfg.get("bark", {})
    return bark.BarkNotifier(bark_cfg)

def get_intervals_client():
    cfg = load_config()
    icu_cfg = cfg.get("intervals_icu", {})
    athlete_id = icu_cfg.get("athlete_id") or db.get_kv("icu_athlete_id", "0")
    api_key = icu_cfg.get("api_key") or db.get_kv("icu_api_key", "")
    return intervals.IntervalsClient(athlete_id, api_key)

class GarminSyncService:
    def __init__(self):
        self.client = None
        self.config = load_config()

    def get_credentials(self):
        cfg = load_config()
        garmin_cfg = cfg.get("garmin", {})
        email = garmin_cfg.get("email") or db.get_kv("garmin_email", "")
        password = garmin_cfg.get("password") or db.get_kv("garmin_password", "")
        is_cn = garmin_cfg.get("is_cn", True)
        return email, password, is_cn

    def init_client(self):
        email, password, is_cn = self.get_credentials()
        os.makedirs(TOKEN_DIR, exist_ok=True)
        
        # 1. 尝试直接加载已缓存的 Session Token (免密)
        token_files = os.listdir(TOKEN_DIR) if os.path.exists(TOKEN_DIR) else []
        if token_files:
            try:
                logger.info(f"正在从本地缓存加载 Garmin 凭据 (is_cn={is_cn})...")
                client = Garmin(is_cn=is_cn)
                client.login(TOKEN_DIR)
                self.client = client
                db.set_kv("auth_status", "logged_in")
                db.set_kv("auth_msg", "使用缓存 Token 成功免密连接")
                return True
            except Exception as e:
                logger.warning(f"本地 Token 失效或过期，将尝试使用账号密码重新登录: {e}")

        # 2. 若无 Token 或 Token 已失效，尝试使用密码登录
        if not email or not password:
            msg = "未配置 Garmin 账号或密码，等待用户在设置页面填写"
            logger.info(msg)
            db.set_kv("auth_status", "need_login")
            db.set_kv("auth_msg", msg)
            return False

        try:
            logger.info(f"正在登录 Garmin Connect (账号: {email[:3]}***, is_cn={is_cn})...")
            client = Garmin(email, password, is_cn=is_cn)
            mfa_status, _ = client.login(TOKEN_DIR)
            if mfa_status:
                msg = f"Garmin 要求二次验证 (MFA)，状态: {mfa_status}"
                logger.warning(msg)
                db.set_kv("auth_status", "mfa_required")
                db.set_kv("auth_msg", msg)
                return False
                
            token_file = os.path.join(TOKEN_DIR, "garmin_token.json")
            with open(token_file, "w") as f:
                f.write(json.dumps({"logged_in_at": datetime.datetime.now().isoformat()}))
            self.client = client
            db.set_kv("auth_status", "logged_in")
            db.set_kv("auth_msg", "登录成功并已更新本地免密 Token")
            return True
        except GarminConnectAuthenticationError as e:
            err = f"认证失败，账号或密码错误: {e}"
            logger.error(err)
            db.set_kv("auth_status", "error")
            db.set_kv("auth_msg", err)
            return False
        except Exception as e:
            err = f"连接 Garmin Connect 异常: {e}"
            logger.error(err)
            db.set_kv("auth_status", "error")
            db.set_kv("auth_msg", err)
            return False

    def sync_date(self, target_date: datetime.date = None):
        if not target_date:
            target_date = datetime.date.today()
        date_str = target_date.strftime("%Y-%m-%d")
        logger.info(f"开始同步日期 [{date_str}] 的佳明健康数据...")

        if not self.client:
            if not self.init_client():
                return False, db.get_kv("auth_msg", "未登录")

        try:
            cfg = load_config()
            
            # 1. 获取全天心率明细
            hr_data = {}
            try:
                hr_data = self.client.get_heart_rates(date_str) or {}
            except Exception as e:
                logger.warning(f"获取心率数据跳过或异常: {e}")
                
            hr_values = hr_data.get("heartRateValues") or []
            resting_hr = hr_data.get("restingHeartRate")
            max_hr = hr_data.get("maxHeartRate")
            min_hr = hr_data.get("minHeartRate")
            
            # 算法分析全天心率序列异常
            processed_points, anomalies = analyzer.analyze_hr_timeline(hr_values, cfg)
            db.save_hr_timeline(date_str, processed_points)
            
            # 2. 获取 HRV 数据
            hrv_last_night = None
            hrv_status = None
            hrv_weekly_avg = None
            hrv_low = None
            hrv_high = None
            try:
                hrv_data = self.client.get_hrv_data(date_str) or {}
                hrv_summary = hrv_data.get("hrvSummary") or {}
                hrv_last_night = hrv_summary.get("lastNightAvg")
                hrv_status = hrv_summary.get("status")
                hrv_weekly_avg = hrv_summary.get("weeklyAvg")
                baseline = hrv_summary.get("baseline") or {}
                hrv_low = baseline.get("balancedLow")
                hrv_high = baseline.get("balancedUpper")
            except Exception as e:
                logger.warning(f"获取 HRV 数据异常: {e}")

            # 3. 获取睡眠数据
            sleep_score = None
            sleep_duration = None
            deep_sec = None
            rem_sec = None
            light_sec = None
            awake_sec = None
            try:
                sleep_data = self.client.get_sleep_data(date_str) or {}
                daily_sleep = sleep_data.get("dailySleepDTO") or {}
                sleep_duration = daily_sleep.get("sleepTimeSeconds")
                deep_sec = daily_sleep.get("deepSleepSeconds")
                rem_sec = daily_sleep.get("remSleepData")
                light_sec = daily_sleep.get("lightSleepSeconds")
                awake_sec = daily_sleep.get("awakeSleepSeconds")
                scores = daily_sleep.get("sleepScores") or {}
                if scores.get("overall"):
                    sleep_score = scores["overall"].get("value")
            except Exception as e:
                logger.warning(f"获取睡眠数据异常: {e}")

            # 4. 获取身体电量 (Body Battery)
            bb_high = None
            bb_low = None
            try:
                bb_data = self.client.get_body_battery(date_str) or []
                if isinstance(bb_data, list) and bb_data:
                    bb_vals = [x[1] for x in bb_data[0].get("bodyBatteryValuesArray", []) if len(x) > 1 and x[1] is not None]
                    if bb_vals:
                        bb_high = max(bb_vals)
                        bb_low = min(bb_vals)
            except Exception as e:
                logger.warning(f"获取身体电量数据异常: {e}")

            # 5. 获取日常统计与压力
            avg_stress = None
            max_stress = None
            steps = None
            calories = None
            try:
                stats = self.client.get_user_summary(date_str) or {}
                steps = stats.get("totalSteps")
                calories = stats.get("totalKilocalories")
                avg_stress = stats.get("averageStressLevel")
                max_stress = stats.get("maxStressLevel")
                if not resting_hr:
                    resting_hr = stats.get("restingHeartRate")
            except Exception as e:
                logger.warning(f"获取总体日统计异常: {e}")

            # 6. 生成每日健康诊断综合报告
            recent_days = db.get_recent_summaries(7)
            summary_dict = {
                "date": date_str,
                "resting_hr": resting_hr,
                "max_hr": max_hr,
                "min_hr": min_hr,
                "hrv_last_night": hrv_last_night,
                "hrv_status": hrv_status,
                "hrv_weekly_avg": hrv_weekly_avg,
                "hrv_baseline_low": hrv_low,
                "hrv_baseline_high": hrv_high,
                "sleep_score": sleep_score,
                "sleep_duration_seconds": sleep_duration,
                "deep_sleep_seconds": deep_sec,
                "rem_sleep_seconds": rem_sec,
                "light_sleep_seconds": light_sec,
                "awake_seconds": awake_sec,
                "body_battery_highest": bb_high,
                "body_battery_lowest": bb_low,
                "avg_stress": avg_stress,
                "max_stress": max_stress,
                "steps": steps,
                "calories": calories,
                "anomaly_count": len(anomalies),
                "analysis_summary": "",
                "raw_json": json.dumps({"hr_count": len(processed_points)})
            }
            
            report = analyzer.generate_daily_health_report(summary_dict, anomalies, recent_days)
            summary_dict["analysis_summary"] = report
            
            # 7. 桥接同步至 Intervals.icu (如果已配置)
            icu = get_intervals_client()
            if icu.is_configured:
                try:
                    logger.info(f"正在将 [{date_str}] 的健康数据推送到 Intervals.icu...")
                    ok, msg = icu.upload_wellness(date_str, summary_dict)
                    if ok:
                        logger.info(f"Intervals.icu Wellness 同步成功: {msg}")
                        # 尝试拉取服务端已更新的 CTL / ATL / TSB
                        w_list = icu.get_wellness(date_str, date_str)
                        if w_list and isinstance(w_list, list):
                            for w in w_list:
                                if w.get("id") == date_str:
                                    ctl = w.get("ctl")
                                    atl = w.get("atl")
                                    tsb = (ctl - atl) if (ctl is not None and atl is not None) else None
                                    summary_dict["icu_ctl"] = ctl
                                    summary_dict["icu_atl"] = atl
                                    summary_dict["icu_tsb"] = tsb
                                    summary_dict["icu_synced"] = 1
                                    logger.info(f"成功拉回 Intervals.icu 负荷指标: CTL={ctl}, ATL={atl}, TSB={tsb}")
                except Exception as e:
                    logger.warning(f"桥接同步至 Intervals.icu 异常: {e}")

            db.save_daily_summary(summary_dict)
            
            # 8. 同步单次运动活动并检测步频锁定
            try:
                activities = self.client.get_activities(0, 5) or []
                for act in activities:
                    act_id = str(act.get("activityId"))
                    act_date = (act.get("startTimeLocal") or "")[:10]
                    act_name = act.get("activityName")
                    act_type = (act.get("activityType") or {}).get("typeKey")
                    avg_cad = act.get("averageRunningCadenceInStepsPerMinute") or act.get("averageBikingCadenceInRevPerMinute")
                    max_cad = act.get("maxRunningCadenceInStepsPerMinute") or act.get("maxBikingCadenceInRevPerMinute")
                    
                    # 尝试拉取活动采样检测步频锁定
                    lock_detected = 0
                    lock_details = "未检测"
                    try:
                        splits = self.client.get_activity_details(act_id) or {}
                        metrics = splits.get("metricDescriptors", [])
                        activity_detail = splits.get("activityDetailMetrics", [])
                        
                        hr_idx = -1
                        cad_idx = -1
                        time_idx = -1
                        for idx, m in enumerate(metrics):
                            key = m.get("key")
                            if "heartRate" in key:
                                hr_idx = idx
                            elif "directCadence" in key or "cadence" in key:
                                cad_idx = idx
                            elif "directTimestamp" in key or "timerDuration" in key:
                                time_idx = idx
                                
                        if hr_idx >= 0 and cad_idx >= 0:
                            samples = []
                            for row in activity_detail:
                                metric_array = row.get("metrics", [])
                                if len(metric_array) > max(hr_idx, cad_idx):
                                    samples.append({
                                        "time": metric_array[time_idx] if time_idx >= 0 else 0,
                                        "hr": metric_array[hr_idx],
                                        "cadence": metric_array[cad_idx]
                                    })
                            detected, details = analyzer.analyze_activity_cadence_lock(samples, cfg)
                            lock_detected = 1 if detected else 0
                            lock_details = details
                    except Exception as e:
                        logger.warning(f"分析活动 {act_id} 细节失败: {e}")

                    icu_act_id = None
                    icu_decoupling = None
                    icu_load = None
                    
                    # 9. 自动下载国区原始 FIT 文件并上传给 Intervals.icu
                    if icu.is_configured:
                        try:
                            logger.info(f"正在从佳明国区下载运动 {act_id} 的原始 FIT 文件并推送到 Intervals.icu...")
                            fit_bytes = self.client.download_activity(act_id, dl_fmt=self.client.ActivityDownloadFormat.ORIGINAL)
                            if fit_bytes:
                                ok, uploaded_id = icu.upload_activity(fit_bytes, f"garmin_{act_id}.zip")
                                if ok and uploaded_id:
                                    icu_act_id = uploaded_id
                                    logger.info(f"运动 {act_id} 成功上传至 Intervals.icu (ID: {icu_act_id})")
                                    # 尝试查询解耦率
                                    icu_act = icu.get_activity(icu_act_id)
                                    if icu_act:
                                        icu_decoupling = icu_act.get("decoupling")
                                        icu_load = icu_act.get("icu_training_load")
                        except Exception as e:
                            logger.warning(f"中继上传运动 {act_id} 至 Intervals.icu 异常: {e}")

                    db.save_activity({
                        "activity_id": act_id,
                        "date": act_date,
                        "name": act_name,
                        "activity_type": act_type,
                        "start_time": act.get("startTimeLocal"),
                        "duration_seconds": act.get("duration"),
                        "distance_meters": act.get("distance"),
                        "avg_hr": act.get("averageHR"),
                        "max_hr": act.get("maxHR"),
                        "avg_cadence": avg_cad,
                        "max_cadence": max_cad,
                        "cadence_lock_detected": lock_detected,
                        "cadence_lock_details": lock_details,
                        "icu_activity_id": icu_act_id,
                        "icu_decoupling": icu_decoupling,
                        "icu_training_load": icu_load,
                        "raw_data": json.dumps({"summary": act_name})
                    })
            except Exception as e:
                logger.warning(f"同步运动记录异常: {e}")

            db.set_kv("last_sync_time", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            db.set_kv("last_sync_status", "success")
            db.set_kv("last_sync_msg", f"成功同步 [{date_str}] 数据，记录心率采样 {len(processed_points)} 点，捕获异常 {len(anomalies)} 处")
            logger.info(f"[{date_str}] 同步并分析完成！")

            # 10. Bark 自动推送（增加去重与每日限次控制，一天仅推送一次简报）
            try:
                notifier = get_bark_notifier()
                if notifier.is_configured:
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    last_pushed_date = db.get_kv("last_daily_report_pushed_date", "")

                    # 1. 每日简报：每天只推送一次（在晨间同步好睡眠/HRV后，或中午前首次同步时推送）
                    if date_str == today_str and notifier.notify_on_sync and last_pushed_date != today_str:
                        has_sleep_data = bool(summary_dict.get("sleep_score") or summary_dict.get("hrv_last_night"))
                        is_after_morning = datetime.datetime.now().hour >= 11
                        
                        # 仅在已有睡眠/HRV数据或已过上午时触发当日唯一一次简报
                        if has_sleep_data or is_after_morning:
                            ctl_val = None
                            tsb_val = None
                            try:
                                recent_summaries = db.get_recent_summaries(14)
                                loads = analyzer.compute_banister_loads(recent_summaries)
                                if loads:
                                    ctl_val = loads[-1].get("ctl")
                                    tsb_val = loads[-1].get("tsb")
                            except Exception:
                                pass
                            
                            ok, push_msg = notifier.send_daily_report(
                                summary=summary_dict,
                                target_date=date_str,
                                anomalies_count=len(anomalies),
                                ctl=ctl_val,
                                tsb=tsb_val
                            )
                            if ok:
                                db.set_kv("last_daily_report_pushed_date", today_str)
                                logger.info(f"今日 [{today_str}] 每日简报已推送，本日后续同步将静默更新，不再重复推送。")

                    # 2. 异常预警：仅在出现新增异常点时推送，避免每次同步重复报警
                    if anomalies and notifier.notify_on_anomaly:
                        last_alert_cnt = int(db.get_kv(f"last_anomaly_count_{today_str}", "0") or 0)
                        if len(anomalies) > last_alert_cnt:
                            new_anomalies = anomalies[last_alert_cnt:]
                            anomaly_descs = [p.get("anomaly_desc") for p in new_anomalies[:3]]
                            details = f"今日 [{date_str}] 新增 {len(new_anomalies)} 处心率异常点：\n- " + "\n- ".join(anomaly_descs)
                            notifier.send_anomaly_alert("佳明手表心率异常预警", details)
                            db.set_kv(f"last_anomaly_count_{today_str}", str(len(anomalies)))
            except Exception as e:
                logger.warning(f"触发 Bark 推送通知异常: {e}")

            return True, "同步成功"

        except Exception as e:
            err = f"同步过程发生异常: {e}"
            logger.error(err)
            db.set_kv("last_sync_status", "error")
            db.set_kv("last_sync_msg", err)
            return False, err

sync_service = GarminSyncService()


import threading
import time

class SmartSyncDetector(threading.Thread):
    def __init__(self, service):
        super().__init__(daemon=True, name="GarminSmartDetector")
        self.service = service
        self.running = True

    def run(self):
        logger.info("🚀 启动 Garmin 实时数据探测器 (秒级静默监听云端更新)...")
        time.sleep(10) # 等待主服务就绪
        while self.running:
            try:
                self.check_and_sync()
            except Exception as e:
                logger.warning(f"实时探测异常: {e}")

            # 默认实时高频探针（白天 06:00 - 24:00 每 40 秒轻量探测一次，夜间 90 秒）
            now = datetime.datetime.now()
            sleep_sec = 40 if 6 <= now.hour <= 23 else 90
            time.sleep(sleep_sec)

    def check_and_sync(self):
        if not self.service.client:
            self.service.init_client()
        if not self.service.client:
            return

        today = datetime.date.today()
        today_str = today.strftime("%Y-%m-%d")

        try:
            # 极轻量探针：获取今日概要（仅比对云端同步微秒时间戳）
            summary = self.service.client.get_user_summary(today_str)
            if not summary:
                return

            last_sync_gmt = summary.get("lastSyncTimestampGMT")
            saved_gmt = db.get_kv("last_cloud_sync_gmt", "")

            # 检测到佳明云端有手表数据更新，自动执行同步与分析处理（无任何提醒骚扰）
            if last_sync_gmt and str(last_sync_gmt) != saved_gmt:
                logger.info(f"✨ [实时获取] 探测到佳明云端数据更新: {saved_gmt} -> {last_sync_gmt}，立即自动同步与桥接！")
                db.set_kv("last_cloud_sync_gmt", str(last_sync_gmt))
                self.service.sync_date(today)

        except Exception as e:
            logger.warning(f"智能探针检测失败: {e}")

smart_detector = None

def start_smart_detector():
    global smart_detector
    if smart_detector is None or not smart_detector.is_alive():
        smart_detector = SmartSyncDetector(sync_service)
        smart_detector.start()
        logger.info("智能自适应探测器线程已成功启动")
