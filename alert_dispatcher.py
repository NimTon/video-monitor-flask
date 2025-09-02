# 导入第三方库和模块
from utils.ai_utils import call_qwen_via_client, call_local_ai_model
import json  # JSON处理库
from datetime import datetime, timedelta  # 日期时间处理
from storage import StorageManager, AlertStorageManager, RecipientsManager, ImageReportManager
import cv2  # OpenCV图像处理库
import numpy as np
from storage import MessageManager
from utils.utils import save_frames_as_video, save_key_frames, md5, log, cv2_frame_to_base64
from daily_schedule import AutoReportScheduler

message_manager = MessageManager()

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)

base_url = f'http://{config['host']}:{config['port']}'

auto_report_scheduler = AutoReportScheduler(StorageManager(), ImageReportManager(), base_url=base_url)

# 初始化存储管理器
storage = StorageManager()  # 流数据存储
alert_storage = AlertStorageManager()  # 报警配置存储
recipient_mgr = RecipientsManager()  # 接收人管理


# 报警分发函数 只有 changed == True 时给所有帧加对应围栏
def dispatch_alert_multi_frames(stream_id, fence_result, frames):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 当前时间格式化
    stream = storage.get_stream(stream_id)  # 获取流信息
    if not stream:  # 流不存在则返回
        return

    stream_name = stream.get("name", stream_id)  # 获取流名称
    templates = alert_storage.get_alert_templates()  # 获取报警模板
    recipients = recipient_mgr.get_recipients_by_stream_id(stream_id)  # 获取接收人列表
    if len(recipients) == 0:
        print('未绑定联系人')
    ratio = fence_result["change_ratio"]  # 变化比例
    fence_id = fence_result["fence_id"]  # 围栏ID

    # 在帧上画出该围栏的红色边界和点
    for frame in frames:
        points = fence_result.get("fence_points", [])
        if points:
            pts = np.array(points, np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame, [pts], isClosed=True, color=(0, 0, 255), thickness=2)
            for pt in points:
                cv2.circle(frame, pt, 5, (0, 0, 255), -1)

    # 保存或显示报警图片
    image_urls, image_paths = save_key_frames(stream_id, fence_id, frames, base_url=base_url)
    image_urls_text = ', '.join(image_urls)

    # 从frame中保存视频
    video_url, video_path = save_frames_as_video(stream_id, fence_id, frames, base_url=base_url, fps=1)

    # 调用AI识别
    ai_report = None
    # base64_images = [cv2_frame_to_base64(f) for f in frames]  # frames_to_return 是 BGR numpy数组列表
    # ai_report = call_qwen_via_client(imgs=base64_images)  # 通义千问大模型
    # ai_report = call_local_ai_model(image_paths=image_paths)  # 本地大模型（图片）
    ai_report = call_local_ai_model(video_path=video_path)  # 本地大模型（视频）

    # 存入report
    frame_data = {"timestamp": timestamp, "image_path": image_paths[-1], "image_url": image_urls[-1]}
    auto_report_scheduler.save_one_frame(stream_id, stream_name, frame_data, datetime.now().strftime("%Y-%m-%d"))

    if not ai_report:
        print('AI识别失效')
    elif ai_report['status'] == "正常":
        # 如果正常，不触发报警，释放帧内存
        print(f"stream_name:{stream_name} fence_id:{fence_id} 一切正常")
        del frames
        return  # 不触发报警，结束函数

    # 存入message.json
    message_manager.add_message(stream_uid=stream_id, fence_uid=fence_id, stream_name=stream_name,
                                change_ratio=f"{ratio:.2f}", ai_report=str(ai_report), image_before_url=image_urls[0],
                                image_after_url=image_urls[1], video_url=video_url)

    # 模板变量
    template_vars = {
        "stream_name": stream_name,
        "fence_id": fence_id,
        "timestamp": timestamp,
        "change_ratio": f"{ratio:.2f}",
        "ai_report": ai_report,
        "image_url": image_urls_text,
        "video_url": video_url
    }

    template = templates[0]  # 获取第一个模板
    message = ''
    try:
        message = template['text'].format(**template_vars)  # 渲染模板
        print(message)
    except Exception as e:
        print(f"[模板渲染失败] {e}")  # 模板渲染错误

    # 遍历接收人发送报警
    for recipient in recipients:
        contact = recipient.get("contact", {})  # 获取联系方式
        for method_name, contact_value in contact.items():
            if contact_value:  # 联系方式有效
                fn = alert_method_map.get(method_name.lower())  # 获取报警方法
                if fn:
                    try:
                        fn(  # 调用报警方法
                            message,
                            contact_value,
                            # prev_image_path=prev_image_path, TODO
                            # curr_image_path=curr_image_path TODO
                        )
                        print(f"✅ 已通过【{method_name}】发送给 {recipient['name']}")  # 成功日志
                    except Exception as e:
                        print(f"❌ 通过【{method_name}】发送失败：{e}")  # 失败日志


# 主程序入口
if __name__ == "__main__":
    stream_id = '06219170-867a-4ff7-96b5-5df12e641442'  # 测试流ID
    fence_result = {  # 测试围栏结果
        "change_ratio": 1,
        "fence_id": 0,
    }
    prev_frame = '1'  # 测试前帧
    curr_frame = '2'  # 测试当前帧
    send_sms_alert('这是一个测试', '13070206760', '1', '1')  # 测试短信发送
