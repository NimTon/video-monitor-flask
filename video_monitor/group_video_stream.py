import asyncio
import cv2
import os
from datetime import datetime
from db_utils import DBHelper
from storage import StorageManager
from video_monitor.fence_detector import FenceChangeDetector
from utils import log

storage_manger = StorageManager()
detector = FenceChangeDetector()
db = DBHelper()

# 激活的视频流列表
streams = [stream for stream in storage_manger.list_streams() if stream.get("status") == "running"]

# 队列用于模块间异步通信
frame_queue = asyncio.Queue()
detect_queue = asyncio.Queue()


# ------------------ 抓帧模块 ------------------
async def capture_stream(stream):
    stream_uid = stream.get("uid")
    stream_name = stream.get("name", stream_uid)
    group_id = stream.get("group_id")
    url = stream.get("stream_url")

    os.makedirs("tmp", exist_ok=True)
    cap = cv2.VideoCapture(url)

    while True:
        ret, frame = cap.read()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if ret:
            frame_path = f"tmp/{stream_uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            success = cv2.imwrite(frame_path, frame)

            if success:
                log("INFO", f"抓取视频流成功: {stream_name} (UID={stream_uid}), 时间={timestamp}, 保存路径={frame_path}")
                # 插入数据库
                frame_id = db.insert_frame(stream_uid, group_id, datetime.now(), frame_path)
                await detect_queue.put(frame_id)
            else:
                log("FAIL", f"抓取视频流失败: {stream_name} (UID={stream_uid}), URL={url}, PATH={frame_path}")
        else:
            log("WARNING", f"读取视频帧失败: {stream_name} (UID={stream_uid}), URL={url}")

        await asyncio.sleep(1)  # 按 buffer_fps 控制抓帧间隔



# ------------------ 异常检测模块 ------------------
async def detect_worker(detectors):
    while True:
        frame_id = await detect_queue.get()

        pending_frames = db.get_pending_frames(limit=1)
        if not pending_frames:
            detect_queue.task_done()
            await asyncio.sleep(0.5)
            continue

        frame_record = pending_frames[0]
        frame_path = frame_record["frame_path"]
        stream_uid = frame_record["stream_uid"]

        detector = detectors.get(stream_uid)
        if detector is None:
            log("WARNING", f"[Detect] Stream {stream_uid} 没有 detector，标记为 normal")
            db.update_detect_status(frame_id, "normal")
            detect_queue.task_done()
            continue

        frame = cv2.imread(frame_path)
        if frame is None:
            log("FAIL", f"[Detect] 读取帧失败: {frame_path}, 标记为 normal")
            db.update_detect_status(frame_id, "normal")
            detect_queue.task_done()
            continue

        changed, area = detector.detect_change(frame, change_threshold=0.1, debug=False)
        status = "abnormal" if changed else "normal"
        log("INFO", f"[Detect] {stream_uid} 检测结果: {status}, 变化面积: {area} 像素, 路径: {frame_path}")

        db.update_detect_status(frame_id, status)
        detect_queue.task_done()
        await asyncio.sleep(0)



# ------------------ 合成视频模块 ------------------
async def merge_worker():
    while True:
        groups = {}  # group_id -> list of异常帧
        for stream_group in storage_manger.list_groups():  # 获取所有 group
            rows = db.get_abnormal_groups(stream_group)
            if rows:
                groups[stream_group] = rows

        for group_id, frames in groups.items():
            frame_paths = [r['frame_path'] for r in frames]
            if not frame_paths:
                continue

            os.makedirs("videos", exist_ok=True)
            video_name = f"videos/{group_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

            first_frame = cv2.imread(frame_paths[0])
            if first_frame is None:
                log("FAIL", f"[Merge] {group_id} 第一帧读取失败，跳过该组合成")
                continue

            h, w, _ = first_frame.shape
            out = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'mp4v'), 5, (w, h))
            log("INFO", f"[Merge] 开始合成视频: {video_name}, 帧数: {len(frame_paths)}")

            for path in frame_paths:
                img = cv2.imread(path)
                if img is not None:
                    if (img.shape[1], img.shape[0]) != (w, h):
                        img = cv2.resize(img, (w, h))
                    out.write(img)
                    log("DEBUG", f"[Merge] 写入帧: {path}")
                else:
                    log("WARNING", f"[Merge] 读取帧失败: {path}")

            out.release()
            log("INFO", f"[Merge] 视频合成完成: {video_name}")

            # 更新数据库合成状态
            for r in frames:
                db.update_merge_status(r['id'], 'merged')
                log("DEBUG", f"[Merge] 更新合成状态: frame_id={r['id']} -> merged")

        await asyncio.sleep(10)



# ------------------ 主程序 ------------------
async def main():
    # 每个视频流启动一个抓帧任务
    capture_tasks = [asyncio.create_task(capture_stream(stream)) for stream in streams]

    # 初始化 detector
    # detectors = {}
    # for stream in streams:
    #     stream_uid, fence_uid, group_id, url, points = stream
    #     det = FenceChangeDetector()
    #     det.set_fence(points)
    #     detectors[stream_uid] = det

    # 启动检测 worker
    # detect_tasks = [asyncio.create_task(detect_worker(detectors)) for _ in range(3)]

    # 启动合成任务
    # merge_task = asyncio.create_task(merge_worker())

    # await asyncio.gather(*capture_tasks, *detect_tasks, merge_task)

    await  asyncio.gather(capture_tasks)


if __name__ == "__main__":
    asyncio.run(main())
