import asyncio
import subprocess
import cv2
import os
from datetime import datetime
import numpy as np
from utils.db_utils import db
from storage import StorageManager
from utils.stream_utils import get_running_streams, FenceChangeDetector, get_stream_resolution
from utils.utils import draw_fence_on_frame
from utils.log_utils import log
from utils.init_ffmpeg import FFMPEG_DIR

storage_manger = StorageManager()
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

    while True:
        try:
            # ---------- 使用 ffmpeg 拉取 HLS 流 ----------
            cmd = [
                f"{FFMPEG_DIR}/bin/ffmpeg.exe",
                "-i", url,
                "-loglevel", "quiet",
                "-f", "image2pipe",
                "-pix_fmt", "bgr24",
                "-vf", "fps=1",
                "-vcodec", "rawvideo", "-"
            ]
            pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10 ** 8)

            width, height = get_stream_resolution(url)
            if width is None or height is None:
                width, height = 1280, 720  # 默认分辨率
            frame_size = width * height * 3
            last_warning = 0

            while True:
                raw_frame = pipe.stdout.read(frame_size)
                if len(raw_frame) != frame_size:
                    now = datetime.now().timestamp()
                    if now - last_warning > 5:
                        log("WARN", f"[CAPTURE] {stream_name} ({stream_uid}) 读取帧长度不匹配，重试...", log_path=log_file_path)
                        last_warning = now
                    await asyncio.sleep(1)
                    continue

                timestamp = datetime.now()
                frame_path = f"{capture_path}/{stream_uid}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.png"
                frame_array = np.frombuffer(raw_frame, dtype=np.uint8).reshape((height, width, 3))
                cv2.imwrite(frame_path, frame_array)

                frame_id = db.insert_frame(stream_uid, group_uid, timestamp, frame_path)
                log("SUCCESS", f"[CAPTURE] {stream_name} ({stream_uid}) frame_id={frame_id}", log_path=log_file_path)

                # ---------- 入队 ----------
                for fence_id in fences:
                    await queues[(stream_uid, fence_id)].put((
                        detecting, stream_name, stream_uid,
                        frame_id, group_uid, fence_id,
                        frame_path, timestamp
                    ))

                await asyncio.sleep(1)

        except Exception as e:
            log("FAIL", f"[CAPTURE] {stream_name} ({stream_uid}) 异常: {str(e)}", log_path=log_file_path)
            await asyncio.sleep(5)


# ------------------ 异常检测模块 ------------------
async def detect_worker(queue, detector, change_threshold, detect_interval):
    """
    每个围栏独立 detector，使用各自的检测时间间隔（秒）和变化阈值
    """
    last_points = None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    interval = max(detect_interval, 0.1)  # 防止为0

    while True:
        detecting, stream_name, stream_uid, frame_id, group_uid, fence_id, frame_path, timestamp = await queue.get()
        try:
            if detecting:
                frame = cv2.imread(frame_path)
                if frame is None:
                    log("FAIL", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}) 读取帧失败: {frame_path}", log_path=log_file_path)
                    db.insert_detection(stream_uid, group_uid, fence_id, 0, False, timestamp, frame_path, frame_id)
                    queue.task_done()
                    await asyncio.sleep(interval)
                    continue

                height, width = frame.shape[:2]
                fence = storage_manger.get_fence(stream_uid, fence_id)
                points = fence.get('points', [])
                if len(points) >= 3:
                    fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
                else:
                    queue.task_done()
                    await asyncio.sleep(interval)
                    continue

                # 更新围栏点
                if fence_points != last_points:
                    detector.set_fence(fence_points)
                    last_points = fence_points

                # 检测变化，使用该围栏的阈值
                changed, change_area, change_ratio = detector.detect_change(frame, change_threshold=change_threshold)

                # 过滤小面积噪声
                if 0 <= change_ratio <= 1:
                    if change_area < 500:
                        changed = False
                        change_ratio = 0.0

                    frame_drawn = draw_fence_on_frame(frame, fence_points)
                    frame_save_path = f"{detect_path}/{stream_uid}_{fence_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
                    cv2.imwrite(frame_save_path, frame_drawn)

                    db.insert_detection(
                        stream_uid, group_uid, fence_id,
                        change_ratio, changed,
                        timestamp, frame_save_path, frame_id
                    )
                    log("SUCCESS", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}) "
                                   f"变化率={change_ratio:.2f} 阈值={change_threshold:.2f} 检测结果={'异常' if changed else '正常'}",
                        log_path=log_file_path)

                queue.task_done()
                await asyncio.sleep(interval)

        except Exception as e:
            log("FAIL", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE_UID={fence_id}) 异常: {str(e)}", log_path=log_file_path)
            queue.task_done()
            await asyncio.sleep(interval)


# ------------------ 主程序 ------------------
async def run_system():
    global detect_queues
    log("INFO", "系统启动中...", log_path=log_file_path)
    log("INFO", "加载存储管理器完成", log_path=log_file_path)
    streams = get_running_streams(storage_manger)
    if len(streams) == 0:
        log("WARN", "当前没有运行的流", log_path=log_file_path)
        await asyncio.sleep(RESTART_INTERVAL)

    log("INFO", f"加载运行中的视频流: {len(streams)} 个", log_path=log_file_path)

    # 初始化队列与 detector
    detect_queues = {}
    detectors = {}

    for stream in streams:
        for fence in stream.get("fences", []):
            uid_pair = (stream['uid'], fence['id'])
            detect_queues[uid_pair] = asyncio.Queue()
            detector = FenceChangeDetector()
            detectors[uid_pair] = detector

    log("INFO", "检测队列与检测器初始化完成", log_path=log_file_path)

    # 抓帧任务
    capture_tasks = []
    for stream in streams:
        log("INFO", f"启动抓帧任务: {stream.get('name')} (UID={stream.get('uid')})", log_path=log_file_path)
        capture_tasks.append(asyncio.create_task(capture_stream(stream, detect_queues)))

    # 检测任务
    detect_tasks = []
    streams = {s['uid']: s for s in streams}
    for (stream_uid, fence_uid), queue in detect_queues.items():
        stream_info = streams.get(stream_uid)
        name = stream_info.get('name')
        change_threshold = float(stream_info.get('threshold', 0.2))
        detect_interval = float(stream_info.get('interval', 1.0))  # 单位：秒
        log("INFO",
            f"启动检测任务: {name} (UID={stream_uid}, FENCE_UID={fence_uid}, "
            f"检测间隔={detect_interval}s, 阈值={change_threshold:.2f})",
            log_path=log_file_path)
        detect_tasks.append(asyncio.create_task(
            detect_worker(queue, detectors[(stream_uid, fence_uid)], change_threshold, detect_interval)
        ))

    return capture_tasks + detect_tasks


# ------------------ 循环主控 ------------------
async def main_loop():
    while True:
        log("INFO", f"系统启动: {datetime.now()}", log_path=log_file_path)
        tasks = await run_system()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=RESTART_INTERVAL)
        except asyncio.TimeoutError:
            log("INFO", f"达到重启周期: {datetime.now()}, 重启系统", log_path=log_file_path)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main_loop())
