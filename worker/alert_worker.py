import asyncio
from datetime import datetime
from utils.db_utils import db
from storage import sm, rm, asm, mm
from utils.utils import log
from utils.alert_utils import send_alert
from urllib.parse import urljoin
import pandas as pd
from config import FLOW_BASE_URL


async def alert_worker():
    while True:
        templates = asm.get_alert_templates()
        if len(templates) == 0:
            log("FAIL", "[ALERT] 当前无消息模板，休眠2秒")
            await asyncio.sleep(2)
            continue
        template = templates[0]
        pending_alerts = pd.DataFrame(db.get_pending_alerts())
        if pending_alerts.empty:
            log("INFO", "[ALERT] 当前无待报警记录，休眠2秒")
            await asyncio.sleep(2)
            continue

        grouped = pending_alerts.groupby(['stream_uid', 'fence_uid'])
        for (stream_uid, fence_uid), group in grouped:
            stream_info = sm.get_stream(stream_uid)
            stream_name = stream_info.get("name")
            log("INFO", f"[ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}), 待报警记录 {len(group)}")
            recipients = rm.get_recipients_by_stream_id(stream_uid)
            if not recipients:
                log("WARNING", f"[ALERT] {stream_name} (UID={stream_uid}) 没有配置报警接收人")
                await asyncio.sleep(2)
                continue

            for _, alert in group.iterrows():
                detection_id = alert.get("id")
                ai_result = alert.get("ai_result")
                fence_uid = alert.get("fence_uid")
                change_ratio = alert.get("change_ratio")
                before_image_path = alert.get("before_image_path")
                after_image_path = alert.get("after_image_path")
                alert_video_path = alert.get("alert_video_path")
                before_image_url = urljoin(FLOW_BASE_URL, before_image_path)
                after_image_url = urljoin(FLOW_BASE_URL, after_image_path)
                alert_video_url = urljoin(FLOW_BASE_URL, alert_video_path)
                timestamp = datetime.fromisoformat(alert.get("timestamp"))
                log("INFO", f"[ALERT] 处理 {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp})")

                # 存入message.json
                mm.add_message(
                    stream_uid=stream_uid,
                    fence_uid=fence_uid,
                    stream_name=stream_name,
                    change_ratio=f"{change_ratio:.3f}",
                    ai_report=ai_result,
                    image_before_url=before_image_url,
                    image_after_url=after_image_url,
                    video_url=alert_video_url
                )

                template_vars = {
                    "stream_name": stream_name,
                    "fence_id": fence_uid,
                    "timestamp": timestamp,
                    "change_ratio": f"{change_ratio:.3f}",
                    "ai_result": ai_result,
                    "image_url": f"{before_image_url} {after_image_url}",
                    "video_url": alert_video_url
                }
                message = ''
                try:
                    message = template['text'].format(**template_vars)  # 渲染模板
                except Exception as e:
                    log("FAIL", f"{stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp}) 的组装报警信息失败: {e}")
                    await asyncio.sleep(1)
                    continue

                # 触发报警 有需要再改为异步
                attachments = [before_image_path, after_image_path, after_image_path]
                alert_status = -1
                for r in recipients:
                    contact = r.get("contact")
                    for method_name, contact_value in contact.items():
                        if contact_value:
                            try:
                                send_alert(method_name, contact_value, message, attachments)
                                log("SUCCESS", f"[ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp}) 已向接收人 {r['name']} ({contact}) 发送 {method_name} 报警")
                                alert_status = 1
                            except Exception as e:
                                log("FAIL", f"[ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp}) 向接收人 {r['name']} ({contact}) 发送报警失败: {e}")
                                await asyncio.sleep(1)
                                continue
                # 更新数据库
                db.update_alerted(
                    detection_id=detection_id,
                    alerted=alert_status
                )
                log("SUCCESS", f"[ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}, DETECTION_ID={detection_id}, TIMESTAMP={timestamp}) 数据库更新完成")
                await asyncio.sleep(1)

async def run_alert_module():
    alert_task = asyncio.create_task(alert_worker())
    await alert_task


if __name__ == "__main__":
    asyncio.run(run_alert_module())
