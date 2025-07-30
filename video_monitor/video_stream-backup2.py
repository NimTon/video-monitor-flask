import threading
import time
import cv2
from video_monitor.fence_detector import FenceChangeDetector


class VideoStreamThread(threading.Thread):
    def __init__(self, stream_id, stream_url, result_callback, compare_interval=10.0, change_threshold=0.1, debug=False):
        super().__init__()
        self.stream_id = stream_id
        self.stream_url = stream_url
        self.result_callback = result_callback
        self.running = threading.Event()
        self.running.set()
        self.detectors = []

        self.compare_interval = compare_interval  # 时间间隔（秒）
        self.change_threshold = change_threshold
        self.debug = debug

        self.last_compare_time = 0
        self.previous_frame = None

        # 新增：帧缓存
        self.frame_buffer = []  # 存储 (时间戳, 帧)
        self.buffer_start_time = time.time()

    def set_fences(self, fences):
        self.detectors = [FenceChangeDetector() for _ in fences]
        for detector, fence in zip(self.detectors, fences):
            detector.set_fence(fence)

    def run(self):
        cap = cv2.VideoCapture(self.stream_url)
        if not cap.isOpened():
            print(f"[{self.stream_id}] 打开视频流失败")
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30
        frame_interval = 1 / fps

        self.last_compare_time = time.time()
        self.buffer_start_time = self.last_compare_time

        while self.running.is_set():
            ret, frame = cap.read()
            if not ret:
                break

            current_time = time.time()
            current_frame = frame.copy()

            # 缓存所有帧
            self.frame_buffer.append((current_time, current_frame))
            # 清除过旧帧，只保留10秒内的帧
            self.frame_buffer = [(ts, f) for ts, f in self.frame_buffer if current_time - ts <= self.compare_interval]

            if current_time - self.last_compare_time >= self.compare_interval and self.previous_frame is not None:
                fence_results = []
                significant_change_detected = False

                for idx, detector in enumerate(self.detectors):
                    changed, area = detector.detect_change(frame, self.change_threshold, self.debug)
                    fence_area = detector.fence_area
                    change_ratio = area / (fence_area + 1e-5)

                    if changed:
                        significant_change_detected = True

                    fence_results.append({
                        'fence_id': idx,
                        'changed': changed,
                        'area': area,
                        'change_ratio': change_ratio,
                        'fence_points': detector.points  # 加上当前围栏的像素坐标
                    })

                # 如果检测到变化，筛选每秒一帧
                # if significant_change_detected:
                #     frames_to_return = []
                #     last_ts = None
                #     for ts, f in self.frame_buffer:
                #         if last_ts is None or ts - last_ts >= 1.0:
                #             frames_to_return.append(f)
                #             last_ts = ts
                if significant_change_detected:
                    frames_to_return = []
                    frame_count = 10
                    buffer_duration = self.compare_interval  # 10秒
                    start_ts = self.buffer_start_time
                    # end_ts = current_time
                    # buffer_duration = end_ts - start_ts  # 从某时间点到当前时间
                    target_times = [start_ts + i * buffer_duration / frame_count for i in range(frame_count)]

                    # 从 frame_buffer 中为每个目标时间点找最接近的一帧
                    for t in target_times:
                        closest = min(self.frame_buffer, key=lambda x: abs(x[0] - t), default=None)
                        if closest:
                            frames_to_return.append(closest[1])
                else:
                    frames_to_return = []

                # 调用回调，传入变化结果及帧列表
                self.result_callback(self.stream_id, fence_results, frames_to_return)

                # 清空缓存并更新时间
                self.frame_buffer.clear()
                # 在执行完比较之后，准备下一轮采样窗口时：
                if self.frame_buffer:
                    self.buffer_start_time = self.frame_buffer[0][0]  # 取最早那帧的时间
                else:
                    self.buffer_start_time = current_time  # fallback
                self.last_compare_time = current_time

            self.previous_frame = current_frame

            if self.debug:
                cv2.imshow(f"Stream {self.stream_id}", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    self.stop()
                    break
            else:
                time.sleep(frame_interval)

        cap.release()
        if self.debug:
            cv2.destroyAllWindows()

    def stop(self):
        self.running.clear()
