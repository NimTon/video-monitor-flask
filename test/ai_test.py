# test.py
import base64
from utils.ai_utils import call_qwen_via_client, call_local_ai_model

def test_qwen_text():
    """测试千问文本模型"""
    prompt = "请生成一个包含 key/value 的 JSON 示例，描述一只猫的特征。"
    try:
        result = call_qwen_via_client(p=prompt, json_str=True)
        print("=== call_qwen_via_client 文本模式 ===")
        print(result)
    except Exception as e:
        print(f"call_qwen_via_client 文本模式测试失败: {e}")


def test_qwen_image():
    """测试千问图文模型"""
    # 这里用一个本地图片做测试，需要替换成真实存在的图片路径
    img_path = "test.jpg"
    try:
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        result = call_qwen_via_client(p="描述这张图片的内容", imgs=[img_b64], json_str=True)
        print("=== call_qwen_via_client 图文模式 ===")
        print(result)
    except FileNotFoundError:
        print(f"测试图片不存在: {img_path}")
    except Exception as e:
        print(f"call_qwen_via_client 图文模式测试失败: {e}")


def test_local_text():
    """测试本地文本模型"""
    prompt = "请生成一个包含 key/value 的 JSON 示例，描述一只狗的特征。"
    try:
        result = call_local_ai_model(ai_prompt=prompt, json_str=True)
        print("=== call_local_ai_model 文本模式 ===")
        print(result)
    except Exception as e:
        print(f"call_local_ai_model 文本模式测试失败: {e}")


def test_local_image():
    """测试本地图像模型"""
    img_path = "test.jpg"
    try:
        result = call_local_ai_model(ai_prompt="描述这张图片的内容", image_paths=[img_path], json_str=True)
        print("=== call_local_ai_model 图像模式 ===")
        print(result)
    except FileNotFoundError:
        print(f"测试图片不存在: {img_path}")
    except Exception as e:
        print(f"call_local_ai_model 图像模式测试失败: {e}")


if __name__ == "__main__":
    test_qwen_text()
    test_qwen_image()
    test_local_text()
    test_local_image()
