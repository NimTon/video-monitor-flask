import asyncio
import json
from datetime import datetime, date
from emergency.utils.api_utils import zk_api, ZhongkaiAPIError
from utils.db_utils import db
from storage import sm, rm, asm, mm, ddm
from utils import email_alert
from utils.log_utils import log
from utils.alert_utils import send_alert, send_email_alert
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
            group_uid = group.group_uid.unique()[0]
            # 是否有异常内容
            if group.ai_status.any():
                # 获取整体状态
                for _, video in group.iterrows():
                    # 单个数据查询
                    stream_uid = video.get('stream_uid')
                    stream_name = video.get('stream_name')
                    video_path = video.get('video_path')
                    before_image_path = video.get('before_image_path')
                    after_image_path = video.get('after_image_path')
                    device_data = ddm.get_by_stream_uid(stream_uid)[0]
                    hj_device_no = device_data.get('hjDeviceNo')
                    hj_service_no = device_data.get('hjServiceNo')
                    ai_result_str = None
                    try:
                        ai_result_str = video.get('ai_result', '{}')
                        ai_result = json.loads(ai_result_str.replace("'", '"'))
                        event_type = ai_result.get('changes', {}).get('event_type', 'unknown')
                        event_msg = ai_result.get('changes', {}).get('description', '无描述')
                    except Exception as e:
                        log("FAIL", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 获取AI识别结果异常: {e}")
                        event_type = 'unknown'
                        event_msg = '无描述'
                    wh_code = device_data.get('whCode')
                    wh_name = device_data.get('whName')
                    loan_no = device_data.get('loanNo')
                    asset_detail = str(device_data.get('assetDetail'))
                    log("INFO", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 待报警")
                    try:
                        # 上传视频
                        file_id = zk_api.upload_byte_file_with_apikey(video_path)
                        log("INFO", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 上传视频完成")
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
                        log("SUCCESS", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 推送至中科云成功")
                    except ZhongkaiAPIError as e:
                        log("FAIL", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 推送至中科云失败: {e}")
                    log("SUCCESS", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 推送完成")
                    # 发送邮件
                    emal_conent = f"编组视频流 {stream_uid} 预警。\n" \
                                  f"设备名称: {stream_name}\n" \
                                  f"设备编号: {hj_device_no}\n" \
                                  f"设备服务编号: {hj_service_no}\n" \
                                  f"设备所在仓库: {wh_code} {wh_name}\n" \
                                  f"设备所在贷款编号: {loan_no}\n" \
                                  f"设备资产详情: {asset_detail}\n" \
                                  f"设备异常内容: {event_msg}\n" \
                                  f"设备异常视频: {urljoin(BASE_URL, video_path)}"
                    email_alert.send_email(emal_conent, subject=f"编组视频流 {stream_uid} 预警。")

                    # 存入message.json
                    mm.add_message(
                        stream_uid=stream_uid,
                        fence_uid='-1',
                        stream_name=stream_name,
                        change_ratio="-1",
                        ai_report=ai_result_str,
                        image_before_url=urljoin(BASE_URL, before_image_path),
                        image_after_url=urljoin(BASE_URL, after_image_path),
                        video_url=urljoin(BASE_URL, video_path)
                    )
                    log("SUCCESS", f"[EMERGENCY ALERT] {stream_name} (UID={stream_uid}, GROUP_UID={group_event_uid}), 邮件发送完成")
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
