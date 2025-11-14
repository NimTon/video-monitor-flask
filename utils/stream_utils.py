import json
import os
import platform
import subprocess
from datetime import datetime
import cv2
import numpy as np
from utils.log_utils import log
from utils.init_ffmpeg import FFMPEG_DIR


def capture_frame(stream_url, save_path):
    """
    从视频流中捕获一帧并保存到指定路径。

    Args:
        stream_url (str): 视频流 URL 或本地视频文件路径
        save_path (str): 保存图片的完整路径
    """
    # 创建保存目录（如果不存在）
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # 打开视频流
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        raise Exception("无法打开视频流")
        # print(f"无法打开视频流: {stream_url}")
        # return False

    # 读取一帧
    ret, frame = cap.read()
    if not ret:
        cap.release()
        raise Exception("无法从视频流获取帧")
        # print(f"无法捕获视频帧: {stream_url}")
        # return False

    # 保存图片
    cv2.imwrite(save_path, frame)
    # print(f"已保存图片: {save_path}")

    # 释放资源
    cap.release()
    return True


def check_device(use_gpu=True):
    """
    检测系统是否支持GPU，支持则使用GPU加速
    """
    try:
        # 检查是否有可用的 GPU
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        has_gpu = "h264_nvenc" in result.stdout

        device_name = "未知"
        if has_gpu and use_gpu:
            try:
                smi_result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                device_name = smi_result.stdout.strip() or "未知"
                if device_name == "未知":
                    use_gpu = False
            except Exception:
                device_name = "nvidia-smi 不可用"
                use_gpu = False
        else:
            # 获取系统平台
            system = platform.system().lower()
            # 检测 CPU 型号
            try:
                if system == "windows":
                    # Windows 平台
                    cpu_result = subprocess.run(
                        ["wmic", "cpu", "get", "name"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    lines = [l.strip() for l in cpu_result.stdout.splitlines() if l.strip()]
                    if len(lines) > 1:
                        device_name = lines[1]  # 第二行是CPU名称
                    else:
                        device_name = "CPU (型号未知)"
                elif system == "linux":
                    # Linux 平台
                    cpu_result = subprocess.run(
                        ["cat", "/proc/cpuinfo"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    for line in cpu_result.stdout.split('\n'):
                        if "model name" in line:
                            device_name = line.split(":")[1].strip()
                            break
                else:
                    device_name = f"未知系统: {system}"
            except Exception:
                device_name = "CPU (型号未知)"

        return has_gpu and use_gpu, device_name
    except Exception as e:
        return False, "未知"


def get_fuse_bool_time_range(streams_frames, fuse_bool):
    """
    streams_frames: {stream_uid: {frame_id: timestamp_str}}
    fuse_bool: {stream_uid: {frame_id: bool}}
    返回 fuse_bool 在 streams_frames 中的最大时间戳区间 (start_ts, end_ts)
    可能来自不同的 stream_uid
    """
    all_timestamps = []
    a_dt = {uid: {fid: datetime.fromisoformat(ts) for fid, ts in frames.items()}
            for uid, frames in streams_frames.items()}
    for uid, bool_dict in fuse_bool.items():
        if uid not in a_dt:
            continue
        for fid, flag in bool_dict.items():
            all_timestamps.append(a_dt[uid][fid])
    if not all_timestamps:
        return None  # 没有匹配的 True 帧
    start_ts = min(all_timestamps)
    end_ts = max(all_timestamps)
    return start_ts, end_ts


def get_stream_change_dict(group_streams_data):
    result = {}
    for stream_uid, frames in group_streams_data.items():
        stream_result = {}
        for fid, detect_frames in frames.items():
            stream_result[fid] = any(df.get("changed", False) for df in detect_frames)
        result[stream_uid] = dict(sorted(stream_result.items()))  # 按 frame_id 排序
    return result


def fuse_streams_by_position(streams_bool_dict, max_consecutive_false=10, max_length=3000):
    stream_keys = list(streams_bool_dict.keys())
    stream_lists = [list(v.values()) for v in streams_bool_dict.values()]
    max_len = min(max(len(lst) for lst in stream_lists), max_length)  # 限制最大长度为 3000

    # 对齐长度
    for lst in stream_lists:
        lst.extend([False] * (max_len - len(lst)))

    # 融合逻辑：如果任意流为 True，则所有流该位置置 True
    for i in range(max_len):
        if any(lst[i] for lst in stream_lists):
            for lst in stream_lists:
                lst[i] = True

    # 找到第一个 True 的位置
    first_true_idx = None
    for i in range(max_len):
        if any(lst[i] for lst in stream_lists):
            first_true_idx = i
            break

    if first_true_idx is not None:
        stream_lists = [lst[first_true_idx:] for lst in stream_lists]
    else:
        first_true_idx = 0

    fused = {}
    for k, lst in zip(stream_keys, stream_lists):
        frame_ids = list(streams_bool_dict[k].keys())
        fused[k] = dict(zip(frame_ids[first_true_idx:], lst[:len(frame_ids) - first_true_idx]))

    # 尾部剪裁：从第一个出现连续 N 个 False 的位置开始裁掉
    for k, lst in fused.items():
        values = list(lst.values())
        cut_index = len(values)  # 默认不裁剪
        consecutive_count = 0
        for i, v in enumerate(values):
            if not v:
                consecutive_count += 1
                if consecutive_count >= max_consecutive_false:
                    cut_index = i - max_consecutive_false + 1
                    break
            else:
                consecutive_count = 0
        # 裁剪
        keys = list(lst.keys())
        for key in keys[cut_index + max_consecutive_false:]:
            lst.pop(key)
        fused[k] = lst

    # 如果融合后的结果中，存在 120 个或更多连续的 False，则是完成，否则是录制中
    status = "recording"  # 默认状态是 "录制中"

    # 判断是否有连续 120 个 False
    for lst in fused.values():
        values = list(lst.values())
        consecutive_count = 0
        for v in values:
            if not v:
                consecutive_count += 1
                if consecutive_count >= max_consecutive_false:
                    status = "completed"
                    break
            else:
                consecutive_count = 0
        if status == "completed":
            break

    return fused, status


def get_running_streams(storage_manager):
    streams = [stream for stream in storage_manager.list_streams() if stream.get("status") == "running"]
    return streams


def get_video_size(url):
    import cv2
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return None
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return (width, height)


class FenceChangeDetector:
    def __init__(self):
        """初始化电子围栏变化检测器"""
        self.points = []  # 存储围栏顶点坐标
        self.drawing_done = False  # 标记围栏是否绘制完成
        # 创建背景减除器（基于混合高斯模型）
        self.backSub = cv2.createBackgroundSubtractorMOG2(history=60, varThreshold=50, detectShadows=True)
        # 创建椭圆形态学核（用于降噪）
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.fence_area = 0  # 电子围栏区域面积（像素）

    def set_fence(self, points):
        """设置电子围栏顶点坐标
        Args:
            points: 多边形顶点坐标列表（至少3个点）
        """
        if len(points) >= 3:
            self.points = points
            self.drawing_done = True
            polygon = np.array(self.points)  # 转换为NumPy数组
            # 计算多边形面积
            self.fence_area = cv2.contourArea(polygon)
            # print(f"[Fence] 设置完成，围栏面积约为 {self.fence_area:.1f} 像素，开始监控...")
        else:
            raise ValueError("电子围栏至少需要3个点")

    def detect_change(self, frame, change_threshold=0.1, debug=False):
        """检测围栏区域内的变化
        Args:
            frame: 输入视频帧
            change_threshold: 变化比例阈值（默认0.1即10%）
            debug: 是否显示调试信息
        Returns:
            tuple: (是否发生变化, 变化区域像素数)
        """
        if not self.drawing_done:
            return False, 0

        # 创建全黑掩码（与帧同尺寸）
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        # 在掩码上绘制白色填充多边形（围栏区域）
        cv2.fillPoly(mask, [np.array(self.points)], 255)
        # 通过掩码提取围栏ROI区域
        roi = cv2.bitwise_and(frame, frame, mask=mask)

        # 应用背景减除获取前景掩码
        fgMask = self.backSub.apply(roi)
        # 开运算去除噪声（先腐蚀后膨胀）
        fgMask = cv2.morphologyEx(fgMask, cv2.MORPH_OPEN, self.kernel)

        # 计算变化区域面积（非零像素数）
        changed_area = cv2.countNonZero(fgMask)
        # 计算变化比例（加极小值防止除零）
        change_ratio = changed_area / (self.fence_area + 1e-5)

        # 判定是否发生显著变化（排除完全变化的情况）
        changed = (change_ratio > change_threshold) and (change_ratio < 1)

        if debug:
            # 调试模式：可视化处理过程
            debug_img = frame.copy()
            # 绘制绿色围栏边界
            cv2.polylines(debug_img, [np.array(self.points)], isClosed=True, color=(0, 255, 0), thickness=2)
            # 将前景掩码转为红色显示
            colored_mask = cv2.cvtColor(fgMask, cv2.COLOR_GRAY2BGR)
            colored_mask[:, :, 1:] = 0  # 保留红色通道
            # 创建半透明叠加图像
            overlay = cv2.addWeighted(debug_img, 0.7, colored_mask, 0.3, 0)
            # 添加变化比例文字
            cv2.putText(overlay, f"Change Ratio: {change_ratio:.3f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            # 显示调试窗口
            cv2.imshow(f"Fence Debug", overlay)
            cv2.waitKey(1)

        return changed, changed_area, change_ratio


def get_stream_resolution(url):
    """
    返回 (width, height)
    """
    cmd = [
        f"{FFMPEG_DIR}/bin/ffprobe.exe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        url
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 错误: {result.stderr}")

    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    if len(streams) == 0:
        raise ValueError("无法获取视频流信息")

    width = streams[0].get("width")
    height = streams[0].get("height")
    if width is None or height is None:
        raise ValueError("无法获取视频分辨率信息")
    return width, height
