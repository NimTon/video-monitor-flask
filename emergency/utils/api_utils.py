from typing import Dict, Any, Optional, List

import requests


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
