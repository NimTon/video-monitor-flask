import sqlite3
from contextlib import contextmanager
import json
from datetime import datetime

with open('config.json', encoding='utf-8') as f:
    config = json.load(f)

db_path = config.get("db_path", "video_monitor.db")


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

            # 抓帧表
            cur.execute("""
            CREATE TABLE IF NOT EXISTS captured_frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_uid TEXT,
                group_uid TEXT,
                timestamp TEXT,
                frame_path TEXT
            );
            """)

            # 异常检测表
            cur.execute("""
            CREATE TABLE IF NOT EXISTS fence_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_uid TEXT,
                group_uid TEXT,
                fence_uid TEXT,
                change_ratio REAL,
                changed INTEGER, -- 0=normal,1=abnormal
                timestamp TEXT,
                frame_path TEXT,
                frame_id INTEGER,
                exported INTEGER DEFAULT 0 -- 0=未导出, 1=已导出
            );
            """)

            # 视频合成表
            cur.execute("""
            CREATE TABLE IF NOT EXISTS merged_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_uid TEXT,
                group_uid TEXT,
                fence_uid TEXT,
                video_path TEXT,
                duration REAL, -- 秒
                size INTEGER,  -- 字节
                timestamp TEXT
            );
            """)

            conn.commit()

    # ------------------ 抓帧表操作 ------------------
    def insert_frame(self, stream_uid, group_uid, timestamp, frame_path):
        """插入抓帧表"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO captured_frames (stream_uid, group_uid, timestamp, frame_path)
            VALUES (?, ?, ?, ?);
            """, (stream_uid, group_uid, timestamp.isoformat(), frame_path))
            conn.commit()
            return cur.lastrowid

    def get_pending_frames(self, limit=10):
        """获取最近抓取的帧，用于异常检测"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT * FROM captured_frames
            ORDER BY timestamp ASC
            LIMIT ?;
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def get_group_frames(self, group_uid):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT * FROM captured_frames
            WHERE GROUP_UID=?
            ORDER BY timestamp ASC;
            """, (group_uid,))
            return [dict(row) for row in cur.fetchall()]

    def get_frames_by_stream_and_time(self, stream_uid, start_ts, end_ts):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM captured_frames
                WHERE stream_uid=?
                AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC;
            """, (stream_uid, start_ts.isoformat(), end_ts.isoformat()))
            return [dict(row) for row in cur.fetchall()]


    # ------------------ 异常检测表操作 ------------------
    def get_pending_exports(self, group_uid=None):
        with self.get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM fence_detections WHERE exported=0"
            params = []
            if group_uid:
                query += " AND group_uid=?"
                params.append(group_uid)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def mark_as_exported(self, detection_ids):
        """将指定检测记录标记为已导出"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"""
            UPDATE fence_detections
            SET exported=1
            WHERE id IN ({','.join('?' for _ in detection_ids)})
            """, detection_ids)
            conn.commit()

    def insert_detection(self, stream_uid, group_uid, fence_uid, change_ratio, changed, timestamp, frame_path, frame_id, exported=False):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO fence_detections 
            (stream_uid, group_uid, fence_uid, change_ratio, changed, timestamp, frame_path, frame_id, exported)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (stream_uid, group_uid, fence_uid, change_ratio, int(changed), timestamp.isoformat(), frame_path, frame_id, int(exported)))
            conn.commit()
            return cur.lastrowid

    def get_detections(self, stream_uid=None, group_uid=None, fence_uid=None):
        """获取异常检测结果"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM fence_detections WHERE 1=1"
            params = []
            if stream_uid:
                query += " AND stream_uid=?"
                params.append(stream_uid)
            if group_uid:
                query += " AND group_uid=?"
                params.append(group_uid)
            if fence_uid:
                query += " AND fence_uid=?"
                params.append(fence_uid)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    # ------------------ 视频合成表操作 ------------------
    def insert_merged_video(self, stream_uid, group_uid, fence_uid, video_path, duration, size, timestamp):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO merged_videos
            (stream_uid, group_uid, fence_uid, video_path, duration, size, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (stream_uid, group_uid, fence_uid, video_path, duration, size, timestamp.isoformat()))
            conn.commit()
            return cur.lastrowid

    # ------------------ 获取某个组下的所有检测数据 ------------------
    def get_detect_data_by_group(self, group_uid):
        """根据 group_uid 获取所有检测数据"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            SELECT stream_uid, group_uid, fence_uid, change_ratio, changed, timestamp, frame_path
            FROM fence_detections 
            WHERE group_uid=?;
            """, (group_uid,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
