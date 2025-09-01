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
streams = [stream for stream in storage_manger.list_streams() if stream.get("status") == "running"]
detect_queue = asyncio.Queue()
capture_path = "tmp/capture"
detect_path = "tmp/detect"
merge_path = "tmp/merge"
change_threshold = 0.2


# ------------------ 抓帧模块 ------------------
async def capture_stream(stream):
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
                log("INFO", f"[抓帧] 抓取视频帧成功: {stream_name} ({stream_uid}), frame_id={frame_id}")
                for fence_id in fences:
                    await detect_queue.put((stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp))
            else:
                log("FAIL", f"[抓帧] 抓取视频帧失败: {stream_name} ({stream_uid}), 保存路径={frame_path}")
        else:
            log("WARNING", f"[抓帧] 读取视频帧失败: {stream_name} ({stream_uid})")
        await asyncio.sleep(1)


# ------------------ 异常检测模块 ------------------
async def detect_worker():
    while True:
        stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp = await detect_queue.get()
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
        changed, change_area, change_ratio = detector.detect_change(frame)
        change_ratio = round(change_ratio, 4)
        db.insert_detection(stream_uid, group_uid, fence_id, change_ratio, changed, timestamp, frame_path, frame_id)
        if 0 <= change_ratio <= 1:
            frame_path = f"{detect_path}/{stream_uid}_{fence_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
            frame = draw_fence_on_frame(frame, fence_points)
            cv2.imwrite(frame_path, frame)
            detect_queue.task_done()
            log("INFO", f"[检测] {stream_name} (UID={stream_uid}, FRENCE_UID={fence_id}) 变化率：{change_ratio} 检测结果: {'异常' if changed else '正常'}")
        await asyncio.sleep(0)


# ------------------ 编组合成视频模块 ------------------
async def merge_worker():
    while True:
        groups = storage_manger.list_groups()
        log("INFO", f"当前存在的组: {list(groups.keys())}")
        for group_uid in groups.keys():
            log("INFO", f"处理组: {group_uid}")
            frame_data = pd.DataFrame(db.get_detections(group_uid=group_uid))
            log("INFO", f"获取到的检测数据行数: {len(frame_data)}")
            group_streams_data = {}
            for _, row in frame_data.iterrows():
                stream_uid = row["stream_uid"]
                frame_id = row["frame_id"]
                detect_frame = row.to_dict()
                group_streams_data.setdefault(stream_uid, {})
                group_streams_data[stream_uid].setdefault(frame_id, [])
                group_streams_data[stream_uid][frame_id].append(detect_frame)
            log("INFO", f"组 {group_uid} 的流数据组装完成, 流数量: {len(group_streams_data)}")
            streams_bool = get_stream_change_dict(group_streams_data)
            log("INFO", f"streams_bool 生成完成: { {k: list(v.values())[:5] for k, v in streams_bool.items()} } (仅前5帧示例)")
            fuse_bool = fuse_streams_by_position(streams_bool)
            log("INFO", f"fuse_bool 生成完成: { {k: list(v.values())[:5] for k, v in fuse_bool.items()} } (仅前5帧示例)")
            for stream_uid, frame_bool in fuse_bool.items():
                export_frame_id = slice_bool_dict(frame_bool).keys()
                log("INFO", f"stream {stream_uid} 需要导出的帧ID数量: {len(list(export_frame_id))}")
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
                    out_file = f"{stream_uid}_{idx}.jpg"
                    success = cv2.imwrite(out_file, frame)
                    if success:
                        log("SUCCESS", f"保存帧成功: {out_file}")
                    else:
                        log("FAIL", f"保存帧失败: {out_file}")
                    video_frames.append(frame)
                log("INFO", f"开始生成视频, 帧数量: {len(video_frames)}")
                video_url, video_path = save_frames_as_video(stream_uid, '0', video_frames, fps=1)
                log("SUCCESS", f"视频生成完成: {video_path}")
                exit()
                # 插入视频合成表
                size = os.path.getsize(video_name)
                duration = len(video_segment[0]) / 5  # fps=5
                db.insert_merged_video(stream_uid, group_uid, fence_uid, video_name, duration, size, datetime.now())
                log("INFO", f"[合成] 合成视频完成: {video_name}, 帧数={len(video_segment[0])}")
                # 标记为“已导出”
                for frame in video_segment[0]:
                    db.update_detect_status(frame['id'], "exported")
        await asyncio.sleep(10)


def slice_bool_dict(bool_dict):
    """
    :param bool_dict: dict {frame_id: bool}, 已按 frame_id 排序
    :return: dict {frame_id: bool} 截取片段
    """
    keys = list(bool_dict.keys())
    values = list(bool_dict.values())
    try:
        start_idx = values.index(True)
    except ValueError:
        return {}
    end_idx = start_idx
    for i in range(start_idx + 1, len(values)):
        if not values[i] and not values[i - 1]:
            break
        end_idx = i
    sliced_keys = keys[start_idx:end_idx]
    return {k: bool_dict[k] for k in sliced_keys}


def get_stream_change_dict(group_streams_data):
    """
    :param group_streams_data: dict, {stream_uid: {frame_id: [detect_frame, ...]}}
    :return: dict {stream_uid: {frame_id: bool}}, 每个 stream_uid 对应自己的 frame_id -> bool
    """
    result = {}
    for stream_uid, frames in group_streams_data.items():
        stream_result = {}
        for fid, detect_frames in frames.items():
            stream_result[fid] = any(df.get("changed", False) for df in detect_frames)
        result[stream_uid] = dict(sorted(stream_result.items()))  # 按 frame_id 排序
    return result


def fuse_streams_by_position(streams_bool_dict):
    """
    按同一顺位融合布尔值：
    - streams 按 list 顺序遍历
    - 每个 stream 内的 bool 按顺序对应
    """
    stream_keys = list(streams_bool_dict.keys())
    # 找出每个 stream 的 bool 列表长度
    stream_lists = [list(v.values()) for v in streams_bool_dict.values()]
    max_len = max(len(lst) for lst in stream_lists)
    for lst in stream_lists:
        lst.extend([False] * (max_len - len(lst)))
    for i in range(max_len):
        if any(lst[i] for lst in stream_lists):
            for lst in stream_lists:
                lst[i] = True
    fused = {}
    for k, lst in zip(stream_keys, stream_lists):
        frame_ids = list(streams_bool_dict[k].keys())
        fused[k] = dict(zip(frame_ids, lst[:len(frame_ids)]))
    return fused


# ------------------ 主程序 ------------------
async def main():
    # 每个视频流启动一个抓帧任务
    capture_tasks = [asyncio.create_task(capture_stream(stream)) for stream in streams]

    # 启动检测 worker
    detect_tasks = [asyncio.create_task(detect_worker()) for _ in range(3)]

    # 启动合成任务
    merge_task = asyncio.create_task(merge_worker())

    # await asyncio.gather(*capture_tasks, *detect_tasks, merge_task)
    # await asyncio.gather(*capture_tasks, *detect_tasks)
    # await asyncio.gather(merge_task)
    # await asyncio.gather(*capture_tasks)


if __name__ == "__main__":
    asyncio.run(main())
