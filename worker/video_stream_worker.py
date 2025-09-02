import asyncio
import uuid
import cv2
import os
from datetime import datetime
from utils.db_utils import db
from storage import StorageManager
from utils.stream_utils import get_fuse_bool_time_range, get_stream_change_dict, fuse_streams_by_position, get_running_streams, FenceChangeDetector
from utils.utils import log, resize_to_720p, draw_fence_on_frame, save_frames_as_video
import pandas as pd

storage_manger = StorageManager()
detector = FenceChangeDetector()
detect_queues = {}
capture_path = "./tmp/capture"
detect_path = "./tmp/detect"
merge_path = "./tmp/merge"
change_threshold = 0.2
RESTART_INTERVAL = 3600  # 秒，每1小时重启一次


# ------------------ 抓帧模块 ------------------
async def capture_stream(stream, queues):
    detecting = stream.get("detecting")
    stream_uid = stream.get("uid")
    stream_name = stream.get("name")
    group_uid = stream.get("group_uid")
    url = stream.get("stream_url")
    fences = [f['id'] for f in stream.get("fences", [])]
    os.makedirs(capture_path, exist_ok=True)
    os.makedirs(detect_path, exist_ok=True)
    os.makedirs(merge_path, exist_ok=True)
    cap = cv2.VideoCapture(url)
    while True:
        ret, frame = cap.read()
        if frame is None:
            log("WARNING", f"[抓帧] 读取到空帧: {stream_name} ({stream_uid})")
            await asyncio.sleep(1)
            continue
        frame = resize_to_720p(frame)
        timestamp = datetime.now()
        if ret:
            frame_path = f"{capture_path}/{stream_uid}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
            success = cv2.imwrite(frame_path, frame)
            if success:
                frame_id = db.insert_frame(stream_uid, group_uid, timestamp, frame_path)
                # log("SUCCESS", f"[抓帧] 抓取视频帧成功: {stream_name} ({stream_uid}), frame_id={frame_id}")
                for fence_id in fences:
                    await queues[(stream_uid, fence_id)].put((detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp))
            else:
                log("FAIL", f"[抓帧] 抓取视频帧失败: {stream_name} ({stream_uid}), 保存路径={frame_path}")
        else:
            log("WARNING", f"[抓帧] 读取视频帧失败: {stream_name} ({stream_uid})")
        await asyncio.sleep(1)


# ------------------ 异常检测模块 ------------------
async def detect_worker(queue):
    while True:
        detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp = await queue.get()
        if detecting:
            frame = cv2.imread(frame_path)
            if frame is None:
                log("FAIL", f"[检测] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}) 读取帧失败: {frame_path}")
                db.insert_detection(stream_uid, group_uid, fence_id, 0, False, timestamp, frame_path, frame_id)
                queue.task_done()
                continue
            height, width = frame.shape[:2]
            fence = storage_manger.get_fence(stream_uid, fence_id)
            fence_points = []
            points = fence.get('points', [])
            if len(points) >= 3:
                fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
            detector.set_fence(fence_points)
            changed, change_area, change_ratio = detector.detect_change(frame, change_threshold=0.0001)
            if 0 <= change_ratio <= 1:
                db.insert_detection(stream_uid, group_uid, fence_id, change_ratio, changed, timestamp, frame_path, frame_id)
                frame_path = f"{detect_path}/{stream_uid}_{fence_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
                frame = draw_fence_on_frame(frame, fence_points)
                cv2.imwrite(frame_path, frame)
                queue.task_done()
                # log("SUCCESS", f"[检测] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}, TIMESTAMPE={timestamp}) 变化率：{change_ratio:.2f} 检测结果: {'异常' if changed else '正常'}")
            await asyncio.sleep(0)


# ------------------ 编组合成视频模块 ------------------
async def merge_worker():
    while True:
        groups = storage_manger.list_groups()
        log("INFO", f"当前存在的组: {list(groups.keys())}")
        for group_uid in groups.keys():
            group_event_uid = None
            log("INFO", f"处理组: {group_uid}")
            frame_data = pd.DataFrame(db.get_pending_exports(group_uid=group_uid))
            log("INFO", f"获取到的检测数据帧数: {len(frame_data)}")
            group_streams_data = {}
            for _, row in frame_data.iterrows():
                stream_uid = row["stream_uid"]
                frame_id = row["frame_id"]
                detect_frame = row.to_dict()
                group_streams_data.setdefault(stream_uid, {})
                group_streams_data[stream_uid].setdefault(frame_id, [])
                group_streams_data[stream_uid][frame_id].append(detect_frame)
            if len(group_streams_data) == 0:
                log("INFO", f"组 {group_uid} 的流数据为空，等待下一轮检测")
                await asyncio.sleep(10)
                continue
            total_frames = max(len(frames) for frames in group_streams_data.values())
            log("INFO", f"组 {group_uid} 的流数据组装完成，单视频流帧数量: {total_frames}")
            streams_bool = get_stream_change_dict(group_streams_data)
            fuse_bool, status = fuse_streams_by_position(streams_bool)
            if status == "completed":
                log("INFO", f"组 {group_uid} 的流数据录制结束，准备处理帧数据")
            elif status == "recording":
                log("INFO", f"组 {group_uid} 的流数据录制中，等待检测正常后再处理")
                await asyncio.sleep(10)
                continue
            elif status == "waiting":
                log("INFO", f"组 {group_uid} 的流数据尚未开始录制，等待检测异常出现")
                await asyncio.sleep(10)
                continue
            captured_frames = pd.DataFrame(db.get_group_frames(group_uid))
            streams_frames = {uid: {int(idx): timestamp for idx, timestamp in zip(captured_frames[captured_frames['stream_uid'] == uid]['id'].values, captured_frames[captured_frames['stream_uid'] == uid]['timestamp'].values)} for uid in set(captured_frames['stream_uid'])}
            start_ts, end_ts = get_fuse_bool_time_range(streams_frames, fuse_bool)
            for stream_uid in streams_frames.keys():
                export_frame_id = pd.DataFrame(db.get_frames_by_stream_and_time(stream_uid, start_ts, end_ts))['id'].values
                log("INFO", f"stream {stream_uid} 需要导出的帧数量: {len(list(export_frame_id))}")
                unique_frame_data = frame_data.drop_duplicates(subset='frame_id', keep='first')
                export_frame_index = unique_frame_data['frame_id'].isin(export_frame_id)
                video_frames = []
                frames = unique_frame_data.loc[export_frame_index, ['stream_uid', 'frame_path']]
                log("INFO", f"stream {stream_uid} 对应帧数量: {len(frames)}")
                for idx, row in frames.iterrows():
                    frame_path = row['frame_path']
                    # log("INFO", f"读取帧: {frame_path} (stream: {stream_uid})")
                    frame = cv2.imread(frame_path)
                    if frame is None:
                        log("WARNING", f"读取帧失败: {frame_path}")
                        continue
                    height, width = frame.shape[:2]
                    fences = storage_manger.list_fences(stream_uid)
                    for fence in fences:
                        fence_points = []
                        points = fence.get('points', [])
                        if len(points) >= 3:
                            fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
                        frame = draw_fence_on_frame(frame, fence_points)
                    out_file = f"{merge_path}/{stream_uid}_{idx}.jpg"
                    success = cv2.imwrite(out_file, frame)
                    if success:
                        # log("SUCCESS", f"保存帧成功: {out_file}")
                        pass
                    else:
                        log("FAIL", f"保存帧失败: {out_file}")
                    video_frames.append(frame)
                log("INFO", f"开始生成视频, 帧数量: {len(video_frames)}")
                video_url, video_path = save_frames_as_video(stream_uid, '0', video_frames, fps=1)
                log("SUCCESS", f"视频生成完成: {video_path}")
                event_uid = str(uuid.uuid4())
                if not group_event_uid:
                    group_event_uid = str(uuid.uuid4())
                db.mark_as_exported(frame_data['id'].tolist(), event_uid, group_event_uid)
                size = os.path.getsize(video_path)
                duration = len(video_frames) / 1  # fps=1
                db.insert_merged_video(stream_uid, group_uid, '0', video_path, duration, size, datetime.now(), event_uid, group_event_uid)
        await asyncio.sleep(10)


# ------------------ 主程序 ------------------
async def run_system():
    global detect_queues
    log("INFO", "系统启动中...")
    storage_manger = StorageManager()
    log("INFO", "加载存储管理器完成")
    streams = get_running_streams(storage_manger)
    log("INFO", f"加载运行中的视频流: {len(streams)} 个")
    # 初始化 (stream_uid, fence_uid) 队列
    detect_queues = {}
    for stream in streams:
        for fence in stream.get("fences", []):
            detect_queues[(stream['uid'], fence['id'])] = asyncio.Queue()
    log("INFO", "检测队列初始化完成")
    # 抓帧任务
    capture_tasks = []
    for stream in streams:
        log("INFO", f"启动抓帧任务: {stream.get("name")} (UID={stream.get("uid")})")
        capture_tasks.append(asyncio.create_task(capture_stream(stream, detect_queues)))
    # 检测任务
    detect_tasks = []
    stream_names = {s['uid']: s['name'] for s in streams}
    for (stream_uid, fence_uid), queue in detect_queues.items():
        log("INFO", f"启动检测任务: {stream_names.get(stream_uid)} (UID={stream_uid}, FENCE_UID={fence_uid})")
        detect_tasks.append(asyncio.create_task(detect_worker(queue)))
    # 合成任务
    log("INFO", "启动合成任务")
    merge_task = asyncio.create_task(merge_worker())
    log("SUCCESS", "系统运行中...")
    return capture_tasks + detect_tasks + [merge_task]


async def main_loop():
    while True:
        log("INFO", f"系统启动: {datetime.now()}")
        tasks = await run_system()
        # 等待一小时或被取消
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=RESTART_INTERVAL)
        except asyncio.TimeoutError:
            log("INFO", f"达到重启周期: {datetime.now()}, 重启系统")
            # 取消所有任务
            for t in tasks:
                t.cancel()
            # 等待任务彻底取消
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(2)  # 防止立刻重启导致冲突


if __name__ == "__main__":
    asyncio.run(main_loop())
