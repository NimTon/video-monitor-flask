import asyncio
import cv2
import os
from datetime import datetime
from utils.db_utils import db
from storage import StorageManager
from utils.stream_utils import FenceChangeDetector, check_device, get_running_streams
from utils.utils import draw_fence_on_frame
from utils.log_utils import log

storage_manager = StorageManager()
detect_queues = {}
capture_path = "./tmp/capture"
detect_path = "./tmp/detect"
RESTART_INTERVAL = 3600  # 每1小时重启一次

# ------------------------
# 日志文件路径
# ------------------------
now = datetime.now()
date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
log_dir = os.path.join("logs", date_str)
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, "detect_worker.log")

# ------------------ 进程管理 ------------------
processes = {}


# ------------------ 抓帧模块 ------------------
async def capture_video(stream, queues):
    """
    从本地 MP4 视频文件读取帧并送入检测队列
    """
    detecting = stream.get("detecting")
    stream_uid = stream.get("uid")
    stream_name = stream.get("name")
    video_path = stream.get("video_path")
    group_uid = stream.get("group_uid", "default")
    detect_interval = float(stream.get("frequency", 1.0))  # 检测间隔（秒）
    fences = [f['id'] for f in stream.get("fences", [])]

    # 自动检测 GPU
    use_gpu = True
    has_gpu, device_name = check_device(use_gpu)
    log("INFO", f"使用 {'GPU' if has_gpu else 'CPU'}: {device_name}", log_path=log_file_path)

    os.makedirs(capture_path, exist_ok=True)
    os.makedirs(detect_path, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log("FAIL", f"无法打开视频文件: {video_path}", log_path=log_file_path)
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = int(fps * detect_interval) if fps > 0 else 25
    frame_index = 0
    last_detect_time = 0

    log("INFO", f"[CAPTURE] 开始处理视频: {video_path} FPS={fps:.2f}", log_path=log_file_path)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            log("INFO", f"[CAPTURE] 视频读取结束: {video_path}", log_path=log_file_path)
            break

        timestamp = datetime.now()
        frame_path = f"{capture_path}/{stream_uid}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.png"
        cv2.imwrite(frame_path, frame)
        frame_id = db.insert_frame(stream_uid, group_uid, timestamp, frame_path)

        now_ts = timestamp.timestamp()
        need_detect = now_ts - last_detect_time >= detect_interval
        if need_detect:
            last_detect_time = now_ts

        for fence_id in fences:
            await queues[(stream_uid, fence_id)].put((
                detecting, stream_name, stream_uid,
                frame_id, group_uid, fence_id,
                frame_path, timestamp, need_detect
            ))

        frame_index += 1
        await asyncio.sleep(1 / fps if fps > 0 else 0.04)

    cap.release()
    log("INFO", f"[CAPTURE] 视频帧抓取完成: {video_path}", log_path=log_file_path)


# ------------------ 异常检测模块 ------------------
async def detect_worker(queue, detector, change_threshold):
    """
    每个围栏独立 detector
    每帧都要处理，但仅当 need_detect=True 时才进行识别
    """
    last_points = None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    while True:
        detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp, need_detect = await queue.get()
        try:
            if detecting:
                frame = cv2.imread(frame_path)
                if frame is None:
                    log("FAIL", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE={fence_id}) 读取帧失败", log_path=log_file_path)
                    db.insert_detection(stream_uid, group_uid, fence_id, 0, False, timestamp, frame_path, frame_id)
                    queue.task_done()
                    continue

                height, width = frame.shape[:2]
                fence = storage_manager.get_fence(stream_uid, fence_id)
                points = fence.get('points', [])
                if len(points) < 3:
                    queue.task_done()
                    continue

                fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]

                # 仅当围栏点变化时重新设置
                if fence_points != last_points:
                    detector.set_fence(fence_points)
                    last_points = fence_points

                if need_detect:
                    # log("INFO", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE={fence_id}) 开始检测...", log_path=log_file_path)
                    # 真正进行检测
                    changed, change_area, change_ratio = detector.detect_change(frame, change_threshold=change_threshold)

                    # 过滤微小变化
                    if 0 <= change_ratio <= 1:
                        if change_area < 500:
                            changed = False
                            change_ratio = 0.0

                    log("SUCCESS",
                        f"[DETECT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}) "
                        f"need_detect={need_detect} 变化率={change_ratio:.2f} 阈值={change_threshold:.2f} 结果={'异常' if changed else '正常'}",
                        log_path=log_file_path)

                else:
                    # 跳过检测
                    changed = False
                    change_ratio = 0.0

                # 保存结果
                frame_drawn = draw_fence_on_frame(frame, fence_points)
                frame_save_path = f"{detect_path}/{stream_uid}_{fence_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
                cv2.imwrite(frame_save_path, frame_drawn)

                db.insert_detection(
                    stream_uid, group_uid, fence_id,
                    change_ratio, changed,
                    timestamp, frame_save_path, frame_id
                )

                queue.task_done()

        except Exception as e:
            log("FAIL", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE={fence_id}) 异常: {str(e)}", log_path=log_file_path)
            queue.task_done()
            await asyncio.sleep(0.5)


# ------------------ 主程序 ------------------
async def run_system():
    global detect_queues
    log("INFO", "系统启动中...", log_path=log_file_path)
    streams = get_running_streams(storage_manager)
    if not streams:
        log("WARN", "当前没有运行的流", log_path=log_file_path)
        await asyncio.sleep(RESTART_INTERVAL)
        return []

    detect_queues = {}
    detectors = {}

    # 初始化
    for stream in streams:
        for fence in stream.get("fences", []):
            uid_pair = (stream['uid'], fence['id'])
            detect_queues[uid_pair] = asyncio.Queue()
            detectors[uid_pair] = FenceChangeDetector()

    log("INFO", f"检测器初始化完成，共 {len(detect_queues)} 个", log_path=log_file_path)

    # 抓帧任务
    capture_tasks = []
    for stream in streams:
        log("INFO", f"启动抓帧任务: {stream.get('name')} (UID={stream.get('uid')})", log_path=log_file_path)
        capture_tasks.append(asyncio.create_task(capture_video(stream, detect_queues)))

    # 检测任务
    detect_tasks = []
    streams = {s['uid']: s for s in streams}
    for (stream_uid, fence_uid), queue in detect_queues.items():
        stream_info = streams[stream_uid]
        name = stream_info['name']
        change_threshold = float(stream_info.get('threshold', 0.2))
        detect_tasks.append(asyncio.create_task(detect_worker(queue, detectors[(stream_uid, fence_uid)], change_threshold)))
        log("INFO", f"启动检测任务: {name} (UID={stream_uid}, FENCE_UID={fence_uid}, 阈值={change_threshold:.2f})", log_path=log_file_path)

    return capture_tasks + detect_tasks


if __name__ == "__main__":
    asyncio.run(run_system())
