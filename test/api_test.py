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
        file_id = zk_api.upload_byte_file_with_apikey("test_file.pdf")
        print("upload_byte_file_with_apikey 成功:", file_id)
    except ZhongkaiAPIError as e:
        print("upload_byte_file_with_apikey 失败:", e, getattr(e, "response", None))

def test_query_and_push_assets():
    print("==== 测试 query_and_push_assets ====")
    try:
        assets = zk_api.query_and_push_assets(
            hj_device_no="DEV001",
            hj_service_no="SERVICE_001",
            video_play_url="http://example.com/live",
            scene_code="SCENE001"
        )
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
            patrol_result="正常",
            report_id=123,
            scene_code="SCENE001",
            loan_no="LOAN20240919001",
            asset_detail='[{"assetNo":"AST001","commodityList":[{"commodityCode":"CMD001","comodityName":"钢材"}]}]',
            video_files="video_123456"
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
            event_img_file_id="img_123456",
            event_video_file_id="video_123456",
            wh_code="WH001",
            wh_name="北京仓库",
            loan_no="LOAN20240919001",
            asset_detail='[{"assetNo":"AST001","commodityList":[{"commodityCode":"CMD001","comodityName":"钢材"}]}]'
        )
        print("push_iot_event 成功:", iot_event)
    except ZhongkaiAPIError as e:
        print("push_iot_event 失败:", e, getattr(e, "response", None))


if __name__ == "__main__":
    test_get_devices()
    test_get_live_url()
    test_upload_byte_file_with_apikey()
    test_query_and_push_assets()
    test_patrol_record()
    test_push_iot_event()
