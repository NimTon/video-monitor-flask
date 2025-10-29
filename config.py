import json
# FLOW_URL = "https://jrlyy.fusionfintrade.com:39100"  # 华为云转流服务
# FLOW_URL = "http://1.94.137.200:5001"   # 华为云转流服务
# BASE_URL = "http://1.94.137.200:5000" # 华为云基础服务

FLOW_URL = "http://10.30.3.178:5001"  # 公司转流服务
BASE_URL = "http://10.30.3.178:5000" # 公司基础服务

# LOCAL_AI_IMAGES_URL = "http://103.25.65.102:15800/api/sayImages"  #华为云调用本地模型公网映射地址
# LOCAL_AI_VIDEO_URL = "http://103.25.65.102:15800/api/sayVideo"   #华为云调用本地模型公网映射地址
# LOCAL_AI_TEXT_URL = "http://103.25.65.102:15800/api/sayMsg"     #华为云调用本地模型公网映射地址

LOCAL_AI_IMAGES_URL = "http://10.30.4.50:5800/api/sayImages"  #本地模型接口地址
LOCAL_AI_VIDEO_URL = "http://10.30.4.50:5800/api/sayVideo"   #本地模型接口地址
LOCAL_AI_TEXT_URL = "http://10.30.4.50:5800/api/sayMsg"     #本地模型接口地址

QWEN_API_KEY = "sk-f3ec150157ec41baaa516b15d1feaeae"
QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

DB_PATH = "video_db.sqlite"

AUTH_CODE = "eynbzlkuuwrqbbed"

with open('prompts.json', encoding='utf-8') as f:
    PROMPTS = json.load(f)
