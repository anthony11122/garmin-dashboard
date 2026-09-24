import sys
import time
import datetime
import logging
from sync import sync_service
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill")

# 1. 确保 client 已经初始化
sync_service.init_client()
client = sync_service.client

if not client:
    logger.error("Garmin Client 初始化失败，无法回溯同步！")
    sys.exit(1)

# 2. 从最早有效日期 2025-12-31 到今天 2026-09-24
start_date = datetime.date(2025, 12, 31)
end_date = datetime.date(2026, 9, 24)

total_days = (end_date - start_date).days + 1
logger.info(f"🚀 开始执行佳明历史数据全量回溯归档: {start_date} -> {end_date} (共 {total_days} 天)")

# 逆序同步：先同步最近的月（如 8 月、7 月、6 月...），确保用户刷新时立刻看到上个月完整数据
current_date = end_date
synced_count = 0
skipped_count = 0
failed_count = 0

while current_date >= start_date:
    d_str = current_date.strftime("%Y-%m-%d")
    
    # 检查本地数据库是否已经存在完整日摘要
    existing = db.get_daily_summary(d_str)
    if existing and existing.get("steps") is not None and existing.get("resting_hr") is not None:
        skipped_count += 1
        current_date -= datetime.timedelta(days=1)
        continue

    logger.info(f"⏳ [{synced_count+1}/{total_days}] 正在同步归档历史日期: {d_str} ...")
    try:
        ok, msg = sync_service.sync_date(current_date)
        if ok:
            synced_count += 1
        else:
            failed_count += 1
            logger.warning(f"⚠️ {d_str} 同步返回未成功: {msg}")
    except Exception as e:
        failed_count += 1
        logger.error(f"❌ {d_str} 同步发生异常: {e}")

    # 控制请求节奏，避免触发佳明 Connect 云端反爬限流
    time.sleep(1.0)
    current_date -= datetime.timedelta(days=1)

logger.info(f"🎉 佳明历史全量数据回溯完成！新同步: {synced_count} 天, 本地已存在跳过: {skipped_count} 天, 失败: {failed_count} 天")
