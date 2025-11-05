import json
import re
import time
import requests
from datetime import datetime
from utils.utils import relative_to_pixel_fence, to_png_bytes, camel_to_snake
from utils.log_utils import log, log_multiline
from utils import watermark_utils as wu
from emergency.utils.api_utils import zk_api
from emergency.config import MACHINE_CODES
from storage import sm, ddm
from config import BASE_URL, FLOW_URL


# ====================== 直播流缓存 ======================
STREAM_EXPIRE_MAP = {}  # {stream_uid: expire_timestamp}


def get_expire_time_from_url(url: str) -> int:
    """从直播URL中提取 expire 参数 (形如 expire=1761631050)"""
    match = re.search(r"expire=(\d+)", url)
    return int(match.group(1)) if match else 0


# ====================== 主逻辑函数 ======================
def get_streams_worker():
    """运行一轮获取设备、启动检测，同时保存 JSON"""
    all_data = ddm.load_all()
    now = int(time.time())

    for machine in MACHINE_CODES:
        log("INFO", f"[EMERGENCY STREAM] 获取机器 {machine} 的设备列表...")
        try:
            devices = zk_api.get_devices(machine)
        except Exception as e:
            log("FAIL", f"[EMERGENCY STREAM] 机器 {machine} 获取设备失败: {e}")
            continue

        log("INFO", f"[EMERGENCY STREAM] 机器 {machine} 获取到 {len(devices)} 个仓库")
        log_multiline("INFO", *devices)

        for warehouse in devices:
            warehouse_code = warehouse.get("warehouseCode")
            owner_code = warehouse.get("ownerCode")
            warehouse_devices = warehouse.get("devices", [])
            log("INFO", f"[EMERGENCY STREAM] 仓库 {warehouse_code} 设备数量: {len(warehouse_devices)}")

            for dev in warehouse_devices:
                device_name = dev.get("deviceName")
                service_no = dev.get("serviceNo")
                device_no = dev.get("deviceNo")
                lot_source = dev.get("lotSource")
                stream_uid = f"{machine}-{owner_code}-{device_no}-{service_no}"
                detecting = dev.get("isAi") == 'Y'
                log("INFO", f"[EMERGENCY STREAM] 处理设备: {device_name} (UID={stream_uid})")

                # ================== 获取直播地址 ==================
                live_url = None
                try:
                    expire_time = STREAM_EXPIRE_MAP.get(stream_uid)
                    # 仅当不存在或已过期时才重新请求
                    if not expire_time or expire_time <= now:
                        live_url = zk_api.get_live_url(lot_source, service_no, device_no)
                        expire_time = get_expire_time_from_url(live_url)
                        STREAM_EXPIRE_MAP[stream_uid] = expire_time
                        log("INFO", f"[EMERGENCY STREAM] 获取直播流: {device_name} (UID={stream_uid})")
                        log("INFO", f"[EMERGENCY STREAM] 新过期时间: {datetime.fromtimestamp(expire_time)}")
                    else:
                        log("INFO", f"[CACHE] {device_name} (UID={stream_uid}) 缓存未过期，跳过获取。")
                        continue
                except Exception as e:
                    log("FAIL", f"[EMERGENCY STREAM] 获取设备 {device_name} (UID={stream_uid}) 直播地址失败: {e}")
                    continue

                if live_url:
                    try:
                        stream = sm.get_stream(stream_uid)
                        if not stream:
                            resp = requests.post(f"{BASE_URL}/api/streams", json={
                                "source_stream_url": live_url,
                                "name": device_name,
                                "stream_uid": stream_uid
                            }, timeout=5)
                            resp.raise_for_status()
                            url = resp.json().get("data", {}).get("stream_url")
                            log("SUCCESS", f"[EMERGENCY STREAM] 新增视频流: {device_name} (UID={stream_uid})")
                        else:
                            resp = requests.patch(f"{BASE_URL}/api/source-streams", json={
                                "source_stream_url": live_url,
                                "stream_uid": stream_uid
                            }, timeout=5)
                            resp.raise_for_status()
                            url = resp.json().get("data", {}).get("hls_url")
                            url = f'{FLOW_URL}/{url}'
                            sm.update_stream(stream_uid, stream_url=url)
                            log("SUCCESS", f"[EMERGENCY STREAM] 更新视频流: {device_name} (UID={stream_uid})")

                        # 调用资产与围栏接口
                        url = url.replace("no_wm", "wm")
                        url = "https://jrlyy.fusionfintrade.com:39100/" + url.split("/", 3)[-1]
                        log("INFO", f"[EMERGENCY STREAM] 推送视频流: {device_name} (UID={stream_uid}, URL={url})")
                        asset_info = zk_api.query_and_push_assets(
                            hj_device_no=device_no,
                            hj_service_no=service_no,
                            video_play_url=url,
                            scene_code=owner_code
                        )
                        all_data[stream_uid] = asset_info.get("data", {})
                        if asset_info.get("rspCode") != '00000000':
                            log("FAIL", f"[EMERGENCY STREAM] 获取资产与围栏信息失败: {device_name} (UID={stream_uid}), RESPONSE={asset_info}")
                            continue

                        for i, pos in enumerate(asset_info.get('data', [])):
                            fence_uid = pos["fenceId"]
                            fence_points = json.loads(pos["locationPoint"])
                            fence_info_text = []

                            if pos.get("assetDetail"):
                                fence_info_text = [
                                    f'客户名称: {pos["assetDetail"][0]["assetList"][0]["ownerEntityName"]}',
                                    f'仓库名称: {pos["whName"]}',
                                    f'仓库编码: {pos["whCode"]}',
                                    f'货架编号: {pos["assetDetail"][0]["positionCode"]}',
                                    f'商品名称: {pos["assetDetail"][0]["assetList"][0]["commodityList"][0]["commodityName"]}',
                                    f'商品数量: {pos["assetDetail"][0]["assetList"][0]["commodityList"][0]["quantity"]}',
                                    f'计量单位: {pos["assetDetail"][0]["assetList"][0]["commodityList"][0]["unit"]}',
                                    f'资产编码: {pos["assetDetail"][0]["assetList"][0]["commodityList"][0]["commodityCode"]}',
                                    f'融资编码: {pos["loanNo"]}',
                                ]
                            else:
                                fence_info_text = [
                                    f'仓库名称: {pos["whName"]}',
                                    f'仓库编号: {pos["whCode"]}'
                                ]

                            try:
                                bg_frame, pixel_fence_points = relative_to_pixel_fence(live_url, fence_points)
                            except Exception as e:
                                log("FAIL", f"[EMERGENCY FENCE] 获取视频流失败：{device_name} (UID={stream_uid}, FENCE_UID={fence_uid}), ERROR={e}")
                                continue

                            fence_data = {camel_to_snake(k): v for k, v in pos.items()}
                            fence_data['scene_code'] = owner_code
                            sm.update_fence_by_fence_uid(stream_uid, fence_uid, fence_points, fence_info_text, fence_data)

                            COLOR_PALETTE = [(0, 0, 255), (0, 255, 0), (255, 0, 0),
                                             (0, 255, 255), (255, 0, 255), (255, 255, 0), (255, 255, 255)]
                            watermark_img = wu.draw_fence_with_text_fixed_color_adaptive_centroid(
                                bg_frame, pixel_fence_points, fence_info_text,
                                color=COLOR_PALETTE[i % len(COLOR_PALETTE)],
                                font_path="C:/Windows/Fonts/msyh.ttc",
                                font_size=30, line_spacing=1.2
                            )
                            png_bytes = to_png_bytes(watermark_img)
                            resp = requests.patch(
                                f"{FLOW_URL}/api/fence/water_mark",
                                files={"file": ("fence.png", png_bytes, "image/png")},
                                data={"stream_uid": stream_uid, "fence_uid": fence_uid},
                                timeout=5
                            )
                            resp.raise_for_status()
                            log("SUCCESS", f"[EMERGENCY WATERMARK] 上传水印成功: {device_name} (UID={stream_uid}, FENCE_UID={fence_uid})")
                    except requests.RequestException as e:
                        log("FAIL", f"[EMERGENCY STREAM] 管理视频流失败: {device_name} (UID={stream_uid}) ERROR={e}")

                    sm.set_stream_group(stream_uid, warehouse_code)
                    sm.set_detecting(stream_uid, detecting)
                    log("SUCCESS", f"[EMERGENCY STREAM] 设置视频流编组: {device_name} (UID={stream_uid}) -> GROUP_UID={warehouse_code}")
                    log("SUCCESS", f"[EMERGENCY STREAM] 设置视频流检测: {device_name} (UID={stream_uid}) -> DETECTING={detecting}")

    # 保存数据
    ddm.save_all(all_data)
    log("INFO", "[EMERGENCY STREAM] === 获取设备信息完成 ===")


# ====================== 主循环控制 ======================
if __name__ == "__main__":
    while True:
        try:
            get_streams_worker()
        except Exception as e:
            log("FAIL", f"[EMERGENCY STREAM] get_streams_worker 运行异常: {e}")

        # 计算下次运行时间（取最早过期时间）
        if STREAM_EXPIRE_MAP:
            now = int(time.time())
            next_expire = min(STREAM_EXPIRE_MAP.values())
            sleep_seconds = max(0, next_expire - now + 1)
            log("INFO", f"[EMERGENCY STREAM] 最近一个直播流将在 {sleep_seconds} 秒后过期 ({datetime.fromtimestamp(next_expire)})")
        else:
            sleep_seconds = 3600
            log("WARN", f"[EMERGENCY STREAM] 无有效过期时间，默认等待 {sleep_seconds} 秒")

        # 仅在过期后才重新请求
        time.sleep(sleep_seconds)
