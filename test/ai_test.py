# test.py
import base64
from utils.ai_utils import call_qwen_via_client, call_local_ai_model
import os

def test_qwen_text():
    """测试千问文本模式"""
    prompt = "请生成一个包含 key/value 的 JSON 示例，描述一只猫的特征。"
    try:
        result = call_qwen_via_client(p=prompt, json_str=True)
        print("=== call_qwen_via_client 文本模式 ===")
        print(result)
    except Exception as e:
        print(f"call_qwen_via_client 文本模式测试失败: {e}")

def test_qwen_image():
    """测试千问图文模式"""
    img_path = "test.jpg"
    if not os.path.exists(img_path):
        print(f"测试图片不存在: {img_path}, 跳过图文测试")
        return
    try:
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        result = call_qwen_via_client(p="描述这张图片的内容", imgs=[img_b64], json_str=True)
        print("=== call_qwen_via_client 图文模式 ===")
        print(result)
    except Exception as e:
        print(f"call_qwen_via_client 图文模式测试失败: {e}")

def test_local_text():
    """测试本地 AI 文本模式"""
    prompt = "请生成一个包含 key/value 的 JSON 示例，描述一只狗的特征。"
    try:
        result = call_local_ai_model(ai_prompt=prompt, json_str=True)
        print("=== call_local_ai_model 文本模式 ===")
        print(result)
    except Exception as e:
        print(f"call_local_ai_model 文本模式测试失败: {e}")

def test_local_image():
    """测试本地 AI 图像模式"""
    img_path = "test.jpg"
    if not os.path.exists(img_path):
        print(f"测试图片不存在: {img_path}, 跳过图像测试")
        return
    try:
        result = call_local_ai_model(ai_prompt="描述这张图片的内容", image_paths=[img_path], json_str=True)
        print("=== call_local_ai_model 图像模式 ===")
        print(result)
    except Exception as e:
        print(f"call_local_ai_model 图像模式测试失败: {e}")

def test_local_video():
    """测试本地 AI 视频模式"""
    video_path = "test.mp4"
    if not os.path.exists(video_path):
        print(f"测试视频不存在: {video_path}, 跳过视频测试")
        return
    try:
        result = call_local_ai_model(ai_prompt="分析这个视频的内容", video_path=video_path, json_str=True)
        print("=== call_local_ai_model 视频模式 ===")
        print(result)
    except Exception as e:
        print(f"call_local_ai_model 视频模式测试失败: {e}")

if __name__ == "__main__":
    test_qwen_text()
    test_qwen_image()
    test_local_text()
    test_local_image()
    test_local_video()
