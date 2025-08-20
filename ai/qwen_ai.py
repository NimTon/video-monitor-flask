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


import ast
import json

def extract_json_dict_from_ai_reply(text: str):
    if not text:
        return None

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or start >= end:
        print("未找到有效的 JSON 结构", text)
        return None

    json_candidate = text[start:end+1].strip()

    # 优先尝试 JSON
    try:
        return json.loads(json_candidate)
    except json.JSONDecodeError:
        pass

    # 退一步尝试 Python dict 字符串
    try:
        return ast.literal_eval(json_candidate)
    except Exception as e:
        print("解析失败:", e, text)
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