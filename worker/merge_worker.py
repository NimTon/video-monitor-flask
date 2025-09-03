import asyncio
import os
import uuid
from datetime import datetime
import cv2
import pandas as pd
from utils.db_utils import db
from utils.stream_utils import get_stream_change_dict, fuse_streams_by_position, get_fuse_bool_time_range
from utils.utils import log, draw_fence_on_frame, save_frames_as_video
from storage import sm

merge_path = "./tmp/merge"
os.makedirs(merge_path, exist_ok=True)


# ------------------ 编组合成视频模块 ------------------
async def merge_worker():
    while True:
        groups = sm.list_groups()
        log("INFO", f"[MERGE] 当前存在的组: {list(groups.keys())}")
        for group_uid in groups.keys():
            group_event_uid = None
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
            captured_frames = pd.DataFrame(db.get_group_frames(group_uid))
            streams_frames = {uid: {int(idx): timestamp for idx, timestamp in zip(captured_frames[captured_frames['stream_uid'] == uid]['id'].values, captured_frames[captured_frames['stream_uid'] == uid]['timestamp'].values)} for uid in set(captured_frames['stream_uid'])}
            start_ts, end_ts = get_fuse_bool_time_range(streams_frames, fuse_bool)
            for stream_uid in streams_frames.keys():
                export_frame_id = pd.DataFrame(db.get_frames_by_stream_and_time(stream_uid, start_ts, end_ts))['id'].values
                log("INFO", f"[MERGE] stream {stream_uid} 需要导出的帧数量: {len(list(export_frame_id))}")
                unique_frame_data = frame_data.drop_duplicates(subset='frame_id', keep='first')
                export_frame_index = unique_frame_data['frame_id'].isin(export_frame_id)
                video_frames = []
                frames = unique_frame_data.loc[export_frame_index, ['stream_uid', 'frame_path']]
                log("INFO", f"[MERGE] stream {stream_uid} 对应帧数量: {len(frames)}")
                for idx, row in frames.iterrows():
                    frame_path = row['frame_path']
                    # log("INFO", f"[MERGE] 读取帧: {frame_path} (stream: {stream_uid})")
                    frame = cv2.imread(frame_path)
                    if frame is None:
                        log("WARNING", f"[MERGE] 读取帧失败: {frame_path}")
                        continue
                    height, width = frame.shape[:2]
                    fences = sm.list_fences(stream_uid)
                    for fence in fences:
                        fence_points = []
                        points = fence.get('points', [])
                        if len(points) >= 3:
                            fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
                        frame = draw_fence_on_frame(frame, fence_points)
                    out_file = f"{merge_path}/{stream_uid}_{idx}.jpg"
                    success = cv2.imwrite(out_file, frame)
                    if success:
                        # log("SUCCESS", f"[MERGE] 保存帧成功: {out_file}")
                        pass
                    else:
                        log("FAIL", f"[MERGE] 保存帧失败: {out_file}")
                    video_frames.append(frame)
                log("INFO", f"[MERGE] 开始生成视频, 帧数量: {len(video_frames)}")
                video_url, video_path = save_frames_as_video(stream_uid, '0', video_frames, fps=1)
                log("SUCCESS", f"[MERGE] 视频生成完成: {video_path}")
                event_uid = str(uuid.uuid4())
                if not group_event_uid:
                    group_event_uid = str(uuid.uuid4())
                db.mark_as_exported(frame_data['id'].tolist(), event_uid, group_event_uid)
                size = os.path.getsize(video_path)
                duration = len(video_frames) / 1  # fps=1
                db.insert_merged_video(stream_uid, group_uid, '0', video_path, duration, size, datetime.now(), event_uid, group_event_uid)
        await asyncio.sleep(10)


async def run_emergency_module():
    ai_task = asyncio.create_task(merge_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_emergency_module())
