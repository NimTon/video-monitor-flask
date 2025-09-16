import requests
from typing import Dict, Any, List, Optional
from storage import StorageManager, RecipientsManager, AlertStorageManager, SourceStreamManager, MessageManager
from video_monitor.video_stream import VideoStreamThread
from alert_dispatcher import dispatch_alert
import threading
import json
import time
from utils import chinese_to_pinyin

# 创建存储管理器实例
storage = StorageManager()
# 创建联系人管理器实例
recipient_mgr = RecipientsManager()
# 创建报警存储管理器实例
alert_storage = AlertStorageManager()
# 创建源视频流管理器实例
source_manager = SourceStreamManager()
# 创建 MessageManager 实例
message_manager = MessageManager()

video_threads = {}

class ZhongkaiAPI:
    def __init__(self, token: str):
        self.headers = {"F-VIDEO-AI-TOKEN": token}

        # 各环境的基础 URL
        self.url_get_devices = "https://openapisit.zhongkaixingye.com/openapi/lot/ai/devices"
        self.url_get_live_url = "https://openapisit.zhongkaixingye.com/openapi/lot/ai/video/url"
        self.url_upload_file = "https://openapisit.zhongkaixingye.com/openapi/lot/ai/file/upload"
        self.url_event_up = "https://openapisit.zhongkaixingye.com/openapi/lot/ai/event/up"

    def get_devices(self, machine_code: str) -> Dict[str, Any]:
        """根据机器编号获取仓库库栋列表"""
        payload = {"machineCode": machine_code}
        resp = requests.post(self.url_get_devices, headers=self.headers, json=payload)
        print(payload)
        print(resp.json())
        return resp.json()

    def get_live_url(self, lot_source: str, service_no: str, device_no: str) -> Optional[str]:
        """获取直播地址"""
        payload = {
            "lotSource": lot_source,
            "serviceNo": service_no,
            "deviceNo": device_no
        }
        resp = requests.post(self.url_get_live_url, headers=self.headers, json=payload).json()
        print(payload)
        print(resp)
        if resp.get("rspCode") == "00000000":
            return resp.get("data")
        return None

    def upload_file(self, file_path: str) -> Optional[str]:
        """上传文件并返回文件编号"""
        with open(file_path, 'rb') as f:
            files = {"file": (file_path, f)}
            resp = requests.post(self.url_upload_file, headers=self.headers, files=files).json()
            print(files)
            print(resp)
        if resp.get("rspCode") == "00000000":
            return resp.get("data")
        return None

    def event_up(
            self,
            owner_code: str,
            warehouse_code: str,
            position_code: str,
            duration: int,
            event_type: str,
            event_time: str,
            devices: List[Dict[str, Any]]
    ) -> bool:
        """上报事件"""
        payload = {
            "ownerCode": owner_code,
            "warehouseCode": warehouse_code,
            "positionCode": position_code,
            "duration": duration,
            "eventType": event_type,
            "eventTime": event_time,
            "devices": devices
        }
        resp = requests.post(self.url_event_up, headers=self.headers, json=payload).json()
        print(payload)
        print(resp)
        if resp.get("rspCode") == "00000000":
            return True
        else:
            return resp


def fetch_all_hls():
    print("=== 开始获取 HLS 地址 ===")
    for machine_code in MACHINE_CODES:
        devices_data = api.get_devices(machine_code)
        if devices_data.get("rspCode") != "00000000":
            print(f"机器 {machine_code} 获取失败：{devices_data.get('rspDesc')}")
            continue

        for warehouse in devices_data.get("data", []):
            warehouse_code = warehouse.get("warehouseCode")
            position_code = warehouse.get("positionCode")
            print(f"[{warehouse_code} - {position_code}]")

            for dev in warehouse.get("devices", []):
                lot_source = dev.get("lotSource")
                service_no = dev.get("serviceNo")
                device_no = dev.get("deviceNo")
                device_name = dev.get("deviceName")

                hls_url = api.get_live_url(lot_source, service_no, device_no)
                if hls_url:
                    print(f"  {device_name} HLS: {hls_url}")
                else:
                    print(f"  {device_name} HLS 获取失败")

def start_stream(warehouse, dev):
    stream_id = chinese_to_pinyin(dev.get("deviceName"))
    # 获取视频流信息
    stream = storage.get_stream(stream_id)
    if not stream:
        # 返回未找到错误
        return {"message": "未找到对应的视频流"}
    fences = storage.list_fences(stream_id)
    if not fences:
        # 返回未找到错误
        return {"message": "未绑定电子围栏"}
    # 检查是否已经在运行（幂等性检查）
    if stream_id in video_threads and video_threads[stream_id].is_alive():
        return {"message": "已在运行"}

    # 获取视频流URL
    stream_url = stream['stream_url']
    name = stream['name']

    # 提取检测参数
    try:
        # 获取阈值参数，默认为0.5
        threshold = float(stream.get('threshold', 0.5))
        # 获取检测频率，默认为10秒
        frequency = float(stream.get('frequency', 10))
    except Exception as e:
        # 返回参数错误
        return {"message": f"参数错误: {e}"}

    # 获取视频帧尺寸用于坐标转换
    import cv2
    cap = cv2.VideoCapture(stream_url)
    success, frame = cap.read()
    if not success:
        # 返回视频读取错误
        return {"message": "无法读取视频帧，请检查视频地址"}
    # 获取视频高度和宽度
    height, width = frame.shape[:2]
    cap.release()

    # 转换围栏点为像素坐标
    fences = stream.get('fences', [])
    fence_points = []
    for fence in fences:
        points = fence.get('points', [])
        if len(points) >= 3:
            # 将相对坐标转换为绝对像素坐标
            abs_points = [(int(p['x'] * width), int(p['y'] * height)) for p in points]
            fence_points.append(abs_points)

    # 检查是否有有效围栏
    if len(fence_points) == 0:
        return {"message": "请先设置至少一个有效的电子围栏（至少3个点）"}

    # 定义结果回调函数
    def result_callback(sid, results, frames):
        for r in results:
            print(name, r, len(frames))
            if r.get("changed"):
                threading.Thread(
                    target=dispatch_alert,
                    args=(sid, r, frames, warehouse, dev),
                    daemon=True
                ).start()

    # 创建并启动视频流线程
    thread = VideoStreamThread(
        stream_id=stream_id,
        stream_url=stream_url,
        result_callback=result_callback,
        compare_interval=frequency,
        change_threshold=threshold,
        debug=False
    )
    # 设置围栏点
    thread.set_fences(fence_points)
    # 设置为守护线程
    thread.daemon = True
    # 启动线程
    thread.start()

    # 保存线程引用
    video_threads[stream_id] = thread
    # 更新视频流状态为运行中
    storage.update_stream(stream_id, status="running")
    return {"message": "流检测已启动"}


def stop_stream(stream_id):
    # 获取视频流线程
    thread = video_threads.get(stream_id)
    # 如果线程不存在或已停止，也返回成功（幂等）
    if not thread:
        storage.update_stream(stream_id, status="stopped")
        return {"message": "已停止"}
    # 停止线程
    thread.stop()
    # 从字典中移除线程
    del video_threads[stream_id]
    # 更新视频流状态为停止
    storage.update_stream(stream_id, name=None, stream_url=None, status="stopped")
    return {"message": "流检测已停止"}

def stop_all_streams():
    """停止所有正在运行的视频流检测"""
    for sid in list(video_threads.keys()):
        print(stop_stream(sid))

def run_cycle():
    """运行一轮获取设备、启动检测"""
    for machine in MACHINE_CODES:
        devices_data = api.get_devices(machine)
        print("仓库库栋列表:", devices_data)
        if devices_data.get("rspCode") != "00000000":
            continue

        for warehouse in devices_data.get("data", []):
            devices = warehouse.get("devices", [])
            owner_code = warehouse.get("warehouseCode")
            for dev in devices:
                lot_source = dev.get("lotSource")
                service_no = dev.get("serviceNo")
                device_no = dev.get("deviceNo")
                device_name = dev.get("deviceName")
                stream_uid = f"{owner_code}-{device_no}-{service_no}"

                live_url = api.get_live_url(lot_source, service_no, device_no)
                if not live_url:
                    print(f"设备 {device_name} 获取 HLS 失败")
                    continue

                # 如果视频流不存在就添加，有则更新
                stream = storage.get_stream(stream_uid)
                if not stream:
                    storage.add_stream(live_url, name=device_name, stream_uid=stream_uid)
                else:
                    storage.update_stream(stream_uid, stream_url=live_url)

                print(start_stream(warehouse, dev))

if __name__ == "__main__":
    with open('config.json', encoding='utf-8') as f:
        config = json.load(f)
    TOKEN = config['zk_token']
    MACHINE_CODES = config['machine_codes']

    api = ZhongkaiAPI(token=TOKEN)

    while True:
        print("=== 新一轮检测开始 ===")
        stop_all_streams()
        run_cycle()

        print("=== 检测运行中（12 小时后重启） ===")
        time.sleep(12 * 3600)  # 等待 12 小时