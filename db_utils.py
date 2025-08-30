import sqlite3
from contextlib import contextmanager
import json
from datetime import datetime

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)

db_path = config.get("db_path")

class DBHelper:
    def __init__(self, db_path=db_path):
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        """初始化表结构"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS video_frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_uid TEXT,
                fence_uid TEXT,
                group_id TEXT,
                timestamp TEXT,
                frame_path TEXT,
                detect_status TEXT DEFAULT 'pending', -- pending / normal / abnormal
                merge_status TEXT DEFAULT 'pending'   -- pending / merged
            );
            """)
            conn.commit()

    def insert_frame(self, stream_uid, fence_uid, group_id, timestamp, frame_path):
        """插入新帧"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO video_frames (stream_uid, fence_uid, group_id, timestamp, frame_path)
            VALUES (?, ?, ?, ?, ?);
            """, (stream_uid, fence_uid, group_id, timestamp.isoformat(), frame_path))
            conn.commit()
            return cur.lastrowid

    def update_detect_status(self, frame_id, status):
        """更新检测状态"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE video_frames SET detect_status=? WHERE id=?;", (status, frame_id))
            conn.commit()

    def update_merge_status(self, frame_id, status):
        """更新合成状态"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE video_frames SET merge_status=? WHERE id=?;", (status, frame_id))
            conn.commit()

    def get_pending_frames(self, limit=10):
        """获取待检测的帧"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM video_frames WHERE detect_status='pending' ORDER BY timestamp ASC LIMIT ?;", (limit,))
            rows = [dict(row) for row in cur.fetchall()]
            return rows

    def get_abnormal_groups(self, group_id):
        """查询某个 group 下的异常帧"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM video_frames WHERE group_id=? AND detect_status='abnormal';", (group_id,))
            rows = [dict(row) for row in cur.fetchall()]
            return rows

    def delete_frame(self, frame_id):
        """删除某一帧"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM video_frames WHERE id=?;", (frame_id,))
            conn.commit()
