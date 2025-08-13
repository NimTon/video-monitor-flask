import cv2
import numpy as np
from datetime import datetime, timedelta
import os
import shutil
from matplotlib import pyplot as plt
from PIL import Image
import io
import base64  # Base64编码库

# 在报警分发时，给frame加上红色围栏标记
def draw_fence_on_frame(frame, fence_points):
    """
    在frame上绘制红色围栏（点和连线）
    fence_points: [(x1, y1), (x2, y2), ...] 电子围栏顶点像素坐标列表
    """
    if not fence_points or len(fence_points) < 3:
        return frame

    # 转成numpy数组方便绘制
    pts = np.array(fence_points, np.int32).reshape((-1, 1, 2))

    # 绘制多边形轮廓，红色，线宽2
    cv2.polylines(frame, [pts], isClosed=True, color=(0, 0, 255), thickness=2)

    # 绘制顶点为红色色小圆点
    for (x, y) in fence_points:
        cv2.circle(frame, (x, y), radius=4, color=(0, 0, 255), thickness=-1)

    return frame


def cv2_frame_to_base64(frame):
    # 转成 RGB
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb_frame)
    buffered = io.BytesIO()
    pil_img.save(buffered, format="JPEG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str


# MD5哈希函数
def md5(str):
    import hashlib
    m = hashlib.md5()  # 创建MD5哈希对象
    m.update(str.encode("utf8"))  # 更新哈希内容
    return m.hexdigest()  # 返回16进制哈希值


def save_frames_as_video(stream_id, fence_id, frames, video_root='./videos', base_url='x.x.x.x:5000', fps=25):
    """
    直接在 video_root 下生成 MP4 文件，不创建子文件夹。
    文件名格式: {stream_id}_{fence_id}_{时间戳}.mp4
    """
    now_time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    now = datetime.now()

    os.makedirs(video_root, exist_ok=True)

    # 删除超过7天的旧文件
    for file in os.listdir(video_root):
        file_path = os.path.join(video_root, file)
        if os.path.isfile(file_path):
            try:
                # 从文件名解析时间戳
                ts = file.split('_')[-1].split('.')[0]
                file_time = datetime.strptime(ts, '%Y%m%d_%H%M%S')
                if now - file_time > timedelta(days=7):
                    os.remove(file_path)
            except ValueError:
                continue

    if not frames:
        print("No frames to save!")
        return None, None

    height, width = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    video_filename = f"{stream_id}_{fence_id}_{now_time_str}.mp4"
    video_path = os.path.join(video_root, video_filename)

    video_writer = cv2.VideoWriter(video_path, fourcc, fps, (width, height))
    for frame in frames:
        if frame.shape[1] != width or frame.shape[0] != height:
            frame = cv2.resize(frame, (width, height))
        video_writer.write(frame)
    video_writer.release()

    video_url = f"{base_url}/videos/{video_filename}"
    return video_url, video_path


def save_key_frames(stream_id, fence_id, frames, image_root='./images', base_url='x.x.x.x:5000'):
    """
    直接在 image_root 下保存第一帧和最后一帧图片，不创建子文件夹。
    文件名格式: {stream_id}_{fence_id}_{时间戳}_1.jpg / _2.jpg
    """
    now_time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    now = datetime.now()

    os.makedirs(image_root, exist_ok=True)

    # 删除超过7天的旧文件
    for file in os.listdir(image_root):
        file_path = os.path.join(image_root, file)
        if os.path.isfile(file_path):
            try:
                ts = file.split('_')[-2]  # 倒数第二个是时间戳
                file_time = datetime.strptime(ts, '%Y%m%d_%H%M%S')
                if now - file_time > timedelta(days=7):
                    os.remove(file_path)
            except ValueError:
                continue

    if not frames:
        print("No frames to save!")
        return None, None

    urls, paths = [], []
    for i, frame in enumerate([frames[0], frames[-1]], start=1):
        frame = resize_to_180p(frame)
        filename = f"{stream_id}_{fence_id}_{now_time_str}_{i}.jpg"
        filepath = os.path.join(image_root, filename)
        cv2.imwrite(filepath, frame)

        file_url = f"{base_url}/images/{filename}"
        urls.append(file_url)
        paths.append(filepath)

    return urls, paths

def resize_to_180p(frame):
    """将图像压缩到 180p 高度，保持宽高比"""
    h, w = frame.shape[:2]
    target_h = 180
    scale = target_h / h
    target_w = int(w * scale)
    resized = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
    return resized