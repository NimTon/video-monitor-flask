import asyncio
import json
from datetime import datetime, date
from emergency.utils.api_utils import zk_api, ZhongkaiAPIError
from utils.db_utils import db
from storage import sm, rm, asm, mm, ddm
from utils.log_utils import log
from utils.alert_utils import send_alert
from urllib.parse import urljoin
import pandas as pd
from config import BASE_URL


async def alert_worker():
    while True:
        pending_alerts = pd.DataFrame(db.get_unalerted_videos())
        if pending_alerts.empty:
            log("INFO", "[EMERGENCY ALERT] 当前无待报警记录，休眠2秒")
            await asyncio.sleep(2)
            continue

        grouped = pending_alerts.groupby('group_event_uid')
        for group_event_uid, group in grouped:
            # 是否有异常内容
            if group.ai_status.any():
                # 获取整体状态
                for _, video in group.iterrows():
                    # 单个数据查询
                    stream_uid = video.get('stream_uid')
                    stream_name = video.get('stream_name')
                    video_path = video.get('video_path')
                    device_data = ddm.get_by_stream_uid(stream_uid)
                    hj_device_no = device_data.get('hjDeviceNo')
                    hj_service_no = device_data.get('hjServiceNo')
                    ai_result = json.loads(video.get('ai_result'))
                    event_type = ai_result.get('changes').get('event_type')
                    event_msg = ai_result.get('changes').get('description')
                    wh_code = device_data.get('whCode')
                    wh_name = device_data.get('whName')
                    loan_no = device_data.get('loanNo')
                    asset_detail = str(device_data.get('assetDetail'))
                    log("INFO", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 待报警")
                    try:
                        # 上传视频
                        file_id = zk_api.upload_byte_file_with_apikey(video_path)
                        print("patrol_record 成功:", file_id)
                        # 调用API接口触发报警
                        iot_event = zk_api.push_iot_event(
                            hj_device_no=hj_device_no,
                            hj_service_no=hj_service_no,
                            event_type=event_type,
                            event_date=date.today().strftime("%Y-%m-%d"),
                            event_msg=event_msg,
                            # event_img_file_id="",
                            event_video_file_id=file_id,
                            wh_code=wh_code,
                            wh_name=wh_name,
                            loan_no=loan_no,
                            asset_detail=asset_detail
                        )
                        print("patrol_record 响应:", iot_event)
                    except ZhongkaiAPIError as e:
                        print("patrol_record 失败:", e, getattr(e, "response", None))
                    log("SUCCESS", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 推送完成")
            else:
                log("INFO", f"[EMERGENCY ALERT] GROUP_UID={group_event_uid}, 无异常内容")
            # 更新数据库
            db.mark_video_as_alerted(group_event_uid)
            await asyncio.sleep(1)

async def run_alert_module():
    alert_task = asyncio.create_task(alert_worker())
    await alert_task


if __name__ == "__main__":
    asyncio.run(run_alert_module())
