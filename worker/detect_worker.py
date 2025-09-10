import asyncio
import cv2
import os
from datetime import datetime
from utils.db_utils import db
from storage import StorageManager
from utils.stream_utils import get_running_streams, FenceChangeDetector
from utils.utils import log, resize_to_720p, draw_fence_on_frame
import time

storage_manger = StorageManager()
detector = FenceChangeDetector()
detect_queues = {}
capture_path = "./tmp/capture"
detect_path = "./tmp/detect"
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
    cap = None
    last_warning = 0  # 用于控制警告频率
    while True:
        # 如果 cap 不存在或被关闭，尝试重新打开
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                now = time.time()
                if now - last_warning > 5:  # 每 5 秒打印一次警告
                    log("WARNING", f"[CAPTURE] 无法打开视频流: {stream_name} ({stream_uid}), 正在重试...")
                    last_warning = now
                await asyncio.sleep(2)
                continue
        ret, frame = cap.read()
        if frame is None:
            now = time.time()
            if now - last_warning > 5:  # 每 5 秒打印一次空帧警告
                log("WARNING", f"[CAPTURE] 读取到空帧: {stream_name} ({stream_uid})")
                last_warning = now
            await asyncio.sleep(1)
            continue
        frame = resize_to_720p(frame)
        timestamp = datetime.now()
        if ret:
            frame_path = f"{capture_path}/{stream_uid}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
            success = cv2.imwrite(frame_path, frame)
            if success:
                frame_id = db.insert_frame(stream_uid, group_uid, timestamp, frame_path)
                log("SUCCESS", f"[CAPTURE] 抓取视频帧成功: {stream_name} ({stream_uid}), frame_id={frame_id}")
                for fence_id in fences:
                    await queues[(stream_uid, fence_id)].put((detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp))
            else:
                log("FAIL", f"[CAPTURE] 抓取视频帧失败: {stream_name} ({stream_uid}), 保存路径={frame_path}")
        else:
            now = time.time()
            if now - last_warning > 5:
                log("WARNING", f"[CAPTURE] 读取视频帧失败: {stream_name} ({stream_uid})")
                last_warning = now
        await asyncio.sleep(1)


# ------------------ 异常检测模块 ------------------
async def detect_worker(queue):
    while True:
        detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp = await queue.get()
        if detecting:
            frame = cv2.imread(frame_path)
            if frame is None:
                log("FAIL", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}) 读取帧失败: {frame_path}")
                db.insert_detection(stream_uid, group_uid, fence_id, 0, False, timestamp, frame_path, frame_id)
                queue.task_done()
                await asyncio.sleep(1)
                continue
            height, width = frame.shape[:2]
            fence = storage_manger.get_fence(stream_uid, fence_id)
            fence_points = []
            points = fence.get('points', [])
            if len(points) >= 3:
                fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
            detector.set_fence(fence_points)
            changed, change_area, change_ratio = detector.detect_change(frame, change_threshold=0.2)
            if 0 <= change_ratio <= 1:
                frame_path = f"{detect_path}/{stream_uid}_{fence_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
                frame = draw_fence_on_frame(frame, fence_points)
                cv2.imwrite(frame_path, frame)
                db.insert_detection(stream_uid, group_uid, fence_id, change_ratio, changed, timestamp, frame_path, frame_id)
                queue.task_done()
                log("SUCCESS", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}, TIMESTAMPE={timestamp}) 变化率：{change_ratio:.2f} 检测结果: {'异常' if changed else '正常'}")
            await asyncio.sleep(1)


# ------------------ 主程序 ------------------
async def run_system():
    global detect_queues
    log("INFO", "系统启动中...")
    log("INFO", "加载存储管理器完成")
    streams = get_running_streams(storage_manger)
    if len(streams) == 0:
        log("WARNING", "当前没有运行的流")
        await asyncio.sleep(RESTART_INTERVAL)
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
    return capture_tasks + detect_tasks


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
