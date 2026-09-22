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
