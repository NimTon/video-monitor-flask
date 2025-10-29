import os
import smtplib
import time
import hmac
import hashlib
import base64
import urllib
import urllib.request
import json
import requests
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from config import AUTH_CODE, FROM_EMAIL
from utils.utils import md5
from utils.log_utils import log


# 钉钉报警函数
def send_dingding_alert(message, contact_value, attachments=None):
    retries = 3
    timeout = 5
    timestamp = str(round(time.time() * 1000))
    access_token, secret = contact_value.replace(' ', '').split(',')

    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    webhook_url = f"https://oapi.dingtalk.com/robot/send?access_token={access_token}&timestamp={timestamp}&sign={sign}"
    headers = {"Content-Type": "application/json"}

    # 如果有 attachments，把它们作为 Markdown 链接拼到消息里
    content = message
    if attachments:
        for path in attachments:
            content += f"\n[{os.path.basename(path)}]({path})"

    payload = {"msgtype": "text", "text": {"content": content}}

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(webhook_url, headers=headers, data=json.dumps(payload), timeout=timeout)
            if resp.status_code == 200:
                return True
            else:
                raise RuntimeError(f"钉钉发送失败，状态码 {resp.status_code}，响应: {resp.text}")
        except Exception as e:
            if attempt == retries:
                raise RuntimeError(f"钉钉发送失败，已重试 {retries} 次，错误: {e}")
            time.sleep(2)


# 短信报警函数
def send_sms_alert(message, contact_value, attachments=None):
    statusStr = {
        '0': '短信发送成功', '-1': '参数不全', '-2': '服务器空间不支持',
        '30': '密码错误', '40': '账号不存在', '41': '余额不足',
        '42': '账户已过期', '43': 'IP地址限制', '50': '内容含有敏感词'
    }
    smsapi = "http://api.smsbao.com/"
    user = 'puyuanfeng'
    password = md5('152401')

    # 如果有 attachments，把路径或 URL 拼到消息里
    if attachments:
        for path in attachments:
            message += f"\n{path}"

    phones = [p.strip() for p in contact_value.split(',')]
    for phone in phones:
        data = urllib.parse.urlencode({'u': user, 'p': password, 'm': phone, 'c': message})
        send_url = smsapi + 'sms?' + data
        try:
            response = urllib.request.urlopen(send_url, timeout=3)
            result_code = response.read().decode('utf-8')
            if result_code == '0':
                return True
            else:
                raise RuntimeError(f"短信发送失败，手机号: {phone}，错误: {statusStr.get(result_code, result_code)}")
        except Exception as e:
            raise RuntimeError(f"短信发送异常，手机号: {phone}，错误: {e}")


# 微信报警函数（待实现）
def send_wechat_alert(message, contact_value=None, attachments=None):
    raise RuntimeError("微信报警尚未实现")


# 邮件报警函数
def send_email_alert(message, contact_value="576467179@qq.com", attachments=None, subject="视频报警通知"):
    from_email = "576467179@qq.com"
    auth_code = AUTH_CODE

    msg = MIMEMultipart()
    msg['From'] = formataddr(("报警系统", from_email))
    msg['To'] = contact_value
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(message.replace("\n", "<br>"), 'html', 'utf-8'))

    # 附件
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
        return True
    except Exception as e:
        raise RuntimeError(f"邮件发送失败: {contact_value}, 错误: {e}")


# 通用报警入口
def send_alert(method_name, contact_value, message, attachments=None):
    method_name = method_name.lower().strip()
    if method_name == "dingding":
        return send_dingding_alert(message, contact_value, attachments)
    elif method_name == "sms":
        return send_sms_alert(message, contact_value, attachments)
    elif method_name == "wechat":
        return send_wechat_alert(message, contact_value, attachments)
    elif method_name == "email":
        return send_email_alert(message, contact_value, attachments)
    else:
        raise ValueError(f"不支持的报警方式: {method_name}")


class EmailAlert:
    def __init__(self, from_email, auth_code, smtp_server="smtp.qq.com", smtp_port=465):
        """
        初始化邮件发送类，并登录邮箱
        :param from_email: 发件人邮箱
        :param auth_code: 邮箱授权码
        :param smtp_server: SMTP服务器地址
        :param smtp_port: SMTP服务器端口
        """
        self.from_email = from_email
        self.auth_code = auth_code
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port

        try:
            self.server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            self.server.login(self.from_email, self.auth_code)
        except Exception as e:
            raise RuntimeError(f"邮件服务器登录失败: {e}")

    def send_email(self, message, to_email=FROM_EMAIL, attachments=None, subject="视频报警通知"):
        """
        发送邮件
        :param message: 邮件正文
        :param to_email: 收件人邮箱
        :param attachments: 附件列表
        :param subject: 邮件主题
        """
        msg = MIMEMultipart()
        msg['From'] = formataddr(("报警系统", self.from_email))
        msg['To'] = to_email
        msg['Subject'] = Header(subject, 'utf-8')
        msg.attach(MIMEText(message.replace("\n", "<br>"), 'html', 'utf-8'))

        # 添加附件
        if attachments:
            for file_path in attachments:
                if file_path and os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        part = MIMEApplication(f.read(), Name=os.path.basename(file_path))
                        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
                        msg.attach(part)

        try:
            self.server.sendmail(self.from_email, [to_email], msg.as_string())
            return True
        except Exception as e:
            raise RuntimeError(f"邮件发送失败: {to_email}, 错误: {e}")

    def close(self):
        """关闭SMTP连接"""
        self.server.quit()
