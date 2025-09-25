import datetime
from emergency.utils.api_utils import zk_api, ZhongkaiAPIError

def test_get_devices():
    print("==== 测试 get_devices ====")
    try:
        devices = zk_api.get_devices("MACHINE_001")
        print("get_devices 成功:", devices)
    except ZhongkaiAPIError as e:
        print("get_devices 失败:", e, getattr(e, "response", None))

def test_get_live_url():
    print("==== 测试 get_live_url ====")
    try:
        live_url = zk_api.get_live_url("SOURCE_001", "SERVICE_001", "DEV001")
        print("get_live_url 成功:", live_url)
    except ZhongkaiAPIError as e:
        print("get_live_url 失败:", e, getattr(e, "response", None))

def test_upload_byte_file_with_apikey():
    print("==== 测试 upload_byte_file_with_apikey ====")
    try:
        file_id = zk_api.upload_byte_file_with_apikey("test_file.txt")  # 替换成本地文件
        print("upload_byte_file_with_apikey 成功:", file_id)
    except ZhongkaiAPIError as e:
        print("upload_byte_file_with_apikey 失败:", e, getattr(e, "response", None))

def test_query_and_push_assets():
    print("==== 测试 query_and_push_assets ====")
    try:
        assets = zk_api.query_and_push_assets("DEV001", "SERVICE_001", "http://example.com/live", "SCENE001")
        print("query_and_push_assets 成功:", assets)
    except ZhongkaiAPIError as e:
        print("query_and_push_assets 失败:", e, getattr(e, "response", None))

def test_patrol_record():
    print("==== 测试 patrol_record ====")
    try:
        patrol = zk_api.patrol_record(
            wh_code="WH001",
            wh_name="北京仓库",
            patrol_person="张三",
            patrol_date=datetime.date.today().strftime("%Y-%m-%d"),
            patrol_result="正常"
        )
        print("patrol_record 成功:", patrol)
    except ZhongkaiAPIError as e:
        print("patrol_record 失败:", e, getattr(e, "response", None))

def test_push_iot_event():
    print("==== 测试 push_iot_event ====")
    try:
        iot_event = zk_api.push_iot_event(
            hj_device_no="DEV001",
            hj_service_no="SVC001",
            event_type="5",
            event_date=datetime.date.today().strftime("%Y-%m-%d"),
            event_msg="测试事件",
            event_img_file_id=None,
            event_video_file_id=None,
            wh_code="WH001",
            wh_name="北京仓库"
        )
        print("push_iot_event 成功:", iot_event)
    except ZhongkaiAPIError as e:
        print("push_iot_event 失败:", e, getattr(e, "response", None))


if __name__ == "__main__":
    # 你可以单独注释掉不需要测试的函数
    test_get_devices()
    test_get_live_url()
    test_upload_byte_file_with_apikey()
    test_query_and_push_assets()
    test_patrol_record()
    test_push_iot_event()
