import time
import schedule
from datetime import datetime, timedelta
from app import VIDEO_DIR, IMAGE_DIR, TEMP_DIR
from utils.db_utils import db  # 引入 db 实例
from utils.utils import clean_task, log  # 引入清理任务和日志函数


def cleanup_24_hours_data():
    """清理24小时以前的数据"""
    # 获取当前时间的 24 小时前时间戳
    threshold_time = datetime.now() - timedelta(days=1)

    # 将时间转为 ISO 格式字符串
    time_threshold = threshold_time.isoformat()

    # 按时间清理每个表的数据
    print("清理24小时以前数据...")
    db.cleanup_captured_frames_by_time(time_threshold)  # 清理抓帧表
    print("清理 抓帧表 24小时以前数据完成！")
    db.cleanup_fence_detections_by_time(time_threshold)  # 清理异常检测表
    print("清理 异常检测表 24小时以前数据完成！")
    db.cleanup_merged_videos_by_time(time_threshold)  # 清理视频合成表
    print("清理 视频合成表 24小时以前数据完成！")


def cleanup_old_files():
    """清理旧文件"""
    # 清理视频和图片目录中的旧文件（超过7天）
    clean_task([VIDEO_DIR, IMAGE_DIR], days=7)
    print("清理 视频和图片目录中的旧文件完成！")

    # 清理临时目录中的旧文件（超过1天）
    clean_task([TEMP_DIR], days=1)
    print("清理 临时目录中的旧文件完成！")


def cleanup_all():
    """执行清理任务：清理数据库和旧文件"""
    cleanup_24_hours_data()  # 清理数据库中的24小时以前的数据
    cleanup_old_files()  # 清理过期的文件


# 首次运行时立即执行清理任务
cleanup_all()  # 立即执行一次清理

# 每24小时运行一次清理任务
schedule.every(24).hours.do(cleanup_all)

# 启动定时任务
while True:
    schedule.run_pending()  # 执行待运行的任务
    time.sleep(60)  # 每60秒检查一次任务
