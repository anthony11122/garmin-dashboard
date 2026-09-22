import logging
import requests
import json
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger("intervals_icu")

class IntervalsClient:
    BASE_URL = "https://intervals.icu/api/v1"

    def __init__(self, athlete_id: str, api_key: str):
        self.athlete_id = athlete_id.strip() if athlete_id else "0"
        self.api_key = api_key.strip() if api_key else ""
        self.auth = ("API_KEY", self.api_key)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def test_connection(self) -> Tuple[bool, str, Optional[dict]]:
        """测试连接并获取 Athlete 基本信息"""
        if not self.is_configured:
            return False, "未配置 Intervals.icu API Key", None
        try:
            url = f"{self.BASE_URL}/athlete/{self.athlete_id}/profile"
            res = requests.get(url, auth=self.auth, timeout=10)
            if res.status_code == 200:
                data = res.json()
                real_id = data.get("id") or self.athlete_id
                name = data.get("name") or "Athlete"
                return True, f"成功连接 Intervals.icu！运动员: {name} (ID: {real_id})", data
            elif res.status_code == 401:
                return False, "Intervals.icu API Key 无效或未授权", None
            elif res.status_code == 404:
                return False, f"未找到指定的 Athlete ID ({self.athlete_id})", None
            else:
                return False, f"HTTP {res.status_code}: {res.text[:100]}", None
        except Exception as e:
            return False, f"连接 Intervals.icu 异常: {e}", None

    def upload_wellness(self, date_str: str, data: dict) -> Tuple[bool, str]:
        """向 Intervals.icu 上传每日健康数据（HRV、睡眠、静息心率等）"""
        if not self.is_configured:
            return False, "未配置 API Key"
        try:
            url = f"{self.BASE_URL}/athlete/{self.athlete_id}/wellness/{date_str}"
            payload = {
                "id": date_str,
                "restingHR": data.get("resting_hr"),
                "hrv": data.get("hrv_last_night"),
                "sleepSecs": data.get("sleep_duration_seconds"),
                "sleepScore": data.get("sleep_score"),
                "avgSleepingHR": data.get("min_hr"),
                "steps": data.get("steps"),
                "calories": data.get("calories")
            }
            # 过滤 None
            payload = {k: v for k, v in payload.items() if v is not None}
            res = requests.put(url, auth=self.auth, json=payload, timeout=12)
            if res.status_code in [200, 201]:
                return True, "成功同步至 Intervals.icu"
            return False, f"上传失败 (HTTP {res.status_code}): {res.text[:100]}"
        except Exception as e:
            return False, f"上传 Wellness 异常: {e}"

    def get_wellness(self, oldest: str, newest: str) -> Optional[list]:
        """获取指定时间段的计算结果（含 CTL / ATL / TSB / Ramp Rate）"""
        if not self.is_configured:
            return None
        try:
            url = f"{self.BASE_URL}/athlete/{self.athlete_id}/wellness?oldest={oldest}&newest={newest}"
            res = requests.get(url, auth=self.auth, timeout=12)
            if res.status_code == 200:
                return res.json()
            return None
        except Exception as e:
            logger.error(f"拉取 Intervals.icu Wellness 失败: {e}")
            return None

    def upload_activity(self, fit_bytes: bytes, filename: str) -> Tuple[bool, Optional[str]]:
        """上传单次运动原始文件（FIT / ZIP）"""
        if not self.is_configured:
            return False, None
        try:
            url = f"{self.BASE_URL}/athlete/{self.athlete_id}/activities"
            files = {"file": (filename, fit_bytes, "application/octet-stream")}
            res = requests.post(url, auth=self.auth, files=files, timeout=30)
            if res.status_code in [200, 201]:
                act_data = res.json()
                return True, str(act_data.get("id"))
            logger.warning(f"上传活动至 Intervals.icu 失败 (HTTP {res.status_code}): {res.text[:100]}")
            return False, None
        except Exception as e:
            logger.error(f"上传活动异常: {e}")
            return False, None

    def get_activity(self, icu_act_id: str) -> Optional[dict]:
        """获取活动的深度分析（解耦率 decoupling、训练负荷 icu_training_load 等）"""
        if not self.is_configured or not icu_act_id:
            return None
        try:
            url = f"{self.BASE_URL}/activity/{icu_act_id}"
            res = requests.get(url, auth=self.auth, timeout=12)
            if res.status_code == 200:
                return res.json()
            return None
        except Exception as e:
            logger.error(f"获取活动深度指标失败: {e}")
            return None
