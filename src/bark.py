import os
import json
import logging
import requests
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("garmin.bark")

class BarkNotifier:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.server = (self.config.get("server") or "https://api.day.app").strip().rstrip("/")
        self.device_key = (self.config.get("device_key") or "").strip()
        self.auth_user = (self.config.get("auth_user") or "").strip()
        self.auth_pass = self.config.get("auth_pass") or ""
        self.group = self.config.get("group") or "佳明健康"
        self.sound = self.config.get("sound") or "minuet"
        self.notify_on_sync = self.config.get("notify_on_sync", True)
        self.notify_on_anomaly = self.config.get("notify_on_anomaly", True)

    @property
    def is_configured(self) -> bool:
        return bool(self.enabled and self.device_key)

    def _get_auth(self) -> Optional[Tuple[str, str]]:
        if self.auth_user:
            return (self.auth_user, self.auth_pass)
        return None

    def send(self, title: str, body: str, group: Optional[str] = None, sound: Optional[str] = None) -> Tuple[bool, str]:
        """
        发送纯文本 Bark 消息（不带任何 URL 链接）
        """
        if not self.is_configured:
            return False, "Bark 未启用或未配置 Device Key"

        target_server = self.server or "https://api.day.app"
        push_url = f"{target_server}/push"

        payload = {
            "device_key": self.device_key,
            "title": title[:100],
            "body": body[:1000],
            "group": group or self.group,
        }
        if sound or self.sound:
            payload["sound"] = sound or self.sound

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Garmin-Dashboard/1.0"
        }

        auth = self._get_auth()

        try:
            resp = requests.post(push_url, json=payload, headers=headers, auth=auth, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200:
                    logger.info(f"Bark 消息发送成功: {title}")
                    return True, "推送成功"
                else:
                    msg = data.get("message") or f"未知错误 (code: {data.get(code)})"
                    logger.warning(f"Bark 推送被拒: {msg}")
                    return False, f"Bark 响应错误: {msg}"
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            logger.error(f"Bark 推送异常: {e}")
            return False, f"网络请求异常: {e}"

    def send_daily_report(self, summary: Dict[str, Any], target_date: str, anomalies_count: int = 0, ctl: Optional[float] = None, tsb: Optional[float] = None) -> Tuple[bool, str]:
        if not self.notify_on_sync:
            return False, "同步完成推送未开启"

        title = f"⌚ Garmin 每日简报 · {target_date}"
        lines = []

        # 1. 静息心率
        rhr = summary.get("resting_hr")
        if rhr:
            max_h = summary.get("max_hr", "--")
            lines.append(f"❤️ 静息心率: {rhr} bpm (最高 {max_h})")

        # 2. HRV
        hrv = summary.get("hrv_last_night")
        if hrv:
            hrv_weekly = summary.get("hrv_weekly_avg")
            hrv_status = summary.get("hrv_status", "正常")
            lines.append(f"🌊 HRV昨夜: {hrv:.0f} ms (7天基线 {hrv_weekly:.0f}ms · {hrv_status})")

        # 3. 睡眠
        sleep_score = summary.get("sleep_score")
        if sleep_score:
            dur = summary.get("sleep_duration_seconds", 0) / 3600
            deep = summary.get("deep_sleep_seconds", 0) / 3600
            lines.append(f"🌙 睡眠质量: {sleep_score}分 ({dur:.1f}h · 深睡 {deep:.1f}h)")

        # 4. 身体电量
        bb_hi = summary.get("body_battery_highest")
        bb_lo = summary.get("body_battery_lowest")
        if bb_hi is not None:
            lines.append(f"⚡ 身体电量: 晨间 {bb_hi} / 晚间 {bb_lo}")

        # 5. 步数与负荷
        steps = summary.get("steps")
        cal = summary.get("calories")
        if steps:
            lines.append(f"🏃 今日活动: {steps:,} 步 · {cal:,} kcal")

        # 6. 心率精度状态
        if anomalies_count > 0:
            lines.append(f"⚠️ 传感器精度: 捕捉到 {anomalies_count} 处假性尖刺/松动脱落")
        else:
            lines.append("✅ 传感器质量: 全天心率连续平稳无异常")

        # 7. Intervals.icu 负荷
        if tsb is not None and ctl is not None:
            status_desc = "充沛" if tsb > 5 else ("平衡" if tsb >= -15 else "疲劳")
            lines.append(f"📊 体能状态: TSB {tsb:+.0f} ({status_desc}) · CTL {ctl:.0f}")

        body = "\n".join(lines)
        return self.send(title=title, body=body)

    def send_anomaly_alert(self, title: str, details: str) -> Tuple[bool, str]:
        if not self.notify_on_anomaly:
            return False, "异常监测推送未开启"
        return self.send(title=f"⚠️ {title}", body=details, sound="alarm")

    def test_notification(self) -> Tuple[bool, str]:
        return self.send(
            title="🔔 Garmin 数据中心 Bark 通道测试",
            body="Bark 推送通道正常接入！已配置每日健康简报自动推送与心率异常实时预警 ✅"
        )
