# 导入OpenCV和NumPy库
import cv2
import numpy as np

class FenceChangeDetector:
    def __init__(self):
        """初始化电子围栏变化检测器"""
        self.points = []  # 存储围栏顶点坐标
        self.drawing_done = False  # 标记围栏是否绘制完成
        # 创建背景减除器（基于混合高斯模型）
        self.backSub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=True)
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
            print(f"[Fence] 设置完成，围栏面积约为 {self.fence_area:.1f} 像素，开始监控...")
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
            cv2.polylines(debug_img, [np.array(self.points)], isClosed=True, color=(0,255,0), thickness=2)
            # 将前景掩码转为红色显示
            colored_mask = cv2.cvtColor(fgMask, cv2.COLOR_GRAY2BGR)
            colored_mask[:, :, 1:] = 0  # 保留红色通道
            # 创建半透明叠加图像
            overlay = cv2.addWeighted(debug_img, 0.7, colored_mask, 0.3, 0)
            # 添加变化比例文字
            cv2.putText(overlay, f"Change Ratio: {change_ratio:.3f}", (10,30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)
            # 显示调试窗口
            cv2.imshow(f"Fence Debug", overlay)
            cv2.waitKey(1)

        return changed, changed_area