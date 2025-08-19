import requests
import os
import json
from ai.qwen_ai import extract_json_dict_from_ai_reply

with open('config.json') as f:
    config = json.load(f)
SAY_IMAGES_URL = config['local_ai_images_url']
SAY_VIDEO_URL = config['local_ai_video_url']

prompt = """你是一个专业的安防监控AI分析系统，专门负责仓库监控画面中**红色电子围栏区域**的变化检测。你的任务如下：
        1. 严格分析由时间间隔1秒的连续帧中**红色电子围栏圈出区域**的图像变化；
        2. 仅对电子围栏内的内容进行判断，忽略区域外的变化；
        3. 根据以下安全策略判断是否需要触发报警：
           - 人员异常出现或移动（未经授权进入电子围栏区域）
           - 货物位置或数量发生异常变化（掉落、被移动、消失）
           - 设备状态异常（如叉车出现/移动、门禁异常开启）
           - 环境突发异常（如烟雾、火焰、水渍等）
           - 有异物移动，突然闯入或者离开（如车辆、货物、人等）
           - 有车辆移动，突然闯入或者离开
        4. 忽略以下正常变化：
           - 灯光明暗变化或自然闪烁
           - 摄像头图像噪点或轻微抖动
           - 小动物经过（如老鼠、鸟类等）
           - 反光、阴影变化或风吹树叶等环境干扰
        5. 输出以下**严格 JSON 格式**的响应，结构不可更改，用于下游系统处理，其中event_type为int，分别表示5（人员聚集）/6（活动车辆）/7（车货），返回int最大值：
        
        {
          "object": "一切正常/货物散落异常/货物位置异常/人员闯入/设备异常/环境异常",
          "status": "正常/报警",
          "report": "对电子围栏区域的自然语言总结说明",
          "detail": {
            "changes": {
              "type": "无变化/货物散落/货物位置变化/人员异常/设备异常/环境异常",
              "event_type": "5/6/7",
              "description": "对异常的详细描述",
              "risk_level": "低/中/高",
              "alert_suggestion": "否/是"
            },
            "recommendations": "提出建议"
          }
        }
        """


def call_local_ai_model(image_paths=None, video_path=None, prompt=prompt):
    files = []
    opened_files = []
    url = None

    # 参数合法性检查
    if image_paths and video_path:
        print("错误：不能同时传入图片和视频")
        return None
    elif image_paths:
        url = SAY_IMAGES_URL
        for path in image_paths:
            if not os.path.exists(path):
                print(f"警告：文件不存在 - {path}")
                continue
            file_ext = os.path.splitext(path)[1].lower()
            mime_type = f"image/{file_ext[1:]}" if file_ext else "image/jpeg"
            f = open(path, "rb")
            opened_files.append(f)
            files.append(("files", (os.path.basename(path), f, mime_type)))
    elif video_path:
        url = SAY_VIDEO_URL
        if not os.path.exists(video_path):
            print(f"错误：视频文件不存在 - {video_path}")
            return None
        file_ext = os.path.splitext(video_path)[1].lower()
        mime_type = f"video/{file_ext[1:]}" if file_ext else "video/mp4"
        f = open(video_path, "rb")
        opened_files.append(f)
        files.append(("files", (os.path.basename(video_path), f, mime_type)))
    else:
        print("错误：必须传入 image_paths 或 video_path")
        return None

    # 如果用户没有传 prompt，使用默认
    ai_prompt = prompt or "请完整描述视频内容?" if video_path else "请描述图片内容?"

    try:
        data = {"prompt": ai_prompt}
        response = requests.post(url, files=files, data=data)

        # 确保关闭文件句柄
        for f in opened_files:
            f.close()

        if response.status_code == 200:
            try:
                result_text = response.json().get("result")
                if result_text:
                    # 这里可以选择直接返回字符串，也可以抽取 JSON
                    return extract_json_dict_from_ai_reply(result_text)
                else:
                    print("响应中没有 result 字段：", response.text)
                    return None
            except json.JSONDecodeError:
                print("响应不是 JSON：", response.text)
                return None
        else:
            print(f"[错误] 状态码: {response.status_code}")
            print("响应内容:", response.text)
            return None
    except Exception as e:
        print("[异常] 调用本地模型接口失败:", e)
        return None
