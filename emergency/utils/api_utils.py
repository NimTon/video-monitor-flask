from typing import Dict, Any, Optional, List
import requests
import base64

from emergency.config import (
    URL_EVENT_UP,
    URL_GET_DEVICES,
    URL_UPLOAD_FILE,
    URL_GET_LIVE_URL,
    URL_QUERY_AND_PUSH_ASSETS,
    URL_UPLOAD_BYTE_FILE,
    URL_PATROL_RECORD,
    ZK_TOKEN,
    API_KEY,
    X_Data_Source
)


class ZhongkaiAPIError(Exception):
    """中凯 API 调用错误"""

    def __init__(self, message: str, response: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.response = response


class ZhongkaiAPI:
    def __init__(self):
        self.headers = {
            "F-VIDEO-AI-TOKEN": ZK_TOKEN,
            "APIKEY": API_KEY,
            "X-Data-Source": X_Data_Source
        }
        self.url_get_devices = URL_GET_DEVICES
        self.url_get_live_url = URL_GET_LIVE_URL
        self.url_upload_file = URL_UPLOAD_FILE
        self.url_event_up = URL_EVENT_UP
        self.url_query_and_push_assets = URL_QUERY_AND_PUSH_ASSETS
        self.url_upload_byte_file = URL_UPLOAD_BYTE_FILE
        self.url_patrol_record = URL_PATROL_RECORD

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

    # def upload_file(self, file_path: str) -> str:
    #     """上传文件并返回文件编号"""
    #     with open(file_path, 'rb') as f:
    #         files = {"file": (file_path, f)}
    #         resp = requests.post(self.url_upload_file, headers={"F-VIDEO-AI-TOKEN": ZK_TOKEN}, files=files).json()
    #     if resp.get("rspCode") != "00000000":
    #         raise ZhongkaiAPIError("文件上传失败", resp)
    #     return resp["data"]

    # def event_up(
    #         self,
    #         owner_code: str,
    #         warehouse_code: str,
    #         position_code: str,
    #         duration: int,
    #         event_type: str,
    #         event_time: str,
    #         devices: List[Dict[str, Any]]
    # ) -> bool:
    #     """上报事件"""
    #     payload = {
    #         "ownerCode": owner_code,
    #         "warehouseCode": warehouse_code,
    #         "positionCode": position_code,
    #         "duration": duration,
    #         "eventType": event_type,
    #         "eventTime": event_time,
    #         "devices": devices
    #     }
    #     resp = requests.post(self.url_event_up, headers=self.headers, json=payload).json()
    #     if resp.get("rspCode") != "00000000":
    #         raise ZhongkaiAPIError("事件上报失败", resp)
    #     return True

    def query_and_push_assets(
            self,
            hj_device_no: str,
            hj_service_no: str,
            video_play_url: str,
            scene_code: str
    ) -> Dict[str, Any]:
        """获取仓库资产和围栏信息并推送实时视频流"""
        payload = [{
            "hjDeviceNo": hj_device_no,
            "hjServiceNo": hj_service_no,
            "videoPlayUrl": video_play_url,
            "sceneCode": scene_code
        }]
        resp = requests.post(self.url_query_and_push_assets, headers=self.headers, json=payload).json()
        if "code" in resp and resp.get("code") != 200:  # 第三接口返回格式和前面不一样
            raise ZhongkaiAPIError("获取资产和围栏信息失败", resp)
        return resp

    def upload_byte_file_with_apikey(self, file_path: str) -> str:
        """文件上传接口（使用Base64编码），返回文件唯一标识ID"""
        with open(file_path, "rb") as f:
            content_base64 = base64.b64encode(f.read()).decode('utf-8')
        payload = {
            "fileName": file_path.split("/")[-1],  # 只传文件名
            "base64Content": content_base64  # Base64编码的字符串
        }
        resp = requests.post(self.url_upload_byte_file, headers=self.headers, json=payload).json()
        if resp.get("rspCode") != "00000000":
            raise ZhongkaiAPIError("文件上传失败", resp)
        return resp["data"]["id"]

    def patrol_record(
            self,
            wh_code: str,
            wh_name: str,
            patrol_person: str,
            patrol_date: str,
            patrol_result: str,
            report_id: Optional[int] = None,
            scene_code: Optional[str] = None,
            loan_no: Optional[str] = None,
            asset_detail: Optional[str] = None,
            video_files: Optional[str] = None
    ) -> Dict[str, Any]:
        """巡库记录上报接口"""
        payload = {
            "whCode": wh_code,
            "whName": wh_name,
            "patrolPerson": patrol_person,
            "patrolDate": patrol_date,
            "partrolResult": patrol_result
        }
        if report_id:
            payload["reportId"] = report_id
        if scene_code:
            payload["sceneCode"] = scene_code
        if loan_no:
            payload["loanNo"] = loan_no
        if asset_detail:
            payload["assetDetail"] = asset_detail
        if video_files:
            payload["videoFiles"] = video_files
        resp = requests.post(self.url_patrol_record, headers=self.headers, json=payload).json()
        if resp.get("rspCode") != "00000000":
            raise ZhongkaiAPIError("巡库记录上报失败", resp)
        return resp["data"]

    def push_iot_event(
            self,
            hj_device_no: str,
            hj_service_no: str,
            event_type: str,
            event_date: str,
            event_msg: Optional[str] = None,
            event_img_file_id: Optional[str] = None,
            event_video_file_id: Optional[str] = None,
            wh_code: Optional[str] = None,
            wh_name: Optional[str] = None,
            loan_no: Optional[str] = None,
            asset_detail: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        推送物联网预警事件

        参数：
        - hj_device_no: hj设备编号（必填）
        - hj_service_no: hj服务编号（必填）
        - event_type: 事件类型（5-人员聚集，6-活动车辆，7-车货）（必填）
        - event_date: 事件发生时间，yyyy-MM-dd（必填）
        - event_msg: 事件消息（可选）
        - event_img_file_id: 事件图片文件ID（可选）
        - event_video_file_id: 事件影像文件ID（可选）
        - wh_code: 仓库编码（可选）
        - wh_name: 仓库名称（可选）
        - loan_no: 融资编号（可选）
        - asset_detail: 资产信息 JSON 字符串（可选）

        返回：
        - 接口返回 JSON 数据
        """
        payload = {
            "hjDeviceNo": hj_device_no,
            "hjServiceNo": hj_service_no,
            "eventType": event_type,
            "eventDate": event_date
        }
        if event_msg:
            payload["eventMsg"] = event_msg
        if event_img_file_id:
            payload["eventImgFileId"] = event_img_file_id
        if event_video_file_id:
            payload["eventVideoFileId"] = event_video_file_id
        if wh_code:
            payload["whCode"] = wh_code
        if wh_name:
            payload["whName"] = wh_name
        if loan_no:
            payload["loanNo"] = loan_no
        if asset_detail:
            payload["assetDetail"] = asset_detail

        resp = requests.post(self.url_event_up, headers=self.headers, json=payload).json()
        if resp.get("rspCode") != "00000000":
            raise ZhongkaiAPIError("巡库记录上报失败", resp)
        return resp["data"]


zk_api = ZhongkaiAPI()