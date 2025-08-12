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


def save_frames_as_video(frames, video_root='./videos', base_url='x.x.x.x:5000', fps=25):
    """
    按时间戳创建文件夹，清理7天前旧文件夹，
    将 frames 保存为 MP4 视频，并返回视频的 URL 和本地路径。

    :param frames: 图像帧列表（OpenCV BGR格式）
    :param video_root: 视频保存根目录
    :param base_url: 视频 URL 路径前缀（假设提供了路由）
    :param fps: 视频帧率
    :return: (url列表, path列表)，通常只返回一个视频文件
    """
    now_time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(video_root, now_time_str)
    now = datetime.now()

    # 删除超过7天的旧文件夹
    if os.path.exists(video_root):
        for folder in os.listdir(video_root):
            folder_path = os.path.join(video_root, folder)
            if os.path.isdir(folder_path):
                try:
                    folder_time = datetime.strptime(folder, '%Y%m%d_%H%M%S')
                    if now - folder_time > timedelta(days=7):
                        shutil.rmtree(folder_path)
                except ValueError:
                    continue

    os.makedirs(save_dir, exist_ok=True)

    if not frames:
        print("No frames to save!")
        return [], []

    height, width = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    video_filename = 'video.mp4'
    video_path = os.path.join(save_dir, video_filename)

    video_writer = cv2.VideoWriter(video_path, fourcc, fps, (width, height))

    for frame in frames:
        if frame.shape[1] != width or frame.shape[0] != height:
            frame = cv2.resize(frame, (width, height))
        video_writer.write(frame)
    video_writer.release()

    video_url = f'{base_url}/videos/{now_time_str}/{video_filename}'
    return [video_url], [video_path]


def save_key_frames(frames, image_root='./images', base_url='x.x.x.x:5000'):
    """
    保存第一帧和最后一帧图像，并删除 ./images 下的旧文件夹（只保留当前时间戳文件夹）

    :param frames: 图像帧列表（OpenCV 格式 BGR）
    :param image_root: 图片保存的根目录
    :param base_url: 图片的 URL 路径前缀（用于生成浏览器可访问的路径）
    :return: 返回图片 URL 列表 [url1, url2]
    """
    now_time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(image_root, now_time_str)

    # 当前时间
    now = datetime.now()

    # 删除超过 7 天的旧文件夹
    if os.path.exists(image_root):
        for folder in os.listdir(image_root):
            folder_path = os.path.join(image_root, folder)

            # 检查是否是目录 + 是否符合时间戳格式
            if os.path.isdir(folder_path):
                try:
                    folder_time = datetime.strptime(folder, '%Y%m%d_%H%M%S')
                    if now - folder_time > timedelta(days=7):
                        shutil.rmtree(folder_path)
                except ValueError:
                    # 文件夹名不符合时间戳格式，忽略或可选择删除
                    continue

    # 创建保存目录
    os.makedirs(save_dir, exist_ok=True)

    # 保存第一帧和最后一帧（原始像素）
    urls = []
    paths = []
    for i, frame in enumerate([frames[0], frames[-1]]):
        filename = f'{i + 1}.jpg'
        filepath = os.path.join(save_dir, filename)

        # 直接保存 BGR 图像
        cv2.imwrite(filepath, frame)

        # 构造 URL
        file_url = f'{base_url}/images/{now_time_str}/{filename}'
        urls.append(file_url)
        paths.append(filepath)

    return urls, paths