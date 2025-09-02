import asyncio
import cv2
import os
from datetime import datetime
from db_utils import DBHelper
from storage import StorageManager
from video_monitor.fence_detector import FenceChangeDetector
from utils import log, resize_to_720p, draw_fence_on_frame, save_frames_as_video
import pandas as pd

storage_manger = StorageManager()
detector = FenceChangeDetector()
db = DBHelper()
detect_queue = asyncio.Queue()
capture_path = "tmp/capture"
detect_path = "tmp/detect"
merge_path = "tmp/merge"
change_threshold = 0.2
RESTART_INTERVAL = 10  # 秒，每1小时重启一次


# ------------------ 抓帧模块 ------------------
async def capture_stream(stream):
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
                    await detect_queue.put((detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp))
            else:
                log("FAIL", f"[抓帧] 抓取视频帧失败: {stream_name} ({stream_uid}), 保存路径={frame_path}")
        else:
            log("WARNING", f"[抓帧] 读取视频帧失败: {stream_name} ({stream_uid})")
        await asyncio.sleep(1)


# ------------------ 异常检测模块 ------------------
async def detect_worker():
    while True:
        detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp = await detect_queue.get()
        if detecting:
            frame = cv2.imread(frame_path)
            if frame is None:
                log("FAIL", f"[检测] {stream_name} (UID={stream_uid}, FRENCE_UID={fence_id}) 读取帧失败: {frame_path}")
                db.insert_detection(stream_uid, group_uid, fence_id, 0, False, timestamp, frame_path, frame_id)
                detect_queue.task_done()
                continue
            height, width = frame.shape[:2]
            fence = storage_manger.get_fence(stream_uid, fence_id)
            fence_points = []
            points = fence.get('points', [])
            if len(points) >= 3:
                fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
            detector.set_fence(fence_points)
            changed, change_area, change_ratio = detector.detect_change(frame, change_threshold=0.1)
            change_ratio = round(change_ratio, 4)
            db.insert_detection(stream_uid, group_uid, fence_id, change_ratio, changed, timestamp, frame_path, frame_id)
            if 0 <= change_ratio <= 1:
                frame_path = f"{detect_path}/{stream_uid}_{fence_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
                frame = draw_fence_on_frame(frame, fence_points)
                cv2.imwrite(frame_path, frame)
                detect_queue.task_done()
                # log("SUCCESS", f"[检测] {stream_name} (UID={stream_uid}, FRENCE_UID={fence_id}) 变化率：{change_ratio} 检测结果: {'异常' if changed else '正常'}")
            await asyncio.sleep(0)


# ------------------ 编组合成视频模块 ------------------
async def merge_worker():
    while True:
        groups = storage_manger.list_groups()
        log("INFO", f"当前存在的组: {list(groups.keys())}")
        for group_uid in groups.keys():
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
                    stream_uid = row['stream_uid']
                    frame_path = row['frame_path']
                    log("INFO", f"读取帧: {frame_path} (stream: {stream_uid})")
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
                db.mark_as_exported(frame_data['id'].tolist())
                size = os.path.getsize(video_path)
                duration = len(video_frames) / 1  # fps=1
                db.insert_merged_video(stream_uid, group_uid, '0', video_path, duration, size, datetime.now())
        await asyncio.sleep(10)


def get_fuse_bool_time_range(streams_frames, fuse_bool):
    """
    streams_frames: {stream_uid: {frame_id: timestamp_str}}
    fuse_bool: {stream_uid: {frame_id: bool}}
    返回 fuse_bool 在 streams_frames 中的最大时间戳区间 (start_ts, end_ts)
    可能来自不同的 stream_uid
    """
    all_timestamps = []
    a_dt = {uid: {fid: datetime.fromisoformat(ts) for fid, ts in frames.items()}
            for uid, frames in streams_frames.items()}
    for uid, bool_dict in fuse_bool.items():
        if uid not in a_dt:
            continue
        for fid, flag in bool_dict.items():
            all_timestamps.append(a_dt[uid][fid])
    if not all_timestamps:
        return None  # 没有匹配的 True 帧
    start_ts = min(all_timestamps)
    end_ts = max(all_timestamps)
    return start_ts, end_ts


def get_stream_change_dict(group_streams_data):
    result = {}
    for stream_uid, frames in group_streams_data.items():
        stream_result = {}
        for fid, detect_frames in frames.items():
            stream_result[fid] = any(df.get("changed", False) for df in detect_frames)
        result[stream_uid] = dict(sorted(stream_result.items()))  # 按 frame_id 排序
    return result


def fuse_streams_by_position(streams_bool_dict):
    stream_keys = list(streams_bool_dict.keys())
    stream_lists = [list(v.values()) for v in streams_bool_dict.values()]
    max_len = max(len(lst) for lst in stream_lists)
    for lst in stream_lists:
        lst.extend([False] * (max_len - len(lst)))
    for i in range(max_len):
        if any(lst[i] for lst in stream_lists):
            for lst in stream_lists:
                lst[i] = True
    first_true_idx = None
    for i in range(max_len):
        if any(lst[i] for lst in stream_lists):
            first_true_idx = i
            break
    if first_true_idx is not None:
        stream_lists = [lst[first_true_idx:] for lst in stream_lists]
    else:
        first_true_idx = 0
    fused = {}
    for k, lst in zip(stream_keys, stream_lists):
        frame_ids = list(streams_bool_dict[k].keys())
        fused[k] = dict(zip(frame_ids[first_true_idx:], lst[:len(frame_ids) - first_true_idx]))
    if first_true_idx == 0 and all(not any(lst) for lst in stream_lists):
        status = "waiting"  # 全 False
    else:
        if all(lst[-1] for lst in stream_lists):
            status = "recording"  # 最后一帧 True
        else:
            status = "completed"  # 最后一帧 False
    return fused, status


def get_running_streams(storage_manger):
    streams = [stream for stream in storage_manger.list_streams() if stream.get("status") == "running"]
    if len(streams) == 0:
        log("WARNING", "当前没有运行的流，只在检测历史内查找合适的数据帧")
    return streams


# ------------------ 主程序 ------------------
async def run_system():
    global streams, detect_queue

    storage_manger = StorageManager()  # 重新加载 json 配置
    streams = get_running_streams(storage_manger)
    detect_queue = asyncio.Queue()

    # 启动任务
    capture_tasks = [asyncio.create_task(capture_stream(stream)) for stream in streams]
    detect_tasks = [asyncio.create_task(detect_worker()) for _ in range(3)]
    merge_task = asyncio.create_task(merge_worker())

    all_tasks = capture_tasks + detect_tasks + [merge_task]
    return all_tasks


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


async def main():
    streams = get_running_streams(storage_manger)
    # 每个视频流启动一个抓帧任务
    capture_tasks = [asyncio.create_task(capture_stream(stream)) for stream in streams]
    # 启动检测 worker
    detect_tasks = [asyncio.create_task(detect_worker()) for _ in range(3)]
    # 启动合成任务
    merge_task = asyncio.create_task(merge_worker())
    await asyncio.gather(*capture_tasks, *detect_tasks, merge_task)
    # await asyncio.gather(*capture_tasks, *detect_tasks)
    # await asyncio.gather(merge_task)
    # await asyncio.gather(*capture_tasks)


async def run(loop=False):
    if loop:
        await main_loop()
    else:
        await main()


if __name__ == "__main__":
    asyncio.run(run(loop=True))
