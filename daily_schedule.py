import threading
import datetime
import time
import cv2  # 用于抓取视频帧
import os
from storage import StorageManager, ImageReportManager, RecipientsManager, sm
import schedule
import json
from utils.ai_utils import call_qwen_via_client, call_local_ai_model
from utils.utils import image_path_to_base64, save_report_to_docx, resize_to_720p, points_to_abs_points, draw_fence_on_frame, docx_to_pdf
from utils.log_utils import log
from utils.alert_utils import send_email_alert
from pathlib import Path
from emergency.utils.api_utils import zk_api

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)
base_url = f'http://{config['host']}:{config['port']}'
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
        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d_%H-%M-%S")  # YYYY-MM-DD_HH-MM-SS
        log_dir = os.path.join("logs", date_str)
        os.makedirs(log_dir, exist_ok=True)
        self.log_file_path = os.path.join(log_dir, "daily_schedule.log")

    def capture_stream_frame(self, stream_name, stream_url, stream_uid, max_retries=3, retry_delay=1):
        """抓取视频流当前帧，失败时最多尝试 max_retries 次"""
        import time

        cap = None
        for attempt in range(1, max_retries + 1):
            cap = cv2.VideoCapture(stream_url)
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()
                if ret:
                    break  # 成功抓到帧，跳出重试循环
            else:
                cap.release()
                frame = None
            log("WARN", f"[尝试 {attempt}/{max_retries}] 抓取视频流失败: {stream_name} (UID={stream_uid}), URL={stream_url}。", log_path=self.log_file_path)
            time.sleep(retry_delay)
        else:
            # 三次尝试都失败
            log("FAIL", f"抓取视频流三次尝试均失败: {stream_name} (UID={stream_uid}), URL={stream_url}。", log_path=self.log_file_path)
            return None

        # 成功抓到帧后处理
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

    def save_one_frame(self, stream_uid, stream_name, frame_data, today):
        if frame_data:
            report = self.report_mgr.get_report(stream_uid)
            if not report:
                self.report_mgr.add_report(stream_uid, stream_name)
                log("INFO", f"新建报表: {stream_name} (UID={stream_uid})")
            report = self.report_mgr.get_report(stream_uid, today)
            # 添加/更新本次抓取的帧
            images = report.get("images", [])
            frame_hour = frame_data["timestamp"].split(":")[0]  # 取小时部分 "15"
            updated = False
            for idx, img in enumerate(images):
                if img["timestamp"].startswith(frame_hour.zfill(2)):  # 找到对应小时
                    if img["image_path"]:
                        log("WARNING", f"{stream_name} ({stream_uid}) 在 {img['timestamp']} 已存在 image_path={img['image_path']}，将被替换为 {frame_data['image_path']}。", log_path=self.log_file_path)
                    images[idx] = frame_data  # 替换
                    updated = True
                    break
            if not updated:
                # 如果不存在该小时，就插入到正确位置（按 timestamp 排序）
                images.append(frame_data)
                images.sort(key=lambda x: x["timestamp"])
            # 更新到当天报告
            self.report_mgr.update_report(stream_uid, date=today, images=images)
            img_count = len([img for img in images if img.get("image_path")])
            log("INFO", f"报表更新完成: {stream_name} (UID={stream_uid}), {today} 帧总数={img_count}。", log_path=self.log_file_path)
            return True
        else:
            log("FAIL", f"当前帧为空，未更新报表: {stream_name} (UID={stream_uid})。", log_path=self.log_file_path)
            return False

    def capture_all_streams(self):
        """整点抓取所有视频流"""
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

    def daily_ai_summary(self):
        """每天8点调用AI生成前一天的总结，并生成总摘要"""
        streams = self.storage_mgr.list_streams()
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        individual_summaries = []  # 用于收集每个监控的AI总结

        for stream in streams:
            stream_uid = stream["uid"]
            stream_name = stream.get("name", stream_uid)
            # 获取昨天的报告
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
            # 调用 AI 生成单个监控总结
            camera_information = f"报告日期：{yesterday}，图片日期：{list(zip(img_paths, image_captions))}，stream_uid：{stream_uid}，stream_name：{stream_name}"
            combined_prompt = camera_information + daily_prompt
            try:
                # ai_summary_json = call_local_ai_model(ai_prompt=combined_prompt, image_paths=img_paths, json_str=True)
                imgs_base64 = [image_path_to_base64(i) for i in img_paths]
                ai_summary_json = call_qwen_via_client(combined_prompt, imgs_base64, model='qwen-vl-max-latest', json_str=True)
                status = ai_summary_json.get("status", "异常")
                ai_summary = ai_summary_json.get("content", "")
            except Exception as e:
                log("FAIL", f"调用模型失败: {e}")
                ai_summary = None
            # 更新当天 report 字段
            self.report_mgr.update_report(stream_uid, date=yesterday, report=ai_summary)
            log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}) 的 {yesterday} AI总结已生成。", log_path=self.log_file_path)
            individual_summaries.append(f"{stream_name} (UID={stream_uid}): {ai_summary}")
            # 发送邮箱
            word_dir = os.path.join("reports_word", yesterday)  # 按日期建目录
            os.makedirs(word_dir, exist_ok=True)
            docx_file = save_report_to_docx(
                content=ai_summary,
                save_dir=word_dir,
                filename=f"{stream_name}_{stream_uid}.docx",
                title=f"{stream_name} {yesterday} 报告",
                images=img_paths,
                image_captions=image_captions
            )
            pdf_file = None
            if docx_file:
                log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}) 的 Word 报告已保存: {docx_file}。", log_path=self.log_file_path)
                try:
                    docx_file = os.path.abspath(docx_file)
                    pdf_file = docx_to_pdf(docx_file)
                    log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}) 的 PDF 报告已保存: {pdf_file}。", log_path=self.log_file_path)
                    fence_uid = ''
                    try:
                        file_id = zk_api.upload_byte_file_with_apikey(pdf_file)
                        log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}) 的 PDF 报告已上传，文件ID={file_id}。", log_path=self.log_file_path)
                        for fence in self.storage_mgr.list_fences(stream_uid):
                            fence_uid = fence.get("id")
                            wh_code = fence.get("fence_data").get("wh_code")
                            wh_name = fence.get("fence_data").get("wh_name")
                            loan_no = fence.get("fence_data").get("loan_no")
                            scene_code = fence.get("fence_data").get("scene_code")
                            asset_detail = fence.get("fence_data").get("asset_detail")
                            patrol_resp = zk_api.patrol_record(
                                wh_code=wh_code,
                                wh_name=wh_name,
                                patrol_person="AI",
                                patrol_date=yesterday,
                                patrol_result=status,
                                report_id=file_id,
                                scene_code=scene_code,
                                loan_no=loan_no,
                                asset_detail=asset_detail,
                                video_files=""
                            )
                            log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}) 的巡库记录已上报: RESPONSE={patrol_resp}。", log_path=self.log_file_path)
                    except Exception as e:
                        if fence_uid:
                            log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}, FENCE_UID={fence_uid}) 的巡库记录上报失败: ERROR={e}。", log_path=self.log_file_path)
                        else:
                            log("FAIL", f"视频流 {stream_name} (UID={stream_uid}) 巡库文件上传失败: ERROR={e}。", log_path=self.log_file_path)
                except Exception as e:
                    log("FAIL", f"视频流 {stream_name} (UID={stream_uid}) 的 PDF 报告导出失败: {e}。", log_path=self.log_file_path)
            else:
                log("FAIL", f"视频流 {stream_name} (UID={stream_uid}) 的 Word 报告保存失败。", log_path=self.log_file_path)
            recipients = RecipientsManager().get_recipients_by_stream_id(stream_uid)
            if not recipients:
                log("WARNING", f"视频流 {stream_name} (UID={stream_uid}) 未绑定联系人。", log_path=self.log_file_path)
            for recipient in recipients:
                contact = recipient.get("contact", {})
                email_addr = contact.get("email")
                if not email_addr:
                    log("WARNING", f"视频流 {stream_name} (UID={stream_uid}) 收件人 {recipient.get('name', '')} 未配置邮箱。", log_path=self.log_file_path)
                    continue
                try:
                    send_email_alert(ai_summary, email_addr, attachments=img_paths.append(pdf_file), subject=f"视频流 {stream_name} (UID={stream_uid}) {yesterday} 报告。")
                    log("SUCCESS", f"视频流 {stream_name} (UID={stream_uid}) 的报告已发送邮件给 {email_addr}。", log_path=self.log_file_path)
                except Exception as e:
                    log("FAIL", f"视频流 {stream_name} (UID={stream_uid}) 的报告邮件发送失败: {email_addr}, ERROR={e}。", log_path=self.log_file_path)

        # 生成所有监控的总摘要
        if individual_summaries:
            combined_prompt = daily_summary_prompt + "请基于以下各监控的AI总结生成一份总摘要:" + "\n".join(individual_summaries)
            today_information = f"报告日期：{yesterday}"
            combined_prompt = today_information + combined_prompt
            try:
                # overall_summary = call_local_ai_model(ai_prompt=combined_prompt, json_str=False)
                overall_summary = call_qwen_via_client(combined_prompt, model="qwen-plus", json_str=False)
            except Exception as e:
                log("FAIL", f"调用本地模型生成总体总结失败: {e}")
                overall_summary = None  # 或设置为默认提示，如 "识别失败"
            # 保存到特殊的总报告 UID，例如 "ALL_STREAMS"
            self.report_mgr.update_overall_summary(yesterday, overall_summary)
            log("SUCCESS", f"{yesterday} 所有监控的总摘要已生成。", log_path=self.log_file_path)
            word_dir = os.path.join("reports_word", yesterday)
            pdf_file = None
            docx_file = save_report_to_docx(
                content=overall_summary,
                save_dir=word_dir,
                filename=f"ALL_STREAMS_SUMMARY_{yesterday}.docx",
                title=f"{yesterday} 所有监控的总摘要"
            )
            if docx_file:
                log("SUCCESS", f"Word 总摘要报告已保存: {docx_file}。", log_path=self.log_file_path)
                try:
                    docx_file = os.path.abspath(docx_file)
                    pdf_file = docx_to_pdf(docx_file)
                    log("SUCCESS", f"PDF 总摘要报告已保存: {pdf_file}。", log_path=self.log_file_path)
                    try:
                        file_id = zk_api.upload_byte_file_with_apikey(pdf_file)
                        log("SUCCESS", f"PDF 总摘要报告已上传，文件ID={file_id}", log_path=self.log_file_path)
                    except Exception as e:
                        log("FAIL", f"PDF 总摘要报告上传失败: {e}", log_path=self.log_file_path)
                except Exception as e:
                    log("FAIL", f"PDF 总摘要报告导出失败: {e}", log_path=self.log_file_path)
            else:
                log("FAIL", f"Word 总摘要报告保存失败。", log_path=self.log_file_path)
            # 发送总摘要邮件
            summary_recipients = ["576467179@qq.com"]
            for email_addr in summary_recipients:
                try:
                    send_email_alert(overall_summary, email_addr, attachments=[pdf_file], subject=f"视频流 {yesterday} 报告总摘要。")
                    log("SUCCESS", f"总摘要已发送给 {email_addr}。", log_path=self.log_file_path)
                except Exception as e:
                    log("FAIL", f"总摘要邮件发送失败: {email_addr}, ERROR={e}。", log_path=self.log_file_path)

    def start_scheduler(self):
        """启动定时任务"""
        # 每整点抓图
        schedule.every().hour.at(":00").do(lambda: threading.Thread(target=self.capture_all_streams).start())
        # 每天8点做AI总结
        schedule.every().day.at("08:00").do(lambda: threading.Thread(target=self.daily_ai_summary).start())


if __name__ == "__main__":
    # 初始化 StorageManager 和 ImageReportManager
    storage_mgr = StorageManager()
    report_mgr = ImageReportManager()

    # 创建调度器实例，换名字避免和 schedule 模块冲突
    report_scheduler = AutoReportScheduler(storage_mgr, report_mgr, save_dir="images/daily", base_url=base_url)

    # 启动定时任务
    report_scheduler.start_scheduler()
    log("INFO", "调度器已启动。")

    # 手动测试抓图
    # report_scheduler.capture_all_streams()

    # 手动测试 AI 总结
    # report_scheduler.daily_ai_summary()

    # schedule 需要不断循环运行才能触发任务
    while True:
        schedule.run_pending()  # 运行所有到期的任务
        time.sleep(1)  # 休眠1秒避免CPU占用过高
