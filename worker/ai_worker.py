import asyncio
from datetime import datetime, timedelta
from utils.db_utils import db
from storage import sm
from utils.ai_utils import call_local_ai_model, call_qwen_via_client
from utils.utils import save_frames_as_video, save_key_frames
from utils.log_utils import log
import pandas as pd
import cv2
from config import BASE_URL, PROMPTS


async def ai_worker():
    while True:
        pending_ai_checked = pd.DataFrame(db.get_pending_ai_checked())
        if pending_ai_checked.empty:
            log("INFO", "[AI] 当前无待处理异常记录，休眠2秒")
            await asyncio.sleep(2)
            continue
        for _, row in pending_ai_checked.iterrows():
            video_path = row['alert_video_path']
            stream_uid = row['stream_uid']
            stream_name = sm.get_stream(stream_uid)['name']
            detection_id = row['id']
            try:
                ai_result = call_local_ai_model(ai_prompt=PROMPTS['normal'], video_path=video_path, json_str=True) # 有需要再改为异步
                if not "status" in ai_result or not "detail" in ai_result:
                    log("WARNING", f"[AI] {stream_name} AI识别返回异常, DETECTION_ID={detection_id}, {ai_result}")
                    ai_result = {"ERROR": "AI识别返回异常"}
                    ai_status = -1
                else:
                    log("INFO", f"[AI] {stream_name} AI识别结果: {ai_result}")
                    ai_status = 1 if ai_result.get("status") != "正常" else 0
            except Exception as e:
                log("FAIL", f"[AI] {stream_name} AI识别失败, DETECTION_ID={detection_id}, ERROR={e}")
                ai_result = {"ERROR": str(e)}
                ai_status = -1
            db.update_ai_result(
                detection_id=detection_id,
                ai_checked=1,
                ai_status=ai_status,
                ai_result=str(ai_result['detail'] if "detail" in ai_result else ai_result)
            )
            log("INFO", f"[AI] {stream_name} 数据库更新完成 DETECTION_ID={detection_id}, AI_STATUS={ai_status}")
            await asyncio.sleep(1)

async def run_ai_module():
    ai_task = asyncio.create_task(ai_worker())
    await ai_task


if __name__ == "__main__":
    asyncio.run(run_ai_module())
