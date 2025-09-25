import json
from utils.utils import log, log_multiline, relative_to_pixel_fence, to_png_bytes, camel_to_snake
from utils import watermark_utils as wu
from emergency.utils.api_utils import zk_api
from emergency.config import MACHINE_CODES
from storage import sm
import requests
from config import BASE_URL, FLOW_BASE_URL, FLOW_LOCAL_URL


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
        log_multiline("INFO", *devices)
        for warehouse in devices:
            warehouse_code = warehouse.get("warehouseCode")
            owner_code = warehouse.get("ownerCode")
            warehouse_devices = warehouse.get("devices", [])
            log("INFO", f"[EMERGENCY STREAM] 仓库 {warehouse_code} 设备数量: {len(warehouse_devices)}")

            for dev in warehouse_devices:
                lot_source = dev.get("lotSource")
                service_no = dev.get("serviceNo")
                device_no = dev.get("deviceNo")
                device_name = dev.get("deviceName")
                stream_uid = f"{machine}-{owner_code}-{device_no}-{service_no}"
                detecting = dev.get("isAi") == 'Y'
                log("INFO", f"[EMERGENCY STREAM] 处理设备: {device_name} (UID={stream_uid})")

                try:
                    live_url = zk_api.get_live_url(lot_source, service_no, device_no)
                    log("INFO", f"[EMERGENCY STREAM] 设备 {device_name} (UID={stream_uid}) 直播地址: {live_url}")
                except Exception as e:
                    log("FAIL", f"[EMERGENCY STREAM] 获取设备 {device_name} (UID={stream_uid}) 直播地址失败: {e}")
                    continue

                if not live_url:
                    log("WARNING", f"[EMERGENCY STREAM] 设备 {device_name} (UID={stream_uid}) 没有可用直播地址")
                    continue

                # 如果视频流不存在就添加，有则更新
                stream = sm.get_stream(stream_uid)
                try:
                    if not stream:
                        resp = requests.post(f"{BASE_URL}/api/streams", json={
                            "source_stream_url": live_url,
                            "name": device_name,
                            "stream_uid": stream_uid
                        }, timeout=5)
                        resp.raise_for_status()
                        url = resp.json().get("data").get("stream_url")
                        log("SUCCESS", f"[EMERGENCY STREAM] 新增视频流: {device_name} (UID={stream_uid})")
                    else:
                        resp = requests.patch(f"{BASE_URL}/api/source-streams", json={
                            "source_stream_url": live_url,
                            "stream_uid": stream_uid
                        }, timeout=5)
                        resp.raise_for_status()
                        url = resp.json().get("data").get("hls_url")
                        url = f'{FLOW_LOCAL_URL}/{url}'
                        sm.update_stream(stream_uid, stream_url=url)
                        log("SUCCESS", f"[EMERGENCY STREAM] 更新视频流: {device_name} (UID={stream_uid})")

                    # 调用中凯资产与围栏信息接口
                    url = url.replace("no_wm", "wm").replace(FLOW_LOCAL_URL, FLOW_BASE_URL)
                    log("INFO", f"[EMERGENCY STREAM] 推送视频流: {device_name} (UID={stream_uid}, URL={url})")
                    asset_info = zk_api.query_and_push_assets(
                        hj_device_no=device_no,
                        hj_service_no=service_no,
                        video_play_url=url,
                        scene_code=owner_code
                    )

                    # 3. 遍历围栏
                    if asset_info.get("rspCode") != '00000000':
                        log("FAIL", f"[EMERGENCY STREAM] 获取资产与围栏信息失败: {device_name} (UID={stream_uid}), RESPONSE={asset_info}")
                        continue
                    for pos in asset_info.get('data'):
                        fence_uid = pos["fenceId"]
                        fence_points = json.loads(pos["locationPoint"])
                        if pos["assetDetail"]:
                            fence_info = [
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
                            fence_info = [f'仓库名称: {pos["whName"]}',
                                          f'仓库编号: {pos["whCode"]}']
                        # 4. 更新本地围栏状态
                        try:
                            bg_frame, pixel_fence_points = relative_to_pixel_fence(live_url, fence_points)
                        except Exception as e:
                            log("FAIL", f"[EMERGENCY FENCE] 获取视频流失败：{device_name} (UID={stream_uid}, FENCE_UID={fence_uid}), ERROR={e}")
                            continue
                        fence_data = {camel_to_snake(pos_key): pos_value for pos_key, pos_value in pos.items()}
                        fence_data['scene_code'] = owner_code
                        changed = sm.update_fence_by_fence_uid(stream_uid, fence_uid, fence_points, fence_info, fence_data)
                        # if changed:
                        # log("INFO", f"[EMERGENCY FENCE] 检测到围栏变化: {device_name} (UID={stream_uid}, FENCE_UID={fence_uid}), 生成新水印")
                        # 5. 生成透明水印
                        watermark_img = wu.draw_fence_with_text(bg_frame, pixel_fence_points, fence_info,
                                                                font_path="C:/Windows/Fonts/msyh.ttc",
                                                                font_size=24, line_spacing=1.2)
                        # 转 PNG 字节流
                        png_bytes = to_png_bytes(watermark_img)
                        # 上传水印到视频流
                        resp = requests.patch(
                            f"{FLOW_LOCAL_URL}/api/fence/water_mark",
                            files={"file": ("fence.png", png_bytes, "image/png")},
                            data={"stream_uid": stream_uid, "fence_uid": fence_uid},
                            timeout=5
                        )
                        resp.raise_for_status()
                        log("SUCCESS", f"[EMERGENCY WATERMARK] 上传水印成功: {device_name} (UID={stream_uid}, FENCE_UID={fence_uid})")
                except requests.RequestException as e:
                    log("FAIL", f"[EMERGENCY STREAM] 管理视频流失败: {device_name} (UID={stream_uid}) ERROR={e}")
                sm.set_stream_group(stream_uid, warehouse_code)
                log("SUCCESS", f"[EMERGENCY STREAM] 设置视频流编组: {device_name} (UID={stream_uid}) -> GROUP_UID={warehouse_code}")
                sm.set_detecting(stream_uid, detecting)
                log("SUCCESS", f"[EMERGENCY STREAM] 设置视频流检测: {device_name} (UID={stream_uid}) -> DETECTING={detecting}")

    log("INFO", "[EMERGENCY STREAM] === 获取设备信息完成 ===")


if __name__ == "__main__":
    import time
    INTERVAL_HOURS = 10
    while True:
        try:
            get_streams_worker()
        except Exception as e:
            log("FAIL", f"[EMERGENCY STREAM] get_streams_worker 运行异常: {e}")
        log("INFO", f"[EMERGENCY STREAM] 等待 {INTERVAL_HOURS} 小时后重新运行...")
        time.sleep(INTERVAL_HOURS * 3600)
