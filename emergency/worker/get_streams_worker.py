from utils.utils import log, chinese_to_pinyin
from emergency.utils.api_utils import zk_api
from emergency.config import MACHINE_CODES
from storage import sm


def get_streams_worker():
    """运行一轮获取设备、启动检测"""
    for machine in MACHINE_CODES:
        log("INFO", f"[EMERGENCY STREAM] 获取机器 {machine} 的设备列表...")
        try:
            devices = zk_api.get_devices(machine)
        except Exception as e:
            log("FAIL", f"[EMERGENCY STREAM] 机器 {machine} 获取设备失败: {e}")
            continue

        log("INFO", f"[EMERGENCY STREAM] 机器 {machine} 获取到 {len(devices)} 个仓库")
        for warehouse in devices:
            warehouse_code = warehouse.get("warehouseCode")
            warehouse_devices = warehouse.get("devices", [])
            log("INFO", f"[EMERGENCY STREAM] 仓库 {warehouse_code} 设备数量: {len(warehouse_devices)}")

            for dev in warehouse_devices:
                lot_source = dev.get("lotSource")
                service_no = dev.get("serviceNo")
                device_no = dev.get("deviceNo")
                device_name = dev.get("deviceName")
                stream_uid = chinese_to_pinyin(device_name)
                log("INFO", f"[EMERGENCY STREAM] 处理设备: {device_name} (UID={stream_uid})")

                try:
                    live_url = zk_api.get_live_url(lot_source, service_no, device_no)
                except Exception as e:
                    log("FAIL", f"[EMERGENCY STREAM] 获取设备 {device_name} (UID={stream_uid}) 直播地址失败: {e}")
                    continue

                if not live_url:
                    log("WARNING", f"[EMERGENCY STREAM] 设备 {device_name} (UID={stream_uid}) 没有可用直播地址")
                    continue

                # 如果视频流不存在就添加，有则更新
                stream = sm.get_stream(stream_uid)
                if not stream:
                    sm.add_stream(live_url, name=device_name, stream_uid=stream_uid)
                    log("SUCCESS", f"[EMERGENCY STREAM] 新增视频流: {device_name} (UID={stream_uid})")
                else:
                    sm.update_stream(stream_uid, stream_url=live_url)
                    log("SUCCESS", f"[EMERGENCY STREAM] 更新视频流: {device_name} (UID={stream_uid})")
                sm.set_stream_group(stream_uid, warehouse_code)
                log("SUCCESS", f"[EMERGENCY STREAM] 设置视频流编组: {device_name} (UID={stream_uid}) -> GROUP_UID={warehouse_code}")

    log("INFO", "[EMERGENCY STREAM] === 获取设备信息完成 ===")


if __name__ == "__main__":
    get_streams_worker()
