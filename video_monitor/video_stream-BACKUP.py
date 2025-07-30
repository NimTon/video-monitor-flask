# 导入必要的库
import threading  # 多线程支持
import time  # 时间相关功能
import cv2  # OpenCV库，用于视频处理
from video_monitor.fence_detector import FenceChangeDetector  # 导入围栏变化检测器
from collections import deque


# 定义视频流线程类，继承自threading.Thread
class VideoStreamThread(threading.Thread):
    def __init__(self, stream_id, stream_url, result_callback, compare_interval=1.0, change_threshold=0.1, debug=False):
        super().__init__()  # 调用父类初始化方法
        self.stream_id = stream_id  # 视频流ID
        self.stream_url = stream_url  # 视频流URL
        self.result_callback = result_callback  # 结果回调函数
        self.running = threading.Event()  # 线程运行控制事件
        self.running.set()  # 初始设置为运行状态
        self.detectors = []  # 围栏检测器列表

        self.compare_interval = compare_interval  # 帧比较间隔时间(秒)
        self.change_threshold = change_threshold  # 变化阈值
        self.debug = debug  # 调试模式标志

        self.last_compare_time = 0  # 上次比较时间戳
        self.previous_frame = None  # 前一帧图像

    # 设置围栏区域
    def set_fences(self, fences):
        # 为每个围栏创建一个检测器
        self.detectors = [FenceChangeDetector() for _ in fences]
        # 为每个检测器设置对应的围栏区域
        for detector, fence in zip(self.detectors, fences):
            detector.set_fence(fence)

    # 线程主运行方法
    def run(self):
        # 打开视频流
        cap = cv2.VideoCapture(self.stream_url)
        if not cap.isOpened():
            print(f"[{self.stream_id}] 打开视频流失败")
            return

        # 获取视频帧率，如果无效则默认30fps
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30
        frame_interval = 1 / fps  # 计算帧间隔时间

        self.last_compare_time = time.time()  # 初始化比较时间

        # 主循环，当running标志为True时持续运行
        while self.running.is_set():
            ret, frame = cap.read()  # 读取视频帧
            if not ret:  # 如果读取失败则退出循环
                break

            current_frame = frame.copy()  # 复制当前帧
            current_time = time.time()  # 获取当前时间

            # 检查是否到达比较间隔时间且有前一帧可供比较
            if current_time - self.last_compare_time >= self.compare_interval and self.previous_frame is not None:
                fence_results = []  # 初始化围栏检测结果列表

                # 遍历所有检测器进行变化检测
                for idx, detector in enumerate(self.detectors):
                    # 检测围栏区域变化
                    changed, area = detector.detect_change(frame, self.change_threshold, self.debug)
                    fence_area = detector.fence_area  # 获取围栏总面积
                    change_ratio = area / (fence_area + 1e-5)  # 计算变化比例(加极小值防止除零)

                    # 记录检测结果
                    fence_results.append({
                        'fence_id': idx,  # 围栏ID
                        'changed': changed,  # 是否变化
                        'area': area,  # 变化区域面积
                        'change_ratio': change_ratio  # 变化比例
                    })

                # 调用回调函数返回检测结果
                self.result_callback(self.stream_id, fence_results, self.previous_frame, frame)
                self.last_compare_time = current_time  # 更新最后比较时间

            self.previous_frame = current_frame  # 保存当前帧供下次比较使用

            # 调试模式下显示视频流
            if self.debug:
                cv2.imshow(f"Stream {self.stream_id}", frame)
                # 按ESC键停止
                if cv2.waitKey(1) & 0xFF == 27:
                    self.stop()
                    break
            else:
                time.sleep(frame_interval)  # 非调试模式下按帧率休眠

        # 释放资源
        cap.release()
        if self.debug:
            cv2.destroyAllWindows()  # 关闭所有OpenCV窗口

    # 停止线程方法
    def stop(self):
        self.running.clear()  # 清除运行标志