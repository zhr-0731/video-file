#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import json
import time
import sys
import glob
from datetime import datetime

# ========== 配置 ==========
RECORD_DIR = "camera/recorder"
MANIFEST_FILE = os.path.join(RECORD_DIR, "manifest.json")
MAX_TOTAL_BYTES = 1 * 1024 * 1024 * 1024   # 1 GB 总上限

# 定义多个直播流
STREAMS = [
    {
        "id": "stream1",
        "url": "https://rvsh.jtw.sh.gov.cn/live/b4710c1c-27eb-4354-a18c-f20fa85f09fc_sub/index.m3u8?t=1933147233&k=0e2debebaffaca58",
        "duration_sec": 1800,   # 30 分钟
        "segment_duration": 4   # 每个 ts 片段 4 秒
    },
    {
        "id": "stream2",
        "url": "https://rvsh.jtw.sh.gov.cn/live/0c1d7fb6-c1ec-4a57-bf7a-0da67f620ca8_sub/index.m3u8?t=1933420295&k=43c8fb418001e311",
        "duration_sec": 1800,   # 30 分钟
        "segment_duration": 4
    }
]
# ==========================

def get_folder_size_bytes(folder):
    total = 0
    for dirpath, _, filenames in os.walk(folder):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total

def record_and_slice(stream, timestamp_str):
    """
    录制单个直播流，输出 HLS 切片（.ts + 临时.m3u8）
    返回：生成的切片文件列表（完整路径），以及本次录制对应的临时 m3u8 路径
    """
    stream_id = stream["id"]
    url = stream["url"]
    duration = stream["duration_sec"]
    seg_dur = stream["segment_duration"]

    os.makedirs(RECORD_DIR, exist_ok=True)
    segment_prefix = os.path.join(RECORD_DIR, f"{stream_id}_{timestamp_str}_")
    temp_m3u8 = os.path.join(RECORD_DIR, f"temp_{stream_id}_{timestamp_str}.m3u8")

    cmd = [
        "ffmpeg", "-i", url,
        "-t", str(duration),
        "-c", "copy",
        "-f", "hls",
        "-hls_time", str(seg_dur),
        "-hls_list_size", "0",
        "-hls_segment_filename", f"{segment_prefix}%03d.ts",
        "-y",
        temp_m3u8
    ]
    print(f"[命令] {' '.join(cmd)}")
    sys.stdout.flush()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 60)
        if result.returncode != 0:
            print(f"ffmpeg 错误 (流 {stream_id}): {result.stderr}")
            return [], None
    except subprocess.TimeoutExpired:
        print(f"录制超时 (流 {stream_id})")
        return [], None

    ts_files = glob.glob(f"{segment_prefix}*.ts")
    ts_files.sort()
    if not ts_files:
        print(f"未生成任何 ts 切片 (流 {stream_id})")
        return [], None

    print(f"流 {stream_id}: 生成了 {len(ts_files)} 个 ts 切片")
    return ts_files, temp_m3u8

def update_playlist(stream_id, new_ts_files, deleted_ts_files):
    """
    更新某个流的播放列表 (playlist_{stream_id}.m3u8)
    追加新 ts 文件，移除已删除的 ts 文件
    """
    playlist_file = os.path.join(RECORD_DIR, f"playlist_{stream_id}.m3u8")
    if not os.path.exists(playlist_file):
        with open(playlist_file, "w") as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            f.write("#EXT-X-TARGETDURATION:10\n")
            f.write("#EXT-X-MEDIA-SEQUENCE:0\n")

    # 读取现有内容
    with open(playlist_file, "r") as f:
        lines = f.readlines()

    # 解析现有的 ts 文件
    existing_ts = []
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            if i+1 < len(lines):
                ts_file = lines[i+1].strip()
                existing_ts.append(ts_file)
                new_lines.append(lines[i])
                new_lines.append(lines[i+1])
                i += 2
            else:
                i += 1
        else:
            new_lines.append(lines[i])
            i += 1

    # 移除被删除的 ts
    deleted_set = set(os.path.basename(f) for f in deleted_ts_files)
    filtered_ts = [ts for ts in existing_ts if ts not in deleted_set]
    # 重建文件内容（保留头部，重新写入 EXTINF 行）
    final_lines = []
    for line in new_lines:
        if line.startswith("#EXTINF"):
            continue
        if line.strip() in deleted_set:
            continue
        final_lines.append(line)
    for ts in filtered_ts:
        # 获取时长（可以用 ffprobe，这里简单用默认 4 秒）
        duration = get_ts_duration(os.path.join(RECORD_DIR, ts)) if ts else 4.0
        final_lines.append(f"#EXTINF:{duration:.3f},\n")
        final_lines.append(f"{ts}\n")
    # 写入
    with open(playlist_file, "w") as f:
        f.writelines(final_lines)

    # 追加新 ts 文件
    with open(playlist_file, "a") as f:
        for ts in new_ts_files:
            duration = get_ts_duration(ts) if ts else 4.0
            f.write(f"#EXTINF:{duration:.3f},\n")
            f.write(f"{os.path.basename(ts)}\n")

def get_ts_duration(ts_file):
    """使用 ffprobe 获取 ts 片段时长"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", ts_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except:
            pass
    return 4.0

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r") as f:
            return json.load(f)
    return []

def save_manifest(manifest):
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

def prune_old_files(manifest, all_new_ts_files):
    """
    添加所有新 ts 文件，检查总大小，删除最旧的直到低于上限
    返回：(更新后的manifest, 所有被删除的ts文件列表)
    """
    # 添加新文件
    for ts in all_new_ts_files:
        size = os.path.getsize(ts)
        manifest.append({
            "path": ts,
            "size_bytes": size,
            "created_at": time.time(),
            "stream_id": os.path.basename(ts).split('_')[0]  # 提取 stream1 或 stream2
        })
    manifest.sort(key=lambda x: x["created_at"])

    total_size = sum(item["size_bytes"] for item in manifest)
    deleted_files = []

    while total_size > MAX_TOTAL_BYTES and len(manifest) > 1:
        oldest = manifest.pop(0)
        oldest_path = oldest["path"]
        if os.path.exists(oldest_path):
            os.remove(oldest_path)
            deleted_files.append(oldest_path)
            print(f"删除旧 ts: {oldest_path} (释放 {oldest['size_bytes']/(1024*1024):.2f} MB)")
            # 尝试删除对应的临时 m3u8
            base = oldest_path.replace(".ts", "")
            temp_m3u8 = base.replace(f"{oldest['stream_id']}_", f"temp_{oldest['stream_id']}_") + ".m3u8"
            if os.path.exists(temp_m3u8):
                os.remove(temp_m3u8)
        total_size -= oldest["size_bytes"]

    if total_size > MAX_TOTAL_BYTES:
        print(f"警告: 总大小 {total_size/(1024*1024):.2f} MB 仍超过上限，但只剩一个文件，无法继续删除")

    return manifest, deleted_files

def main():
    print(f"[{datetime.now()}] 开始多流监控...")
    print(f"当前文件夹总大小: {get_folder_size_bytes(RECORD_DIR)/(1024*1024):.2f} MB")
    print(f"上限: {MAX_TOTAL_BYTES/(1024*1024):.0f} MB")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_new_ts_files = []
    stream_results = []

    # 依次录制每个流（串行，避免资源冲突）
    for stream in STREAMS:
        print(f"\n--- 开始录制流: {stream['id']} ---")
        ts_files, _ = record_and_slice(stream, timestamp_str)
        if ts_files:
            all_new_ts_files.extend(ts_files)
            stream_results.append((stream["id"], ts_files))
        else:
            print(f"流 {stream['id']} 录制失败，跳过")

    if not all_new_ts_files:
        print("所有流均录制失败，退出")
        sys.exit(1)

    # 加载清单
    manifest = load_manifest()

    # 根据总大小删除旧文件（全局）
    updated_manifest, deleted_files = prune_old_files(manifest, all_new_ts_files)

    # 按流分别更新播放列表
    for stream_id, new_ts_files in stream_results:
        # 找出属于该流且被删除的文件
        deleted_this_stream = [f for f in deleted_files if os.path.basename(f).startswith(f"{stream_id}_")]
        update_playlist(stream_id, new_ts_files, deleted_this_stream)

    # 保存清单
    save_manifest(updated_manifest)

    total_size_mb = sum(item["size_bytes"] for item in updated_manifest) / (1024*1024)
    print(f"\n清理完成。当前总大小: {total_size_mb:.2f} MB")
    for stream_id, _ in stream_results:
        playlist_file = os.path.join(RECORD_DIR, f"playlist_{stream_id}.m3u8")
        print(f"流 {stream_id} 播放列表: {playlist_file}")

if __name__ == "__main__":
    main()