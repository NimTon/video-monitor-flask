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
    stream_name = stream.get("name")
    group_uid = stream.get("group_uid")
    url = stream.get("stream_url")
    fences = [f['id'] for f in stream.get("fences", [])]

    os.makedirs("tmp", exist_ok=True)
    cap = cv2.VideoCapture(url)

    while True:
        ret, frame = cap.read()
        timestamp = datetime.now()
        if ret:
            frame_path = f"tmp/capture/{stream_uid}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
            success = cv2.imwrite(frame_path, frame)
            if success:
                # 插入抓帧表
                frame_id = db.insert_frame(stream_uid, group_uid, timestamp, frame_path)
                log("INFO", f"抓取视频帧成功: {stream_name} ({stream_uid}), frame_id={frame_id}")

                # 对每个围栏加入检测队列
                for fence_id in fences:
                    await detect_queue.put((frame_id, fence_id, frame_path, timestamp))
            else:
                log("FAIL", f"抓取视频帧失败: {stream_name} ({stream_uid}), 保存路径={frame_path}")
        else:
            log("WARNING", f"读取视频帧失败: {stream_name} ({stream_uid})")
        await asyncio.sleep(1)

# ------------------ 异常检测模块 ------------------
async def detect_worker(detectors):
    while True:
        frame_id, fence_id, frame_path, timestamp = await detect_queue.get()
        stream_uid = db.get_frame_stream(frame_id)  # 假设新增方法获取 stream_uid
        detector = detectors.get(stream_uid)
        if detector is None:
            log("WARNING", f"[Detect] Stream {stream_uid} 无 detector，标记 normal")
            db.insert_detection(stream_uid, group_uid, fence_id, 0, False, timestamp, frame_path)
            detect_queue.task_done()
            continue

        frame = cv2.imread(frame_path)
        if frame is None:
            log("FAIL", f"[Detect] 读取帧失败: {frame_path}")
            db.insert_detection(stream_uid, group_uid, fence_id, 0, False, timestamp, frame_path)
            detect_queue.task_done()
            continue

        changed, area = detector.detect_change(frame, fence_id=fence_id, change_threshold=0.1)
        db.insert_detection(stream_uid, group_uid, fence_id, change_ratio=area, changed=changed, timestamp=timestamp, frame_path=frame_path)
        log("INFO", f"[Detect] {stream_uid}-{fence_id} 检测结果: {'abnormal' if changed else 'normal'}, area={area}")
        detect_queue.task_done()
        await asyncio.sleep(0)

# ------------------ 合成视频模块 ------------------
async def merge_worker():
    while True:
        # 每个 stream + fence 合成视频
        for stream in storage_manger.list_streams():
            stream_uid = stream.get("uid")
            group_uid = stream.get("group_uid")
            for fence in stream.get("fences", []):
                fence_uid = fence['id']
                rows = db.get_abnormal_detections(stream_uid=stream_uid, group_uid=group_uid, fence_uid=fence_uid)
                if not rows:
                    continue
                frame_paths = [r['frame_path'] for r in rows]
                if not frame_paths:
                    continue

                os.makedirs("videos", exist_ok=True)
                video_name = f"videos/{stream_uid}_{fence_uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                first_frame = cv2.imread(frame_paths[0])
                h, w, _ = first_frame.shape
                out = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'mp4v'), 5, (w, h))
                for path in frame_paths:
                    img = cv2.imread(path)
                    if img is not None:
                        img = cv2.resize(img, (w, h))
                        out.write(img)
                out.release()

                # 插入视频合成表
                size = os.path.getsize(video_name)
                duration = len(frame_paths)/5  # fps=5
                db.insert_merged_video(stream_uid, group_uid, fence_uid, video_name, duration, size, datetime.now())
                log("INFO", f"[Merge] 合成视频完成: {video_name}, 帧数={len(frame_paths)}")
        await asyncio.sleep(10)



# ------------------ 主程序 ------------------
async def main():
    # 每个视频流启动一个抓帧任务
    capture_tasks = [asyncio.create_task(capture_stream(stream)) for stream in streams]

    # 初始化 detector
    # detectors = {}
    # for stream in streams:
    #     stream_uid, fence_uid, group_uid, url, points = stream
    #     det = FenceChangeDetector()
    #     det.set_fence(points)
    #     detectors[stream_uid] = det

    # 启动检测 worker
    # detect_tasks = [asyncio.create_task(detect_worker(detectors)) for _ in range(3)]

    # 启动合成任务
    # merge_task = asyncio.create_task(merge_worker())

    # await asyncio.gather(*capture_tasks, *detect_tasks, merge_task)

    await  asyncio.gather(*capture_tasks)


if __name__ == "__main__":
    asyncio.run(main())
