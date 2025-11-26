import sqlite3
from contextlib import contextmanager
from config import DB_PATH

MAX_SQL_VARS = 900


class DBHelper:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            # 设置 WAL 模式，允许并发读写
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
        finally:
            conn.commit()
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
                            id                INTEGER PRIMARY KEY AUTOINCREMENT,
                            stream_uid        TEXT,
                            group_uid         TEXT,
                            fence_uid         TEXT,
                            change_ratio      REAL,
                            changed           INTEGER,              -- 0=normal,1=abnormal
                            timestamp         TEXT,
                            frame_path        TEXT,
                            frame_id          INTEGER,
                            exported          INTEGER DEFAULT 0,    -- 0=未导出, 1=已导出
                            group_exported    INTEGER DEFAULT 0,    -- 0=未导出, 1=已导出
                            ai_checked        INTEGER DEFAULT 0,
                            ai_status         INTEGER DEFAULT NULL, -- 0=normal,1=AI判定异常,-1=失败
                            ai_result         TEXT    DEFAULT NULL,
                            alerted           INTEGER DEFAULT 0,
                            event_uid         TEXT,                 -- 事件ID (UUID)
                            group_event_uid   TEXT,
                            before_image_path TEXT    DEFAULT NULL, -- 新增：前一帧图像路径
                            after_image_path  TEXT    DEFAULT NULL, -- 新增：后一帧图像路径
                            alert_video_path  TEXT    DEFAULT NULL
                        );
                        """)

            # 视频合成表
            cur.execute("""
                        CREATE TABLE IF NOT EXISTS merged_videos
                        (
                            id                INTEGER PRIMARY KEY AUTOINCREMENT,
                            stream_name       TEXT,
                            stream_uid        TEXT,
                            group_uid         TEXT,
                            fence_uid         TEXT,
                            video_path        TEXT,
                            before_image_path TEXT    DEFAULT NULL, -- 新增：前一帧图像路径
                            after_image_path  TEXT    DEFAULT NULL, -- 新增：后一帧图像路径
                            duration          REAL,                 -- 秒
                            size              INTEGER,              -- 字节
                            timestamp         TEXT,
                            exported          INTEGER DEFAULT 0,    -- 0=未导出, 1=已导出
                            ai_checked        INTEGER DEFAULT 0,
                            ai_status         INTEGER DEFAULT NULL, -- 0=normal,1=AI判定异常,-1=失败
                            ai_result         TEXT    DEFAULT NULL,
                            alerted           INTEGER DEFAULT 0,
                            event_uid         TEXT,                 -- 事件ID (UUID)
                            group_event_uid   TEXT
                        );
                        """)

            # 编组预警事件表
            cur.execute("""
                        CREATE TABLE IF NOT EXISTS events
                        (
                            id              INTEGER PRIMARY KEY AUTOINCREMENT,
                            group_uid       TEXT,
                            group_event_uid TEXT,
                            timestamp       TEXT,
                            exported        INTEGER DEFAULT 0,
                            ai_checked      INTEGER DEFAULT 0,
                            ai_status       INTEGER DEFAULT 0,
                            ai_result       TEXT,
                            alerted         INTEGER DEFAULT 0
                        );
                        """)

            conn.commit()

    # ------------------ 清理方法 ------------------
    def cleanup_table_by_time(self, table_name, time_column, time_threshold):
        """根据时间清理指定表的数据"""
        with self.get_conn() as conn:
            conn.execute("PRAGMA busy_timeout = 3000;")  # 设置忙碌等待的超时，避免冲突时立即报错
            try:
                cur = conn.cursor()
                cur.execute(f"""
                            DELETE FROM {table_name}
                            WHERE {time_column} < ?;
                            """, (time_threshold,))

                # 提交事务
                conn.commit()

            except Exception as e:
                conn.rollback()  # 如果发生异常，回滚事务
                raise Exception(f"删除数据失败: {e}")

        # 执行 VACUUM 操作，缩小数据库文件，确保事务已提交
        with self.get_conn() as conn:
            try:
                conn.execute("VACUUM")  # 不能在事务中执行，必须在事务外部
            except Exception as e:
                raise Exception(f"VACUUM 执行失败: {e}")

    def cleanup_table_by_column(self, table_name, column_name, value):
        """根据指定列的值清理数据"""
        with self.get_conn() as conn:
            conn.execute("PRAGMA busy_timeout = 3000;")  # 设置忙碌等待的超时，避免冲突时立即报错
            try:
                cur = conn.cursor()
                cur.execute(f"""
                            DELETE FROM {table_name}
                            WHERE {column_name} = ?;
                            """, (value,))

                # 提交事务
                conn.commit()

            except Exception as e:
                conn.rollback()  # 如果发生异常，回滚事务
                raise Exception(f"删除数据失败: {e}")

        # 执行 VACUUM 操作，缩小数据库文件，确保事务已提交
        with self.get_conn() as conn:
            try:
                conn.execute("VACUUM")  # 不能在事务中执行，必须在事务外部
            except Exception as e:
                raise Exception(f"VACUUM 执行失败: {e}")

    # ------------------ 清理抓帧表 ------------------
    def cleanup_captured_frames_by_time(self, time_threshold):
        """按时间清理抓帧表"""
        self.cleanup_table_by_time('captured_frames', 'timestamp', time_threshold)

    def cleanup_captured_frames_by_column(self, column_value):
        """按列值清理抓帧表"""
        self.cleanup_table_by_column('captured_frames', 'frame_path', column_value)

    # ------------------ 清理异常检测表 ------------------
    def cleanup_fence_detections_by_time(self, time_threshold):
        """按时间清理异常检测表"""
        self.cleanup_table_by_time('fence_detections', 'timestamp', time_threshold)

    def cleanup_fence_detections_by_column(self, column_value):
        """按列值清理异常检测表"""
        self.cleanup_table_by_column('fence_detections', 'changed', column_value)

    # ------------------ 清理视频合成表 ------------------
    def cleanup_merged_videos_by_time(self, time_threshold):
        """按时间清理视频合成表"""
        self.cleanup_table_by_time('merged_videos', 'timestamp', time_threshold)

    def cleanup_merged_videos_by_column(self, column_value):
        """按列值清理视频合成表"""
        self.cleanup_table_by_column('merged_videos', 'exported', column_value)

    # ------------------ 清理事件表 ------------------
    def cleanup_events_by_time(self, time_threshold):
        """按时间清理事件表"""
        self.cleanup_table_by_time('events', 'timestamp', time_threshold)

    def cleanup_events_by_column(self, column_value):
        """按列值清理事件表"""
        self.cleanup_table_by_column('events', 'alerted', column_value)

    # ------------------ 抓帧表操作 ------------------
    def bind_group_event_uid_to_frames(self, start_ts, end_ts, group_event_uid):
        """给抓帧表绑定start_ts到end_ts的group_event_uid"""
        with self.get_conn() as conn:
            conn.execute("PRAGMA busy_timeout = 3000;")
            cur = conn.cursor()
            cur.execute("""
                        UPDATE captured_frames
                        SET group_uid = ?
                        WHERE timestamp BETWEEN ? AND ?
                        """, (group_event_uid, start_ts.isoformat(), end_ts.isoformat()))
            conn.commit()
            return cur.rowcount

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
                          AND timestamp BETWEEN ?
                            AND ?
                        ORDER BY timestamp ASC;
                        """, (stream_uid, start_ts.isoformat(), end_ts.isoformat()))
            return [dict(row) for row in cur.fetchall()]

    # ------------------ 异常检测表操作 ------------------
    def get_changed_and_pending_export_frames_by_stream_fence(self, stream_uid, fence_uid=None):
        with self.get_conn() as conn:
            cur = conn.cursor()

            # 构建基础 SQL
            sql = """
                  SELECT *
                  FROM fence_detections
                  WHERE stream_uid = ?
                    AND (changed = '1' AND exported = '0')
                  """
            params = [stream_uid]

            # 可选的 fence_uid 条件
            if fence_uid is not None:
                sql += " AND fence_uid = ?"
                params.append(fence_uid)

            # 按时间排序，方便后续合并处理
            sql += " ORDER BY timestamp ASC;"

            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def get_detected_frames_by_stream_fence_and_time(self, stream_uid, start_ts, end_ts, fence_uid=None):
        with self.get_conn() as conn:
            cur = conn.cursor()
            # 基础 SQL 和参数
            sql = """
                  SELECT *
                  FROM fence_detections
                  WHERE stream_uid = ?
                    AND timestamp BETWEEN ?
                      AND ? \
                  """
            params = [stream_uid, start_ts.isoformat(), end_ts.isoformat()]
            # 如果传了 fence_uid，则添加条件
            if fence_uid is not None:
                sql += " AND fence_uid = ?"
                params.append(fence_uid)
            # 排序
            sql += " ORDER BY timestamp ASC;"
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

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

    def update_media_paths(self, detection_id, before_image_path=None, after_image_path=None, alert_video_path=None):
        """
        单独更新指定检测记录的前后帧图像和回溯视频路径
        :param detection_id: 检测记录 ID
        :param before_image_path: 前一帧图像路径
        :param after_image_path: 后一帧图像路径
        :param alert_video_path: 回溯视频路径
        """
        with self.get_conn() as conn:
            cur = conn.cursor()

            # 构造可变 SQL
            fields = []
            params = []
            if before_image_path is not None:
                fields.append("before_image_path=?")
                params.append(before_image_path)
            if after_image_path is not None:
                fields.append("after_image_path=?")
                params.append(after_image_path)
            if alert_video_path is not None:
                fields.append("alert_video_path=?")
                params.append(alert_video_path)

            if not fields:
                return 0  # 没有字段需要更新

            sql = f"""
                UPDATE fence_detections
                SET {', '.join(fields)}
                WHERE id = ?;
            """
            params.append(detection_id)
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount

    def update_ai_result(
            self,
            detection_id,
            ai_checked=1,
            ai_status=None,
            ai_result=None
    ):
        """
        更新指定检测记录的 AI 识别结果
        :param detection_id: 检测记录 ID
        :param ai_checked: 是否已 AI 识别，默认 1
        :param ai_status: AI 判断状态，1=异常, 0=正常, -1=失败
        :param ai_result: AI 识别结果（文本）
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        UPDATE fence_detections
                        SET ai_checked=?,
                            ai_result=?,
                            ai_status=?
                        WHERE id = ?;
                        """, (
                            int(ai_checked),
                            ai_result,
                            int(ai_status) if ai_status is not None else None,
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
                          AND timestamp BETWEEN ?
                            AND ?
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

    def get_group_pending_exports(self, group_uid=None):
        with self.get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM fence_detections WHERE group_exported=0"
            params = []
            if group_uid:
                query += " AND group_uid=?"
                params.append(group_uid)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def mark_as_exported(self, detection_ids):
        with self.get_conn() as conn:
            cur = conn.cursor()
            for i in range(0, len(detection_ids), MAX_SQL_VARS):
                batch = detection_ids[i:i + MAX_SQL_VARS]
                cur.execute(f"""
                    UPDATE fence_detections
                    SET exported=1
                    WHERE id IN ({','.join('?' for _ in batch)})
                """, batch)
            conn.commit()

    def mark_as_group_exported(self, detection_ids, event_uid, group_event_uid):
        with self.get_conn() as conn:
            cur = conn.cursor()
            for i in range(0, len(detection_ids), MAX_SQL_VARS):
                batch = detection_ids[i:i + MAX_SQL_VARS]
                cur.execute(f"""
                    UPDATE fence_detections
                    SET group_exported=1,
                        event_uid=?,
                        group_event_uid=?
                    WHERE id IN ({','.join('?' for _ in batch)})
                """, [event_uid, group_event_uid] + batch)
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
            exported=0,
            group_exported=0,
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
                         frame_path, frame_id, group_exported, exported, event_uid, group_event_uid,
                         ai_checked, ai_status, ai_result, alerted,
                         before_image_path, after_image_path, alert_video_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                            int(group_exported),
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
            for i in range(0, len(detection_ids), MAX_SQL_VARS):
                batch = detection_ids[i:i + MAX_SQL_VARS]
                cur.execute(f"""
                    UPDATE fence_detections
                    SET alerted=1
                    WHERE id IN ({','.join('?' for _ in batch)})
                """, batch)
            conn.commit()

    def get_ai_result_by_group_event_uid(self, group_event_uid):
        """
        根据 group_event_uid 获取AI检测结果
        :param group_event_uid: 组事件ID
        :return: 检测结果列表
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT stream_uid, ai_checked, ai_status, ai_result
                        FROM fence_detections
                        WHERE group_event_uid = ?
                          AND changed = 1
                        """, (group_event_uid,))
            return [dict(row) for row in cur.fetchall()]

    def get_pending_alerts(self, group_uid=None):
        """
        获取未报警的异常检测记录。
        :param group_uid: 可选，指定组
        :return: 未报警的记录列表
        """
        with self.get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM fence_detections WHERE ai_status=1 AND alerted=0"
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
            query = "SELECT * FROM fence_detections WHERE changed=1 AND ai_checked=0 AND alert_video_path IS NOT NULL"
            params = []
            if group_uid:
                query += " AND group_uid=?"
                params.append(group_uid)
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    # ------------------ 视频合成表操作 ------------------
    def get_videos_by_group_event_uid(self, group_event_uid):
        """获取指定组事件下的视频合成数据"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM merged_videos
                        WHERE group_event_uid = ?
                        """, (group_event_uid,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def insert_merged_video(self, stream_name, stream_uid, group_uid, fence_uid, video_path, before_image_path,
                            after_image_path, duration, size, timestamp, event_uid, group_event_uid,
                            exported=0, ai_checked=0, ai_status=None, ai_result=None, alerted=0):
        """插入一条视频合成数据"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        INSERT INTO merged_videos
                        (stream_name, stream_uid, group_uid, fence_uid, video_path, before_image_path, after_image_path,
                         duration, size, timestamp, event_uid, group_event_uid,
                         exported, ai_checked, ai_status, ai_result, alerted)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            stream_name, stream_uid, group_uid, fence_uid, video_path, before_image_path,
                            after_image_path, duration, size, timestamp.isoformat(), event_uid, group_event_uid,
                            exported, ai_checked, ai_status, ai_result, alerted

                        ))
            conn.commit()
            return cur.lastrowid

    # ------------------ 更新 AI 检测结果 ------------------
    def update_video_ai_result(self, video_id, ai_checked=1, ai_status=None, ai_result=None):
        """
        更新 merged_videos 表的 AI 检测结果
        :param video_id: 视频记录 id
        :param ai_checked: 是否已检测 (默认 1)
        :param ai_status: AI 状态 (0=normal,1=异常,-1=失败)
        :param ai_result: AI 返回的详细结果 (JSON或文本)
        :return: 更新的行数
        """
        query = """
                UPDATE merged_videos
                SET ai_checked=?,
                    ai_status=?,
                    ai_result=?
                WHERE id = ?; \
                """
        params = (ai_checked, ai_status, ai_result, video_id)

        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()
            return cur.rowcount

    # ------------------ 获取尚未AI检测的视频数据 ------------------
    def get_unchecked_videos(self, limit=None):
        """查询尚未进行AI检测(ai_checked=0)的视频记录"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            sql = """
                  SELECT *
                  FROM merged_videos
                  WHERE ai_checked = 0
                    AND exported = 1
                  ORDER BY timestamp ASC
                  """
            if limit:
                sql += f" LIMIT {limit}"

            cur.execute(sql)
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    # ------------------ 获取尚未报警且识别过的视频数据 ------------------
    def get_unalerted_videos(self, limit=None):
        """查询尚未报警(alerted=0, ai_checked=1)的视频记录"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            sql = """
                  SELECT *
                  FROM merged_videos
                  WHERE alerted = 0
                    AND ai_checked = 1
                  ORDER BY timestamp ASC
                  """
            if limit:
                sql += f" LIMIT {limit}"

            cur.execute(sql)
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def mark_video_as_exported(self, group_event_uid):
        """根据 group_event_uid 标记视频检测记录为已导出"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        UPDATE merged_videos
                        SET exported = 1
                        WHERE group_event_uid = ?;
                        """, (group_event_uid,))
            conn.commit()
            return cur.rowcount > 0

    def mark_video_as_alerted(self, group_event_uid):
        """根据 group_event_uid 标记视频检测记录为已报警"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        UPDATE merged_videos
                        SET alerted = 1
                        WHERE group_event_uid = ?;
                        """, (group_event_uid,))
            conn.commit()
            return cur.rowcount > 0

    # ------------------ 事件表操作 ------------------
    def insert_event(self, group_uid, group_event_uid, timestamp):
        """插入一条事件记录"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        INSERT INTO events (group_uid, group_event_uid, timestamp)
                        VALUES (?, ?, ?);
                        """, (group_uid, group_event_uid, timestamp.isoformat()))
            conn.commit()
            return cur.lastrowid

    def get_all_events(self):
        """获取所有的 group_event_uid"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM events
                        ORDER BY timestamp ASC;
                        """)
            return [dict(row) for row in cur.fetchall()]

    def get_events_by_group(self, group_event_uid):
        """根据 group_event_uid 获取事件列表"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM events
                        WHERE group_event_uid = ?
                        ORDER BY timestamp ASC;
                        """, (group_event_uid,))
            return [dict(row) for row in cur.fetchall()]

    def get_unchecked_events(self, limit=10):
        """获取未经过 AI 检查的事件"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM events
                        WHERE ai_checked = 0
                        ORDER BY timestamp ASC
                        LIMIT ?;
                        """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def mark_event_checked(self, group_event_uid, ai_status, ai_result):
        """更新事件的 AI 检查结果"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        UPDATE events
                        SET ai_checked = 1,
                            ai_status  = ?,
                            ai_result  = ?
                        WHERE group_event_uid = ?;
                        """, (ai_status, ai_result,))
            conn.commit()
            return cur.rowcount

    def get_unalerted_events(self, limit=10):
        """获取未告警的事件"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        SELECT *
                        FROM events
                        WHERE alerted = 0
                        ORDER BY timestamp ASC
                        LIMIT ?;
                        """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def mark_event_alerted(self, group_event_uid):
        """标记事件为已告警"""
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                        UPDATE events
                        SET alerted = 1
                        WHERE group_event_uid = ?;
                        """, (group_event_uid,))
            conn.commit()
            return cur.rowcount


db = DBHelper()
