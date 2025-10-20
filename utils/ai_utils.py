import os
import requests
from openai import OpenAI
from config import LOCAL_AI_VIDEO_URL, LOCAL_AI_IMAGES_URL, LOCAL_AI_TEXT_URL
import re
import json
import ast

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
api_key = config['qwen_api_key']
base_url = config['qwen_url']
with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
prompt = prompts['normal']


def try_local_ai_fix_json(text: str):
    """
    尝试调用 local_ai 来帮忙修复非标准 JSON 文本。
    """
    try:
        payload = {"prompt": f"请将以下文本转换为标准 JSON 格式：\n{text}"}
        response = requests.post(LOCAL_AI_TEXT_URL, data=payload)
        if response.status_code == 200:
            fixed_text = response.json().get("result", "")
            if fixed_text:
                return json.loads(fixed_text)
        raise ValueError(f"local_ai 修复失败: {response.text}")
    except Exception as e:
        raise RuntimeError(f"local_ai 格式化失败: {e}") from e


def try_qwen_ai_fix_json(text: str):
    """
    调用 qwen_ai 来修复格式。
    """
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        system_prompt = "你是一个专业的数据清洗助手，请将输入文本转换为严格的 JSON。"
        completion = client.chat.completions.create(
            model="qwen-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"修复以下内容为标准 JSON：\n{text}"}
            ]
        )
        result = completion.choices[0].message.content
        if result:
            return json.loads(result)
        raise ValueError("qwen_ai 未返回内容")
    except Exception as e:
        raise RuntimeError(f"qwen_ai 格式化失败: {e}") from e


def extract_json_dict_from_ai_reply(text: str):
    """
    从 AI 回复中提取 JSON 对象。
    支持多种情况：
    - 纯 JSON
    - Markdown 代码块 ```json``` ... ```
    - XML 样式 <json>...</json>
    - JSON 前后带说明文字
    如果所有尝试失败，则依次调用 local_ai、qwen_ai 修复。
    """
    if not text:
        raise ValueError("AI 回复为空")

    # ----------- Step 1: 清洗文本（去掉空白、常见提示等）-----------
    cleaned = text.strip()

    # 移除常见“标记语句”
    cleaned = re.sub(r'^[\s\S]*?```json', '```json', cleaned, flags=re.I)  # 去掉前导废话
    cleaned = cleaned.replace("```", "").replace("json", "").replace("JSON", "").strip()
    cleaned = re.sub(r'^.*?(?=\{)', '', cleaned, flags=re.S)  # 丢弃JSON前的非花括号内容
    cleaned = re.sub(r'(?<=\})[^}]*$', '', cleaned, flags=re.S)  # 丢弃JSON后的多余内容

    # ----------- Step 2: 提取可能的 JSON 块 -----------
    candidates = []

    # (1) Markdown 代码块 ```json ... ```
    for m in re.finditer(r"```json(.*?)```", text, flags=re.S | re.I):
        candidates.append(m.group(1).strip())

    # (2) <json> ... </json> 块
    for m in re.finditer(r"<json>(.*?)</json>", text, flags=re.S | re.I):
        candidates.append(m.group(1).strip())

    # (3) 最外层 {...} 块
    for m in re.finditer(r"\{[\s\S]*?\}", text, flags=re.S):
        candidates.append(m.group(0).strip())

    # 若无候选，则直接使用 cleaned
    if not candidates:
        candidates = [cleaned]

    # ----------- Step 3: 逐一尝试解析 JSON -----------
    for c in sorted(candidates, key=len, reverse=True):  # 优先尝试较长的候选
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(c)
            except Exception:
                continue

    # ----------- Step 4: fallback — local_ai 修复 -----------
    try:
        return try_local_ai_fix_json(text)
    except Exception as e:
        pass

    # ----------- Step 5: fallback — qwen_ai 修复 -----------
    try:
        return try_qwen_ai_fix_json(text)
    except Exception as e:
        raise ValueError(f"所有方法均解析失败，原始文本: {text}")


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
            return extract_json_dict_from_ai_reply(result_text)
        else:
            return result_text

    except Exception as e:
        raise RuntimeError(f"调用本地模型接口异常: {e}") from e
