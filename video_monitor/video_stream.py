import threading
import time
import cv2
from video_monitor.fence_detector import FenceChangeDetector


class VideoStreamThread(threading.Thread):
    def __init__(self, stream_id, stream_url, result_callback, compare_interval=10.0, change_threshold=0.2, buffer_duration=10.0, buffer_fps=1, debug=False):
        super().__init__()
        self.stream_id = stream_id
        self.stream_url = stream_url
        self.result_callback = result_callback
        self.compare_interval = compare_interval
        self.change_threshold = change_threshold
        self.buffer_duration = buffer_duration
        self.buffer_fps = buffer_fps
        self.debug = debug

        self.running = threading.Event()
        self.running.set()
        self.detectors = []

        self.last_compare_time = 0
        self.previous_frame = None
        self.frame_buffer = []  # 存储 (时间戳, 帧)
        self.last_buffered_time = 0

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

        self.max_buffer_size = int(fps * self.buffer_duration)  # 最大缓存帧数
        self.last_compare_time = time.time()

        while self.running.is_set():
            ret, frame = cap.read()
            if not ret:
                break

            current_time = time.time()
            current_frame = frame.copy()

            # 每一帧都加入缓存（不再限制采样频率）
            self.frame_buffer.append((current_time, current_frame))
            # print(len(self.frame_buffer))
            # 保留最新的 max_buffer_size 帧
            if len(self.frame_buffer) > self.max_buffer_size:
                self.frame_buffer = self.frame_buffer[-self.max_buffer_size:]

            # 定期检测变化
            if current_time - self.last_compare_time >= self.compare_interval and self.previous_frame is not None:
                print(f"[{self.stream_id}] 检测开始: 时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time))}")
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
                        'fence_points': detector.points
                    })

                # 帧抽取逻辑
                frames_to_return = []
                if significant_change_detected and len(self.frame_buffer) > 0:
                    frame_count = min(int(self.buffer_duration * self.buffer_fps), len(self.frame_buffer))
                    step = len(self.frame_buffer) / frame_count if frame_count > 0 else 1
                    print(step, len(self.frame_buffer))
                    frames_to_return = [
                        self.frame_buffer[int(i * step)][1]
                        for i in range(frame_count)
                    ]

                self.result_callback(self.stream_id, fence_results, frames_to_return)
                print(f"[{self.stream_id}] 检测结束: 时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

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
        print(f"[{self.stream_id}] 收到停止信号: 时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
        self.running.clear()
