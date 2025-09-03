import asyncio
from datetime import datetime, timedelta
from utils.db_utils import db
from storage import sm
from utils.ai_utils import extract_json_dict_from_ai_reply, call_local_ai_model, call_qwen_via_client
from utils.utils import log, save_frames_as_video, draw_fence_on_frame, save_key_frames
import pandas as pd
import cv2
from config import BASE_URL


async def ai_worker():
    while True:
        pending_alerts = pd.DataFrame(db.get_pending_ai_checked())
        if pending_alerts.empty:
            log("INFO", "[AI] 当前无待处理异常记录，休眠2秒")
            await asyncio.sleep(2)
            continue
        grouped = pending_alerts.groupby(['stream_uid', 'fence_uid'])
        for (stream_uid, fence_uid), group in grouped:
            # 获取 stream_name，可以从存储管理器 sm 获取
            stream_info = sm.get_stream(stream_uid)
            stream_name = stream_info.get("name", stream_uid) if stream_info else stream_uid
            log("INFO", f"[AI] {stream_name} (UID={stream_uid}), 围栏 {fence_uid}, 记录数 {len(group)}")
            for _, alert in group.iterrows():
                detection_id = alert.get("id")
                timestamp = datetime.fromisoformat(alert.get("timestamp"))
                log("INFO", f"[AI] 处理 DETECTION_ID={detection_id}, TIMESTAMPE={timestamp}")
                start_ts = timestamp - timedelta(seconds=10)
                end_ts = timestamp
                frames_10s = pd.DataFrame(db.get_detected_frames_by_stream_and_time(stream_uid, fence_uid, start_ts, end_ts))
                log("INFO", f"[AI] 检索到 {len(frames_10s)} 帧用于AI分析")
                video_frames = []
                for idx, row in frames_10s.iterrows():
                    frame_path = row['frame_path']
                    frame = cv2.imread(frame_path)
                    if frame is None:
                        log("FAIL", f"[AI] {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}) 读取帧失败: {frame_path}")
                        continue
                    video_frames.append(frame)
                if not video_frames:
                    log("WARNING", f"[AI] {stream_name} (UID={stream_uid}) 无可用帧生成视频，跳过 DETECTION_ID={detection_id}")
                    continue
                video_url, video_path = save_frames_as_video(stream_uid, fence_uid, video_frames, base_url=BASE_URL, fps=1)
                image_urls, image_paths = save_key_frames(stream_uid, fence_uid, video_frames, base_url=BASE_URL)
                log("INFO", f"[AI] {stream_name} 视频生成完成: {video_path}")
                try:
                    ai_result = call_local_ai_model(video_path=video_path)
                    if not ai_result:
                        log("WARNING", f"[AI] {stream_name} AI识别返回空结果 DETECTION_ID={detection_id}")
                        ai_status = -1
                    else:
                        log("INFO", f"[AI] {stream_name} AI识别结果: {ai_result}")
                        ai_status = 1 if ai_result.get("status") != "正常" else 0
                except Exception as e:
                    log("FAIL", f"[AI] {stream_name} AI识别失败 DETECTION_ID={detection_id}, ERROR={e}")
                    ai_result = {"ERROR": str(e)}
                    ai_status = -1
                db.update_ai_result(
                    detection_id=detection_id,
                    ai_checked=1,
                    ai_status=ai_status,
                    ai_result=str(ai_result),
                    before_image_path=image_paths[0],
                    after_image_path=image_paths[1],
                    alert_video_path=video_path,
                )
                log("INFO", f"[AI] {stream_name} 数据库更新完成 DETECTION_ID={detection_id}, AI_STATUS={ai_status}")
                await asyncio.sleep(1)


async def run_ai_module():
    ai_task = asyncio.create_task(ai_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_ai_module())
