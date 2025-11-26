import time
import schedule
from datetime import datetime, timedelta
from storage import mm
from config import VIDEO_DIR, IMAGE_DIR, TEMP_DIR
from utils.db_utils import db  # 引入 db 实例
from utils.utils import clean_task, log  # 引入清理任务和日志函数


def cleanup_24_hours_data():
    """清理24小时以前的数据"""
    # 获取当前时间的 24 小时前时间戳
    threshold_time = datetime.now() - timedelta(hours=12)
    threshold_time2 = datetime.now() - timedelta(hours=13)

    # 将时间转为 ISO 格式字符串
    time_threshold = threshold_time.isoformat()
    time_threshold2 = threshold_time2.isoformat()

    # 按时间清理每个表的数据
    log('INFO', "清理24小时以前数据...")
    try:
        events = db.get_all_events()
        for event in events:
            alerted = event['alerted']
            group_event_uid = event['group_event_uid']
            event_timestamp = datetime.fromisoformat(event['timestamp'])
            if alerted == 1 and event_timestamp < threshold_time:
                # 清理该UID对应的所有数据
                db.cleanup_events_by_column(group_event_uid)
                db.cleanup_merged_videos_by_column(group_event_uid)
                db.cleanup_fence_detections_by_column(group_event_uid)
                db.cleanup_captured_frames_by_column(group_event_uid)
                log('INFO', f"成功清理了UID {group_event_uid} 对应的数据。")
    except Exception as e:
        log('FAIL', f"清理事件数据时出错: {str(e)}")

    try:
        db.cleanup_merged_videos_by_time(time_threshold2)  # 清理视频合成表
        log('INFO', f"成功清理了时间阈值为 {time_threshold2} 的视频合成表数据。")
    except Exception as e:
        log('FAIL', f"清理视频合成表数据时出错: {str(e)}")

    try:
        db.cleanup_fence_detections_by_time(time_threshold2)  # 清理异常检测表
        log('INFO', f"成功清理了时间阈值为 {time_threshold2} 的异常检测表数据。")
    except Exception as e:
        log('FAIL', f"清理异常检测表数据时出错: {str(e)}")

    try:
        db.cleanup_captured_frames_by_time(time_threshold2)  # 清理抓帧表
        log('INFO', f"成功清理了时间阈值为 {time_threshold2} 的抓帧表数据。")
    except Exception as e:
        log('FAIL', f"清理抓帧表数据时出错: {str(e)}")


def cleanup_old_files():
    """清理旧文件"""
    # 清理视频和图片目录中的旧文件（超过7天）
    clean_task([VIDEO_DIR, IMAGE_DIR], days=7)
    log('INFO', "清理 视频和图片目录中的旧文件完成！")

    # 清理临时目录中的旧文件（超过1天）
    clean_task([TEMP_DIR], days=1)
    log('INFO', "清理 临时目录中的旧文件完成！")

def cleanup_old_message():
    """清理预警信息"""
    mm.clear_old_messages(1)


def cleanup_all():
    """执行清理任务：清理数据库和旧文件"""
    cleanup_24_hours_data()  # 清理数据库中的24小时以前的数据
    cleanup_old_files()  # 清理过期的文件
    # cleanup_old_message()  # 清理过期的预警信息


# 首次运行时立即执行清理任务
cleanup_all()  # 立即执行一次清理

# 每12小时运行一次清理任务
schedule.every(12).hours.do(cleanup_all)

# 启动定时任务
while True:
    schedule.run_pending()  # 执行待运行的任务
    time.sleep(60)  # 每60秒检查一次任务
