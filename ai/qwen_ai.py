import os
import ast
import re
import base64
import cv2
import json
from openai import OpenAI

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
api_key = config['qwen_api_key']
base_url = config['qwen_url']
with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
prompt = prompts['normal']

def extract_json_dict_from_ai_reply(text):
    """
    从 AI 返回的文本中提取 markdown 格式中的 JSON 字符串并转换为 dict。

    参数:
        text (str): 包含 AI 返回内容的字符串。

    返回:
        dict 或 None: 成功返回 dict，失败返回 None。
    """
    text = text.replace("```", "").replace("json", "").replace("，", ",")
    match = re.search(r'```json(.*?)```', text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        try:
            data = json.loads(json_str)
            return data  # 直接返回 dict
        except json.JSONDecodeError as e:
            print("JSON 解析失败:", e)
            return None
    else:
        text = text.strip()
        try:
            # 尝试作为标准 JSON 解析
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                # 尝试作为 Python dict 字符串解析
                return ast.literal_eval(text)
            except Exception as e:
                print("解析失败:", e)
                return None


# 使用OpenAI客户端调用通义千问API
def call_qwen_via_client(img_list):
    client = OpenAI(
        api_key=api_key,  # 建议使用环境变量管理
        base_url=base_url
    )

    # 系统提示
    system_prompt = prompt

    user_prompt = f"""以下是间隔1秒的连续监控画面："""

    # 构造图片内容
    images = []
    for img_b64 in img_list:
        images.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
        })

    try:
        # 调用通义千问接口
        completion = client.chat.completions.create(
            model="qwen-vl-max-latest",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": images + [{"type": "text", "text": user_prompt}]
                }
            ]
        )
        # 去除代码块标记
        # print()

        json_str = extract_json_dict_from_ai_reply(completion.choices[0].message.content)
        # print(json_str, type(json_str))
        return json_str
    except Exception as e:
        print("[调用失败] 千问接口返回：", e)
        return None


def encode_image_to_base64(img):
    _, buffer = cv2.imencode('.jpg', img)  # 编码为JPG格式二进制数据
    return base64.b64encode(buffer).decode('utf-8')  # 转为base64字符串


# 主函数，加载图片调用
if __name__ == "__main__":
    img_paths = ["./2.png", "./1.png"]
    img_list = []

    for path in img_paths:
        if os.path.exists(path):
            img = cv2.imread(path)
            if img is not None:
                img_list.append(encode_image_to_base64(img))  # 传入base64字符串
            else:
                print(f"无法读取图像内容：{path}")
        else:
            print(f"文件不存在：{path}")

    if len(img_list) >= 2:
        report = call_qwen_via_client(img_list)
        print("【分析结果】：")
        print(report)
    else:
        print("请至少提供两张图片")
