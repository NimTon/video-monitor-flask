import ast
import json
import os
import requests
from openai import OpenAI

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
SAY_IMAGES_URL = config['local_ai_images_url']
SAY_VIDEO_URL = config['local_ai_video_url']
SAY_MSG_URL = config['local_ai_text_url']
api_key = config['qwen_api_key']
base_url = config['qwen_url']
with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
prompt = prompts['normal']


def extract_json_dict_from_ai_reply(text: str):
    if not text:
        return None

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or start >= end:
        print("未找到有效的 JSON 结构", text)
        return None

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
        print("解析失败:", e, text)
        return None


def call_qwen_via_client(p=prompt, imgs=None, model='qwen-vl-max-latest', json_str=True):
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
            result = completion.choices[0].message.content
            if json_str:
                return extract_json_dict_from_ai_reply(result)
            else:
                return result
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
            if json_str:
                return extract_json_dict_from_ai_reply(result)
            else:
                return result
    except Exception as e:
        print("[调用失败] 千问接口返回：", e)
        return None


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
