import requests
import os
import json
from ai.qwen_ai import extract_json_dict_from_ai_reply

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
SAY_IMAGES_URL = config['local_ai_images_url']
SAY_VIDEO_URL = config['local_ai_video_url']
SAY_MSG_URL = config['local_ai_text_url']
with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
prompt = prompts['normal']


def call_local_ai_model(ai_prompt=prompt, image_paths=None, video_path=None, json_str=True):
    files = []
    opened_files = []
    url = None
    # 参数合法性检查
    if image_paths and video_path:
        print("[错误] 不能同时传入图片和视频")
        return None
    elif image_paths:
        url = SAY_IMAGES_URL
        for path in image_paths:
            if not os.path.exists(path):
                print(f"[警告] 文件不存在 - {path}")
                continue
            ext = os.path.splitext(path)[1].lower()
            mime = f"image/{ext[1:]}" if ext else "image/jpeg"
            f = open(path, "rb")
            opened_files.append(f)
            files.append(("files", (os.path.basename(path), f, mime)))
    elif video_path:
        url = SAY_VIDEO_URL
        if not os.path.exists(video_path):
            print(f"[错误] 视频文件不存在 - {video_path}")
            return None
        ext = os.path.splitext(video_path)[1].lower()
        mime = f"video/{ext[1:]}" if ext else "video/mp4"
        f = open(video_path, "rb")
        opened_files.append(f)
        files.append(("files", (os.path.basename(video_path), f, mime)))
    else:
        # 纯文本模式
        url = SAY_MSG_URL
    try:
        if files:
            response = requests.post(url, files=files, data={"prompt": ai_prompt})
            # 关闭文件
            for f in opened_files:
                f.close()
        else:
            response = requests.post(url, data={"prompt": ai_prompt})
        if response.status_code == 200:
            result_text = None
            try:
                result_text = response.json().get("result")
            except json.JSONDecodeError:
                print("[异常] 响应不是 JSON：", response.text)
                return None
            if result_text:
                if json_str:
                    try:
                        return extract_json_dict_from_ai_reply(result_text)
                    except Exception as e:
                        print("[异常] JSON 解析失败，返回原始文本:", e)
                        return result_text
                else:
                    return result_text
            else:
                print("[警告] 响应中没有 result 字段：", response.text)
                return None
        else:
            print(f"[错误] 状态码: {response.status_code}，响应内容: {response.text}")
            return None
    except Exception as e:
        print("[异常] 调用本地模型接口失败:", e)
        return None

if __name__ == "__main__":
    # 1️⃣ 纯文本测试
    text_prompt = "请对以下内容生成摘要：今天天气很好，适合外出。"
    print("=== 纯文本测试 ===")
    text_result = call_local_ai_model(ai_prompt=text_prompt, json_str=False)
    print("返回结果:", text_result, "\n")

    # 2️⃣ 图片测试
    image_paths = [
        "./test_images/image1.jpg",
        "./test_images/image2.png"
    ]
    print("=== 图片测试 ===")
    image_result = call_local_ai_model(ai_prompt="请描述这些图片内容", image_paths=image_paths, json_str=False)
    print("返回结果:", image_result, "\n")

    # 3️⃣ 视频测试
    video_path = "./test_videos/test_video.mp4"
    print("=== 视频测试 ===")
    video_result = call_local_ai_model(ai_prompt="请分析这段视频内容", video_path=video_path, json_str=False)
    print("返回结果:", video_result, "\n")

    # 4️⃣ JSON 字典模式
    print("=== JSON 字典模式测试 ===")
    json_result = call_local_ai_model(ai_prompt="请生成JSON格式的总结", json_str=True)
    print("返回 JSON:", json_result, "\n")
