import os
import time
import re
import base64
import cv2
import json
from openai import OpenAI

with open('config.json') as f:
    config = json.load(f)
api_key = config['qwen_api_key']
base_url = config['qwen_url']

def extract_json_dict_from_ai_reply(text):
    """
    从 AI 返回的文本中提取 markdown 格式中的 JSON 字符串并转换为 dict。

    参数:
        text (str): 包含 AI 返回内容的字符串。

    返回:
        dict 或 None: 成功返回 dict，失败返回 None。
    """
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
        print("未找到 JSON 代码块")
        return None


# 使用OpenAI客户端调用通义千问API
def call_qwen_via_client(img_list):
    client = OpenAI(
        api_key="sk-f3ec150157ec41baaa516b15d1feaeae",  # 建议使用环境变量管理
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    # 系统提示
    system_prompt = """你是一个专业的安防监控AI分析系统，专门负责仓库监控画面中**绿色电子围栏区域**的变化检测。你的任务如下：

1. 严格分析由时间间隔1秒的连续帧中**绿色电子围栏圈出区域**的图像变化；
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
