from flask import Flask, request, jsonify, send_from_directory
from storage import StorageManager, RecipientsManager, AlertStorageManager, MessageManager
import requests
import json
import os
from datetime import datetime
from utils.stream_utils import get_video_size
from utils.utils import draw_fence_on_frame, points_to_abs_points
import numpy as np
import cv2
from config import FLOW_BASE_URL
import traceback

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)

# 设置前端静态文件目录
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
os.makedirs(FRONTEND_DIST, exist_ok=True)
# 创建Flask应用实例
# app = create_app()
app = Flask(__name__, static_folder=None)  # 关闭默认的 static 文件服务
# 创建存储管理器实例
storage = StorageManager()
# 创建联系人管理器实例
recipient_mgr = RecipientsManager()
# 创建报警存储管理器实例
alert_storage = AlertStorageManager()
# 创建 MessageManager 实例
message_manager = MessageManager()
# 初始化视频流线程字典，用于存储stream_id到线程的映射
app.video_threads = {}
# ZLMediaKit服务器配置
ZLMediaKit_secret = config['zlmk_secret']  # 虚拟机
# ZLMediaKit_secret = 'k9mlFsMF38CGAUVSdIzpiPKonvgxBT9v'  # 公司服务器
# ZLMediaKit_url = 'http://172.26.18.19/index/api'  # 测试虚拟机
ZLMediaKit_url = config['zlmk_url']  # 虚拟机
# ZLMediaKit_url = 'http://10.30.4.50:180/index/api'  # 公司服务器
# 图片存放路径
IMAGE_DIR = os.path.join(os.getcwd(), 'images')  # 绝对路径更安全
# 视频存放路径
VIDEO_DIR = os.path.join(os.getcwd(), 'videos')  # 绝对路径更安全
PORT = config['port']


# -------- 前端路由 --------
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_vue(path):
    full_path = os.path.join(FRONTEND_DIST, path)
    if path and os.path.exists(full_path) and not os.path.isdir(full_path):
        # 静态资源存在，直接返回
        return send_from_directory(FRONTEND_DIST, path)
    else:
        # 不存在文件，返回 index.html，交给 Vue Router 处理
        return send_from_directory(FRONTEND_DIST, 'index.html')


# -------- 图片接口 --------
@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)


# -------- 视频接口 --------
@app.route('/videos/<path:filename>')
def serve_video(filename):
    return send_from_directory(VIDEO_DIR, filename)


# -------- 健康接口 --------
@app.route('/api/welcome', methods=['GET'])
def welcome():
    try:
        # 调用下游 welcome 接口
        resp = requests.get(f"{FLOW_BASE_URL}/api/welcome", timeout=3)
        resp.raise_for_status()  # 如果状态码不是 200，抛出异常
    except requests.RequestException as e:
        return jsonify({
            "message": "转流服务离线",
            "status": "fail"
        }), 200

    return jsonify({
        "message": "服务器在线，欢迎使用监控预警管理系统",
        "status": "success"
    }), 200


# -------- 视频流管理接口 --------
@app.route('/api/streams', methods=['POST'])
def create_stream():
    data = request.json
    source_stream_url = data.get('source_stream_url')
    stream_url = data.get('stream_url')
    name = data.get('name')
    stream_uid = data.get('stream_uid')
    # 检查名称和 URL 是否重复
    if name in [s.get('name') for s in storage.list_streams() if s.get('name')]:
        return jsonify({"message": "流名称 已存在"}), 400
    if source_stream_url in [s.get('stream_url') for s in storage.list_streams() if s.get('stream_url')]:
        return jsonify({"message": "流url 已存在"}), 400
    if stream_url in [s.get('stream_url') for s in storage.list_streams() if s.get('stream_url')]:
        return jsonify({"message": "流url 已存在"}), 400

    stream_uid = storage.add_stream(name=name, stream_uid=stream_uid)

    try:
        if source_stream_url:
            # 转流逻辑，例如调用下游 bind 接口
            response = requests.post(
                f"{FLOW_BASE_URL}/api/bind",
                data={"stream_uid": stream_uid, "url": source_stream_url}
            )
            response.raise_for_status()
            hls_data = response.json().get("data", {})
            stream_url = f"{FLOW_BASE_URL}/{hls_data.get('hls_url')}"
            if not stream_url:
                return jsonify({"message": "下游服务未返回 HLS 地址"}), 500

        storage.update_stream(stream_uid, stream_url=stream_url)
    except requests.RequestException as e:
        return jsonify({"message": f"绑定失败: {e}"}), 500

    return jsonify({"message": "视频流创建成功", "data": {"stream_uid": stream_uid, "stream_url": stream_url}})


@app.route('/api/streams/<stream_uid>', methods=['GET'])
def get_stream(stream_uid):
    # 从存储中获取指定视频流
    stream = storage.get_stream(stream_uid)
    if not stream:
        # 返回未找到错误
        return jsonify({"message": "未找到对应的视频流"}), 404
    # 返回视频流信息
    return jsonify(stream)


@app.route('/api/streams', methods=['GET'])
def list_streams():
    # 获取所有视频流列表
    streams = storage.list_streams()
    # 返回列表
    return jsonify(streams)


@app.route('/api/streams/<stream_id>/config', methods=['POST'])
def update_stream_config(stream_id):
    # 获取请求中的配置数据
    data = request.json
    if not data:
        # 返回配置为空错误
        return jsonify({"message": "配置不能为空"}), 400
    # 更新视频流配置
    updated = storage.update_stream(stream_id, **data)
    if not updated:
        # 返回未找到错误
        return jsonify({"message": "未找到对应的视频流"}), 404
    # 返回成功响应
    return jsonify({"message": "流配置已更新"})


@app.route('/api/streams/<stream_uid>', methods=['DELETE'])
def delete_stream(stream_uid):
    # 获取视频流信息
    stream = storage.get_stream(stream_uid)
    # 解绑所有关联的联系人
    for recipient_uid in stream.get('recipient_uids', []):
        storage.unbind_recipient_from_stream(stream_uid, recipient_uid)  # 流解绑接收人
        recipient_mgr.unbind_stream_from_recipient(recipient_uid, stream_uid)  # 接收人解绑流
    # 从存储中删除视频流
    if not storage.delete_stream(stream_uid):
        # 返回未找到错误
        return jsonify({"message": "未找到对应的视频流"}), 404
    # 删除关联的转流线程
    try:
        resp = requests.delete(f"{FLOW_BASE_URL}/api/unbind/{stream_uid}")
        if resp.status_code != 200:
            return jsonify({"message": f"解绑失败: {resp.text}"}), 500
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": f"调用解绑接口失败: {str(e)}"}), 500
    # 返回成功响应
    return jsonify({"message": "视频流已删除"})


# -------- 电子围栏管理接口 --------
@app.route('/api/streams/<stream_id>/fences', methods=['POST'])
def add_fence(stream_id):
    # 获取请求中的围栏数据
    data = request.json
    points = data.get('points')
    # 检查围栏点数是否足够
    if not points or len(points) < 3:
        return jsonify({"message": "围栏点数不足，至少需要3个点"}), 400
    # 添加围栏到存储
    fence_id = storage.add_fence(stream_id, points)
    if not fence_id:
        # 返回未找到错误
        return jsonify({"message": "未找到对应的视频流"}), 404
    # 绘制围栏水印
    url = storage.get_stream(stream_id).get("stream_url")
    width, height = get_video_size(url)
    empty_frame = np.zeros((height, width, 4), dtype=np.uint8)  # 4通道
    frame = empty_frame.copy()
    fences = storage.list_fences(stream_id)
    abs_points = points_to_abs_points(empty_frame, fences)
    for fence in abs_points:
        frame = draw_fence_on_frame(frame, fence)

    # 转PNG字节流，准备传给第二个接口
    _, buf = cv2.imencode(".png", frame)
    png_bytes = buf.tobytes()

    # 调用第二个接口（保存水印）
    requests.patch(
        f"{FLOW_BASE_URL}/api/water_mark",
        files={"file": ("fence.png", png_bytes, "image/png")},
        data={"stream_uid": stream_id}
    )

    # 返回成功响应
    return jsonify({
        "id": fence_id,
        "message": "fence created"
    })


@app.route('/api/streams/<stream_id>/fences/<fence_id>', methods=['PUT'])
def update_fence(stream_id, fence_id):
    # 获取请求中的围栏数据
    data = request.json
    points = data.get('points')
    # 检查围栏点数是否足够
    if not points or len(points) < 3:
        return jsonify({"message": "围栏点数不足，至少需要3个点"}), 400
    # 更新围栏
    if storage.update_fence(stream_id, fence_id, points):
        return jsonify({"message": "围栏已更新"})
    # 返回未找到错误
    return jsonify({"message": "未找到对应的围栏或视频流"}), 404


@app.route('/api/streams/<stream_id>/fences/<fence_id>', methods=['DELETE'])
def delete_fence(stream_id, fence_id):
    # 删除围栏
    if storage.delete_fence(stream_id, fence_id):
        # 绘制围栏水印
        url = storage.get_stream(stream_id).get("stream_url")
        width, height = get_video_size(url)
        empty_frame = np.zeros((height, width, 4), dtype=np.uint8)  # 4通道
        frame = empty_frame.copy()
        fences = storage.list_fences(stream_id)
        if fences:
            abs_points = points_to_abs_points(empty_frame, fences)
            for fence in abs_points:
                frame = draw_fence_on_frame(frame, fence)

            # 转PNG字节流，准备传给第二个接口
            _, buf = cv2.imencode(".png", frame)
            png_bytes = buf.tobytes()

            # 调用第二个接口（保存水印）
            requests.patch(
                f"{FLOW_BASE_URL}/api/water_mark",
                files={"file": ("fence.png", png_bytes, "image/png")},
                data={"stream_uid": stream_id}
            )
        else:
            requests.delete(
                f"{FLOW_BASE_URL}/api/water_mark",
                json={"stream_uid": stream_id}
            )
        return jsonify({"message": "围栏已删除"})
    # 返回未找到错误
    return jsonify({"message": "未找到对应的围栏或视频流"}), 404


@app.route('/api/streams/<stream_id>/fences', methods=['GET'])
def list_fences(stream_id):
    # 获取视频流的所有围栏
    fences = storage.list_fences(stream_id)
    return jsonify(fences)


# -------- 视频流线程控制接口 --------
@app.route('/api/streams/<stream_id>/start', methods=['POST'])
def start_stream(stream_id):
    # 获取视频流信息
    stream = storage.get_stream(stream_id)
    if not stream:
        # 返回未找到错误
        return jsonify({"message": "未找到对应的视频流"}), 404
    fences = storage.list_fences(stream_id)
    if not fences:
        # 返回未找到错误
        return jsonify({"message": "未绑定电子围栏"}), 404
    storage.update_stream(stream_id, status="running")
    return jsonify({"message": "流已启动"})


@app.route('/api/streams/<stream_id>/stop', methods=['POST'])
def stop_stream(stream_id):
    storage.update_stream(stream_id, status="stopped")
    return jsonify({"message": "流已停止"})


@app.route('/api/streams/<stream_id>/activate', methods=['POST'])
def activate_stream(stream_id):
    # 获取视频流信息
    stream = storage.get_stream(stream_id)
    if not stream:
        # 返回未找到错误
        return jsonify({"message": "未找到对应的视频流"}), 404
    fences = storage.list_fences(stream_id)
    if not fences:
        # 返回未找到错误
        return jsonify({"message": "未绑定电子围栏"}), 404
    storage.update_stream(stream_id, detecting=True)
    return jsonify({"message": "流已启动"})


@app.route('/api/streams/<stream_id>/deactivate', methods=['POST'])
def deactivate_stream(stream_id):
    storage.update_stream(stream_id, detecting=False)
    return jsonify({"message": "流已停止"})


# -------- 状态查询接口 --------
@app.route('/api/streams/<stream_id>/status', methods=['GET'])
def check_status(stream_id):
    # 获取视频流检测状态，默认为未变化
    result = app.video_results.get(stream_id, {"changed": False, "area": 0})
    return jsonify(result)


@app.route('/api/streams/<stream_id>', methods=['GET'])
def check_stream(stream_id):
    # 获取视频流信息
    stream = storage.get_stream(stream_id)
    if not stream:
        # 返回未找到错误
        return jsonify({"message": "未找到对应的视频流"}), 404
    return jsonify(stream)


# -------- 报警模板管理接口 --------
@app.route('/api/alerts/templates', methods=['GET'])
def get_alert_templates():
    # 获取所有报警模板
    templates = alert_storage.get_alert_templates()
    return jsonify({"templates": templates})


@app.route('/api/alerts/templates', methods=['POST'])
def update_alert_templates():
    # 获取请求中的模板数据
    data = request.json
    templates = data.get('templates')
    # 检查模板数据是否有效
    if not isinstance(templates, list):
        return jsonify({"message": "无效的模板列表"}), 400
    # 更新报警模板
    alert_storage.update_alert_templates(templates)
    return jsonify({"message": "报警模板已更新"})


# -------- 联系人管理接口 --------
@app.route('/api/recipients', methods=['POST'])
def create_recipient():
    # 获取请求中的联系人数据
    data = request.json
    name = data.get('name')
    contact = data.get('contact')
    stream_uids = data.get('stream_uids', [])
    # 检查必填字段
    if not name or not contact:
        return jsonify({"message": "姓名和联系方式必填"}), 400

    # 创建联系人
    recipient_uid = recipient_mgr.add_recipient(name, contact, stream_uids)

    # 双向绑定联系人和视频流
    for stream_uid in stream_uids:
        # 绑定联系人到视频流
        storage.bind_recipient_to_stream(stream_uid, recipient_uid)
        # 绑定视频流到联系人
        recipient_mgr.bind_stream_to_recipient(recipient_uid, stream_uid)

    return jsonify({"message": "联系人创建成功", "recipient_uid": recipient_uid})


@app.route('/api/recipients/<recipient_uid>', methods=['GET'])
def get_recipient(recipient_uid):
    # 获取联系人信息
    r = recipient_mgr.get_recipient(recipient_uid)
    if not r:
        # 返回未找到错误
        return jsonify({"message": "未找到联系人"}), 404
    return jsonify(r)


@app.route('/api/recipients', methods=['GET'])
def list_recipients():
    # 获取所有联系人列表
    recipients = recipient_mgr.list_recipients()
    return jsonify(recipients)


@app.route('/api/recipients/<recipient_uid>', methods=['PUT'])
def update_recipient(recipient_uid):
    # 获取请求中的更新数据
    data = request.json
    # 只更新姓名和联系方式
    name = data.get('name')
    contact = data.get('contact')
    # 更新联系人信息
    updated = recipient_mgr.update_recipient(recipient_uid, name=name, contact=contact)
    if not updated:
        # 返回未找到错误
        return jsonify({"message": "未找到联系人"}), 404
    return jsonify({"message": "联系人信息已更新"})


@app.route('/api/recipients/<recipient_uid>', methods=['DELETE'])
def delete_recipient(recipient_uid):
    # 获取联系人信息
    recipient = recipient_mgr.get_recipient(recipient_uid)
    if not recipient:
        # 返回未找到错误
        return jsonify({"message": "未找到联系人"}), 404

    # 解绑所有关联的视频流
    for stream_uid in recipient.get('stream_uids', []):
        storage.unbind_recipient_from_stream(stream_uid, recipient_uid)
    # 删除联系人
    recipient_mgr.delete_recipient(recipient_uid)
    return jsonify({"message": "联系人已删除"})


# -------- 绑定管理接口 --------
@app.route('/api/streams/<stream_uid>/recipients/<recipient_uid>', methods=['POST'])
def bind_recipient(stream_uid, recipient_uid):
    # 双向绑定联系人和视频流
    s_res = storage.bind_recipient_to_stream(stream_uid, recipient_uid)
    r_res = recipient_mgr.bind_stream_to_recipient(recipient_uid, stream_uid)
    if not s_res or not r_res:
        # 返回绑定失败错误
        return jsonify({"message": "绑定失败，检查stream和recipient是否存在"}), 404
    return jsonify({"message": "绑定成功"})


@app.route('/api/streams/<stream_uid>/recipients/<recipient_uid>', methods=['DELETE'])
def unbind_recipient(stream_uid, recipient_uid):
    # 双向解绑联系人和视频流
    s_res = storage.unbind_recipient_from_stream(stream_uid, recipient_uid)
    r_res = recipient_mgr.unbind_stream_from_recipient(recipient_uid, stream_uid)
    if not s_res or not r_res:
        # 返回解绑失败错误
        return jsonify({"message": "解绑失败，检查stream和recipient是否存在或已绑定"}), 404
    return jsonify({"message": "解绑成功"})


# -------- 查询接口 --------
@app.route('/api/streams/<stream_uid>/recipients', methods=['GET'])
def list_recipients_of_stream(stream_uid):
    # 获取视频流信息
    stream = storage.get_stream(stream_uid)
    if not stream:
        # 返回未找到错误
        return jsonify({"message": "未找到视频流"}), 404
    # 获取所有绑定的联系人
    recipient_uids = stream.get('recipient_uids', [])
    recipients = []
    for uid in recipient_uids:
        r = recipient_mgr.get_recipient(uid)
        if r:
            recipients.append(r)
    return jsonify(recipients)


@app.route('/api/recipients/<recipient_uid>/streams', methods=['GET'])
def list_streams_of_recipient(recipient_uid):
    # 获取联系人信息
    recipient = recipient_mgr.get_recipient(recipient_uid)
    if not recipient:
        # 返回未找到错误
        return jsonify({"message": "未找到联系人"}), 404
    # 获取所有绑定的视频流
    stream_uids = recipient.get('stream_uids', [])
    streams = []
    for uid in stream_uids:
        s = storage.get_stream(uid)
        if s:
            streams.append(s)
    return jsonify(streams)


# ----------------------
# 源视频流列表
# ----------------------
@app.route('/api/source-streams', methods=['GET'])
def list_source_streams():
    try:
        resp = requests.get(f"{FLOW_BASE_URL}/api/list")
        resp.raise_for_status()  # 非 200 会抛异常
        data = resp.json().get("data")  # 获取 Flow 返回的 data 字段
        streams = []
        for stream_uid, info in data.items():
            stream_info = storage.get_stream(stream_uid)
            streams.append({
                "stream_name": stream_info.get('name'),
                "stream_uid": stream_uid,
                "url": info.get("url"),
                "hls": f'{FLOW_BASE_URL}/{info.get("hls_wm")}',
                "status": info.get("status")
            })
        return jsonify(streams), 200
    except requests.HTTPError as e:
        return jsonify({"message": f"下游服务返回错误: {e}", "data": []}), resp.status_code
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e), "data": []}), 500


# ----------------------
# 添加源视频流
# ----------------------
@app.route('/api/source-streams', methods=['POST'])
def add_source_stream():
    try:
        url = request.json.get('url')
        stream_uid = request.json.get('uid')
        watermark_path = request.json.get('watermark')
        if not url:
            return jsonify({"message": "url 必填"}), 400
        data = {"stream_uid": stream_uid, "url": url}
        files = {}
        if watermark_path:
            files['file'] = open(watermark_path, 'rb')
        resp = requests.post(f"{FLOW_BASE_URL}/api/bind", data=data, files=files)
        if resp.status_code == 200:
            return jsonify(resp.json()), 200
        else:
            return jsonify({"message": "下游绑定失败", "detail": resp.text}), resp.status_code
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


# ----------------------
# 更新源视频流
# ----------------------
@app.route('/api/source-streams', methods=['PATCH'])
def update_source_stream():
    try:
        url = request.json.get('source_stream_url')
        stream_uid = request.json.get('uid')
        data = {"stream_uid": stream_uid, "url": url}
        resp = requests.post(f"{FLOW_BASE_URL}/api/bind", json=data)
        if resp.status_code == 200:
            return jsonify(resp.json()), 200
        else:
            return jsonify({"message": "下游绑定失败", "detail": resp.text}), resp.status_code
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


# ----------------------
# 启动单条流
# ----------------------
@app.route('/api/source-streams/<uid>/start', methods=['POST'])
def start_source_stream(uid):
    try:
        resp = requests.post(f"{FLOW_BASE_URL}/api/start/{uid}")
        if resp.status_code == 200:
            return jsonify(resp.json()), 200
        else:
            return jsonify({"message": "下游启动失败", "detail": resp.text}), resp.status_code
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


# ----------------------
# 停止单条流
# ----------------------
@app.route('/api/source-streams/<uid>/stop', methods=['POST'])
def stop_source_stream(uid):
    try:
        resp = requests.post(f"{FLOW_BASE_URL}/api/stop/{uid}")
        if resp.status_code == 200:
            return jsonify(resp.json()), 200
        else:
            return jsonify({"message": "下游停止失败", "detail": resp.text}), resp.status_code
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


# ----------------------
# 获取单条流信息
# ----------------------
@app.route('/api/source-streams/<uid>', methods=['GET'])
def get_source_stream(uid):
    try:
        resp = requests.get(f"{FLOW_BASE_URL}/api/list")
        resp.raise_for_status()
        data = resp.json().get('data', {})
        if uid in data:
            return jsonify({"message": "获取成功", "data": data[uid]}), 200
        else:
            return jsonify({"message": "Stream not found"}), 404
    except requests.HTTPError as e:
        return jsonify({"message": f"下游服务返回错误: {e}"}), resp.status_code
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


# ------- 消息管理接口 -------
@app.route('/api/messages', methods=['POST'])
def add_message():
    """添加新告警信息"""
    try:
        # 从请求中获取告警信息字段
        stream_uid = request.json.get('stream_uid')
        fence_uid = request.json.get('fence_uid')
        stream_name = request.json.get('stream_name')
        change_ratio = request.json.get('change_ratio')
        ai_report = request.json.get('ai_report')
        image_before_url = request.json.get('image_before_url')
        image_after_url = request.json.get('image_after_url')

        # 检查必填字段
        if not all([stream_uid, fence_uid, stream_name, change_ratio, ai_report, image_before_url, image_after_url]):
            return jsonify({"message": "Missing required fields"}), 400

        # 调用 MessageManager 添加告警信息
        message_uid = message_manager.add_message(stream_uid, fence_uid, stream_name, change_ratio, ai_report, image_before_url, image_after_url)
        return jsonify({"message_uid": message_uid}), 201

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


@app.route('/api/messages/<message_uid>', methods=['GET'])
def get_message(message_uid):
    """获取单个告警信息详情"""
    try:
        message = message_manager.get_message(message_uid)
        if not message:
            return jsonify({"message": "Message not found"}), 404
        return jsonify(message), 200
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


@app.route('/api/messages/<message_uid>', methods=['PUT'])
def update_message(message_uid):
    """更新告警信息"""
    try:
        update_fields = request.json  # 获取更新字段

        # 调用 MessageManager 更新告警信息
        success = message_manager.update_message(message_uid, **update_fields)
        if not success:
            return jsonify({"message": "Message not found"}), 404

        return jsonify({"message": "Message updated successfully"}), 200

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


@app.route('/api/messages/<message_uid>', methods=['DELETE'])
def delete_message(message_uid):
    """删除告警信息"""
    try:
        success = message_manager.delete_message(message_uid)
        if not success:
            return jsonify({"message": "Message not found"}), 404

        return jsonify({"message": "Message deleted successfully"}), 200

    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


@app.route('/api/messages', methods=['GET'])
def list_messages():
    """列出所有告警信息（按时间倒序）"""
    try:
        messages = message_manager.list_messages()
        # 按 timestamp 倒序排序
        messages.sort(
            key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S"),
            reverse=True
        )
        return jsonify(messages), 200
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


@app.route('/api/messages/stream/<stream_uid>', methods=['GET'])
def get_messages_by_stream(stream_uid):
    """获取绑定到指定视频流的所有告警信息"""
    try:
        messages = message_manager.get_messages_by_stream(stream_uid)
        # 按 timestamp 倒序排序
        messages.sort(
            key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S"),
            reverse=True
        )
        return jsonify(messages), 200
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


@app.route('/api/messages/fence/<fence_uid>', methods=['GET'])
def get_messages_by_fence(fence_uid):
    """获取绑定到指定围栏的所有告警信息"""
    try:
        messages = message_manager.get_messages_by_fence(fence_uid)
        return jsonify(messages), 200
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"message": str(e)}), 500


# 主程序入口
if __name__ == '__main__':
    # 启动Flask应用
    app.run(host='0.0.0.0', port=PORT)
