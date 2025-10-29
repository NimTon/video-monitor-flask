from config import AUTH_CODE, FROM_EMAIL
from utils.alert_utils import EmailAlert

email_alert = EmailAlert(from_email=FROM_EMAIL, auth_code=AUTH_CODE)