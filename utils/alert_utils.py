# 钉钉报警函数
import os
import smtplib
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from utils.utils import md5, log
import time
import hmac  # HMAC加密库
import hashlib  # 哈希算法库
import base64  # Base64编码库
import urllib  # URL处理
import urllib.request  # URL请求
import json
import requests


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


def send_email_alert(message, contact_value, attachments=None, subject="视频报警通知"):
    from_email = "576467179@qq.com"
    auth_code = "mirozaqvewotbdci"
    msg = MIMEMultipart()
    msg['From'] = formataddr(("报警系统", from_email))
    msg['To'] = contact_value
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(message.replace("\n", "<br>"), 'html', 'utf-8'))
    if attachments:
        for file_path in attachments:
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(file_path))
                    part['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
                    msg.attach(part)
    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(from_email, auth_code)
        server.sendmail(from_email, [contact_value], msg.as_string())
        server.quit()
        log("SUCCESS", f"邮件发送成功: {contact_value}")
        return True
    except Exception as e:
        log("FAIL", f"邮件发送失败: {contact_value}, 错误: {e}")
        return False
