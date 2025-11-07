# test.py
import base64
import json
import os
from utils import ai_manager


def qwen_text():
    """测试千问文本模式"""
    prompt = "请生成一个包含 key/value 的 JSON 示例，描述一只猫的特征。"
    try:
        future = ai_manager.add_task("call_qwen_via_client", p=prompt, json_str=True)
        result = future.result()  # 等待执行完成
        print("=== call_qwen_via_client 文本模式 ===")
        print(result)
    except Exception as e:
        print(f"call_qwen_via_client 文本模式测试失败: {e}")


def qwen_image():
    """测试千问图文模式"""
    img_path = "test.jpg"
    if not os.path.exists(img_path):
        print(f"测试图片不存在: {img_path}, 跳过图文测试")
        return
    try:
        with open(img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        future = ai_manager.add_task("call_qwen_via_client", p="描述这张图片的内容", imgs=[img_b64], json_str=True)
        result = future.result()  # 等待执行完成
        print("=== call_qwen_via_client 图文模式 ===")
        print(result)
    except Exception as e:
        print(f"call_qwen_via_client 图文模式测试失败: {e}")


def local_text():
    """测试本地 AI 文本模式"""
    prompt = "请生成一个包含 key/value 的 JSON 示例，描述一只狗的特征。"
    try:
        future = ai_manager.add_task("call_local_ai_model", ai_prompt=prompt, json_str=True)
        result = future.result()  # 等待执行完成
        print("=== call_local_ai_model 文本模式 ===")
        print(result)
    except Exception as e:
        print(f"call_local_ai_model 文本模式测试失败: {e}")


# def local_image():
#     """测试本地 AI 图像模式"""
#     img_path = "test.jpg"
#     if not os.path.exists(img_path):
#         print(f"测试图片不存在: {img_path}, 跳过图像测试")
#         return
#     try:
#         future = ai_manager.add_task("call_local_ai_model", ai_prompt="描述这张图片的内容", image_paths=[img_path], json_str=True)
#         result = future.result()  # 等待执行完成
#         print("=== call_local_ai_model 图像模式 ===")
#         print(result)
#     except Exception as e:
#         print(f"call_local_ai_model 图像模式测试失败: {e}")


def local_image():
    """测试本地 AI 图像模式 - 货物定位与计数"""
    img_path = "./test/test1.jpg"
    if not os.path.exists(img_path):
        print(f"测试图片不存在: {img_path}, 跳过图像测试")
        return

    # 使用中文提示词，并要求返回字段名也是中文
    detailed_prompt = """仓库环境：长50米，宽50米，高8米。
摄像头参数：安装位置(0,25,4)，视角-20°，焦距6mm,像素200万。

请分析图片并完成以下任务：
1. 识别电子围栏区域内的所有货物
2. 计算每个货物在仓库中的坐标位置(x,y,z)
3. 统计货物的总数量
4. 如果可能，识别货物的类型

重要要求：
- 请使用中文简体返回所有分析结果
- 返回的JSON字段名也要使用中文
- 货物类型统计请返回字典格式，如 {"纸箱": 5, "木箱": 3}

请以JSON格式返回结果，包含以下字段：
- 货物总数: 整数
- 货物坐标: 列表，包含每个货物的编号和坐标 [{"编号": "1", "坐标": [x,y,z]}, ...]
- 分析摘要: 字符串，描述分析结果
- 货物类型: 字典，记录不同类型货物的数量
"""

    try:
        future = ai_manager.add_task(
            "call_local_ai_model",
            ai_prompt=detailed_prompt,
            image_paths=[img_path],
            json_str=True
        )
        result = future.result()  # 等待执行完成
        print("=== 货物定位与计数分析结果 ===")
        print(f"仓库尺寸: 50m × 50m × 8m")
        print(f"摄像头位置: (0, 25, 4)")
        print("分析结果:")

        # 检查结果类型并适当处理
        if isinstance(result, str):
            print(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))

        # 使用中文字段名提取信息
        if isinstance(result, dict):
            # 尝试不同的字段名，兼容可能的响应变化
            total_count = result.get('货物总数', result.get('total_count', 0))
            goods_positions = result.get('货物坐标', result.get('goods_positions', []))
            analysis_summary = result.get('分析摘要', result.get('analysis_summary', ''))
            goods_types = result.get('货物类型', result.get('goods_types', {}))

            print(f"\n关键统计:")
            print(f"电子围栏内货物总数: {total_count}")
            print(f"定位到的货物坐标数量: {len(goods_positions)}")
            if analysis_summary:
                print(f"分析摘要: {analysis_summary}")

            # 处理货物类型统计 - 安全处理不同类型
            print(f"\n货物类型统计:")
            if isinstance(goods_types, dict):
                for goods_type, count in goods_types.items():
                    print(f"  {goods_type}: {count}个")
            elif isinstance(goods_types, str):
                print(f"  {goods_types}")
            else:
                print("  无法获取货物类型信息")

            # 显示货物坐标示例
            if goods_positions:
                print("\n货物坐标:")
                for goods in goods_positions:
                    # 兼容不同的字段名
                    goods_id = goods.get('编号', goods.get('id', '未知'))
                    coords = goods.get('坐标', goods.get('coordinates', []))
                    print(f"货物{goods_id}: 坐标{coords}")

    except Exception as e:
        print(f"货物定位分析测试失败: {e}")
        # 记录详细错误信息
        import traceback
        print(f"详细错误: {traceback.format_exc()}")


def local_video():
    """测试本地 AI 视频模式"""
    video_path = "6.mp4"
    if not os.path.exists(video_path):
        print(f"测试视频不存在: {video_path}, 跳过视频测试")
        return
    try:
        future = ai_manager.add_task(
            "call_local_ai_model",
            ai_prompt="分析这个视频的内容，用中文简体回复",
            video_path=video_path,
            json_str=True
        )
        result = future.result()  # 等待执行完成
        print("=== call_local_ai_model 视频模式 ===")
        print(result)
    except Exception as e:
        print(f"call_local_ai_model 视频模式测试失败: {e}")


if __name__ == "__main__":
    # qwen_text()
    # qwen_image()
    # local_text()
    local_image()
    # local_video()
