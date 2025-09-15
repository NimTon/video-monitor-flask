from datetime import datetime

import cv2
import numpy as np

from utils.utils import log


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


def fuse_streams_by_position(streams_bool_dict, max_consecutive_false=2):
    stream_keys = list(streams_bool_dict.keys())
    stream_lists = [list(v.values()) for v in streams_bool_dict.values()]
    max_len = max(len(lst) for lst in stream_lists)

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

    # 状态判断
    last_values = [list(lst.values())[-1] if lst else False for lst in fused.values()]
    if first_true_idx == 0 and all(not any(lst) for lst in stream_lists):
        status = "waiting"
    else:
        if all(last_values):
            status = "recording"
        else:
            status = "completed"

    return fused, status


def get_running_streams(storage_manger):
    streams = [stream for stream in storage_manger.list_streams() if stream.get("status") == "running"]
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
        self.backSub = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=50, detectShadows=True)
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
