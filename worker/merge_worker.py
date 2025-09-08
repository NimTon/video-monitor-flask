import asyncio
import os
import cv2
import pandas as pd
from utils.db_utils import db
from utils.stream_utils import get_stream_change_dict, fuse_streams_by_position
from utils.utils import log, save_frames_as_video, save_key_frames
from storage import sm
from config import BASE_URL

merge_path = "./tmp/merge"
os.makedirs(merge_path, exist_ok=True)


# ------------------ 编组合成视频模块 ------------------
async def merge_worker():
    while True:
        groups = sm.list_groups()
        log("INFO", f"[MERGE] 当前存在的组: {list(groups.keys())}")
        for group_uid in groups.keys():
            log("INFO", f"[MERGE] 处理组: {group_uid}")
            frame_data = pd.DataFrame(db.get_pending_exports(group_uid=group_uid))
            log("INFO", f"[MERGE] 获取到的检测数据帧数: {len(frame_data)}")
            group_streams_data = {}
            for _, row in frame_data.iterrows():
                stream_uid = row["stream_uid"]
                frame_id = row["frame_id"]
                detect_frame = row.to_dict()
                group_streams_data.setdefault(stream_uid, {})
                group_streams_data[stream_uid].setdefault(frame_id, [])
                group_streams_data[stream_uid][frame_id].append(detect_frame)
            if len(group_streams_data) == 0:
                log("INFO", f"[MERGE] 组 {group_uid} 的流数据为空，等待下一轮检测")
                await asyncio.sleep(10)
                continue
            total_frames = max(len(frames) for frames in group_streams_data.values())
            log("INFO", f"[MERGE] 组 {group_uid} 的流数据组装完成，单视频流帧数量: {total_frames}")
            streams_bool = get_stream_change_dict(group_streams_data)
            fuse_bool, status = fuse_streams_by_position(streams_bool)
            if status == "completed":
                log("INFO", f"[MERGE] 组 {group_uid} 的流数据录制结束，准备处理帧数据")
            elif status == "recording":
                log("INFO", f"[MERGE] 组 {group_uid} 的流数据录制中，等待检测正常后再处理")
                await asyncio.sleep(10)
                continue
            elif status == "waiting":
                log("INFO", f"[MERGE] 组 {group_uid} 的流数据尚未开始录制，等待检测异常出现")
                await asyncio.sleep(10)
                continue
            for stream_uid in group_streams_data.keys():
                fence_uids = [fence['id'] for fence in sm.get_stream(stream_uid).get('fences')]
                for fence_uid in fence_uids:
                    detect_fence_frame = frame_data[frame_data['fence_uid'] == fence_uid]
                    detect_fence_frame['timestamp'] = pd.to_datetime(detect_fence_frame['timestamp'])
                    first_changed_row = detect_fence_frame[detect_fence_frame['changed'] == True].iloc[0]
                    end_ts = first_changed_row['timestamp']
                    start_ts = end_ts - pd.Timedelta(seconds=10)
                    export_detected_frame_id = pd.DataFrame(db.get_detected_frames_by_stream_fence_and_time(stream_uid, start_ts, end_ts, fence_uid=fence_uid))['id'].values
                    log("INFO", f"[MERGE] stream {stream_uid} 需要导出的帧数量: {len(list(export_detected_frame_id))}")
                    video_frames = []
                    for idx, row in export_detected_frame_id.iterrows():
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
                    db.mark_as_exported(frame_data['id'].tolist())
                    db.update_media_paths(frame_data['id'].tolist(),
                                          before_image_path=image_paths[0],
                                          after_image_path=image_paths[1],
                                          alert_video_path=video_path)
        await asyncio.sleep(10)


async def run_emergency_module():
    ai_task = asyncio.create_task(merge_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_emergency_module())
