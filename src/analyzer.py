import datetime
from typing import List, Dict, Tuple, Any

def analyze_hr_timeline(hr_values: List[List[Any]], config: dict) -> Tuple[List[dict], List[dict]]:
    """
    分析 Garmin 全天心率序列中的异常点（假性尖刺、骤跌脱落）
    hr_values 格式: [[timestamp_ms, bpm], ...]
    """
    if not hr_values:
        return [], []
    
    spike_thresh = config.get("anomaly_detection", {}).get("spike_threshold_bpm", 35)
    dropout_thresh = config.get("anomaly_detection", {}).get("dropout_threshold_bpm", 42)
    
    processed_points = []
    anomalies = []
    
    clean_series = []
    for item in hr_values:
        if not item or len(item) < 2 or item[1] is None:
            continue
        ts_sec = int(item[0] / 1000) if item[0] > 10000000000 else int(item[0])
        bpm = int(item[1])
        time_str = datetime.datetime.fromtimestamp(ts_sec).strftime("%H:%M")
        clean_series.append({"timestamp": ts_sec, "time_str": time_str, "bpm": bpm})
    
    n = len(clean_series)
    for i in range(n):
        curr = clean_series[i]
        ts = curr["timestamp"]
        time_str = curr["time_str"]
        bpm = curr["bpm"]
        
        is_anomaly = 0
        anomaly_type = None
        anomaly_desc = None
        
        # 1. 假性骤升尖刺检测 (Sudden Spike)
        # 前后两端有参考点，且在极短时间内脉冲式暴涨随后快速回落
        if 2 <= i <= n - 3:
            prev_bpm = clean_series[i-1]["bpm"]
            prev2_bpm = clean_series[i-2]["bpm"]
            next_bpm = clean_series[i+1]["bpm"]
            next2_bpm = clean_series[i+2]["bpm"]
            
            baseline = (prev_bpm + prev2_bpm) / 2
            aftermath = (next_bpm + next2_bpm) / 2
            
            delta_up = bpm - baseline
            delta_down = bpm - aftermath
            
            if delta_up >= spike_thresh and delta_down >= (spike_thresh - 10):
                is_anomaly = 1
                anomaly_type = "optical_spike"
                anomaly_desc = f"疑似光电假性尖刺：瞬间跳变 +{int(delta_up)} bpm 至 {bpm} bpm 后骤降"
        
        # 2. 传感器接触不良/骤跌 (Contact Loss / Dropout)
        # 白天或活动期间（08:00 - 23:00），心率突然跌破极低阈值（如 <42）且前后心率明显偏高（>70）
        if not is_anomaly and 1 <= i <= n - 2:
            prev_bpm = clean_series[i-1]["bpm"]
            next_bpm = clean_series[i+1]["bpm"]
            if bpm < dropout_thresh and prev_bpm > 72 and next_bpm > 72:
                is_anomaly = 1
                anomaly_type = "sensor_dropout"
                anomaly_desc = f"疑似佩戴松动/信号丢失：心率骤跌至 {bpm} bpm (前后正常值约 {int((prev_bpm+next_bpm)/2)} bpm)"
        
        point_data = {
            "timestamp": ts,
            "time_str": time_str,
            "hr": bpm,
            "is_anomaly": is_anomaly,
            "anomaly_type": anomaly_type,
            "anomaly_desc": anomaly_desc
        }
        processed_points.append(point_data)
        if is_anomaly:
            anomalies.append(point_data)
            
    return processed_points, anomalies


def analyze_activity_cadence_lock(samples: List[dict], config: dict) -> Tuple[bool, str]:
    """
    针对单次跑步/徒步等运动数据，检测是否存在【步频锁定（Cadence Lock）】
    samples: [{"time": s, "hr": bpm, "cadence": spm}, ...]
    """
    if not samples or len(samples) < 30:
        return False, "样本量不足，未见明显步频锁定特征"
        
    tol = config.get("anomaly_detection", {}).get("cadence_lock_tolerance", 3)
    min_seconds = config.get("anomaly_detection", {}).get("cadence_lock_min_seconds", 45)
    
    consecutive_match = 0
    max_consecutive = 0
    lock_periods = []
    start_time = None
    
    for item in samples:
        hr = item.get("hr")
        cad = item.get("cadence")
        if hr is None or cad is None or cad < 120:  # 步频过低不属于跑步摆臂共振
            if consecutive_match >= min_seconds:
                lock_periods.append((start_time, item.get("time"), consecutive_match))
            consecutive_match = 0
            start_time = None
            continue
            
        if abs(hr - cad) <= tol:
            if consecutive_match == 0:
                start_time = item.get("time")
            consecutive_match += 1
            if consecutive_match > max_consecutive:
                max_consecutive = consecutive_match
        else:
            if consecutive_match >= min_seconds:
                lock_periods.append((start_time, item.get("time"), consecutive_match))
            consecutive_match = 0
            start_time = None
            
    if consecutive_match >= min_seconds:
        lock_periods.append((start_time, samples[-1].get("time"), consecutive_match))
        
    if lock_periods:
        details = f"检测到 {len(lock_periods)} 处疑似步频锁定区间（最长持续 {max_consecutive} 秒），心率与步频曲线完全贴合，建议运动前将表带收紧一格。"
        return True, details
    else:
        return False, "心率与步频解耦正常，未发现步频共振锁定现象"


def generate_daily_health_report(summary: dict, anomalies: list, recent_summaries: list) -> str:
    """
    综合 HRV、睡眠、身体电量、静息心率与心率传感器异常，生成结构化诊断报告
    """
    lines = []
    
    # 1. 核心状态评级
    sleep_score = summary.get("sleep_score") or 0
    hrv_val = summary.get("hrv_last_night") or 0
    hrv_weekly = summary.get("hrv_weekly_avg") or 0
    bb_max = summary.get("body_battery_highest") or 0
    rhr = summary.get("resting_hr") or 0
    anomaly_cnt = len(anomalies)
    
    # 计算近7天静息心率均值
    past_rhrs = [r["resting_hr"] for r in recent_summaries if r.get("resting_hr")]
    avg_rhr_baseline = sum(past_rhrs) / len(past_rhrs) if past_rhrs else rhr
    
    # 身体恢复综合评级
    if sleep_score >= 80 and (hrv_val >= hrv_weekly * 0.95 or hrv_val == 0) and bb_max >= 75:
        overall_status = "🟢 极佳（恢复充沛）"
        recovery_desc = "昨夜自主神经修复充分，身体电量满格回血，各项机能处于理想状态，适合安排中高强度训练或专注工作。"
    elif sleep_score >= 65 and bb_max >= 50:
        overall_status = "🟡 良好（平稳维持）"
        recovery_desc = "睡眠与神经恢复处于正常基线水平，身体负荷在可控范围内，保持日常节奏即可。"
    else:
        overall_status = "🔴 需休整（恢复偏弱）"
        recovery_desc = "昨夜恢复指标有所落后，自主神经张力稍偏交感端，建议今日减少剧烈运动，适当提早休息补眠。"
        
    lines.append(f"【整体恢复状态】{overall_status}")
    lines.append(f"• 评估综述：{recovery_desc}")
    
    # 2. HRV 与自主神经解读
    if hrv_val > 0:
        hrv_status_str = summary.get("hrv_status") or "测量中"
        diff = hrv_val - hrv_weekly
        diff_str = f"+{diff:.1f}" if diff >= 0 else f"{diff:.1f}"
        lines.append(f"\n【HRV 自主神经分析】")
        lines.append(f"• 昨夜平均：{hrv_val:.0f} ms ｜ 7天均值基线：{hrv_weekly:.0f} ms（较基线 {diff_str} ms）")
        if hrv_val < hrv_weekly - 5:
            lines.append("• 状态提示：昨晚 HRV 偏向低位，副交感神经修复受抑，常与睡前较晚进食、饮酒、轻微疲劳或压力相关。")
        elif hrv_val > hrv_weekly + 10:
            lines.append("• 状态提示：HRV 出现大幅冲高，若昨日有高强度消耗，需警惕副交感神经反弹式代偿过度。")
        else:
            lines.append("• 状态提示：HRV 稳定在个人典型范围内，自主神经系统处于平衡状态。")
            
    # 3. 静息心率与生理基准
    if rhr > 0 and avg_rhr_baseline > 0:
        rhr_diff = rhr - avg_rhr_baseline
        lines.append(f"\n【静息心率（RHR）】")
        if rhr_diff >= 4:
            lines.append(f"• 今日 RHR: {rhr} bpm（较近7天均值偏高 {rhr_diff:.1f} bpm ⚠️）")
            lines.append("• 提示：静息心率明显偏高，通常是身体存在潜在微疲劳、微炎症或脱水/未充分排酸的早期信号。")
        else:
            lines.append(f"• 今日 RHR: {rhr} bpm（与基线均值 {avg_rhr_baseline:.1f} bpm 吻合，心血管负荷正常稳定）")
            
    # 4. 心率传感器质量与不准诊断
    lines.append(f"\n【心率传感器精度与异常诊断】")
    if anomaly_cnt == 0:
        lines.append("• 传感器表现：全天心率采样平滑，未检测到明显的光电假性尖刺或脱落断连，数据可信度高。")
    else:
        spikes = [a for a in anomalies if a.get("anomaly_type") == "optical_spike"]
        dropouts = [a for a in anomalies if a.get("anomaly_type") == "sensor_dropout"]
        lines.append(f"• 共捕捉到 {anomaly_cnt} 处疑似传感器测量异常：")
        if spikes:
            lines.append(f"  - 假性骤升尖刺：{len(spikes)} 次（多由手腕快速晃动或瞬时漏光引发）")
        if dropouts:
            lines.append(f"  - 骤降断连/脱落：{len(dropouts)} 次（多由表带松动移位造成）")
        lines.append("• 建议：日常佩戴保持在腕骨上方约一指距离，佩戴以能插入一根手指为最佳紧致度。")
        
    return "\n".join(lines)

import math

def compute_banister_loads(summaries: list) -> list:
    """
    根据历史健康与运动负荷计算 Banister CTL / ATL / TSB 模型
    summaries 按时间正序排列 [oldest -> newest]
    """
    if not summaries:
        return summaries
        
    ctl = 0.0
    atl = 0.0
    tc_ctl = 42.0  # 长期适应时间常数（天）
    tc_atl = 7.0   # 短期疲劳时间常数（天）
    
    k_ctl = 1.0 - math.exp(-1.0 / tc_ctl)
    k_atl = 1.0 - math.exp(-1.0 / tc_atl)
    
    for row in summaries:
        # 优先使用 Intervals.icu 官方回传的权威数据
        if row.get("icu_ctl") is not None:
            ctl = row["icu_ctl"]
            atl = row.get("icu_atl") or ctl
            row["ctl"] = round(ctl, 1)
            row["atl"] = round(atl, 1)
            row["tsb"] = round(row.get("icu_tsb") or (ctl - atl), 1)
            continue
            
        # 本地估算负荷 (基于步数、活动消耗卡路里、压力值)
        steps = row.get("steps") or 0
        cal = row.get("calories") or 0
        avg_stress = row.get("avg_stress") or 25
        
        # 估算日训练刺激 TSS (以 10000 步约 40-50 TSS, 每额外500大卡+20 TSS)
        step_tss = (steps / 10000.0) * 45.0
        cal_tss = max(0, (cal - 2000) / 500.0) * 15.0
        stress_factor = (avg_stress / 35.0)
        daily_tss = min(200.0, (step_tss + cal_tss) * stress_factor)
        
        ctl = ctl + (daily_tss - ctl) * k_ctl
        atl = atl + (daily_tss - atl) * k_atl
        tsb = ctl - atl
        
        row["ctl"] = round(ctl, 1)
        row["atl"] = round(atl, 1)
        row["tsb"] = round(tsb, 1)
        
    return summaries

import calendar

def get_week_range(date_str: str):
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        dt = datetime.date.today()
    monday = dt - datetime.timedelta(days=dt.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday

def analyze_weekly_health(target_date_str: str, all_summaries: list) -> dict:
    """
    分析指定日期所在自然周（周一至周日）的健康指标聚合、环比对比与深度评估
    """
    try:
        dt = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except Exception:
        dt = datetime.date.today()

    monday = dt - datetime.timedelta(days=dt.weekday())
    sunday = monday + datetime.timedelta(days=6)
    
    prev_monday = monday - datetime.timedelta(days=7)
    prev_sunday = monday - datetime.timedelta(days=1)
    next_monday = monday + datetime.timedelta(days=7)
    
    iso_year, iso_week, _ = monday.isocalendar()
    
    summary_map = {item["date"]: item for item in all_summaries if item and "date" in item}
    
    # 填充本周 7 天
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    week_days = []
    week_summaries = []
    for i in range(7):
        cur_d = monday + datetime.timedelta(days=i)
        cur_d_str = cur_d.strftime("%Y-%m-%d")
        item = summary_map.get(cur_d_str)
        day_entry = {
            "date": cur_d_str,
            "weekday": weekday_names[i],
            "day_num": cur_d.strftime("%m.%d"),
            "has_data": bool(item),
            "data": item or {},
            "is_today": (cur_d == datetime.date.today())
        }
        week_days.append(day_entry)
        if item:
            week_summaries.append(item)
            
    # 上周对比数据
    prev_summaries = []
    for i in range(7):
        cur_d = prev_monday + datetime.timedelta(days=i)
        cur_d_str = cur_d.strftime("%Y-%m-%d")
        if cur_d_str in summary_map:
            prev_summaries.append(summary_map[cur_d_str])
            
    # 1. 步数与消耗
    steps_list = [s["steps"] for s in week_summaries if s.get("steps") is not None]
    total_steps = sum(steps_list) if steps_list else 0
    avg_steps = round(total_steps / len(steps_list)) if steps_list else 0
    goal_days_count = sum(1 for s in steps_list if s >= 10000)
    
    cal_list = [s["calories"] for s in week_summaries if s.get("calories")]
    total_calories = sum(cal_list) if cal_list else 0
    avg_calories = round(total_calories / len(cal_list)) if cal_list else 0
    
    # 2. 静息心率 (RHR)
    rhr_list = [s["resting_hr"] for s in week_summaries if s.get("resting_hr")]
    avg_rhr = round(sum(rhr_list) / len(rhr_list), 1) if rhr_list else None
    min_rhr = min(rhr_list) if rhr_list else None
    max_rhr = max(rhr_list) if rhr_list else None
    
    # 3. 夜间 HRV
    hrv_list = [s["hrv_last_night"] for s in week_summaries if s.get("hrv_last_night")]
    avg_hrv = round(sum(hrv_list) / len(hrv_list), 1) if hrv_list else None
    hrv_balanced_count = sum(1 for s in week_summaries if s.get("hrv_status") == "BALANCED" or (s.get("hrv_last_night") and s.get("hrv_weekly_avg") and s["hrv_last_night"] >= s["hrv_weekly_avg"] * 0.95))
    
    # 4. 睡眠质量
    sleep_score_list = [s["sleep_score"] for s in week_summaries if s.get("sleep_score")]
    avg_sleep_score = round(sum(sleep_score_list) / len(sleep_score_list), 1) if sleep_score_list else None
    
    sleep_sec_list = [s["sleep_duration_seconds"] for s in week_summaries if s.get("sleep_duration_seconds")]
    avg_sleep_hours = round(sum(sleep_sec_list) / len(sleep_sec_list) / 3600, 1) if sleep_sec_list else 0
    
    deep_sec_list = [s["deep_sleep_seconds"] for s in week_summaries if s.get("deep_sleep_seconds")]
    avg_deep_hours = round(sum(deep_sec_list) / len(deep_sec_list) / 3600, 1) if deep_sec_list else 0
    deep_ratio = round((avg_deep_hours / avg_sleep_hours * 100), 1) if avg_sleep_hours > 0 else 0
    
    # 5. 身体电量
    bb_high_list = [s["body_battery_highest"] for s in week_summaries if s.get("body_battery_highest")]
    avg_bb_high = round(sum(bb_high_list) / len(bb_high_list)) if bb_high_list else None
    bb_low_list = [s["body_battery_lowest"] for s in week_summaries if s.get("body_battery_lowest")]
    avg_bb_low = round(sum(bb_low_list) / len(bb_low_list)) if bb_low_list else None
    
    total_anomalies = sum(s.get("anomaly_count", 0) for s in week_summaries)
    
    # 6. 上周环比对比
    prev_steps = [s["steps"] for s in prev_summaries if s.get("steps") is not None]
    prev_avg_steps = round(sum(prev_steps) / len(prev_steps)) if prev_steps else 0
    step_diff_pct = round(((avg_steps - prev_avg_steps) / prev_avg_steps) * 100, 1) if prev_avg_steps > 0 and avg_steps > 0 else None
    
    prev_rhrs = [s["resting_hr"] for s in prev_summaries if s.get("resting_hr")]
    prev_avg_rhr = round(sum(prev_rhrs) / len(prev_rhrs), 1) if prev_rhrs else None
    rhr_diff = round(avg_rhr - prev_avg_rhr, 1) if (avg_rhr is not None and prev_avg_rhr is not None) else None
    
    prev_hrvs = [s["hrv_last_night"] for s in prev_summaries if s.get("hrv_last_night")]
    prev_avg_hrv = round(sum(prev_hrvs) / len(prev_hrvs), 1) if prev_hrvs else None
    hrv_diff = round(avg_hrv - prev_avg_hrv, 1) if (avg_hrv is not None and prev_avg_hrv is not None) else None
    
    prev_sleeps = [s["sleep_score"] for s in prev_summaries if s.get("sleep_score")]
    prev_avg_sleep = round(sum(prev_sleeps) / len(prev_sleeps), 1) if prev_sleeps else None
    sleep_diff = round(avg_sleep_score - prev_avg_sleep, 1) if (avg_sleep_score is not None and prev_avg_sleep is not None) else None

    # 7. 周度智能健康综述 (AI 周报)
    score_weights = []
    if avg_sleep_score: score_weights.append(avg_sleep_score)
    if avg_hrv: score_weights.append(min(100, max(50, avg_hrv * 1.25)))
    if avg_bb_high: score_weights.append(avg_bb_high)
    overall_score = round(sum(score_weights) / len(score_weights)) if score_weights else 75
    
    if overall_score >= 82:
        status_tag = "🟢 极佳恢复周（充沛巅峰）"
        status_summary = "本周整体夜间副交感神经活动充分，深睡修复充沛，晨间身体电量满格回血，处于极佳的运动表现与精力充沛期。"
    elif overall_score >= 70:
        status_tag = "🟡 稳健平衡周（负荷可控）"
        status_summary = "本周生理指标处于健康基线典型范围，神经恢复与训练消耗处于稳态平衡，保持当前生活节律即可。"
    else:
        status_tag = "🔴 疲劳累积周（注意调养）"
        status_summary = "本周睡眠或 HRV 恢复略有受抑，提示身体存在轻度生理压力或疲劳蓄积。建议适当提早入睡，减少晚间高强度脑力或剧烈运动。"

    report_lines = [
        f"【周度总体评价】{status_tag} · 综合健康评分: {overall_score}分",
        f"• 评估概述：{status_summary}",
        f"\n【日常运动与活力】",
        f"• 本周累计步数: {total_steps:,} 步（日均 {avg_steps:,} 步），达标10,000步天数: {goal_days_count} 天 ｜ 总热量消耗: {total_calories:,} kcal"
    ]
    if step_diff_pct is not None:
        report_lines.append(f"• 环比分析：较上周活动量 {'↑ 提升' if step_diff_pct >= 0 else '↓ 减少'} {abs(step_diff_pct)}%")
        
    report_lines.append(f"\n【心血管与自主神经 (HRV)】")
    if avg_rhr:
        rhr_text = f"• 周均静息心率 (RHR): {avg_rhr} bpm (极值 {min_rhr}~{max_rhr} bpm)"
        if rhr_diff is not None:
            rhr_text += f"，较上周 {'偏高 +' if rhr_diff > 0 else '降低 -'}{abs(rhr_diff)} bpm"
        report_lines.append(rhr_text)
    if avg_hrv:
        report_lines.append(f"• 周均夜间 HRV: {avg_hrv} ms（{len(week_summaries)} 个采样天中 {hrv_balanced_count} 天处于完全均衡状态）")
        
    report_lines.append(f"\n【睡眠质量与结构深度】")
    if avg_sleep_score:
        report_lines.append(f"• 周均睡眠质量: {avg_sleep_score} 分 ｜ 日均总睡眠: {avg_sleep_hours} 小时")
        report_lines.append(f"• 深睡深度: 日均 {avg_deep_hours} 小时 (深睡占比 {deep_ratio}%) · {'深度修复充沛' if deep_ratio >= 18 else '深睡比例适中'}")

    weekly_report = "\n".join(report_lines)

    return {
        "year": iso_year,
        "week": iso_week,
        "week_title": f"{iso_year}年 第{iso_week:02d}周 ({monday.strftime('%m.%d')} - {sunday.strftime('%m.%d')})",
        "start_date": monday.strftime("%Y-%m-%d"),
        "end_date": sunday.strftime("%Y-%m-%d"),
        "prev_week_date": prev_monday.strftime("%Y-%m-%d"),
        "next_week_date": next_monday.strftime("%Y-%m-%d"),
        "is_current_week": (monday <= datetime.date.today() <= sunday),
        "days": week_days,
        "metrics": {
            "total_steps": total_steps,
            "avg_steps": avg_steps,
            "goal_days_count": goal_days_count,
            "step_diff_pct": step_diff_pct,
            "total_calories": total_calories,
            "avg_calories": avg_calories,
            "avg_rhr": avg_rhr,
            "min_rhr": min_rhr,
            "max_rhr": max_rhr,
            "rhr_diff": rhr_diff,
            "avg_hrv": avg_hrv,
            "hrv_diff": hrv_diff,
            "hrv_balanced_count": hrv_balanced_count,
            "avg_sleep_score": avg_sleep_score,
            "sleep_diff": sleep_diff,
            "avg_sleep_hours": avg_sleep_hours,
            "avg_deep_hours": avg_deep_hours,
            "deep_ratio": deep_ratio,
            "avg_bb_high": avg_bb_high,
            "avg_bb_low": avg_bb_low,
            "total_anomalies": total_anomalies,
            "recorded_days": len(week_summaries),
            "overall_score": overall_score,
            "status_tag": status_tag
        },
        "report": weekly_report
    }

def analyze_monthly_health(year_month_str: str, all_summaries: list) -> dict:
    """
    分析指定月份（例如 '2026-09'）的全月日历热力图、统计聚合与月度健康趋势
    """
    try:
        parts = year_month_str.split("-")
        year = int(parts[0])
        month = int(parts[1])
    except Exception:
        today = datetime.date.today()
        year = today.year
        month = today.month

    _, last_day = calendar.monthrange(year, month)
    first_date = datetime.date(year, month, 1)
    last_date = datetime.date(year, month, last_day)
    
    prev_month_str = f"{year-1:04d}-12" if month == 1 else f"{year:04d}-{month-1:02d}"
    next_month_str = f"{year+1:04d}-01" if month == 12 else f"{year:04d}-{month+1:02d}"

    summary_map = {item["date"]: item for item in all_summaries if item and "date" in item}
    leading_empty_days = first_date.weekday()
    
    calendar_days = []
    month_summaries = []
    
    for day in range(1, last_day + 1):
        cur_d = datetime.date(year, month, day)
        d_str = cur_d.strftime("%Y-%m-%d")
        item = summary_map.get(d_str)
        
        status_level = "empty"
        if item:
            month_summaries.append(item)
            sleep_sc = item.get("sleep_score") or 0
            bb = item.get("body_battery_highest") or 0
            steps = item.get("steps") or 0
            
            if sleep_sc >= 80 and (bb >= 75 or steps >= 9000):
                status_level = "great" # 绿色
            elif sleep_sc >= 70 or steps >= 7000:
                status_level = "good"  # 蓝青
            elif sleep_sc > 0 or steps > 0:
                status_level = "fair"  # 琥珀
            else:
                status_level = "empty"
                
        calendar_days.append({
            "day": day,
            "date": d_str,
            "weekday": cur_d.weekday(),
            "has_data": bool(item),
            "status_level": status_level,
            "steps": item.get("steps") if item else None,
            "sleep_score": item.get("sleep_score") if item else None,
            "hrv": item.get("hrv_last_night") if item else None,
            "rhr": item.get("resting_hr") if item else None,
            "is_today": (cur_d == datetime.date.today())
        })
        
    steps_list = [s["steps"] for s in month_summaries if s.get("steps") is not None]
    total_steps = sum(steps_list) if steps_list else 0
    avg_steps = round(total_steps / len(steps_list)) if steps_list else 0
    goal_days = sum(1 for s in steps_list if s >= 10000)
    
    rhr_list = [s["resting_hr"] for s in month_summaries if s.get("resting_hr")]
    avg_rhr = round(sum(rhr_list) / len(rhr_list), 1) if rhr_list else None
    min_rhr = min(rhr_list) if rhr_list else None
    max_rhr = max(rhr_list) if rhr_list else None
    
    hrv_list = [s["hrv_last_night"] for s in month_summaries if s.get("hrv_last_night")]
    avg_hrv = round(sum(hrv_list) / len(hrv_list), 1) if hrv_list else None
    
    sleep_list = [s["sleep_score"] for s in month_summaries if s.get("sleep_score")]
    avg_sleep_score = round(sum(sleep_list) / len(sleep_list), 1) if sleep_list else None
    
    sleep_sec = [s["sleep_duration_seconds"] for s in month_summaries if s.get("sleep_duration_seconds")]
    avg_sleep_hours = round(sum(sleep_sec) / len(sleep_sec) / 3600, 1) if sleep_sec else 0
    
    cal_list = [s["calories"] for s in month_summaries if s.get("calories")]
    total_calories = sum(cal_list) if cal_list else 0
    avg_calories = round(total_calories / len(cal_list)) if cal_list else 0
    
    report_lines = [
        f"【月度健康概览】{year}年{month:02d}月",
        f"• 数据记录：本月有效记录 {len(month_summaries)} 天（总天数 {last_day} 天，记录覆盖率 {round(len(month_summaries)/last_day*100)}%）",
        f"• 日常步数：累计 {total_steps:,} 步（日均 {avg_steps:,} 步），达标 10,000 步天数: {goal_days} 天",
        f"• 综合心血管：月均静息心率 (RHR) 为 {avg_rhr} bpm (最低 {min_rhr} bpm，最高 {max_rhr} bpm)",
        f"• 自主神经恢复：月均夜间 HRV 为 {avg_hrv} ms，身体基础抗压与恢复韧性稳定",
        f"• 睡眠质量：月均睡眠评分 {avg_sleep_score} 分，日均睡眠时长约 {avg_sleep_hours} 小时"
    ]
    monthly_report = "\n".join(report_lines)

    return {
        "year": year,
        "month": month,
        "month_title": f"{year}年 {month:02d}月",
        "year_month": f"{year:04d}-{month:02d}",
        "prev_month": prev_month_str,
        "next_month": next_month_str,
        "last_day": last_day,
        "leading_empty_days": leading_empty_days,
        "calendar_days": calendar_days,
        "metrics": {
            "total_steps": total_steps,
            "avg_steps": avg_steps,
            "goal_days": goal_days,
            "total_calories": total_calories,
            "avg_calories": avg_calories,
            "avg_rhr": avg_rhr,
            "min_rhr": min_rhr,
            "max_rhr": max_rhr,
            "avg_hrv": avg_hrv,
            "avg_sleep_score": avg_sleep_score,
            "avg_sleep_hours": avg_sleep_hours,
            "recorded_days": len(month_summaries)
        },
        "report": monthly_report
    }

def analyze_hrv_deep(date_str, summary, hrv_data, recent_summaries):
    """
    HRV 深度运动医学与自主神经 (ANS) 专栏分析:
    1. 核心指标拆解 (昨夜均值、7天基线、基线区间、5分钟极值、状态解析)
    2. 夜间 5 分钟连续采样曲线 (时间与数值序列)
    3. 近 30 天 HRV 长期趋势 (含 RHR 双轴对抗)
    4. 自主神经临床与训练指导报告
    """
    hrv_sum = (hrv_data or {}).get("hrvSummary") or (hrv_data or {}).get("hrv_summary") or {}
    last_night_avg = hrv_sum.get("lastNightAvg") or hrv_sum.get("last_night_avg") or (summary.get("hrv_last_night") if summary else None)
    weekly_avg = hrv_sum.get("weeklyAvg") or hrv_sum.get("weekly_avg") or (summary.get("hrv_weekly_avg") if summary else None)
    status = hrv_sum.get("status") or (summary.get("hrv_status") if summary else None)
    baseline = hrv_sum.get("baseline") or {}
    balanced_low = baseline.get("balancedLow") or baseline.get("balanced_low") or (summary.get("hrv_baseline_low") if summary else 64)
    balanced_upper = baseline.get("balancedUpper") or baseline.get("balanced_upper") or (summary.get("hrv_baseline_high") if summary else 77)
    low_upper = baseline.get("lowUpper") or baseline.get("low_upper") or (balanced_low - 2 if balanced_low else 62)
    marker_val = baseline.get("markerValue", baseline.get("marker_value", 0.5))
    peak_5min = hrv_sum.get("lastNight5MinHigh") or hrv_sum.get("last_night_5min_high")

    # 5分钟采样序列处理
    raw_readings = (hrv_data or {}).get("hrvReadings") or (hrv_data or {}).get("hrv_readings") or []
    epoch_series = []
    min_val = 999
    max_val = 0
    for r in raw_readings:
        t_local = r.get("readingTimeLocal") or ""
        val = r.get("hrvValue")
        if val is not None and t_local:
            time_part = t_local[11:16] if len(t_local) >= 16 else t_local
            epoch_series.append({"time": time_part, "val": val})
            if val < min_val: min_val = val
            if val > max_val: max_val = val
    if min_val == 999: min_val = None
    if max_val == 0: max_val = None
    if not peak_5min and max_val: peak_5min = max_val

    # 历史趋势 (最近 30 天，升序排)
    trend_data = []
    sorted_recent = sorted([s for s in recent_summaries if s.get("date") and s.get("date") <= date_str], key=lambda x: x["date"])[-30:]
    balanced_days_count = 0
    unbalanced_days_count = 0
    low_days_count = 0
    for s in sorted_recent:
        s_hrv = s.get("hrv_last_night")
        s_st = s.get("hrv_status")
        if s_st == "BALANCED": balanced_days_count += 1
        elif s_st == "UNBALANCED": unbalanced_days_count += 1
        elif s_st == "LOW": low_days_count += 1
        trend_data.append({
            "date": s["date"][5:],
            "full_date": s["date"],
            "hrv": s_hrv,
            "weekly_avg": s.get("hrv_weekly_avg"),
            "status": s_st,
            "rhr": s.get("resting_hr"),
            "sleep_score": s.get("sleep_score"),
            "baseline_low": s.get("hrv_baseline_low"),
            "baseline_high": s.get("hrv_baseline_high")
        })

    diff_baseline = round(last_night_avg - weekly_avg, 1) if (last_night_avg and weekly_avg) else 0
    status_map = {
        "BALANCED": "均衡良好",
        "UNBALANCED": "不均衡",
        "LOW": "显著偏低",
        "POOR": "恢复不良",
        None: "测量中"
    }
    status_desc = status_map.get(status, status or "正常")

    insights = []
    recommendations = []

    if status == "BALANCED":
        insights.append(f"自主神经系统处于黄金平衡状态（昨夜 {last_night_avg} ms vs 基线 {weekly_avg} ms，基线偏离 {diff_baseline:+} ms）。副交感神经（迷走神经）在夜间恢复充分，心血管中枢抑制与激活高度协调。")
        recommendations.append("【训练准备度高】今日心血管与神经系统承受力充沛，适合安排高强度间歇（HIIT）、乳酸阈值配速跑或高负荷抗阻力量训练。")
    elif status == "LOW":
        insights.append(f"自主神经系统受到显著交感神经压制（昨夜 {last_night_avg} ms 低于基线区间下限 {balanced_low} ms）。通常由中枢神经疲劳、睡眠剥夺、晚餐饮酒、潜伏期免疫应激或高负荷运动蓄积引发。")
        recommendations.append("【建议主动恢复】今日机体应激处于高位，建议降低训练负荷至 Zone 2 轻松有氧、筋膜放松或彻底休息；提早 30 分钟入睡并充分补充电解质与水分。")
    elif status == "UNBALANCED":
        insights.append(f"HRV 呈现不均衡波动（昨夜 {last_night_avg} ms 偏离 7 天移动均线 {diff_baseline:+} ms），提示自主神经调节正在经历适应性重塑或急性负荷冲击。")
        recommendations.append("【控制训练总量】避免极限突破性大负荷，优先保持心率平稳的基础耐力练习，密切关注明日晨起心率与静息体感。")
    else:
        insights.append(f"HRV 记录持续积累中，昨夜均值 {last_night_avg or '--'} ms。基线正在基于 7~21 天连续生理节律建立。")
        recommendations.append("建议保持夜间佩戴习惯，确保至少 3 周连续睡眠监测以建立更精准的生理个性化基线。")

    if peak_5min and last_night_avg:
        dyn_range = peak_5min - (min_val or (last_night_avg * 0.7))
        insights.append(f"夜间副交感神经波幅动态极差为 {dyn_range:.0f} ms（最低 {min_val or '--'} ms ~ 峰值 {peak_5min} ms），展现了睡眠周期各阶段的神经张力阶梯式复苏。")

    return {
        "date": date_str,
        "summary": {
            "last_night_avg": last_night_avg,
            "weekly_avg": weekly_avg,
            "status": status,
            "status_desc": status_desc,
            "balanced_low": balanced_low,
            "balanced_upper": balanced_upper,
            "low_upper": low_upper,
            "marker_value": marker_val,
            "peak_5min": peak_5min,
            "min_5min": min_val,
            "diff_baseline": diff_baseline
        },
        "epoch_readings": epoch_series,
        "trend_history": trend_data,
        "stats": {
            "total_days_evaluated": len(trend_data),
            "balanced_days": balanced_days_count,
            "unbalanced_days": unbalanced_days_count,
            "low_days": low_days_count,
            "balanced_ratio": round(balanced_days_count / len(trend_data) * 100 if trend_data else 100)
        },
        "insights": insights,
        "recommendations": recommendations
    }
