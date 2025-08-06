# 导入第三方库和模块
from qwen_ai import call_qwen_via_client  # 导入Qwen AI的私有API调用模块
import requests  # HTTP请求库
import json  # JSON处理库
import hmac  # HMAC加密库
from datetime import datetime, timedelta  # 日期时间处理
import hashlib  # 哈希算法库
import base64  # Base64编码库
import urllib.parse  # URL解析库
from storage import StorageManager, AlertStorageManager, RecipientsManager  # 自定义存储管理模块
import cv2  # OpenCV图像处理库
import time  # 时间模块
import smtplib  # SMTP邮件协议库
from email.mime.text import MIMEText  # 邮件文本处理
from email.mime.multipart import MIMEMultipart  # 邮件多部分处理
from email.mime.application import MIMEApplication  # 邮件附件处理
from email.utils import formataddr  # 邮件地址格式化
from email.header import Header  # 邮件头处理
import os  # 操作系统接口
import urllib  # URL处理
import urllib.request  # URL请求
import numpy as np
from PIL import Image
import io
import matplotlib.pyplot as plt
import shutil
from storage import MessageManager

message_manager = MessageManager()

base_url = '10.30.3.178:5000'

def save_key_frames(frames, image_root='./images', base_url='x.x.x.x:5000'):
    """
    保存第一帧和最后一帧图像，并删除 ./images 下的旧文件夹（只保留当前时间戳文件夹）

    :param frames: 图像帧列表（OpenCV 格式 BGR）
    :param image_root: 图片保存的根目录
    :param base_url: 图片的 URL 路径前缀（用于生成浏览器可访问的路径）
    :return: 返回图片 URL 列表 [url1, url2]
    """
    now_time_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_dir = os.path.join(image_root, now_time_str)

    # 当前时间
    now = datetime.now()

    # 删除超过 7 天的旧文件夹
    if os.path.exists(image_root):
        for folder in os.listdir(image_root):
            folder_path = os.path.join(image_root, folder)

            # 检查是否是目录 + 是否符合时间戳格式
            if os.path.isdir(folder_path):
                try:
                    folder_time = datetime.strptime(folder, '%Y%m%d_%H%M%S')
                    if now - folder_time > timedelta(days=7):
                        shutil.rmtree(folder_path)
                except ValueError:
                    # 文件夹名不符合时间戳格式，忽略或可选择删除
                    continue

    # 创建保存目录
    os.makedirs(save_dir, exist_ok=True)

    # 保存第一帧和最后一帧
    urls = []
    for i, frame in enumerate([frames[0], frames[-1]]):
        filename = f'{i + 1}.jpg'
        filepath = os.path.join(save_dir, filename)

        # 转换为 RGB 并保存
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        plt.imshow(frame_rgb)
        plt.title(f'Frame {i + 1}')
        plt.axis('off')
        plt.savefig(filepath)
        plt.close()

        # 构造 URL（前提是 Flask 提供了 /images/<folder>/<filename> 路由）
        file_url = f'{base_url}/images/{now_time_str}/{filename}'
        urls.append(file_url)

    return urls


# 在报警分发时，给frame加上红色围栏标记
def draw_fence_on_frame(frame, fence_points):
    """
    在frame上绘制红色围栏（点和连线）
    fence_points: [(x1, y1), (x2, y2), ...] 电子围栏顶点像素坐标列表
    """
    if not fence_points or len(fence_points) < 3:
        return frame

    # 转成numpy数组方便绘制
    pts = np.array(fence_points, np.int32).reshape((-1, 1, 2))

    # 绘制多边形轮廓，红色，线宽2
    cv2.polylines(frame, [pts], isClosed=True, color=(0, 0, 255), thickness=2)

    # 绘制顶点为红色色小圆点
    for (x, y) in fence_points:
        cv2.circle(frame, (x, y), radius=4, color=(0, 0, 255), thickness=-1)

    return frame


def cv2_frame_to_base64(frame):
    # 转成 RGB
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb_frame)
    buffered = io.BytesIO()
    pil_img.save(buffered, format="JPEG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str


# MD5哈希函数
def md5(str):
    import hashlib
    m = hashlib.md5()  # 创建MD5哈希对象
    m.update(str.encode("utf8"))  # 更新哈希内容
    return m.hexdigest()  # 返回16进制哈希值


# 初始化存储管理器
storage = StorageManager()  # 流数据存储
alert_storage = AlertStorageManager()  # 报警配置存储
recipient_mgr = RecipientsManager()  # 接收人管理


# 邮件报警函数
def send_email_alert(message, contact_value, prev_image_path=None, curr_image_path=None):
    """
    发送邮件报警

    参数：
        message - 邮件正文（HTML格式字符串）
        contact_value - 收件人邮箱（字符串）
        prev_image_path - 报警前图像路径（可选）
        curr_image_path - 报警后图像路径（可选）
    """
    # 邮件配置
    subject = "🚨 视频报警通知"  # 邮件主题
    from_email = "576467179@qq.com"  # 发件邮箱
    auth_code = "mirozaqvewotbdci"  # 授权码

    # 创建邮件对象
    msg = MIMEMultipart()  # 多部分邮件
    msg['From'] = formataddr(("报警系统", from_email))  # 格式化发件人
    msg['To'] = contact_value  # 收件人
    msg['Subject'] = Header(subject, 'utf-8')  # 邮件主题

    # 添加HTML正文
    msg.attach(MIMEText(message.replace("\n", "<br>"), 'html', 'utf-8'))

    # 添加图片附件
    for img_path in [prev_image_path, curr_image_path]:
        if img_path and os.path.exists(img_path):  # 检查图片是否存在
            with open(img_path, 'rb') as f:  # 二进制读取图片
                part = MIMEApplication(f.read(), Name=os.path.basename(img_path))  # 创建附件
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(img_path)}"'  # 设置附件头
                msg.attach(part)  # 添加附件

    # 发送邮件
    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)  # QQ邮箱SMTP服务器
        server.login(from_email, auth_code)  # 登录
        server.sendmail(from_email, [contact_value], msg.as_string())  # 发送邮件
        server.quit()  # 退出
    except Exception as e:
        print("❌ 邮件发送失败:", e)  # 打印错误


# 保存报警图片函数
def save_alert_images(stream_id, fence_id, prev_frame, curr_frame, change_ratio):
    timestamp = int(time.time())  # 获取当前时间戳
    dir_path = f"alerts/{stream_id}/{timestamp}_{change_ratio:.2f}"  # 创建存储路径
    os.makedirs(dir_path, exist_ok=True)  # 创建目录
    prev_path = os.path.join(dir_path, "prev.jpg")  # 前帧图片路径
    curr_path = os.path.join(dir_path, "curr.jpg")  # 当前帧图片路径
    cv2.imwrite(prev_path, prev_frame)  # 保存前帧图片
    cv2.imwrite(curr_path, curr_frame)  # 保存当前帧图片
    return prev_path, curr_path  # 返回图片路径


# 钉钉报警函数
def send_dingding_alert(message, contact_value, prev_image_path=None, curr_image_path=None):
    """
    发送钉钉文本消息
    参数：
        message       - 要发送的消息内容（str）
        access_token  - 钉钉机器人 access_token
        secret        - 钉钉机器人安全设置的 secret
        retries       - 失败重试次数（默认 3）
        timeout       - 请求超时时间（默认 5秒）
    """
    retries = 3  # 重试次数
    timeout = 5  # 超时时间(秒)
    timestamp = str(round(time.time() * 1000))  # 当前时间戳(毫秒)
    contact_value_list = contact_value.replace(' ', '').split(',')  # 分割access_token和secret
    access_token = contact_value_list[0]  # 获取access_token
    secret = contact_value_list[1]  # 获取secret

    # 签名计算
    string_to_sign = f"{timestamp}\n{secret}"  # 签名字符串
    hmac_code = hmac.new(secret.encode('utf-8'), string_to_sign.encode('utf-8'),
                         hashlib.sha256).digest()  # HMAC-SHA256加密
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))  # Base64编码和URL编码

    # 构造webhook URL
    webhook_url = f"https://oapi.dingtalk.com/robot/send?access_token={access_token}&timestamp={timestamp}&sign={sign}"
    headers = {'Content-Type': 'application/json'}  # 请求头

    # 请求体
    payload = {
        "msgtype": "text",
        "text": {
            "content": message
        }
    }

    # 重试机制
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(webhook_url, headers=headers, data=json.dumps(payload), timeout=timeout)  # 发送POST请求
            if resp.status_code == 200:  # 成功响应
                return resp.status_code, resp.text
            else:
                raise Exception(f"状态码 {resp.status_code}，响应：{resp.text}")  # 抛出异常
        except Exception as e:
            if attempt == retries:  # 达到最大重试次数
                raise RuntimeError(f"[钉钉消息发送失败] 已重试 {retries} 次：{e}")
            time.sleep(2)  # 间隔2秒重试


# 短信报警函数
def send_sms_alert(message, contact_value, prev_image_path=None, curr_image_path=None):
    """
    发送短信报警
    参数：
        msg           - 短信内容字符串
        contact_value - 手机号字符串，多个手机号用逗号隔开
    """
    # 状态码映射
    statusStr = {
        '0': '短信发送成功',
        '-1': '参数不全',
        '-2': '服务器空间不支持',
        '30': '密码错误',
        '40': '账号不存在',
        '41': '余额不足',
        '42': '账户已过期',
        '43': 'IP地址限制',
        '50': '内容含有敏感词'
    }

    smsapi = "http://api.smsbao.com/"  # 短信API地址
    user = 'puyuanfeng'  # 账号
    password_plain = '152401'  # 明文密码
    password = md5(password_plain)  # MD5加密密码

    phones = [p.strip() for p in contact_value.split(',')]  # 分割多个手机号
    for phone in phones:
        data = urllib.parse.urlencode({'u': user, 'p': password, 'm': phone, 'c': message})  # URL编码参数
        send_url = smsapi + 'sms?' + data  # 构造请求URL

        try:
            response = urllib.request.urlopen(send_url, timeout=3)  # 发送请求
            result_code = response.read().decode('utf-8')  # 获取响应
            status_msg = statusStr.get(result_code, f'未知错误码 {result_code}')  # 获取状态信息
            if result_code == '0':  # 发送成功
                break
            else:
                raise RuntimeError(f"短信发送失败，手机号: {phone}，错误: {status_msg}")  # 抛出异常
        except Exception as e:
            print(f"发送短信失败，手机号: {phone}，错误: {e}")  # 打印错误


# 微信报警函数(待实现)
def send_wechat_alert(msg, prev_image_path=None, curr_image_path=None):
    pass


# 报警方法映射表
alert_method_map = {
    "dingding": lambda msg, contact_value, **kwargs: send_dingding_alert(msg, contact_value=contact_value, **kwargs),
    "sms": lambda msg, contact_value, **kwargs: send_sms_alert(msg, contact_value=contact_value, **kwargs),
    "wechat": lambda msg, contact_value, **kwargs: send_wechat_alert(msg, contact_value=contact_value, **kwargs),
    "email": lambda msg, contact_value, **kwargs: send_email_alert(msg, contact_value=contact_value, **kwargs),
}


# 报警分发函数 只有 changed == True 时给所有帧加对应围栏
def dispatch_alert_multi_frames(stream_id, fence_result, frames):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 当前时间格式化
    stream = storage.get_stream(stream_id)  # 获取流信息
    if not stream:  # 流不存在则返回
        return

    stream_name = stream.get("name", stream_id)  # 获取流名称
    templates = alert_storage.get_alert_templates()  # 获取报警模板
    recipients = recipient_mgr.get_recipients_by_stream_id(stream_id)  # 获取接收人列表
    if len(recipients) == 0:
        print('未绑定联系人')
    ratio = fence_result["change_ratio"]  # 变化比例
    fence_id = fence_result["fence_id"]  # 围栏ID

    # 在帧上画出该围栏的红色边界和点
    for frame in frames:
        points = fence_result.get("fence_points", [])
        if points:
            pts = np.array(points, np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame, [pts], isClosed=True, color=(0, 0, 255), thickness=2)
            for pt in points:
                cv2.circle(frame, pt, 5, (0, 0, 255), -1)

    # 调用AI识别
    base64_images = [cv2_frame_to_base64(f) for f in frames]  # frames_to_return 是 BGR numpy数组列表
    ai_report = call_qwen_via_client(base64_images)

    # 判断是否需要报警
    if ai_report['status'] == "正常":
        # 如果正常，不触发报警，释放帧内存
        print('一切正常')
        del frames
        return  # 不触发报警，结束函数

    # 保存或显示报警图片
    image_url = save_key_frames(frames, base_url=base_url)
    image_url_text = ', '.join(image_url)

    # 存入message.json
    message_manager.add_message(stream_uid=stream_id, fence_uid=fence_id, stream_name=stream_name,
                                change_ratio=f"{ratio:.2f}", ai_report=str(ai_report), image_before_url=image_url[0].replace(base_url, ""),
                                image_after_url=image_url[1].replace(base_url, ""))

    # 模板变量
    template_vars = {
        "stream_name": stream_name,
        "fence_id": fence_id,
        "timestamp": timestamp,
        "change_ratio": f"{ratio:.2f}",
        "ai_report": ai_report,
        "image_url": image_url_text
    }

    template = templates[0]  # 获取第一个模板
    message = ''
    try:
        message = template['text'].format(**template_vars)  # 渲染模板
        print(message)
    except Exception as e:
        print(f"[模板渲染失败] {e}")  # 模板渲染错误

    # 遍历接收人发送报警
    for recipient in recipients:
        contact = recipient.get("contact", {})  # 获取联系方式
        for method_name, contact_value in contact.items():
            if contact_value:  # 联系方式有效
                fn = alert_method_map.get(method_name.lower())  # 获取报警方法
                if fn:
                    try:
                        fn(  # 调用报警方法
                            message,
                            contact_value,
                            # prev_image_path=prev_image_path, TODO
                            # curr_image_path=curr_image_path TODO
                        )
                        print(f"✅ 已通过【{method_name}】发送给 {recipient['name']}")  # 成功日志
                    except Exception as e:
                        print(f"❌ 通过【{method_name}】发送失败：{e}")  # 失败日志


# 主程序入口
if __name__ == "__main__":
    stream_id = '06219170-867a-4ff7-96b5-5df12e641442'  # 测试流ID
    fence_result = {  # 测试围栏结果
        "change_ratio": 1,
        "fence_id": 0,
    }
    prev_frame = '1'  # 测试前帧
    curr_frame = '2'  # 测试当前帧
    send_sms_alert('这是一个测试', '13070206760', '1', '1')  # 测试短信发送
