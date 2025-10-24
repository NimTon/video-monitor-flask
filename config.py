import json
# FLOW_URL = "https://jrlyy.fusionfintrade.com:39100"  # 华为云转流服务
FLOW_URL = "http://1.94.137.200:5001"   # 华为云转流服务
BASE_URL = "http://1.94.137.200:5000" # 华为云基础服务

# FLOW_URL = "http://10.30.3.178:5001"  # 公司转流服务
# BASE_URL = "http://10.30.3.178:5000" # 公司基础服务

LOCAL_AI_IMAGES_URL = "http://103.25.65.102:15800/api/sayImages"
LOCAL_AI_VIDEO_URL = "http://103.25.65.102:15800/api/sayVideo"
LOCAL_AI_TEXT_URL = "http://103.25.65.102:15800/api/sayMsg"

QWEN_API_KEY = "sk-f3ec150157ec41baaa516b15d1feaeae"
QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

DB_PATH = "video_db.sqlite"


with open('prompts.json', encoding='utf-8') as f:
    PROMPTS = json.load(f)
