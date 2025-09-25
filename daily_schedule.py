import threading
import datetime
import time
import cv2
import os
import json
from pathlib import Path
from storage import StorageManager, ImageReportManager, RecipientsManager, sm
from utils.ai_utils import call_qwen_via_client, call_local_ai_model
from utils.utils import log, log_multiline, image_path_to_base64, save_report_to_docx, resize_to_720p, points_to_abs_points, draw_fence_on_frame, docx_to_pdf
from utils.alert_utils import send_email_alert
from emergency.utils.api_utils import zk_api
import schedule

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
base_url = f'http://{config["host"]}:{config["port"]}'

with open('prompts.json', encoding='utf-8') as f:
    prompts = json.load(f)
daily_prompt = prompts['daily']
daily_summary_prompt = prompts['daily_summary']


class AutoReportScheduler:
    def __init__(self, storage_mgr: StorageManager, report_mgr: ImageReportManager, save_dir="images/daily", base_url='127.0.0.1:5000'):
        self.storage_mgr = storage_mgr
        self.report_mgr = report_mgr
        self.save_dir = save_dir
        self.base_url = base_url
        os.makedirs(save_dir, exist_ok=True)

        # ------------------------
        # 日志文件路径
        # ------------------------
        os.makedirs("/logs", exist_ok=True)
        now_str = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_file_path = f"/logs/daily_schedule-{now_str}.log"

    # ------------------------
    # 抓取单个视频流帧
    # ------------------------
    def capture_stream_frame(self, stream_name, stream_url, stream_uid, max_retries=3, retry_delay=1):
        cap = None
        for attempt in range(1, max_retries + 1):
            cap = cv2.VideoCapture(stream_url)
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                if ret:
                    break
            else:
                cap.release()
                frame = None
            log("WARNING", f"[尝试 {attempt}/{max_retries}] 抓取视频流失败: {stream_name} (UID={stream_uid}), URL={stream_url}。", log_path=self.log_file_path)
            time.sleep(retry_delay)
        else:
            log("FAIL", f"抓取视频流三次尝试均失败: {stream_name} (UID={stream_uid}), URL={stream_url}。", log_path=self.log_file_path)
            return None

        now = datetime.datetime.now()
        minute = (now.minute // 10) * 10
        timestamp = now.replace(minute=minute, second=0, microsecond=0).strftime("%H:%M:%S")
        filename = f"{stream_uid}_{now.strftime('%Y-%m-%d-%H-%M-%S')}.jpg"
        filepath = f"{self.save_dir}/{stream_uid}/{filename}"
        Path(f"{self.save_dir}/{stream_uid}").mkdir(exist_ok=True)
        fileurl = f"{self.base_url}/{filepath}"
        frame = resize_to_720p(frame)
        fences = self.storage_mgr.list_fences(stream_uid)
        abs_points = points_to_abs_points(frame, fences)
        for fence in abs_points:
            frame = draw_fence_on_frame(frame, fence)
        success = cv2.imwrite(filepath, frame)
        if success:
            log("INFO", f"抓取视频流成功: {stream_name} (UID={stream_uid}), 时间={timestamp}, 保存路径={filepath}。", log_path=self.log_file_path)
            return {"timestamp": timestamp, "image_path": filepath, "image_url": fileurl}
        else:
            log("FAIL", f"抓取视频流失败: {stream_name} (UID={stream_uid}), URL={stream_url}, PATH={filepath}。", log_path=self.log_file_path)
            return None

    # ------------------------
    # 保存单帧到当天 report
    # ------------------------
    def save_one_frame(self, stream_uid, stream_name, frame_data, today):
        if frame_data:
            report = self.report_mgr.get_report(stream_uid)
            if not report:
                self.report_mgr.add_report(stream_uid, stream_name)
                log("INFO", f"新建报表: {stream_name} (UID={stream_uid})", log_path=self.log_file_path)
            report = self.report_mgr.get_report(stream_uid, today)
            images = report.get("images", [])
            frame_hour = frame_data["timestamp"].split(":")[0]
            updated = False
            for idx, img in enumerate(images):
                if img["timestamp"].startswith(frame_hour.zfill(2)):
                    if img["image_path"]:
                        log("WARNING",
                            f"{stream_name} ({stream_uid}) 在 {img['timestamp']} 已存在 image_path={img['image_path']}，将被替换为 {frame_data['image_path']}。",
                            log_path=self.log_file_path)
                    images[idx] = frame_data
                    updated = True
                    break
            if not updated:
                images.append(frame_data)
                images.sort(key=lambda x: x["timestamp"])
            self.report_mgr.update_report(stream_uid, date=today, images=images)
            img_count = len([img for img in images if img.get("image_path")])
            log("INFO", f"报表更新完成: {stream_name} (UID={stream_uid}), {today} 帧总数={img_count}。", log_path=self.log_file_path)
            return True
        else:
            log("FAIL", f"当前帧为空，未更新报表: {stream_name} (UID={stream_uid})。", log_path=self.log_file_path)
            return False

    # ------------------------
    # 抓取所有视频流
    # ------------------------
    def capture_all_streams(self):
        streams = self.storage_mgr.list_streams()
        if not streams:
            log("WARNING", "没有视频流可抓取。", log_path=self.log_file_path)
            return
        log("INFO", f"开始抓取视频流，总数: {len(streams)}。", log_path=self.log_file_path)
        all_success = True
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        for stream in streams:
            stream_uid = stream["uid"]
            stream_name = stream.get("name", "未知名称")
            stream_url = stream["stream_url"]
            frame_data = self.capture_stream_frame(stream_name, stream_url, stream_uid)
            all_success = self.save_one_frame(stream_uid, stream_name, frame_data, today)
        if all_success:
            log("SUCCESS", "本轮抓图所有视频流均成功。", log_path=self.log_file_path)
        else:
            log("INFO", "本轮抓图完成，但部分视频流抓取失败。", log_path=self.log_file_path)

    # ------------------------
    # AI 每日总结
    # ------------------------
    def daily_ai_summary(self):
        streams = self.storage_mgr.list_streams()
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        individual_summaries = []
        for stream in streams:
            stream_uid = stream["uid"]
            stream_name = stream.get("name", stream_uid)
            day_report = self.report_mgr.get_report(stream_uid, yesterday)
            if not day_report:
                log("WARNING", f"视频流 {stream_name} (UID={stream_uid}) 缺少 {yesterday} 的报告，跳过。", log_path=self.log_file_path)
                continue
            images = day_report.get("images", [])
            img_count = len([img for img in images if img.get("image_path")])
            if img_count < 1:
                log("WARNING", f"视频流 {stream_name} (UID={stream_uid}) 的 {yesterday} 报告不足 1 张，跳过。", log_path=self.log_file_path)
                continue
            elif 1 <= img_count < 24:
                log("WARNING", f"视频流 {stream_name} (UID={stream_uid}) 的 {yesterday} 报告不足 24 张（那天 {img_count} 张）。", log_path=self.log_file_path)
            img_paths = [img.get("image_path") for img in images if img.get("image_path")]
            image_captions = [img.get("timestamp") for img in images if img.get("image_path")]
            camera_information = f"报告日期：{yesterday}，图片日期：{list(zip(img_paths, image_captions))}，stream_uid：{stream_uid}，stream_name：{stream_name}"
            combined_prompt = camera_information + daily_prompt
            try:
                imgs_base64 = [image_path_to_base64(i) for i in img_paths]
                ai_summary_json = call_qwen_via_client(combined_prompt, imgs_base64, model='qwen-vl-max-latest', json_str=True)
                status = ai_summary_json.get("status", "异常")
                ai_summary = ai_summary_json.get("content", "")
            except Exception as e:
                log("FAIL", f"调用模型失败: {e}", log_path=self.log_file_path)
                ai_summary = None
            self.report_mgr.update_report(stream_uid, date=yesterday, report=ai_summary)
            log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}) 的 {yesterday} AI总结已生成。", log_path=self.log_file_path)
            individual_summaries.append(f"{stream_name} (UID={stream_uid}): {ai_summary}")

        # 总摘要
        if individual_summaries:
            combined_prompt = daily_summary_prompt + "请基于以下各监控的AI总结生成一份总摘要:" + "\n".join(individual_summaries)
            today_information = f"报告日期：{yesterday}"
            combined_prompt = today_information + combined_prompt
            try:
                overall_summary = call_qwen_via_client(combined_prompt, model="qwen-plus", json_str=False)
            except Exception as e:
                log("FAIL", f"调用本地模型生成总体总结失败: {e}", log_path=self.log_file_path)
                overall_summary = None
            self.report_mgr.update_overall_summary(yesterday, overall_summary)
            log("SUCCESS", f"{yesterday} 所有监控的总摘要已生成。", log_path=self.log_file_path)

    # ------------------------
    # 启动调度器
    # ------------------------
    def start_scheduler(self):
        schedule.every().hour.at(":00").do(lambda: threading.Thread(target=self.capture_all_streams).start())
        schedule.every().day.at("08:00").do(lambda: threading.Thread(target=self.daily_ai_summary).start())
        log("INFO", "调度器已启动。", log_path=self.log_file_path)


if __name__ == "__main__":
    storage_mgr = StorageManager()
    report_mgr = ImageReportManager()

    report_scheduler = AutoReportScheduler(storage_mgr, report_mgr, save_dir="images/daily", base_url=base_url)

    # 启动定时任务
    report_scheduler.start_scheduler()
    log("INFO", "调度器已启动。")

    # 手动测试抓图
    # report_scheduler.capture_all_streams()

    # 手动测试 AI 总结
    # report_scheduler.daily_ai_summary()

    while True:
        schedule.run_pending()
        time.sleep(1)
