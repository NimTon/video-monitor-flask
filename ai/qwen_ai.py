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
def call_qwen_via_client(p=prompt, imgs=None, model='qwen-vl-max-latest'):
    client = OpenAI(api_key=api_key, base_url=base_url)
    system_prompt = "你是一个ai助手"
    user_prompt = p
    try:
        if imgs:
            content = [*[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}} for img_b64 in imgs], {"type": "text", "text": user_prompt}]
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ]
            )
            json_str = extract_json_dict_from_ai_reply(completion.choices[0].message.content)
            return json_str
        else:
            content = [{"type": "text", "text": user_prompt}]
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content}
                ]
            )
            text = completion.choices[0].message.content
            return text
    except Exception as e:
        print("[调用失败] 千问接口返回：", e)
        return None