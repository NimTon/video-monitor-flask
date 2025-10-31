from config import AUTH_CODE, FROM_EMAIL
from utils.alert_utils import EmailAlert
from utils.ai_utils import AIModelManager

email_alert = EmailAlert(from_email=FROM_EMAIL, auth_code=AUTH_CODE)
ai_manager = AIModelManager()