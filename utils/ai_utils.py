import ast
import json
import os
import requests
from openai import OpenAI
from config import LOCAL_AI_VIDEO_URL, LOCAL_AI_IMAGES_URL, LOCAL_AI_TEXT_URL

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
api_key = config['qwen_api_key']
base_url = config['qwen_url']
with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
prompt = prompts['normal']


def extract_json_dict_from_ai_reply(text: str):
    if not text:
        raise ValueError("AI 回复为空")

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or start >= end:
        raise ValueError(f"未找到有效的 JSON 结构: {text}")

    json_candidate = text[start:end + 1].strip()

    # 优先尝试 JSON
    try:
        return json.loads(json_candidate)
    except json.JSONDecodeError:
        pass

    # 退一步尝试 Python dict 字符串
    try:
        return ast.literal_eval(json_candidate)
    except Exception as e:
        raise ValueError(f"解析失败: {e}, 原始文本: {text}") from e


def call_qwen_via_client(p=prompt, imgs=None, model='qwen-vl-max-latest', json_str=True):
    client = OpenAI(api_key=api_key, base_url=base_url)
    system_prompt = "你是一个ai助手"
    user_prompt = p

    try:
        if imgs:
            content = [*[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}} for img_b64 in imgs],
                       {"type": "text", "text": user_prompt}]
        else:
            content = [{"type": "text", "text": user_prompt}]

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
        )

        result = completion.choices[0].message.content
        if not result:
            raise ValueError("AI 回复为空")

        if json_str:
            return extract_json_dict_from_ai_reply(result)
        else:
            return result

    except Exception as e:
        raise RuntimeError(f"调用千问接口失败: {e}") from e


def call_local_ai_model(ai_prompt=None, image_paths=None, video_path=None, json_str=True):
    files = []
    opened_files = []
    url = None

    # 参数合法性检查
    if image_paths and video_path:
        raise ValueError("不能同时传入图片和视频")
    elif image_paths:
        url = LOCAL_AI_IMAGES_URL
        for path in image_paths:
            if not os.path.exists(path):
                raise FileNotFoundError(f"文件不存在: {path}")
            ext = os.path.splitext(path)[1].lower()
            mime = f"image/{ext[1:]}" if ext else "image/jpeg"
            f = open(path, "rb")
            opened_files.append(f)
            files.append(("files", (os.path.basename(path), f, mime)))
    elif video_path:
        url = LOCAL_AI_VIDEO_URL
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        ext = os.path.splitext(video_path)[1].lower()
        mime = f"video/{ext[1:]}" if ext else "video/mp4"
        f = open(video_path, "rb")
        opened_files.append(f)
        files.append(("files", (os.path.basename(video_path), f, mime)))
    else:
        url = LOCAL_AI_TEXT_URL  # 纯文本模式

    try:
        if files:
            response = requests.post(url, files=files, data={"prompt": ai_prompt})
        else:
            response = requests.post(url, data={"prompt": ai_prompt})

        # 关闭文件
        for f in opened_files:
            f.close()

        if response.status_code != 200:
            raise RuntimeError(f"调用模型接口失败，状态码: {response.status_code}，响应内容: {response.text}")

        try:
            result_text = response.json().get("result")
        except json.JSONDecodeError as e:
            raise ValueError(f"响应不是有效 JSON: {response.text}") from e

        if not result_text:
            raise ValueError(f"响应中没有 result 字段: {response.text}")

        if json_str:
            try:
                return extract_json_dict_from_ai_reply(result_text)
            except Exception as e:
                raise ValueError(f"解析 AI 回复 JSON 失败: {result_text}") from e
        else:
            return result_text

    except Exception as e:
        # 统一抛出异常
        raise RuntimeError(f"调用本地模型接口异常: {e}") from e
call_local_ai_model("你是谁")