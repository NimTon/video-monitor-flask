import requests
import os
import json
from ai.qwen_ai import extract_json_dict_from_ai_reply

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
SAY_IMAGES_URL = config['local_ai_images_url']
SAY_VIDEO_URL = config['local_ai_video_url']
with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
prompt = prompts['normal']

def call_local_ai_model(image_paths=None, video_path=None, prompt=prompt):
    files = []
    opened_files = []
    url = None

    # 参数合法性检查
    if image_paths and video_path:
        print("错误：不能同时传入图片和视频")
        return None
    elif image_paths:
        url = SAY_IMAGES_URL
        for path in image_paths:
            if not os.path.exists(path):
                print(f"警告：文件不存在 - {path}")
                continue
            file_ext = os.path.splitext(path)[1].lower()
            mime_type = f"image/{file_ext[1:]}" if file_ext else "image/jpeg"
            f = open(path, "rb")
            opened_files.append(f)
            files.append(("files", (os.path.basename(path), f, mime_type)))
    elif video_path:
        url = SAY_VIDEO_URL
        if not os.path.exists(video_path):
            print(f"错误：视频文件不存在 - {video_path}")
            return None
        file_ext = os.path.splitext(video_path)[1].lower()
        mime_type = f"video/{file_ext[1:]}" if file_ext else "video/mp4"
        f = open(video_path, "rb")
        opened_files.append(f)
        files.append(("files", (os.path.basename(video_path), f, mime_type)))
    else:
        print("错误：必须传入 image_paths 或 video_path")
        return None

    # 如果用户没有传 prompt，使用默认
    ai_prompt = prompt or "请完整描述视频内容?" if video_path else "请描述图片内容?"

    try:
        data = {"prompt": ai_prompt}
        response = requests.post(url, files=files, data=data)

        # 确保关闭文件句柄
        for f in opened_files:
            f.close()

        if response.status_code == 200:
            try:
                result_text = response.json().get("result")
                if result_text:
                    # 这里可以选择直接返回字符串，也可以抽取 JSON
                    return extract_json_dict_from_ai_reply(result_text)
                else:
                    print("响应中没有 result 字段：", response.text)
                    return None
            except json.JSONDecodeError:
                print("响应不是 JSON：", response.text)
                return None
        else:
            print(f"[错误] 状态码: {response.status_code}")
            print("响应内容:", response.text)
            return None
    except Exception as e:
        print("[异常] 调用本地模型接口失败:", e)
        return None
