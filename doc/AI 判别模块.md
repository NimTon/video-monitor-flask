## 模块名称
AI 判别模块 `qwen_ai.py`

## 模块定位
本模块用于调用通义千问多模态模型（Qwen-VL）对仓库监控图像进行智能分析，识别人员、货物、环境的异常行为，辅助系统判断是否需要触发报警。作为整个系统的“智能大脑”，它在视频检测模块之后，对关键帧进行语义分析，输出结构化 JSON 结果供报警模块使用。

## 技术栈与依赖
- Python 3.10+
- OpenCV 4.x（用于图像读取、编码）
- OpenAI Python SDK（兼容通义千问 DashScope 接口）
- Base64（图像转字符串）
- 正则表达式（清洗 API 返回内容）
- JSON（格式化 AI 返回内容）

## 输入与输出
- 输入：
  - 图片列表（长度 ≥2，推荐2帧，10秒间隔，BGR numpy 格式）
- 输出：
  - 一个结构化 JSON 对象，包含以下字段：
    - object：主要监测目标（如“货物散落异常”）
    - status：是否报警（正常/报警）
    - report：简要文字报告
    - detail：细化变更类型、风险等级、建议
    - recommendations：后续建议行动

## 核心功能与逻辑说明
### 核心函数 `call_qwen_via_client(img_list)`
该函数接受若干图片帧，先将它们编码为 base64 格式，再通过 OpenAI SDK 调用 Qwen-VL 模型进行分析，获得一个判断结果。

### 核心流程伪代码如下：
```

图像帧列表 → base64 编码 → 构造 prompt → 调用 Qwen API → 清洗响应 → 结构化 JSON 返回

````

### 系统 prompt 设计
通过精心编写的系统 prompt，明确约束 AI 响应的判断标准（如人员异常、货物变化、环境风险），并指定返回格式为结构化 JSON，保证 AI 输出稳定性。

### 图片处理逻辑
使用 `cv2.imencode` 将每帧转换为 JPEG 格式，并 base64 编码，使其符合 DashScope 的 `image_url` 接口输入标准。

## 配置说明
该模块目前硬编码了以下内容，建议后期通过配置文件或环境变量改造：
- `api_key`: 通义千问密钥（推荐用 `os.environ` 管理）
- `base_url`: DashScope 的兼容模式地址
- `model`: 使用 `qwen-vl-max-latest` 模型
- `system_prompt`: 内嵌于代码中，描述具体监控分析规则

## 与其他模块的交互
- 被 `video_stream.py` 调用：当检测到围栏区域变化时，采集图像帧传入此模块分析。
- 向 `alert_dispatcher.py` 提供结构化结果：由后者将 AI 分析内容渲染入报警模板并推送。
- 输出结果格式被 `alert_template.json` 等模板引用。

## 调试建议
可单独运行模块进行测试：
```bash
python qwen_ai.py
````

此时会读取本地 `1.png`、`2.png` 并输出 AI 判别结果。适合离线调试 prompt 或分析返回内容结构。
