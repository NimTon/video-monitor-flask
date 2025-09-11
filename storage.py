# 导入所需模块
import json  # 用于JSON数据的读写操作
import threading  # 提供线程锁功能，确保线程安全
import os  # 提供操作系统相关功能，如文件路径检查
import uuid  # 用于生成唯一标识符
import datetime
from utils.utils import chinese_to_pinyin


class StorageManager:
    """视频流数据管理类，负责视频流及其围栏的CRUD操作"""

    def __init__(self, filepath='video_fences.json'):
        """初始化存储管理器"""
        self.filepath = filepath  # 存储文件路径
        self.lock = threading.Lock()  # 创建线程锁对象

        # 初始化数据文件
        if not os.path.exists(filepath):  # 如果文件不存在
            with open(filepath, 'w', encoding='utf-8') as f:  # 创建新文件
                json.dump([], f, indent=2, ensure_ascii=False)  # 写入空列表作为初始数据
        else:  # 文件已存在
            with self.lock:  # 加锁确保线程安全
                # 读取现有数据
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 重置所有视频流状态为stopped
                for stream in data:
                    pass
                    # stream["status"] = "stopped"  # 暂时取消重置状态

                    # 写回更新后的数据
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)  # 格式化输出，便于阅读

    def load_all(self):
        """加载所有视频流数据"""
        with self.lock:  # 加锁
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)  # 返回解析后的JSON数据

    def save_all(self, data):
        """保存所有视频流数据"""
        with self.lock:  # 加锁
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)  # 格式化写入JSON数据

    def _find_stream_index(self, data, stream_uid):
        """内部方法：根据UID查找视频流索引"""
        for i, stream in enumerate(data):  # 遍历所有流
            if stream["uid"] == stream_uid:  # 匹配UID
                return i  # 返回索引位置
        return -1  # 未找到返回-1

    def _find_fence_index(self, stream, fence_id):
        """内部方法：在指定视频流中查找围栏索引"""
        for i, fence in enumerate(stream["fences"]):  # 遍历围栏列表
            if fence["id"] == fence_id:  # 匹配围栏ID
                return i  # 返回索引
        return -1  # 未找到返回-1

    def add_stream(self, stream_url=None, name=None, stream_uid=None, group_uid=""):
        """添加新视频流"""
        data = self.load_all()  # 加载现有数据
        if not stream_uid:
            stream_uid = str(uuid.uuid4())  # 生成唯一ID
        stream_uid = chinese_to_pinyin(stream_uid)

        # 创建新视频流对象
        new_stream = {
            "uid": stream_uid,  # 唯一标识
            "name": name or f"视频流-{stream_uid[:8]}",  # 名称或默认名称
            "stream_url": stream_url,  # 视频流URL
            "status": "stopped",  # 初始状态
            "detecting": False,  # 是否检测中
            "threshold": 0.8,  # 默认阈值
            "frequency": 10,  # 默认检测频率
            "fences": [],  # 空围栏列表
            "recipient_uids": [],  # 空接收人列表
            "group_uid": group_uid
        }

        data.append(new_stream)  # 添加到数据列表
        self.save_all(data)  # 保存数据
        return stream_uid  # 返回新流ID

    def set_detecting(self, stream_uid, detecting: bool):
        """设置检测状态"""
        return self.update_stream(stream_uid, detecting=detecting)

    def is_detecting(self, stream_uid):
        """获取检测状态"""
        stream = self.get_stream(stream_uid)
        if stream:
            return stream.get("detecting", False)
        return False

    def update_stream(self, stream_uid, **kwargs):
        """更新视频流信息"""
        data = self.load_all()  # 加载数据
        idx = self._find_stream_index(data, stream_uid)  # 查找索引
        if idx == -1:
            return False  # 未找到返回False

        # 更新提供的字段
        for key, value in kwargs.items():
            if value is not None:  # 忽略None值
                data[idx][key] = value

        self.save_all(data)  # 保存更新
        return True  # 成功返回True

    def delete_stream(self, stream_uid):
        """删除视频流"""
        data = self.load_all()  # 加载数据
        idx = self._find_stream_index(data, stream_uid)  # 查找索引
        if idx != -1:
            data.pop(idx)  # 移除元素
            self.save_all(data)  # 保存
            return True  # 成功
        return False  # 未找到

    def get_stream(self, stream_uid):
        """获取单个视频流详情"""
        data = self.load_all()  # 加载数据
        for stream in data:  # 遍历查找
            if stream["uid"] == stream_uid:
                return stream  # 返回匹配项
        return None  # 未找到返回None

    def list_streams(self):
        """列出所有视频流"""
        data = self.load_all()  # 加载数据
        return data  # 返回完整列表

    def add_fence(self, stream_uid, points):
        """为视频流添加围栏"""
        data = self.load_all()  # 加载数据
        idx = self._find_stream_index(data, stream_uid)  # 查找流索引
        if idx == -1:
            return None  # 未找到

        fence_id = str(uuid.uuid4())  # 生成围栏ID
        fence = {"id": fence_id, "points": points}  # 创建围栏对象
        data[idx]["fences"].append(fence)  # 添加到围栏列表
        self.save_all(data)  # 保存
        return fence_id  # 返回新围栏ID

    def update_fence(self, stream_uid, fence_id, points):
        """更新围栏坐标点"""
        data = self.load_all()  # 加载数据
        sidx = self._find_stream_index(data, stream_uid)  # 查找流索引
        if sidx == -1:
            return False

        fidx = self._find_fence_index(data[sidx], fence_id)  # 查找围栏索引
        if fidx == -1:
            return False

        data[sidx]["fences"][fidx]["points"] = points  # 更新坐标点
        self.save_all(data)  # 保存
        return True  # 成功

    def delete_fence(self, stream_uid, fence_id):
        """删除围栏"""
        data = self.load_all()  # 加载数据
        sidx = self._find_stream_index(data, stream_uid)  # 查找流索引
        if sidx == -1:
            return False

        fidx = self._find_fence_index(data[sidx], fence_id)  # 查找围栏索引
        if fidx != -1:
            data[sidx]["fences"].pop(fidx)  # 移除围栏
            self.save_all(data)  # 保存
            return True  # 成功
        return False  # 未找到

    def get_fence(self, stream_uid, fence_id):
        """获取单个围栏详情"""
        stream = self.get_stream(stream_uid)  # 获取视频流
        if not stream:
            return None

        for fence in stream["fences"]:  # 遍历围栏
            if fence["id"] == fence_id:
                return fence  # 返回匹配项
        return None  # 未找到

    def list_fences(self, stream_uid):
        """列出视频流的所有围栏"""
        stream = self.get_stream(stream_uid)  # 获取视频流
        return stream["fences"] if stream else []  # 返回围栏列表或空列表

    def bind_recipient_to_stream(self, stream_uid, recipient_uid):
        """绑定接收人到视频流"""
        data = self.load_all()  # 加载数据
        idx = self._find_stream_index(data, stream_uid)  # 查找流索引
        if idx == -1:
            return False

        if "recipient_uids" not in data[idx]:  # 初始化接收人列表
            data[idx]["recipient_uids"] = []

        if recipient_uid not in data[idx]["recipient_uids"]:  # 避免重复
            data[idx]["recipient_uids"].append(recipient_uid)  # 添加接收人
            self.save_all(data)  # 保存
        return True  # 成功

    def unbind_recipient_from_stream(self, stream_uid, recipient_uid):
        """解绑接收人"""
        data = self.load_all()  # 加载数据
        idx = self._find_stream_index(data, stream_uid)  # 查找流索引
        if idx == -1:
            return False

        # 如果存在则移除
        if "recipient_uids" in data[idx] and recipient_uid in data[idx]["recipient_uids"]:
            data[idx]["recipient_uids"].remove(recipient_uid)  # 移除接收人
            self.save_all(data)  # 保存
        return True  # 成功

    def set_stream_group(self, stream_uid, group_uid):
        """设置视频流的编组"""
        return self.update_stream(stream_uid, group_uid=group_uid)

    def get_stream_group(self, stream_uid):
        """获取视频流所在编组"""
        stream = self.get_stream(stream_uid)
        if stream:
            return stream.get("group_uid")
        return None

    def list_groups(self):
        """列出所有存在的编组及其对应的 stream_uid 列表"""
        data = self.load_all()
        groups = {}
        for stream in data:
            gid = stream.get("group_uid")
            sid = stream.get("stream_uid")
            if gid:
                groups.setdefault(gid, []).append(sid)
        return groups

    def list_streams_by_group(self, group_uid):
        """获取某个编组下的所有视频流"""
        data = self.load_all()
        return [s for s in data if s.get("group_uid") == group_uid]


class RecipientsManager:
    """接收人管理类，负责接收人信息的CRUD操作"""

    def __init__(self, filepath='recipients.json'):
        """初始化接收人管理器"""
        self.filepath = filepath  # 存储文件路径
        self.lock = threading.Lock()  # 创建线程锁

        # 初始化数据文件
        if not os.path.exists(filepath):  # 文件不存在
            with open(filepath, 'w', encoding='utf-8') as f:  # 创建新文件
                json.dump([], f, indent=2, ensure_ascii=False)  # 写入空列表

    def load_all(self):
        """加载所有接收人数据"""
        with self.lock:  # 加锁
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)  # 返回解析后的数据

    def save_all(self, data):
        """保存所有接收人数据"""
        with self.lock:  # 加锁
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)  # 格式化写入

    def _find_recipient_index(self, data, recipient_uid):
        """内部方法：查找接收人索引"""
        for i, r in enumerate(data):  # 遍历接收人
            if r["uid"] == recipient_uid:  # 匹配UID
                return i  # 返回索引
        return -1  # 未找到

    def add_recipient(self, name, contact, stream_uids=None):
        """添加新接收人"""
        data = self.load_all()  # 加载数据
        recipient_uid = str(uuid.uuid4())  # 生成唯一ID

        # 创建接收人对象
        new_recipient = {
            "uid": recipient_uid,  # 唯一ID
            "name": name,  # 姓名
            "contact": contact,  # 联系方式
            "stream_uids": stream_uids or []  # 绑定的视频流列表
        }

        data.append(new_recipient)  # 添加到列表
        self.save_all(data)  # 保存
        return recipient_uid  # 返回新ID

    def update_recipient(self, recipient_uid, **kwargs):
        """更新接收人信息"""
        data = self.load_all()  # 加载数据
        idx = self._find_recipient_index(data, recipient_uid)  # 查找索引
        if idx == -1:
            return False  # 未找到

        # 更新提供的字段
        for key, value in kwargs.items():
            if value is not None:  # 忽略None值
                data[idx][key] = value

        self.save_all(data)  # 保存
        return True  # 成功

    def delete_recipient(self, recipient_uid):
        """删除接收人"""
        data = self.load_all()  # 加载数据
        idx = self._find_recipient_index(data, recipient_uid)  # 查找索引
        if idx != -1:
            data.pop(idx)  # 移除元素
            self.save_all(data)  # 保存
            return True  # 成功
        return False  # 未找到

    def get_recipient(self, recipient_uid):
        """获取单个接收人详情"""
        data = self.load_all()  # 加载数据
        for r in data:  # 遍历查找
            if r["uid"] == recipient_uid:
                return r  # 返回匹配项
        return None  # 未找到

    def list_recipients(self):
        """列出所有接收人"""
        data = self.load_all()  # 加载数据
        return data  # 返回完整列表

    def get_recipients_by_stream_id(self, stream_uid):
        """获取绑定到指定视频流的所有接收人"""
        data = self.load_all()  # 加载数据
        return [r for r in data if stream_uid in r.get("stream_uids", [])]  # 列表推导过滤

    def bind_stream_to_recipient(self, recipient_uid, stream_uid):
        """绑定视频流到接收人"""
        data = self.load_all()  # 加载数据
        idx = self._find_recipient_index(data, recipient_uid)  # 查找索引
        if idx == -1:
            return False  # 未找到

        if "stream_uids" not in data[idx]:  # 初始化视频流列表
            data[idx]["stream_uids"] = []

        if stream_uid not in data[idx]["stream_uids"]:  # 避免重复
            data[idx]["stream_uids"].append(stream_uid)  # 添加绑定
            self.save_all(data)  # 保存
        return True  # 成功

    def unbind_stream_from_recipient(self, recipient_uid, stream_uid):
        """解绑视频流"""
        data = self.load_all()  # 加载数据
        idx = self._find_recipient_index(data, recipient_uid)  # 查找索引
        if idx == -1:
            return False

        # 如果存在则移除
        if "stream_uids" in data[idx] and stream_uid in data[idx]["stream_uids"]:
            data[idx]["stream_uids"].remove(stream_uid)  # 移除绑定
            self.save_all(data)  # 保存
        return True  # 成功


class AlertStorageManager:
    """告警模板管理类"""

    def __init__(self, filepath='alerts.json'):
        """初始化告警模板管理器"""
        self.filepath = filepath  # 存储文件路径
        self.lock = threading.Lock()  # 创建线程锁

        # 初始化数据文件
        if not os.path.exists(filepath):  # 文件不存在
            with open(filepath, 'w', encoding='utf-8') as f:  # 创建新文件
                json.dump([], f, indent=2, ensure_ascii=False)  # 写入空列表

    def load_all(self):
        """加载所有告警模板"""
        with self.lock:  # 加锁
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)  # 返回解析后的数据

    def save_all(self, data):
        """保存所有告警模板"""
        with self.lock:  # 加锁
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)  # 格式化写入

    def get_alert_templates(self):
        """获取所有告警模板"""
        data = self.load_all()  # 加载数据
        return data  # 返回完整列表

    def update_alert_templates(self, templates):
        """更新告警模板列表"""
        data = self.load_all()  # 加载现有数据(实际未使用)
        data = templates  # 直接替换为新模板
        self.save_all(data)  # 保存


class MessageManager:
    """告警信息管理类，负责告警信息的CRUD操作"""

    def __init__(self, filepath='messages.json'):
        """初始化告警信息管理器"""
        self.filepath = filepath  # 存储文件路径
        self.lock = threading.Lock()  # 创建线程锁

        # 初始化数据文件
        if not os.path.exists(filepath):  # 文件不存在
            with open(filepath, 'w', encoding='utf-8') as f:  # 创建新文件
                json.dump([], f, indent=2, ensure_ascii=False)  # 写入空列表

    def load_all(self):
        """加载所有告警信息"""
        with self.lock:  # 加锁
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)  # 返回解析后的数据

    def save_all(self, data):
        """保存所有告警信息"""
        with self.lock:  # 加锁
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)  # 格式化写入

    def _find_message_index(self, data, message_uid):
        """内部方法：根据message_uid查找告警信息的索引"""
        for i, msg in enumerate(data):  # 遍历所有告警信息
            if msg["message_uid"] == message_uid:  # 匹配message_uid
                return i  # 返回索引位置
        return -1  # 未找到返回-1

    def add_message(self, stream_uid, fence_uid, stream_name, change_ratio, ai_report, image_before_url, image_after_url, video_url):
        """添加新告警信息"""
        data = self.load_all()  # 加载现有数据
        message_uid = str(uuid.uuid4())  # 生成唯一ID
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 创建新告警信息对象
        new_message = {
            "message_uid": message_uid,  # 唯一标识
            "stream_uid": stream_uid,  # 视频流UID
            "fence_uid": fence_uid,  # 围栏UID
            "stream_name": stream_name,  # 视频流名称
            "timestamp": timestamp,  # 时间戳
            "change_ratio": change_ratio,  # 变化比例
            "ai_report": ai_report,  # AI生成的报告
            "image_before_url": image_before_url,  # 修改前图像链接
            "image_after_url": image_after_url,  # 修改后图像链接
            "video_url": video_url,  # 缓冲区视频链接
        }

        data.append(new_message)  # 添加到数据列表
        self.save_all(data)  # 保存数据
        return message_uid  # 返回新告警信息的UID

    def update_message(self, message_uid, **kwargs):
        """更新告警信息"""
        data = self.load_all()  # 加载数据
        idx = self._find_message_index(data, message_uid)  # 查找索引
        if idx == -1:
            return False  # 未找到返回False

        # 更新提供的字段
        for key, value in kwargs.items():
            if value is not None:  # 忽略None值
                data[idx][key] = value

        self.save_all(data)  # 保存更新
        return True  # 成功返回True

    def delete_message(self, message_uid):
        """删除告警信息"""
        data = self.load_all()  # 加载数据
        idx = self._find_message_index(data, message_uid)  # 查找索引
        if idx != -1:
            data.pop(idx)  # 移除元素
            self.save_all(data)  # 保存
            return True  # 成功
        return False  # 未找到

    def get_message(self, message_uid):
        """获取单个告警信息详情"""
        data = self.load_all()  # 加载数据
        for msg in data:  # 遍历查找
            if msg["message_uid"] == message_uid:
                return msg  # 返回匹配项
        return None  # 未找到返回None

    def list_messages(self):
        """列出所有告警信息"""
        data = self.load_all()  # 加载数据
        return data  # 返回完整列表

    def get_messages_by_stream(self, stream_uid):
        """获取绑定到指定视频流的所有告警信息"""
        data = self.load_all()  # 加载数据
        return [msg for msg in data if msg["stream_uid"] == stream_uid]  # 筛选并返回匹配的告警信息

    def get_messages_by_fence(self, fence_uid):
        """获取绑定到指定围栏的所有告警信息"""
        data = self.load_all()  # 加载数据
        return [msg for msg in data if msg["fence_uid"] == fence_uid]  # 筛选并返回匹配的告警信息


class ImageReportManager:
    """报告信息管理类，负责报告信息的CRUD操作"""

    def __init__(self, filepath='image_report.json'):
        """初始化报告信息管理器"""
        self.filepath = filepath
        self.lock = threading.Lock()

        if not os.path.exists(filepath):
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=2, ensure_ascii=False)

    def load_all(self):
        with self.lock:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)

    def save_all(self, data):
        with self.lock:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    def _find_report_index(self, data, stream_uid):
        for i, msg in enumerate(data):
            if msg["stream_uid"] == stream_uid:
                return i
        return -1

    def add_report(self, stream_uid, stream_name, date=None):
        """添加新报告（默认当天 24 小时初始化，可指定日期）"""
        data = self.load_all()
        # 默认用今天，支持传入 date
        if date is None:
            date = datetime.datetime.now().strftime("%Y-%m-%d")
        images = []
        for i in range(24):
            hour_time = datetime.datetime.combine(
                datetime.datetime.strptime(date, "%Y-%m-%d").date(),
                datetime.time(i, 0, 0)
            )
            images.append({
                "timestamp": hour_time.strftime("%H:00:00"),
                "image_path": "",
                "image_url": "",
            })
        new_report = {
            "stream_uid": stream_uid,
            "stream_name": stream_name,
            date: {
                "images": images,
                "report": ""
            }
        }
        data.append(new_report)
        self.save_all(data)
        return new_report

    def update_report(self, stream_uid, date: str, report=None, hour: str = None, image_path=None, image_url=None, images=None):
        """
        更新指定日期的报告
        - report: 更新当天的总结文本
        - images: 替换整天的 images（不常用）
        - hour + image_path/image_url: 更新某个小时的图片
        """
        data = self.load_all()
        idx = self._find_report_index(data, stream_uid)
        if idx == -1:
            return False
        if report is not None:
            data[idx][date]["report"] = report
        if images is not None:
            data[idx][date]["images"] = images
        if hour is not None and (image_path or image_url):
            for img in data[idx][date]["images"]:
                if img["timestamp"].startswith(hour.zfill(2)):  # 例如 hour="05" 匹配 "05:00:00"
                    if image_path:
                        img["image_path"] = image_path
                    if image_url:
                        img["image_url"] = image_url
                    break
        self.save_all(data)
        return True

    def delete_report(self, stream_uid):
        data = self.load_all()
        idx = self._find_report_index(data, stream_uid)
        if idx != -1:
            data.pop(idx)
            self.save_all(data)
            return True
        return False

    def reset_report(self, stream_uid, date: str):
        """重置指定日期的报告"""
        data = self.load_all()
        idx = self._find_report_index(data, stream_uid)
        if idx == -1:
            return False

        today = datetime.date.today()
        images = []
        for i in range(24):
            hour_time = datetime.datetime.combine(today, datetime.time(i, 0, 0))
            images.append({
                "timestamp": hour_time.strftime("%H:00:00"),
                "image_path": "",
                "image_url": "",
            })

        data[idx][date] = {
            "images": images,
            "report": ""
        }

        self.save_all(data)
        return data[idx][date]

    def get_report(self, stream_uid, date: str = None):
        """获取单个报告（可指定日期）"""
        data = self.load_all()
        for report in data:
            if report["stream_uid"] == stream_uid:
                if date:
                    if report.get(date, None):
                        return report.get(date)
                    else:
                        return self.reset_report(stream_uid, date)
                else:
                    return report
        return None

    def list_reports(self, date: str = None):
        """列出所有报告（可指定日期）"""
        data = self.load_all()
        if date:
            reports = []
            for msg in data:
                if date in msg:
                    reports.append({
                        "stream_uid": msg["stream_uid"],
                        "stream_name": msg["stream_name"],
                        date: msg[date]
                    })
            return reports
        return data

    def get_overall_summary(self, date: str):
        """获取所有视频流的总摘要"""
        return self.get_report("ALL_STREAMS", date)

    def update_overall_summary(self, date: str, report_text: str):
        """更新所有视频流的总摘要"""
        # 如果总摘要不存在，则初始化（这里用昨天的 date）
        overall_report = self.get_report("ALL_STREAMS")
        if not overall_report:
            self.add_report("ALL_STREAMS", "ALL_STREAMS", date=date)
        self.get_report("ALL_STREAMS", date)
        # 更新指定日期的 report 字段
        return self.update_report("ALL_STREAMS", date=date, report=report_text)

    def reset_overall_summary(self, date: str):
        """重置总摘要（清空 report）"""
        overall_report = self.get_report("ALL_STREAMS")
        if not overall_report:
            self.add_report("ALL_STREAMS", "ALL_STREAMS")
        images = []
        for i in range(24):
            hour_time = datetime.datetime.combine(datetime.date.today(), datetime.time(i, 0, 0))
            images.append({
                "timestamp": hour_time.strftime("%H:00:00"),
                "image_path": "",
                "image_url": "",
            })
        return self.update_report("ALL_STREAMS", date=date, report="", images=images)


# ==== 辅助函数 ====
def bind_stream_and_recipient(storage_mgr: StorageManager, recipients_mgr: RecipientsManager, stream_uid, recipient_uid):
    """双向绑定：视频流和接收人互相绑定"""
    storage_mgr.bind_recipient_to_stream(stream_uid, recipient_uid)  # 流绑定接收人
    recipients_mgr.bind_stream_to_recipient(recipient_uid, stream_uid)  # 接收人绑定流


def unbind_stream_and_recipient(storage_mgr: StorageManager, recipients_mgr: RecipientsManager, stream_uid, recipient_uid):
    """双向解绑：视频流和接收人互相解绑"""
    storage_mgr.unbind_recipient_from_stream(stream_uid, recipient_uid)  # 流解绑接收人
    recipients_mgr.unbind_stream_from_recipient(recipient_uid, stream_uid)  # 接收人解绑流


sm = StorageManager()
rm = RecipientsManager()
asm = AlertStorageManager()
ssm = SourceStreamManager()
mm = MessageManager()
irm = ImageReportManager()
