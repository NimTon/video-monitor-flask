from flask import Flask
from flask_cors import CORS  # ✅ 导入 CORS

def create_app():
    app = Flask(__name__)
    CORS(app, supports_credentials=True)  # ✅ 允许所有来源跨域，含Cookie

    app.video_results = {}

    return app
