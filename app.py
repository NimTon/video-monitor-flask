# 导入Flask框架及相关模块
import time
import threading
from flask import Flask, request, jsonify, send_from_directory
# 从video_monitor模块导入create_app函数
from video_monitor import create_app
# 从video_monitor.video_stream模块导入VideoStreamThread类
from video_monitor.video_stream import VideoStreamThread
# 从storage模块导入三个管理类
from storage import StorageManager, RecipientsManager, AlertStorageManager, SourceStreamManager, MessageManager
# 从alert_dispatcher模块导入dispatch_alert函数
from alert_dispatcher import dispatch_alert_multi_frames
import requests
import os
from datetime import datetime

# 设置前端静态文件目录
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
# 创建Flask应用实例
# app = create_app()
app = Flask(__name__, static_folder=None)  # 关闭默认的 static 文件服务
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
# 初始化视频流线程字典，用于存储stream_id到线程的映射
app.video_threads = {}
# ZLMediaKit服务器配置
ZLMediaKit_secret = 'RMys9486msj1NraRsncf0k0lpAMmLaHP'  # 虚拟机
#ZLMediaKit_secret = 'k9mlFsMF38CGAUVSdIzpiPKonvgxBT9v'  # 公司服务器
# ZLMediaKit_url = 'http://172.26.18.19/index/api'  # 测试虚拟机
ZLMediaKit_url = 'http://172.27.109.14/index/api'  # 虚拟机
#ZLMediaKit_url = 'http://10.30.4.50:180/index/api'  # 公司服务器
# 图片存放路径
IMAGE_DIR = os.path.join(os.getcwd(), 'images')  # 绝对路径更安全

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


# -------- 健康接口 --------
@app.route('/api/welcome', methods=['GET'])
def welcome():
    return jsonify({"message": "服务器在线，欢迎使用视频流管理系统"}), 200


# -------- 视频流管理接口 --------
@app.route('/api/streams', methods=['POST'])
def create_stream():
    # 获取请求中的JSON数据
    data = request.json
    # 从数据中提取视频流URL
    stream_url = data['stream_url']
    # 可选获取视频流名称
    name = data.get('name')
    # 检查是否已存在相同的视频流
    if name in [stream_data['name'] for stream_data in storage.list_streams()]:
        return jsonify({"message": "流名称 已存在"}), 400
    if stream_url in [stream_data['stream_url'] for stream_data in storage.list_streams()]:
        return jsonify({"message": "流url 已存在"}), 400

    # 添加视频流到存储
    stream_uid = storage.add_stream(stream_url, name)
    # 返回成功响应
    return jsonify({"message": "视频流创建成功", "stream_uid": stream_uid})


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
    # 停止并删除关联的视频流线程
    thread = app.video_threads.get(stream_uid)
    if thread:
        thread.stop()
        del app.video_threads[stream_uid]
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
    recipients = recipient_mgr.get_recipients_by_stream_id(stream_id)
    if not recipients:
        # 返回未找到错误
        return jsonify({"message": "未绑定联系人"}), 404
    # 检查是否已经在运行（幂等性检查）
    if stream_id in app.video_threads and app.video_threads[stream_id].is_alive():
        return jsonify({"message": "已在运行"}), 400

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
        return jsonify({"message": f"参数错误: {e}"}), 400

    # 获取视频帧尺寸用于坐标转换
    import cv2
    cap = cv2.VideoCapture(stream_url)
    success, frame = cap.read()
    if not success:
        # 返回视频读取错误
        return jsonify({"message": "无法读取视频帧，请检查视频地址"}), 400
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
        return jsonify({"message": "请先设置至少一个有效的电子围栏（至少3个点）"}), 400

    # 定义结果回调函数
    def result_callback(sid, results, frames):
        for r in results:
            print(name, r, len(frames))
            if r.get("changed"):
                threading.Thread(
                    target=dispatch_alert_multi_frames,
                    args=(sid, r, frames),
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
    app.video_threads[stream_id] = thread
    # 更新视频流状态为运行中
    storage.update_stream(stream_id, status="running")
    return jsonify({"message": "流检测已启动"})


@app.route('/api/streams/<stream_id>/stop', methods=['POST'])
def stop_stream(stream_id):
    # 获取视频流线程
    thread = app.video_threads.get(stream_id)
    # 如果线程不存在或已停止，也返回成功（幂等）
    if not thread:
        storage.update_stream(stream_id, status="stopped")
        return jsonify({"message": "已停止"}), 400
    # 停止线程
    thread.stop()
    # 从字典中移除线程
    del app.video_threads[stream_id]
    # 更新视频流状态为停止
    storage.update_stream(stream_id, name=None, stream_url=None, status="stopped")
    return jsonify({"message": "流检测已停止"})


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


# -------- 源视频流接口 --------
# 添加拉流代理（RTMP、RTSP、HTTP-FLV 等）
def add_stream_proxy(uid, url):
    params = {
        'secret': ZLMediaKit_secret,
        'vhost': '__defaultVhost__',
        'app': 'live',
        'stream': uid,
        'url': url,
        'retry_count': -1,
        'rtp_type': 0,
        'timeout_sec': 5,
        'enable_hls': True,
        'enable_hls_fmp4': False,
        'enable_mp4': False,
        'enable_rtsp': False,
        'enable_rtmp': False,
        'enable_ts': False,
        'enable_fmp4': False,
        'hls_demand': False,
        'rtsp_demand': False,
        'rtmp_demand': False,
        'ts_demand': False,
        'fmp4_demand': False,
        'enable_audio': True,
        'add_mute_audio': True,
        'mp4_max_second': 10,
        'mp4_as_player': False,
        'auto_close': False,
    }
    try:
        response = requests.get(f'{ZLMediaKit_url}/addStreamProxy', params=params)
        return response.json()
    except Exception as e:
        # print(f'添加拉流代理失败: {e}')
        return None


# 获取拉流代理列表
def list_stream_proxy():
    try:
        response = requests.get(f'{ZLMediaKit_url}/listStreamProxy', params={'secret': ZLMediaKit_secret})
        if response.json() == {'code': 0}:
            return {'data': []}
        else:
            return response.json()
    except:
        return {'data': []}


# 删除拉流代理
def del_stream_proxy(uid):
    params = {
        'secret': ZLMediaKit_secret,
        'key': f'__defaultVhost__/live/{uid}'
    }
    try:
        response = requests.get(f'{ZLMediaKit_url}/delStreamProxy', params=params)
        return response.json()
    except Exception as e:
        print(f'删除拉流代理失败: {e}')
        return None


@app.route('/api/source-streams', methods=['GET'])
def list_source_streams():
    """列出所有源视频流"""
    try:
        streams = source_manager.list_source_streams()
        stream_proxy_list = list_stream_proxy()['data']
        # 对比拉流代理，设置状态
        for stream in streams:
            if any(proxy['src']['stream'] == stream['uid'] for proxy in stream_proxy_list):
                stream['status'] = 'running'
            else:
                stream['status'] = 'stopped'
        return jsonify(streams), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@app.route('/api/source-streams', methods=['POST'])
def add_source_stream():
    """添加一个新的源视频流"""
    try:
        # 获取传入的参数
        url = request.json.get('url')  # 获取视频流URL
        stream_id = request.json.get('stream_id')  # 获取视频流ID
        uid = request.json.get('uid')  # 获取视频流UID
        if not uid:
            if stream_id in [stream_data['stream_id'] for stream_data in source_manager.list_source_streams()]:
                return jsonify({"message": "流id 已存在"}), 400
            if url in [stream_data['stream_url'] for stream_data in source_manager.list_source_streams()]:
                return jsonify({"message": "流url 已存在"}), 400
        if not url:
            return jsonify({"message": "stream_url is required"}), 400
        if not stream_id:
            return jsonify({"message": "stream_id is required"}), 400
        if uid == '':
            # 1. 添加视频流到本地JSON文件
            uid = source_manager.add_source_stream(url, stream_id)
        # 2. 调用外部接口添加拉流代理
        response = add_stream_proxy(uid, url)
        if not response:
            return jsonify({"message": "代理服务连接失败"}), 500

        return jsonify({"streamid": uid}), 200

    except Exception as e:
        print(e)
        return jsonify({"message": str(e)}), 500


@app.route('/api/source-streams/<uid>', methods=['DELETE'])
def delete_source_stream(uid):
    """删除源视频流"""
    try:
        # 1. 删除本地 JSON 文件中的视频流
        success = source_manager.delete_source_stream(uid)
        if not success:
            return jsonify({"message": "Stream not found"}), 404

        # 2. 调用外部接口删除拉流代理
        response = del_stream_proxy(uid)
        if not response:
            return jsonify({"message": "Failed to delete stream proxy"}), 500

        return jsonify({"message": "Stream deleted successfully"}), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@app.route('/api/source-streams/<stream_id>', methods=['GET'])
def get_source_stream(stream_id):
    """获取单个源视频流的详情"""
    try:
        stream = source_manager.get_source_stream(stream_id)
        if stream is None:
            return jsonify({"message": "Stream not found"}), 404
        return jsonify(stream), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@app.route('/api/source-streams/<stream_id>', methods=['PUT'])
def update_source_stream(stream_id):
    """更新源视频流的 URL"""
    try:
        stream_url = request.json.get('streamurl')  # 获取视频流URL
        if not stream_url:
            return jsonify({"message": "streamurl is required"}), 400

        # 更新本地 JSON 文件中的视频流信息
        success = source_manager.update_source_stream(stream_id, stream_url)
        if not success:
            return jsonify({"message": "Stream not found"}), 404

        return jsonify({"message": "Stream updated successfully"}), 200
    except Exception as e:
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
        return jsonify({"message": str(e)}), 500

@app.route('/api/messages/fence/<fence_uid>', methods=['GET'])
def get_messages_by_fence(fence_uid):
    """获取绑定到指定围栏的所有告警信息"""
    try:
        messages = message_manager.get_messages_by_fence(fence_uid)
        return jsonify(messages), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500


# 主程序入口
if __name__ == '__main__':
    # 启动Flask应用
    app.run(debug=True, host='0.0.0.0', port=5000)
