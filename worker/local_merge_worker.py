from utils.utils import save_imgs_as_video
import os
from utils.log_utils import log
from storage import sm
import pandas as pd
from datetime import datetime

stream_uid = "1-91370000698086271U-609239518-10"
# 获取指定时间范围内的帧
start_time = '2025-11-13 14:38:00'  # 格式: YYYY-MM-DD HH:MM:SS
end_time = '2025-11-13 14:40:00'  # 格式: YYYY-MM-DD HH:MM:SS
start_dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
end_dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
stream_uid_list = [stream['uid'] for stream in sm.list_streams()]
if stream_uid not in stream_uid_list:
    log('FAIL', '流 ID 不存在')
    exit()

stream_frames = [frame for frame in os.listdir(f'tmp/capture') if stream_uid in frame]

if not stream_frames:
    log('FAIL', '没有找到帧')
    exit()

# 创建数据框，包含文件名和时间戳两列
frame_data = []
for frame in stream_frames:
    timestamp_str = '_'.join(frame.split('_')[-3:-1])  # '20251113_143910'
    frame_data.append({
        'timestamp': timestamp_str,
        'file_path': os.path.join(f'tmp/capture', frame)
    })

df = pd.DataFrame(frame_data)

# 筛选出在时间范围内的帧
df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y%m%d_%H%M%S')
df = df[(df['timestamp'] >= start_dt) & (df['timestamp'] <= end_dt)].sort_values('timestamp')

imgs_paths = df['file_path'].to_list()
os.makedirs(f'tmp/merge', exist_ok=True)
output_path = f'tmp/merge/{stream_uid}_{start_dt.strftime("%Y%m%d%H%M%S")}_{end_dt.strftime("%Y%m%d%H%M%S")}.mp4'
save_imgs_as_video(imgs_paths, output_path, fps=1)