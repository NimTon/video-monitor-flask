from typing import Dict, Any, Optional, List
import requests
from emergency.config import URL_EVENT_UP, URL_GET_DEVICES, URL_UPLOAD_FILE, URL_GET_LIVE_URL, ZK_TOKEN, MACHINE_CODES


class ZhongkaiAPIError(Exception):
    """中凯 API 调用错误"""

    def __init__(self, message: str, response: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.response = response


class ZhongkaiAPI:
    def __init__(self):
        self.headers = {"F-VIDEO-AI-TOKEN": ZK_TOKEN}
        self.url_get_devices = URL_GET_DEVICES
        self.url_get_live_url = URL_GET_LIVE_URL
        self.url_upload_file = URL_UPLOAD_FILE
        self.url_event_up = URL_EVENT_UP

    def get_devices(self, machine_code: str) -> Dict[str, Any]:
        """根据机器编号获取仓库库栋列表"""
        payload = {"machineCode": machine_code}
        resp = requests.post(self.url_get_devices, headers=self.headers, json=payload).json()
        if resp.get("rspCode") != "00000000":
            raise ZhongkaiAPIError("获取设备列表失败", resp)
        return resp.get("data")

    def get_live_url(self, lot_source: str, service_no: str, device_no: str) -> str:
        """获取直播地址"""
        payload = {
            "lotSource": lot_source,
            "serviceNo": service_no,
            "deviceNo": device_no
        }
        resp = requests.post(self.url_get_live_url, headers=self.headers, json=payload).json()
        if resp.get("rspCode") != "00000000":
            raise ZhongkaiAPIError("获取直播地址失败", resp)
        return resp["data"]

    def upload_file(self, file_path: str) -> str:
        """上传文件并返回文件编号"""
        with open(file_path, 'rb') as f:
            files = {"file": (file_path, f)}
            resp = requests.post(self.url_upload_file, headers=self.headers, files=files).json()
        if resp.get("rspCode") != "00000000":
            raise ZhongkaiAPIError("文件上传失败", resp)
        return resp["data"]

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
        if resp.get("rspCode") != "00000000":
            raise ZhongkaiAPIError("事件上报失败", resp)
        return True


zk_api = ZhongkaiAPI()
