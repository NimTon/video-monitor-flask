import sqlite3
from contextlib import contextmanager
from config import DB_PATH


class DBHelper:
    def __init__(self, db_path=DB_PATH):
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
                        CREATE TABLE IF NOT EXISTS captured_frames
                        (
                            id         INTEGER PRIMARY KEY AUTOINCREMENT,
                            stream_uid TEXT,
                            group_uid  TEXT,
                            timestamp  TEXT,
                            frame_path TEXT
                        );
                        """)

            # 异常检测表
            cur.execute("""
                        CREATE TABLE IF NOT EXISTS fence_detections 
                        (
                            id               INTEGER PRIMARY KEY AUTOINCREMENT,
                            stream_uid       TEXT,
                            group_uid        TEXT,
                            fence_uid        TEXT,
                            change_ratio     REAL,
                            changed          INTEGER,              -- 0=normal,1=abnormal
                            timestamp        TEXT,
                            frame_path       TEXT,
                            frame_id         INTEGER,
                            exported         INTEGER DEFAULT 0,    -- 0=未导出, 1=已导出
                            ai_checked       INTEGER DEFAULT 0,
                            ai_status        INTEGER DEFAULT NULL, -- 0=normal,1=AI判定异常,-1=失败
                            ai_result        TEXT    DEFAULT NULL,
                            alerted          INTEGER DEFAULT 0,
                            event_uid        TEXT,                 -- 事件ID (UUID)
                            group_event_uid  TEXT,
                            before_image_path TEXT   DEFAULT NULL, -- 新增：前一帧图像路径
                            after_image_path  TEXT   DEFAULT NULL, -- 新增：后一帧图像路径
                            alert_video_path TEXT    DEFAULT NULL
                        );
                        """)

            # 视频合成表
            cur.execute("""
                        CREATE TABLE IF NOT EXISTS merged_videos
                        (
                            id              INTEGER PRIMARY KEY AUTOINCREMENT,
                            stream_uid      TEXT,
                            group_uid       TEXT,
                            fence_uid       TEXT,
                            video_path      TEXT,
                            duration        REAL,    -- 秒
                            size            INTEGER, -- 字节
                            timestamp       TEXT,
                            event_uid       TEXT,    -- 事件ID (UUID)
                            group_event_uid TEXT,
                            alerted          INTEGER DEFAULT 0
                        );
                        """)

            # 预警事件表
            # cur.execute("""
            #             CREATE TABLE IF NOT EXISTS events
            #             (
            #                 id                INTEGER PRIMARY KEY AUTOINCREMENT,
            #                 event_uid         TEXT UNIQUE,
            #                 group_event_id    TEXT,
            #                 group_uid         TEXT,
            #                 stream_uid        TEXT,
            #                 fence_uid         TEXT,
            #                 stream_name       TEXT,
            #                 timestamp         TEXT,
            #                 change_ratio      TEXT,
            #                 alerted           INTEGER DEFAULT 0,
            #                 ai_checked        INTEGER DEFAULT 0,
            #                 ai_report         TEXT,
            #                 image_before_url  TEXT,
            #                 image_after_url   TEXT,
            #                 image_before_path TEXT,
            #                 image_after_path  TEXT,
            #                 videourl          TEXT,
            #                 videopath         TEXT
            #             );
            #             """)

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
                        SELECT *
                        FROM captured_frames
                        ORDER BY timestamp ASC
                        LIMIT ?;
                        """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def get_group_frames(self, group_uid):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM captured_frames
                        WHERE GROUP_UID = ?
                        ORDER BY timestamp ASC;
                        """, (group_uid,))
            return [dict(row) for row in cur.fetchall()]

    def get_frames_by_stream_and_time(self, stream_uid, start_ts, end_ts):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM captured_frames
                        WHERE stream_uid = ?
                          AND timestamp BETWEEN ? AND ?
                        ORDER BY timestamp ASC;
                        """, (stream_uid, start_ts.isoformat(), end_ts.isoformat()))
            return [dict(row) for row in cur.fetchall()]

    # ------------------ 异常检测表操作 ------------------
    def update_alerted(self, detection_id, alerted=1):
        """
        更新指定检测记录的 alerted 状态为 True
        :param detection_id: 检测记录 ID
        :param alerted: 是否已报警，默认 1（True）
        :return: 更新的行数
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE fence_detections
                SET alerted = ?
                WHERE id = ?;
            """, (int(alerted), detection_id))
            conn.commit()
            return cur.rowcount  # 返回更新的行数

    def update_ai_result(
            self,
            detection_id,
            ai_checked=1,
            ai_status=None,
            ai_result=None,
            before_image_path=None,
            after_image_path=None,
            alert_video_path=None
    ):
        """
        更新指定检测记录的 AI 识别结果
        :param detection_id: 检测记录 ID
        :param ai_checked: 是否已 AI 识别，默认 1
        :param ai_status: AI 判断状态，1=异常, 0=正常, -1=失败
        :param ai_result: AI 识别结果（文本）
        :param before_image_path: 前一帧图像路径
        :param after_image_path: 后一帧图像路径
        :param alert_video_path: 回溯视频路径
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE fence_detections
                SET ai_checked=?,
                    ai_result=?,
                    ai_status=?,
                    before_image_path=?,
                    after_image_path=?,
                    alert_video_path=?
                WHERE id=?;
            """, (
                int(ai_checked),
                ai_result,
                int(ai_status) if ai_status is not None else None,
                before_image_path,
                after_image_path,
                alert_video_path,
                detection_id
            ))
            conn.commit()
            return cur.rowcount  # 返回更新的行数

    def get_detected_frames_by_stream_and_time(self, stream_uid, fence_uid, start_ts, end_ts):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM fence_detections
                        WHERE stream_uid = ?
                          AND fence_uid = ?
                          AND timestamp BETWEEN ? AND ?
                        ORDER BY timestamp ASC;
                        """, (stream_uid, fence_uid, start_ts.isoformat(), end_ts.isoformat()))
            return [dict(row) for row in cur.fetchall()]

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

    def mark_as_exported(self, detection_ids, event_uid, group_event_uid):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"""
        UPDATE fence_detections
        SET exported=1,
            event_uid=?,
            group_event_uid=?
        WHERE id IN ({','.join('?' for _ in detection_ids)})
        """, [event_uid, group_event_uid] + detection_ids)
            conn.commit()
            return event_uid, group_event_uid

    def insert_detection(
            self,
            stream_uid,
            group_uid,
            fence_uid,
            change_ratio,
            changed,
            timestamp,
            frame_path,
            frame_id,
            exported=False,
            event_uid=None,
            group_event_uid=None,
            ai_checked=False,
            ai_status=None,
            ai_result=None,
            alerted=False,
            before_image_path=None,
            after_image_path=None,
            alert_video_path=None,
    ):
        """
        插入一条检测记录
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO fence_detections
                (stream_uid, group_uid, fence_uid, change_ratio, changed, timestamp,
                 frame_path, frame_id, exported, event_uid, group_event_uid,
                 ai_checked, ai_status, ai_result, alerted,
                 before_image_path, after_image_path, alert_video_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                stream_uid,
                group_uid,
                fence_uid,
                change_ratio,
                int(changed),
                timestamp.isoformat(),
                frame_path,
                frame_id,
                int(exported),
                event_uid,
                group_event_uid,
                int(ai_checked),
                int(ai_status) if ai_status is not None else None,
                ai_result,
                int(alerted),
                before_image_path,
                after_image_path,
                alert_video_path
            ))
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

    def mark_as_alerted(self, detection_ids):
        """将指定检测记录标记为已报警"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"""
            UPDATE fence_detections
            SET alerted=1
            WHERE id IN ({','.join('?' for _ in detection_ids)})
            """, detection_ids)
            conn.commit()

    def get_pending_alerts(self, group_uid=None):
        """
        获取未报警的异常检测记录。
        :param group_uid: 可选，指定组
        :return: 未报警的记录列表
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM fence_detections WHERE changed=1 AND alerted=0"
            params = []
            if group_uid:
                query += " AND group_uid=?"
                params.append(group_uid)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def get_pending_ai_checked(self, group_uid=None):
        """
        获取未AI识别的异常检测记录。
        :param group_uid: 可选，指定组
        :return: 未报警的记录列表
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM fence_detections WHERE changed=1 AND ai_checked=0"
            params = []
            if group_uid:
                query += " AND group_uid=?"
                params.append(group_uid)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    # ------------------ 视频合成表操作 ------------------
    def insert_merged_video(self, stream_uid, group_uid, fence_uid, video_path, duration, size, timestamp, event_uid, group_event_uid):
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        INSERT INTO merged_videos
                        (stream_uid, group_uid, fence_uid, video_path, duration, size, timestamp, event_uid, group_event_uid)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (stream_uid, group_uid, fence_uid, video_path, duration, size, timestamp.isoformat(), event_uid, group_event_uid))
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
                        WHERE group_uid = ?;
                        """, (group_uid,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    # ------------------ 更新alerted数据 ------------------
    def update_alerted(self,
                       ids=None,
                       stream_uids=None,
                       event_uids=None,
                       group_event_uids=None,
                       group_uids=None,
                       fence_uids=None,
                       alerted=1):
        """
        更新 merged_videos 表的 alerted 字段
        :param ids: 单个 id 或 id 列表
        :param stream_uids: 单个 stream_uid 或列表
        :param event_uids: 单个 event_uid 或列表
        :param group_event_uids: 单个 group_event_uid 或列表
        :param group_uids: 单个 group_uid 或列表
        :param fence_uids: 单个 fence_uid 或列表
        :param alerted: alerted 状态 (默认 1)
        :return: 更新的行数
        """
        conditions = []
        params = []
        def add_condition(field, values):
            if values is None:
                return
            if not isinstance(values, list):
                values = [values]
            placeholders = ",".join("?" * len(values))
            conditions.append(f"{field} IN ({placeholders})")
            params.extend(values)
        add_condition("id", ids)
        add_condition("stream_uid", stream_uids)
        add_condition("event_uid", event_uids)
        add_condition("group_event_uid", group_event_uids)
        add_condition("group_uid", group_uids)
        add_condition("fence_uid", fence_uids)
        if not conditions:
            raise ValueError("必须提供至少一个条件参数")
        where_clause = " OR ".join(conditions)  # 不同条件之间 OR，满足任意条件即可
        query = f"""
            UPDATE merged_videos
            SET alerted=?
            WHERE {where_clause};
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, [alerted] + params)
            conn.commit()
            return cur.rowcount

    # ------------------ 事件表操作 ------------------
    # def insert_event(self, event_uid, group_event_uid, group_uid, stream_uid, fence_uid,
    #                  stream_name, timestamp, change_ratio, alerted=0, ai_checked=0,
    #                  ai_report="", image_before_url="", image_after_url="",
    #                  image_before_path="", image_after_path="", videourl="", videopath=""):
    #     """插入事件记录"""
    #     with self.get_conn() as conn:
    #         cur = conn.cursor()
    #         cur.execute("""
    #                     INSERT INTO events
    #                     (event_uid, group_event_uid, group_uid, stream_uid, fence_uid, stream_name,
    #                      timestamp, change_ratio, alerted, ai_checked, ai_report,
    #                      image_before_url, image_after_url, image_before_path, image_after_path,
    #                      videourl, videopath)
    #                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    #                     """, (
    #                         event_uid, group_event_uid, group_uid, stream_uid, fence_uid, stream_name,
    #                         timestamp, str(change_ratio), int(alerted), int(ai_checked), ai_report,
    #                         image_before_url, image_after_url, image_before_path, image_after_path,
    #                         videourl, videopath
    #                     ))
    #         conn.commit()
    #         return cur.lastrowid


db = DBHelper()
