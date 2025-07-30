## 模块名称

后端服务入口模块 `app.py`

## 模块定位

该模块是整个系统的后端 HTTP 接口服务的主入口，基于 Flask 框架实现，负责接收前端请求并路由到各子模块完成处理。它集成了视频流控制、电子围栏配置、报警管理、联系人管理等核心功能，协调系统中各模块之间的协作。

## 技术栈与依赖

* Python 3.x
* Flask（Web 框架）
* OpenCV（用于初始化流信息）
* 多线程（用于管理视频检测线程）
* 自定义模块：`video_monitor.video_stream`、`storage`、`alert_dispatcher`

## 输入与输出

### 输入：

* 前端 HTTP 请求（通过 Vue 页面发起）
* 请求体 JSON 数据（如添加视频流、添加围栏等）

### 输出：

* JSON 响应体（包含操作结果、错误提示等）
* 调用 `VideoStreamThread` 实时检测视频变化
* 调用 `dispatch_alert_multi_frames` 分发报警

## 核心功能与逻辑说明

该模块的功能可分为以下几个部分：

### 1. 系统健康检查

* `/api/welcome` 返回服务器正常运行状态。

### 2. 视频流管理

* 支持添加、查询、删除、更新视频流信息。
* 自动判断视频流唯一性，生成 stream\_uid。

### 3. 视频流运行控制

* `/start` 启动视频检测线程：

  * 打开视频流验证有效性
  * 读取帧尺寸并转化电子围栏相对坐标为像素坐标
  * 初始化 `VideoStreamThread` 线程，设置围栏与检测参数
* `/stop` 停止视频检测线程并清理引用

### 4. 电子围栏管理

* 添加、更新、删除和列出指定视频流的围栏区域
* 电子围栏为多边形，由 3 个及以上点组成，坐标为相对值（0-1）

### 5. 联系人管理

* 新增、查询、修改、删除联系人
* 支持联系人与视频流的绑定与解绑
* 每个联系人支持多路流接收

### 6. 报警模板管理

* 支持添加和更新报警模板，用于动态生成报警消息

### 7. 查询绑定关系

* 查询某视频流的所有接收人，或某联系人对应的视频流

### 8. 报警回调逻辑（内部函数）

```python
# callback 中调用 dispatch_alert_multi_frames
# 将 sid + frames + 检测结果 一起提交
```

## 配置说明

该模块本身无独立配置项，依赖于 `video_fences.json`, `alerts.json`, `recipients.json` 等存储内容。

部分重要参数由视频流配置携带：

* `threshold`: 判断围栏变化的灵敏度（0.1\~1）
* `frequency`: 多久检测一次（秒）

## 与其他模块的交互

* 调用 `VideoStreamThread` 进行视频帧提取与变化检测（video\_stream.py）
* 调用 `dispatch_alert_multi_frames` 进行报警（alert\_dispatcher.py）
* 通过 `StorageManager`、`RecipientsManager` 读写 JSON 文件（storage.py）
* 与前端 `MonitorView.vue`、`BindingView.vue`、`RecipientsView.vue` 等页面通信

## 调试建议

运行测试：

```bash
python app.py
```

或使用 gunicorn:

```bash
gunicorn app:app --bind 0.0.0.0:5000 --workers 1
```

查看控制台输出验证接口响应，推荐配合 Postman 调试。

## 注意事项

* 启动流前必须先配置电子围栏，否则将拒绝启动。
* 删除视频流时必须停止线程并解绑所有关联联系人。
* 所有坐标为相对值，需在读取帧尺寸后再转换。
* 注意使用 `.get()` 安全获取 JSON 字段，避免空值错误。

## 后续扩展建议

* 增加用户鉴权功能，如 token 验证
* 添加 WebSocket 推送报警状态回前端
* 结合数据库替代 JSON 文件持久化
