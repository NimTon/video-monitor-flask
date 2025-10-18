import asyncio
from datetime import datetime
from utils.db_utils import db
from storage import sm, rm, asm, mm
from utils.log_utils import log
from utils.alert_utils import send_alert
from urllib.parse import urljoin
import pandas as pd
from config import BASE_URL


async def alert_worker():
    while True:
        pending_alerts = pd.DataFrame(db.get_unalerted_videos())
        if pending_alerts.empty:
            log("INFO", "[EMERGENCY ALERT] 当前无待报警记录，休眠2秒")
            await asyncio.sleep(2)
            continue

        grouped = pending_alerts.groupby('group_event_uid')
        for group_event_uid, group in grouped:
            # 获取整体状态
            for _, video in group.iterrows():
                video_id = video.get("id")
                stream_uid = video.get('stream_uid')
                stream_name = video.get('stream_name')
                group_uid = video.get('group_uid')
                timestamp = datetime.fromisoformat(video.get('timestamp'))
                video_path = video.get('video_path')
                ai_status = video.get('ai_status')
                ai_result = video.get('ai_result')
                log("INFO", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}), 待报警")

            # 触发报警 TODO 有需要再改为异步
            attachments = [before_image_path, after_image_path, after_image_path]
            alert_status = -1
            for r in recipients:
                contact = r.get("contact")
                try:
                    for method_name, contact_value in contact.items():
                        send_alert(method_name, contact_value, message, attachments)
                        log("SUCCESS", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp}) 已向接收人 {r['name']} ({contact}) 发送 {method_name} 报警")
                        alert_status = 1
                except Exception as e:
                    log("FAIL", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp}) 向接收人 {r['name']} ({contact}) 发送报警失败: {e}")
                    await asyncio.sleep(1)
                    continue
            # 更新数据库
            db.update_alerted(
                detection_id=detection_id,
                alerted=alert_status
            )
            log("SUCCESS", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp}) 数据库更新完成")
            await asyncio.sleep(1)

async def run_alert_module():
    alert_task = asyncio.create_task(alert_worker())
    await alert_task


if __name__ == "__main__":
    asyncio.run(run_alert_module())
