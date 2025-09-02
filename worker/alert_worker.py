import asyncio
from utils.db_utils import DBHelper
from utils.utils import log
from utils.alert_utils import send_dingding_alert, send_email_alert, send_wechat_alert, send_sms_alert

db = DBHelper()


# ------------------ 报警模块 ------------------
async def alert_worker(interval=10, group_uid=None):
    """
    异步报警任务，每 interval 秒查询未报警记录并处理
    :param interval: 查询间隔，单位秒
    :param group_uid: 可选，指定组
    """
    while True:
        pending_alerts = db.get_pending_alerts(group_uid)
        if not pending_alerts:
            await asyncio.sleep(interval)
            continue

        for alert in pending_alerts:
            try:
                # 这里可以扩展成实际的报警逻辑，例如调用短信/语音/邮件接口
                stream_uid = alert['stream_uid']
                fence_uid = alert['fence_uid']
                change_ratio = alert['change_ratio']
                timestamp = alert['timestamp']
                log("ALERT", f"异常检测报警: Stream={stream_uid}, Fence={fence_uid}, 变化率={change_ratio}, 时间={timestamp}")

                # 标记为已报警
                db.mark_as_alerted([alert['id']])
            except Exception as e:
                log("ERROR", f"报警失败: {e}")

        await asyncio.sleep(interval)


# ------------------ 启动报警任务 ------------------
async def main():
    alert_task = asyncio.create_task(alert_worker(interval=10))
    await alert_task


if __name__ == "__main__":
    asyncio.run(main())
