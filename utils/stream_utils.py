from datetime import datetime
from utils.utils import log


def get_fuse_bool_time_range(streams_frames, fuse_bool):
    """
    streams_frames: {stream_uid: {frame_id: timestamp_str}}
    fuse_bool: {stream_uid: {frame_id: bool}}
    返回 fuse_bool 在 streams_frames 中的最大时间戳区间 (start_ts, end_ts)
    可能来自不同的 stream_uid
    """
    all_timestamps = []
    a_dt = {uid: {fid: datetime.fromisoformat(ts) for fid, ts in frames.items()}
            for uid, frames in streams_frames.items()}
    for uid, bool_dict in fuse_bool.items():
        if uid not in a_dt:
            continue
        for fid, flag in bool_dict.items():
            all_timestamps.append(a_dt[uid][fid])
    if not all_timestamps:
        return None  # 没有匹配的 True 帧
    start_ts = min(all_timestamps)
    end_ts = max(all_timestamps)
    return start_ts, end_ts


def get_stream_change_dict(group_streams_data):
    result = {}
    for stream_uid, frames in group_streams_data.items():
        stream_result = {}
        for fid, detect_frames in frames.items():
            stream_result[fid] = any(df.get("changed", False) for df in detect_frames)
        result[stream_uid] = dict(sorted(stream_result.items()))  # 按 frame_id 排序
    return result


def fuse_streams_by_position(streams_bool_dict):
    stream_keys = list(streams_bool_dict.keys())
    stream_lists = [list(v.values()) for v in streams_bool_dict.values()]
    max_len = max(len(lst) for lst in stream_lists)
    for lst in stream_lists:
        lst.extend([False] * (max_len - len(lst)))
    for i in range(max_len):
        if any(lst[i] for lst in stream_lists):
            for lst in stream_lists:
                lst[i] = True
    first_true_idx = None
    for i in range(max_len):
        if any(lst[i] for lst in stream_lists):
            first_true_idx = i
            break
    if first_true_idx is not None:
        stream_lists = [lst[first_true_idx:] for lst in stream_lists]
    else:
        first_true_idx = 0
    fused = {}
    for k, lst in zip(stream_keys, stream_lists):
        frame_ids = list(streams_bool_dict[k].keys())
        fused[k] = dict(zip(frame_ids[first_true_idx:], lst[:len(frame_ids) - first_true_idx]))
    if first_true_idx == 0 and all(not any(lst) for lst in stream_lists):
        status = "waiting"  # 全 False
    else:
        if all(lst[-1] for lst in stream_lists):
            status = "recording"  # 最后一帧 True
        else:
            status = "completed"  # 最后一帧 False
    return fused, status


def get_running_streams(storage_manger):
    streams = [stream for stream in storage_manger.list_streams() if stream.get("status") == "running"]
    if len(streams) == 0:
        log("WARNING", "当前没有运行的流，只在检测历史内查找合适的数据帧")
    return streams
