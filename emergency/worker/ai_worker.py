import asyncio
from datetime import datetime
from utils import ai_manager
from utils.db_utils import db
from utils.log_utils import log
import pandas as pd
from config import PROMPTS


async def ai_worker():
    while True:
        pending_alerts = pd.DataFrame(db.get_unchecked_videos())
        if pending_alerts.empty:
            log("INFO", "[EMERGENCY AI] 当前无待处理异常记录，休眠2秒")
            await asyncio.sleep(2)
            continue
        grouped = pending_alerts.groupby('group_event_uid')
        for group_event_uid, group in grouped:
            for _, video in group.iterrows():
                video_id = video.get("id")
                stream_uid = video.get('stream_uid')
                stream_name = video.get('stream_name')
                group_uid = video.get('group_uid')
                timestamp = datetime.fromisoformat(video.get('timestamp'))
                video_path = video.get('video_path')
                log("INFO", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) 开始识别")
                try:
                    future = ai_manager.add_task("call_local_ai_model", ai_prompt=PROMPTS['normal'], video_path=video_path, json_str=True)
                    ai_result = future.result()  # 阻塞等待后台线程执行完成
                    if not "status" in ai_result or not "detail" in ai_result:
                        log("WARN", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) AI识别返回异常, {ai_result}")
                        ai_result = {"ERROR": "AI识别返回异常"}
                        ai_status = -1
                    else:
                        log("INFO", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) AI识别结果: {ai_result}")
                        ai_status = 1 if ai_result.get("status") != "正常" else 0
                except Exception as e:
                    log("FAIL", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) AI识别失败, ERROR={e}")
                    ai_result = {"ERROR": str(e)}
                    ai_status = -1
                db.update_video_ai_result(
                    video_id,
                    ai_checked=1,
                    ai_status=ai_status,
                    ai_result=str(ai_result['detail'] if "detail" in ai_result else ai_result)
                )
                log("INFO", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) 数据库更新完成, AI_STATUS={ai_status}")
                await asyncio.sleep(1)


async def run_ai_module():
    ai_task = asyncio.create_task(ai_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_ai_module())
