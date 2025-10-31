import os
import re
import ast
import json
import requests
import threading
from queue import Queue
from concurrent.futures import Future
from openai import OpenAI
from config import LOCAL_AI_VIDEO_URL, LOCAL_AI_IMAGES_URL, LOCAL_AI_TEXT_URL


class AIModelManager:
    def __init__(self, config_path='config.json', prompts_path='prompts.json'):
        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)
        self.api_key = config['qwen_api_key']
        self.base_url = config['qwen_url']

        with open(prompts_path, encoding='utf-8') as f:
            prompts = json.load(f)
        self.default_prompt = prompts['normal']

        # 队列与后台线程
        self.task_queue = Queue()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    # ------------------ 队列核心逻辑 ------------------

    def _worker(self):
        """后台线程，从队列中取任务并顺序执行"""
        while True:
            func, args, kwargs, future = self.task_queue.get()
            try:
                result = func(*args, **kwargs)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                self.task_queue.task_done()

    def add_task(self, func_name, *args, **kwargs):
        """将任务加入队列（例如 func_name='call_qwen_via_client'）"""
        if not hasattr(self, func_name):
            raise AttributeError(f"未定义方法: {func_name}")

        func = getattr(self, func_name)
        future = Future()
        self.task_queue.put((func, args, kwargs, future))
        return future

    # ------------------ JSON 解析与修复 ------------------

    def try_local_ai_fix_json(self, text: str):
        """调用 local_ai 修复 JSON"""
        try:
            payload = {"prompt": f"请将以下文本转换为标准 JSON 格式：\n{text}"}
            response = requests.post(LOCAL_AI_TEXT_URL, data=payload)
            if response.status_code == 200:
                fixed_text = response.json().get("result", "")
                if fixed_text:
                    return self.extract_json_dict_from_ai_reply(fixed_text, use_ai=False)
            raise ValueError(f"local_ai 修复失败: {response.text}")
        except Exception as e:
            raise RuntimeError(f"local_ai 格式化失败: {e}") from e

    def try_qwen_ai_fix_json(self, text: str):
        """调用 qwen_ai 修复 JSON"""
        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            completion = client.chat.completions.create(
                model="qwen-turbo",
                messages=[
                    {"role": "system", "content": "你是一个专业的数据清洗助手，请将输入文本转换为严格的 JSON。"},
                    {"role": "user", "content": f"修复以下内容为标准 JSON：\n{text}"}
                ]
            )
            result = completion.choices[0].message.content
            if result:
                return self.extract_json_dict_from_ai_reply(result, use_ai=False)
            raise ValueError("qwen_ai 未返回内容")
        except Exception as e:
            raise RuntimeError(f"qwen_ai 格式化失败: {e}") from e

    def extract_json_dict_from_ai_reply(self, text: str, use_ai=True):
        """提取或修复 JSON"""
        if not text:
            raise ValueError("AI 回复为空")

        cleaned = text.strip().replace("'", '"')
        cleaned = re.sub(r'^[\s\S]*?```json', '```json', cleaned, flags=re.I)
        cleaned = cleaned.replace("```", "").replace("json", "").replace("JSON", "").strip()
        cleaned = re.sub(r'^.*?(?=\{)', '', cleaned, flags=re.S)
        cleaned = re.sub(r'(?<=\})[^}]*$', '', cleaned, flags=re.S)

        candidates = []

        for m in re.finditer(r"```json(.*?)```", text, flags=re.S | re.I):
            candidates.append(m.group(1).strip())
        for m in re.finditer(r"<json>(.*?)</json>", text, flags=re.S | re.I):
            candidates.append(m.group(1).strip())
        for m in re.finditer(r"\{[\s\S]*?\}", text, flags=re.S):
            candidates.append(m.group(0).strip())
        if not candidates:
            candidates = [cleaned]

        # 尝试解析
        for c in sorted(candidates, key=len, reverse=True):
            try:
                return json.loads(c)
            except json.JSONDecodeError:
                try:
                    return ast.literal_eval(c)
                except Exception:
                    continue

        # 调用AI修复
        if use_ai:
            try:
                return self.try_local_ai_fix_json(text)
            except Exception:
                pass
            return self.try_qwen_ai_fix_json(text)
        else:
            raise ValueError(f"所有方法均解析失败，原始文本: {text}")

    # ------------------ 模型调用 ------------------

    def call_qwen_via_client(self, p=None, imgs=None, model='qwen-vl-max-latest', json_str=True):
        """调用千问模型"""
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        prompt = p or self.default_prompt
        try:
            if imgs:
                content = [
                    *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in imgs],
                    {"type": "text", "text": prompt}
                ]
            else:
                content = [{"type": "text", "text": prompt}]

            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个ai助手"},
                    {"role": "user", "content": content}
                ]
            )
            result = completion.choices[0].message.content
            if not result:
                raise ValueError("AI 回复为空")

            return self.extract_json_dict_from_ai_reply(result) if json_str else result
        except Exception as e:
            raise RuntimeError(f"调用千问接口失败: {e}") from e

    def call_local_ai_model(self, ai_prompt=None, image_paths=None, video_path=None, json_str=True):
        """调用本地 AI 模型"""
        files = []
        opened_files = []
        url = None

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
            url = LOCAL_AI_TEXT_URL

        try:
            if files:
                response = requests.post(url, files=files, data={"prompt": ai_prompt})
            else:
                response = requests.post(url, data={"prompt": ai_prompt})
        finally:
            for f in opened_files:
                f.close()

        if response.status_code != 200:
            raise RuntimeError(f"调用模型接口失败，状态码: {response.status_code}，响应内容: {response.text}")

        result_text = response.json().get("result", "")
        if not result_text:
            raise ValueError(f"响应中没有 result 字段: {response.text}")

        return self.extract_json_dict_from_ai_reply(result_text) if json_str else result_text
