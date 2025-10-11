# 获取设备列表接口地址
URL_GET_DEVICES = "https://openapi.zhongkaixingye.com/openapi/lot/ai/devices" #生产环境
# URL_GET_DEVICES = "https://openapisit.zhongkaixingye.com/openapi/lot/ai/devices" # 测试环境

# 获取视频直播流地址接口
URL_GET_LIVE_URL = "https://openapi.zhongkaixingye.com/openapi/lot/ai/video/url"

# 文件上传接口（测试环境）
URL_UPLOAD_FILE = "https://openapisit.zhongkaixingye.com/openapi/lot/ai/file/upload"

# 事件上报接口（测试环境）
URL_EVENT_UP_TEST = "https://openapisit.zhongkaixingye.com/openapi/lot/ai/event/up"

# 事件上报接口（正式环境）
# URL_EVENT_UP = "http://103.25.65.102:9020/asset/iotDeviceEvent/hj/cameraEvent/create"  测试环境
URL_EVENT_UP = "http://122.112.132.10:19020/asset/iotDeviceEvent/hj/cameraEvent/create"  #生产环境
# 资产与设备关系查询接口
# URL_QUERY_AND_PUSH_ASSETS = "http://103.25.65.102:9020/asset/assetDeviceRela/hj/queryRela"  测试环境
URL_QUERY_AND_PUSH_ASSETS = "http://122.112.132.10:19020/asset/assetDeviceRela/hj/queryRela"  #生产环境

# 文件上传接口（正式环境，二进制流方式，支持 APIKEY）
# URL_UPLOAD_BYTE_FILE = "http://103.25.65.102:9020/sps/comm/file/uploadBase64FileWithApikey"  测试环境
URL_UPLOAD_BYTE_FILE = "http://122.112.132.10:19020/sps/comm/file/uploadBase64FileWithApikey"   #生产环境
# 巡库记录上报接口（正式环境）
# URL_PATROL_RECORD = "http://103.25.65.102:9020/shareop/share-event/patrolRecord"   测试环境
URL_PATROL_RECORD = "http://122.112.132.10:19020/shareop/share-event/patrolRecord"    #生产环境
# 访问平台的 token（类似 session key，用于验证身份）
ZK_TOKEN = "FZK865AI9184C4A66"

# 设备编号列表，可以用来批量请求多个设备
MACHINE_CODES = ["1", "2"]

# 可能用于 AI 提示词（目前为空，可以在调用大模型时填充）
PROMPT = ""

# API 访问密钥（和 token 搭配使用，用于身份校验）
API_KEY = "k8#Pm@3q!W9"

# 数据来源标识（企业或系统唯一标识代码）
X_Data_Source = "91370000698086271U"
