import asyncio
import cv2
import pandas as pd
from utils.db_utils import db
from utils.utils import log, save_frames_as_video, save_key_frames, get_first_changed_row
from storage import sm
from config import BASE_URL


# ------------------ 编组合成视频模块 ------------------
async def merge_worker():
    while True:
        streams = sm.list_streams()
        for stream in streams:
            stream_uid = stream["uid"]
            stream_name = stream.get("name")
            fence_uids = [fence['id'] for fence in stream.get('fences')]
            for fence_uid in fence_uids:
                detect_fence_frame = pd.DataFrame(db.get_changed_and_pending_export_frames_by_stream_fence(stream_uid, fence_uid)).copy()
                if len(detect_fence_frame) == 0:
                    log("INFO", f"[MERGE] 流 {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}) 未检测到异常，跳过")
                    continue
                detect_fence_frame['timestamp'] = pd.to_datetime(detect_fence_frame['timestamp'])
                first_changed_row = get_first_changed_row(detect_fence_frame)
                for _, first_row in first_changed_row.iterrows():
                    end_ts = first_row['timestamp']
                    start_ts = end_ts - pd.Timedelta(seconds=10)
                    export_detected_frames = pd.DataFrame(db.get_detected_frames_by_stream_fence_and_time(stream_uid, start_ts, end_ts, fence_uid=fence_uid))
                    if len(export_detected_frames) < 10:
                        log("INFO", f"[MERGE] 流 {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}) 的回放帧不足 10 张(现有 {len(export_detected_frames)} 张)，跳过")
                        continue
                    log("INFO", f"[MERGE] stream {stream_uid} 需要导出的帧数量: {len(export_detected_frames)}")
                    video_frames = []
                    for idx, row in export_detected_frames.iterrows():
                        frame_path = row['frame_path']
                        # log("INFO", f"[MERGE] 读取帧: {frame_path} (stream: {stream_uid})")
                        frame = cv2.imread(frame_path)
                        if frame is None:
                            log("WARNING", f"[MERGE] 读取帧失败: {frame_path}")
                            continue
                        video_frames.append(frame)
                    log("INFO", f"[MERGE] 开始生成视频, 帧数量: {len(video_frames)}")
                    video_url, video_path = save_frames_as_video(stream_uid, fence_uid, video_frames, fps=1)
                    image_urls, image_paths = save_key_frames(stream_uid, fence_uid, video_frames, base_url=BASE_URL)
                    log("SUCCESS", f"[MERGE] 视频生成完成: {video_path}")
                    db.update_media_paths(detect_fence_frame['id'].tolist()[0],
                                          before_image_path=image_paths[0],
                                          after_image_path=image_paths[1],
                                          alert_video_path=video_path)
                db.mark_as_exported(detect_fence_frame['id'].tolist())
        await asyncio.sleep(10)


async def run_emergency_module():
    ai_task = asyncio.create_task(merge_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_emergency_module())
