import asyncio
import cv2
import os
from datetime import datetime
import numpy as np
from utils.db_utils import db
from storage import StorageManager
from utils.stream_utils import get_running_streams, FenceChangeDetector, get_stream_resolution, check_device
from utils.utils import draw_fence_on_frame
from utils.log_utils import log
import ffmpeg
from utils.init_ffmpeg import FFMPEG_EXE
from config import TEMP_DIR

storage_manager = StorageManager()
detect_queues = {}
capture_path = f"{TEMP_DIR}/capture"
detect_path = f"{TEMP_DIR}/detect"
os.makedirs(capture_path, exist_ok=True)
os.makedirs(detect_path, exist_ok=True)

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
async def capture_stream(stream, queues):
    """
    基于 ffmpeg-python + pipe 的抓帧模块
    完全无阻塞，不会被 read(frame_size) 卡住
    """
    detecting = stream.get("detecting")
    stream_uid = stream.get("uid")
    stream_name = stream.get("name")
    group_uid = stream.get("group_uid")
    url = stream.get("stream_url")
    detect_interval = float(stream.get("frequency", 1.0))
    fences = [f['id'] for f in stream.get("fences", [])]

    # 检查是否支持 GPU
    use_gpu = True
    has_gpu, device_name = check_device(use_gpu)
    if has_gpu:
        hwaccel = "cuda"
        log("INFO", f"使用 GPU：{device_name} 进行抓帧", log_path=log_file_path)
    else:
        hwaccel = None
        log("INFO", f"使用 CPU：{device_name} 进行抓帧", log_path=log_file_path)

    os.makedirs(capture_path, exist_ok=True)

    # 获取分辨率
    width, height = get_stream_resolution(url)
    if not width or not height:
        width, height = 1280, 720

    frame_size = width * height * 3

    last_detect_time = 0

    while True:
        try:
            # ------------------------
            # 启动 ffmpeg 异步管道
            # ------------------------
            stream_input = ffmpeg.input(url, **({"hwaccel": hwaccel} if hwaccel else {}))

            process = (
                ffmpeg
                .output(
                    stream_input,
                    'pipe:',
                    format='rawvideo',
                    pix_fmt='bgr24',
                    vf=f"fps=1"
                )
                .global_args('-loglevel', 'error')
                .run_async(pipe_stdout=True, pipe_stderr=True, cmd=FFMPEG_EXE)
            )

            log("INFO", f"[CAPTURE] {stream_name} ({stream_uid}) ffmpeg 启动", log_path=log_file_path)

            # ------------------------
            # 逐帧读取（非阻塞）
            # ------------------------
            loop = asyncio.get_running_loop()

            while True:
                # 非阻塞读取：在子线程执行 read(frame_size)
                raw_frame = await loop.run_in_executor(None, process.stdout.read, frame_size)

                if not raw_frame:
                    log("WARN", f"[CAPTURE] {stream_name} ({stream_uid}) FFmpeg 输出为空，准备重启", log_path=log_file_path)
                    break  # 重新启动 ffmpeg

                if len(raw_frame) != frame_size:
                    log("WARN", f"[CAPTURE] {stream_name} ({stream_uid}) 读取到异常帧，长度 {len(raw_frame)}", log_path=log_file_path)
                    break  # 也重启

                # ------------- 正常处理帧 -------------
                timestamp = datetime.now()
                frame_path = f"{capture_path}/{stream_uid}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.png"

                frame = np.frombuffer(raw_frame, np.uint8).reshape((height, width, 3))
                cv2.imwrite(frame_path, frame)

                frame_id = db.insert_frame(stream_uid, group_uid, timestamp, frame_path)

                now_ts = timestamp.timestamp()
                need_detect = now_ts - last_detect_time >= detect_interval
                if need_detect:
                    last_detect_time = now_ts

                # 入队
                for fence_id in fences:
                    await queues[(stream_uid, fence_id)].put((
                        detecting, stream_name, stream_uid,
                        frame_id, group_uid, fence_id,
                        frame_path, timestamp, need_detect
                    ))

                await asyncio.sleep(1)

        except Exception as e:
            log("FAIL", f"[CAPTURE] {stream_name} ({stream_uid}) 异常: {str(e)}", log_path=log_file_path)

        # FFmpeg 重启前的间隔
        await asyncio.sleep(2)


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
                    log("INFO", f"[DETECT] {stream_name} (UID={stream_uid}, FENCE={fence_id}) 开始检测...", log_path=log_file_path)
                    # 真正进行检测
                    changed, change_area, change_ratio = detector.detect_change(frame, change_threshold=change_threshold)
                    changed = np.random.rand() < 0.1  # 1%概率触发changed
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
                frame_drawn = draw_fence_on_frame(frame, fence_points, changed)
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


async def stop_ffmpeg_processes():
    """
    停止所有 FFmpeg 进程（跨平台安全）
    """
    for stream_uid, process in processes.items():
        try:
            if process.poll() is None:
                # 优先 terminate（Windows/Linux 都支持）
                process.terminate()
                log("INFO", f"停止 FFmpeg 进程 {stream_uid}", log_path=log_file_path)

        except Exception as e:
            log("WARN", f"停止 FFmpeg 进程 {stream_uid} 时出错: {str(e)}", log_path=log_file_path)

    processes.clear()



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
        capture_tasks.append(asyncio.create_task(capture_stream(stream, detect_queues)))

    # 检测任务
    detect_tasks = []
    streams = {s['uid']: s for s in streams}
    for (stream_uid, fence_uid), queue in detect_queues.items():
        stream_info = streams[stream_uid]
        name = stream_info['name']
        change_threshold = float(stream_info.get('threshold', 0.2))
        detect_tasks.append(asyncio.create_task(
            detect_worker(queue, detectors[(stream_uid, fence_uid)], change_threshold)
        ))
        log("INFO", f"启动检测任务: {name} (UID={stream_uid}, FENCE_UID={fence_uid}, 阈值={change_threshold:.2f})", log_path=log_file_path)

    return capture_tasks + detect_tasks


# ------------------ 循环主控 ------------------
async def main_loop():
    while True:
        log("INFO", f"系统启动时间: {datetime.now()}", log_path=log_file_path)
        tasks = await run_system()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=RESTART_INTERVAL)
        except asyncio.TimeoutError:
            log("INFO", f"到达重启周期，系统重启中...", log_path=log_file_path)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            # 重启前停止所有 FFmpeg 进程
            await stop_ffmpeg_processes()

            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main_loop())
