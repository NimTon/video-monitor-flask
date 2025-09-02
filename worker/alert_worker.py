import asyncio
from datetime import datetime, timedelta
from utils.db_utils import db
from storage import sm,rm
from utils.utils import log, save_frames_as_video
import pandas as pd
import cv2


async def alert_worker():
    while True:
        pending_alerts = pd.DataFrame(db.get_pending_alerts())
        if pending_alerts.empty:
            log("INFO", "[ALERT] 当前无待报警记录，休眠2秒")
            await asyncio.sleep(2)
            continue

        grouped = pending_alerts.groupby(['stream_uid', 'fence_uid'])
        for (stream_uid, fence_uid), group in grouped:
            stream_info = sm.get_stream(stream_uid)
            stream_name = stream_info.get("name", stream_uid) if stream_info else stream_uid
            log("INFO", f"[ALERT] {stream_name} (UID={stream_uid}), 围栏 {fence_uid}, 待报警记录 {len(group)}")

            # 获取所有绑定该 stream 的接收人
            recipients = rm.get_recipients_by_stream_id(stream_uid)

            for _, alert in group.iterrows():
                detection_id = alert.get("id")
                timestamp = datetime.fromisoformat(alert.get("timestamp"))
                log("INFO", f"[ALERT] 处理 DETECTION_ID={detection_id}, TIMESTAMP={timestamp}")

                # 获取前10秒的帧生成报警视频
                start_ts = timestamp - timedelta(seconds=10)
                end_ts = timestamp
                frames_10s = pd.DataFrame(
                    db.get_detected_frames_by_stream_and_time(stream_uid, fence_uid, start_ts, end_ts)
                )
                video_frames = []
                for idx, row in frames_10s.iterrows():
                    frame_path = row['frame_path']
                    frame = cv2.imread(frame_path)
                    if frame is None:
                        log("FAIL", f"[ALERT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}) 读取帧失败: {frame_path}")
                        continue
                    video_frames.append(frame)

                if not video_frames:
                    log("WARNING", f"[ALERT] {stream_name} (UID={stream_uid}) 无可用帧生成报警视频，跳过 DETECTION_ID={detection_id}")
                    continue

                video_url, video_path = save_frames_as_video(stream_uid, fence_uid, video_frames, fps=1)
                log("INFO", f"[ALERT] {stream_name} 报警视频生成完成: {video_path}")

                # 触发报警（这里用循环调用接收人 contact，可以替换为实际发送接口）
                alert_status = -1
                for r in recipients:
                    try:
                        contact = r.get("contact")
                        # send_alert(contact, stream_name, fence_uid, video_path)
                        log("INFO", f"[ALERT] 已向接收人 {r['name']} ({contact}) 发送报警")
                        alert_status = 1
                    except Exception as e:
                        log("FAIL", f"[ALERT] 向接收人 {r['name']} ({contact}) 发送报警失败: {e}")

                # 更新数据库
                db.update_alerted(
                    detection_id=detection_id,
                    alerted=alert_status,
                    alert_time=datetime.now(),
                    alert_video_path=video_path
                )
                log("INFO", f"[ALERT] {stream_name} 数据库更新完成 DETECTION_ID={detection_id}, ALERTED={alert_status}")


async def run_alert_module():
    alert_task = asyncio.create_task(alert_worker())
    await alert_task


if __name__ == "__main__":
    asyncio.run(run_alert_module())
