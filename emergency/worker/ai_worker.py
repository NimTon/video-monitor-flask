import asyncio
import json
from datetime import datetime
from utils import ai_manager
from utils.db_utils import db
from utils.log_utils import log
import pandas as pd
from config import PROMPTS


async def ai_worker():
    while True:
        pending_check_events = db.get_unchecked_events()
        if pending_check_events == []:
            log("INFO", "[EMERGENCY AI] 当前无待处理异常记录，休眠2秒")
            await asyncio.sleep(2)
            continue
        for event in pending_check_events:
            group_event_uid = event['group_event_uid']
            group_event_videos = db.get_videos_by_group_event_uid(group_event_uid)
            for video in group_event_videos:
                video_id = video["id"]
                stream_uid = video['stream_uid']
                stream_name = video['stream_name']
                group_uid = video['group_uid']
                timestamp = datetime.fromisoformat(video.get('timestamp'))
                video_path = video['video_path']
                group_event_uid = video['group_event_uid']
                # 查询单个视频内相关识别内容
                single_ai_results = db.get_ai_result_by_group_event_uid(group_event_uid)
                single_ai_results = pd.DataFrame(single_ai_results)
                if single_ai_results.empty:
                    log("INFO", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) 无AI结果，跳过")
                    await asyncio.sleep(5)
                    continue
                # 如果ai_checked为0则记录日志
                if (single_ai_results['ai_checked'] == 0).any():
                    log("INFO", f"[EMERGENCY AI] 有尚未识别的单个AI结果，group_event_uid: {group_event_uid}, 跳过")
                    await asyncio.sleep(5)
                    continue
                if not 1 in single_ai_results['ai_status'].unique():
                    log("INFO", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) 无报警内容，跳过")
                    await asyncio.sleep(5)
                    continue
                single_ai_results = single_ai_results[single_ai_results['ai_status'] != 0].to_json()
                log("INFO", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) 开始识别")
                try:
                    future = ai_manager.add_task("call_local_ai_model", ai_prompt=PROMPTS['single'] + single_ai_results, json_str=True)
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
                db.mark_event_checked(
                    group_event_uid,
                    ai_status,
                    str(ai_result['detail'] if "detail" in ai_result else ai_result)
                )
                log("INFO", f"[EMERGENCY AI] {stream_name} (UID={stream_uid}, GROUP_UID={group_uid}, TIMESTAMPE={timestamp}) 数据库更新完成, AI_STATUS={ai_status}")
                await asyncio.sleep(5)


async def run_ai_module():
    ai_task = asyncio.create_task(ai_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_ai_module())
