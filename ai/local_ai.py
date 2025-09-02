import json
from utils.ai_utils import call_local_ai_model

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
SAY_IMAGES_URL = config['local_ai_images_url']
SAY_VIDEO_URL = config['local_ai_video_url']
SAY_MSG_URL = config['local_ai_text_url']
with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
prompt = prompts['normal']

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
