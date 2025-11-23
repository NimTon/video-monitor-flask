import os

import cv2

from utils import ai_manager
from storage import sm
from datetime import datetime
from utils.stream_utils import capture_frame
from utils.utils import draw_fence_on_frame


def detect_with_stream_info(stream_info, prompt):
    image_paths = []
    for key, value in stream_info.items():
        prompt += str(value)
        stream_data = sm.get_stream(key)
        stream_url = stream_data['stream_url']
        stream_fences = stream_data['fences']
        # 通过stream_url获取一帧存入tmp/detect
        timestamp = datetime.now()
        image_path = f"tmp/detect/{key}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        # 创建保存目录（如果不存在）
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        frame = capture_frame(stream_url)
        height, width = frame.shape[:2]
        for fence in stream_fences:
            points = fence.get('points', [])
            fence_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
            frame = draw_fence_on_frame(frame, fence_points)
        cv2.imwrite(image_path, frame)
        image_paths.append(image_path)
    future = ai_manager.add_task("call_local_ai_model", ai_prompt=prompt, image_paths=image_paths, json_str=False)
    ai_result = future.result()  # 阻塞等待后台线程执行完成
    return ai_result
