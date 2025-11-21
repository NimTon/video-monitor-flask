from utils import ai_manager
from storage import sm
from datetime import datetime
from utils.stream_utils import capture_frame


def detect_with_stream_info(stream_info, prompt):
    image_paths = []
    for key, value in stream_info.items():
        prompt += str(value)
        stream_url = sm.get_stream(key)['stream_url']
        # 通过stream_url获取一帧存入tmp/detect
        timestamp = datetime.now()
        image_path = f"tmp/detect/{key}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        success = capture_frame(stream_url, image_path)
        if not success:
            raise Exception("获取一帧图片失败")
        image_paths.append(image_path)
    future = ai_manager.add_task("call_local_ai_model", ai_prompt=prompt, image_paths=image_paths, json_str=False)
    ai_result = future.result()  # 阻塞等待后台线程执行完成
    return ai_result
