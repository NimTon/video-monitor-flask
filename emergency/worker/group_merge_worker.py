import asyncio
import os
import shutil
import uuid
from datetime import datetime
import cv2
import pandas as pd
from utils.db_utils import db
from utils.stream_utils import get_stream_change_dict, fuse_streams_by_position, get_fuse_bool_time_range
from utils.utils import draw_fence_on_frame, save_frames_as_video
from utils.log_utils import log
from storage import sm

merge_path = "./tmp/merge"
os.makedirs(merge_path, exist_ok=True)


# ------------------ 编组合成视频模块 ------------------
async def group_merge_worker():
    while True:
        groups = sm.list_groups()
        log("INFO", f"[GROUP MERGE] 当前存在的组: {list(groups.keys())}")
        for group_uid in groups.keys():
            group_event_uid = str(uuid.uuid4())
            log("INFO", f"[GROUP MERGE] 处理组: {group_uid}")
            frame_data = pd.DataFrame(db.get_group_pending_exports(group_uid=group_uid))
            log("INFO", f"[GROUP MERGE] 获取到的检测数据帧数: {len(frame_data)}")
            group_streams_data = {}
            for _, row in frame_data.iterrows():
                stream_uid = row["stream_uid"]
                frame_id = row["frame_id"]
                detect_frame = row.to_dict()
                group_streams_data.setdefault(stream_uid, {})
                group_streams_data[stream_uid].setdefault(frame_id, [])
                group_streams_data[stream_uid][frame_id].append(detect_frame)
            if len(group_streams_data) == 0:
                log("INFO", f"[GROUP MERGE] 组 {group_uid} 的流数据为空，等待下一轮检测")
                await asyncio.sleep(10)
                continue
            total_frames = max(len(frames) for frames in group_streams_data.values())
            log("INFO", f"[GROUP MERGE] 组 {group_uid} 的流数据组装完成，单视频流帧数量: {total_frames}")
            streams_bool = get_stream_change_dict(group_streams_data)
            fuse_bool, status = fuse_streams_by_position(streams_bool)
            if status == "completed":
                log("INFO", f"[GROUP MERGE] 组 {group_uid} 的流数据录制结束，准备处理帧数据")
            elif status == "recording":
                log("INFO", f"[GROUP MERGE] 组 {group_uid} 的流数据录制中，等待检测正常后再处理")
                await asyncio.sleep(10)
                continue
            elif status == "waiting":
                log("INFO", f"[GROUP MERGE] 组 {group_uid} 的流数据尚未开始录制，等待检测异常出现")
                await asyncio.sleep(10)
                continue
            captured_frames = pd.DataFrame(db.get_group_frames(group_uid))
            streams_frames = {uid: {int(idx): timestamp for idx, timestamp in zip(captured_frames[captured_frames['stream_uid'] == uid]['id'].values, captured_frames[captured_frames['stream_uid'] == uid]['timestamp'].values)} for uid in set(captured_frames['stream_uid'])}
            start_ts, end_ts = get_fuse_bool_time_range(streams_frames, fuse_bool)
            for stream_uid in streams_frames.keys():
                stream_name = sm.get_stream(stream_uid).get("name")
                export_frame_df = pd.DataFrame(db.get_frames_by_stream_and_time(stream_uid, start_ts, end_ts))
                if not export_frame_df.empty and 'id' in export_frame_df.columns:
                    export_frame_id = export_frame_df['id'].values
                    log("INFO", f"[GROUP MERGE] stream {stream_uid} 需要导出的帧数量: {len(list(export_frame_id))}")
                else:
                    log("WARN", f"[GROUP MERGE] stream {stream_uid} 在时间段 {start_ts} - {end_ts} 没有可用帧，跳过")
                    await asyncio.sleep(10)
                    continue
                unique_frame_data = frame_data.drop_duplicates(subset='frame_id', keep='first')
                export_frame_index = unique_frame_data['frame_id'].isin(export_frame_id)
                video_frames = []
                frames = unique_frame_data.loc[export_frame_index, ['stream_uid', 'frame_path']]
                log("INFO", f"[GROUP MERGE] stream {stream_uid} 对应帧数量: {len(frames)}")
                before_image_path = None
                frame_path = None
                for idx, row in frames.iterrows():
                    frame_path = row['frame_path']
                    if before_image_path is None:
                        filename = os.path.basename(frame_path)
                        before_image_path = f"images/{stream_uid}/{filename}"
                        os.makedirs(f"images/{stream_uid}", exist_ok=True)
                        shutil.copy(frame_path, before_image_path)
                    log("INFO", f"[GROUP MERGE] 读取帧: {frame_path} (stream: {stream_uid})")
                    frame = cv2.imread(frame_path)
                    if frame is None:
                        log("WARN", f"[GROUP MERGE] 读取帧失败: {frame_path}")
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
                        log("SUCCESS", f"[GROUP MERGE] 保存帧成功: {out_file}")
                        pass
                    else:
                        log("FAIL", f"[GROUP MERGE] 保存帧失败: {out_file}")
                    video_frames.append(frame)
                if len(video_frames) == 0:
                    log("WARN", f"[GROUP MERGE] 组 {group_uid} 的流 {stream_uid} 没有可用帧，跳过")
                    continue
                filename = os.path.basename(frame_path)
                after_image_path = f"images/{stream_uid}/{filename}"
                shutil.copy(frame_path, after_image_path)
                log("INFO", f"[GROUP MERGE] 开始生成视频, 帧数量: {len(video_frames)}")
                video_url, video_path = save_frames_as_video(stream_uid, '0', video_frames, fps=1)
                log("SUCCESS", f"[GROUP MERGE] 视频生成完成: {video_path}")
                event_uid = str(uuid.uuid4())


                frame_data['timestamp'] = pd.to_datetime(frame_data['timestamp'], format='ISO8601', errors='coerce')

                # 移除无法解析的时间数据
                frame_data = frame_data.dropna(subset=['timestamp'])

                # 确保时间列存在
                if 'timestamp' not in frame_data.columns:
                    log("WARN", "[GROUP MERGE] 时间列不存在，跳过当前处理")
                    continue

                start_ts, end_ts = get_fuse_bool_time_range(streams_frames, fuse_bool)
                if start_ts is None or end_ts is None:
                    log("WARN", "[GROUP MERGE] 无法获取有效时间范围，跳过")
                    continue

                # 修改标记导出的逻辑
                if not frame_data.empty:
                    # 确保时间比较有效
                    valid_frames = frame_data[frame_data['timestamp'] <= end_ts]
                    if not valid_frames.empty:
                        db.mark_as_group_exported(valid_frames['id'].tolist(), event_uid, group_event_uid)

                db.mark_as_group_exported(frame_data[frame_data['timestamp'] <= end_ts]['id'].tolist(), event_uid, group_event_uid)
                size = os.path.getsize(video_path)
                duration = len(video_frames) / 1  # fps=1
                db.insert_merged_video(stream_name, stream_uid, group_uid, '0', video_path, before_image_path, after_image_path, duration, size, datetime.now(), event_uid, group_event_uid)
            db.mark_video_as_exported(group_event_uid)
        await asyncio.sleep(10)


async def run_emergency_module():
    ai_task = asyncio.create_task(group_merge_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_emergency_module())
