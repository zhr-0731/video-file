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
PLAYLIST_FILE = os.path.join(RECORD_DIR, "playlist.m3u8")
MAX_TOTAL_BYTES = 1 * 1024 * 1024 * 1024   # 1 GB
RECORD_SECONDS = 3600                        # 每次录制60分钟
M3U8_URL = "https://rvsh.jtw.sh.gov.cn/live/b4710c1c-27eb-4354-a18c-f20fa85f09fc_sub/index.m3u8?t=1933147233&k=0e2debebaffaca58"
# ==========================

def get_folder_size_bytes(folder):
    total = 0
    for dirpath, _, filenames in os.walk(folder):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total

def record_and_slice(m3u8_url, duration_sec):
    """
    录制直播流，并直接输出为 HLS 切片（.ts + 临时.m3u8）
    返回：生成的切片文件列表（.ts路径），以及本次录制对应的临时m3u8路径
    """
    os.makedirs(RECORD_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    segment_prefix = os.path.join(RECORD_DIR, f"seg_{timestamp}_")
    temp_m3u8 = os.path.join(RECORD_DIR, f"temp_{timestamp}.m3u8")

    # ffmpeg 直接输出 HLS 切片
    cmd = [
        "ffmpeg", "-i", m3u8_url,
        "-t", str(duration_sec),
        "-c", "copy",
        "-f", "hls",
        "-hls_time", "4",           # 每个 ts 片段 4 秒
        "-hls_list_size", "0",      # 不限制列表长度（保留所有片段）
        "-hls_segment_filename", f"{segment_prefix}%03d.ts",
        "-y",
        temp_m3u8
    ]
    print(f"[命令] {' '.join(cmd)}")
    sys.stdout.flush()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_sec + 60)
        if result.returncode != 0:
            print(f"ffmpeg 错误: {result.stderr}")
            return [], None
    except subprocess.TimeoutExpired:
        print("录制超时")
        return [], None

    # 收集生成的 .ts 文件
    ts_files = glob.glob(f"{segment_prefix}*.ts")
    if not ts_files:
        print("未生成任何 ts 切片")
        return [], None

    # 按文件名排序（自然顺序）
    ts_files.sort()
    print(f"生成了 {len(ts_files)} 个 ts 切片，临时 m3u8: {temp_m3u8}")
    return ts_files, temp_m3u8

def update_master_playlist(ts_files_to_add, deleted_ts_files):
    """
    更新总播放列表 playlist.m3u8：
    将新生成的 ts 文件追加到列表末尾，并移除已删除的 ts 文件条目。
    """
    # 如果总播放列表不存在，创建初始内容
    if not os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE, "w") as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            f.write("#EXT-X-TARGETDURATION:10\n")
            f.write("#EXT-X-MEDIA-SEQUENCE:0\n")

    # 读取现有内容（按行）
    with open(PLAYLIST_FILE, "r") as f:
        lines = f.readlines()

    # 提取现有的 ts 文件路径（去除 EXTINF 行）
    existing_ts = []
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            # 下一行是 ts 文件名
            if i+1 < len(lines):
                ts_file = lines[i+1].strip()
                existing_ts.append(ts_file)
                new_lines.append(lines[i])   # 保留 EXTINF
                new_lines.append(lines[i+1]) # 保留文件名
                i += 2
            else:
                i += 1
        else:
            new_lines.append(lines[i])
            i += 1

    # 移除被删除的 ts 文件
    deleted_set = set(deleted_ts_files)
    filtered_ts = [ts for ts in existing_ts if ts not in deleted_set]
    # 重建行内容：只保留未被删除的
    final_lines = []
    # 先保留头部（非 EXTINF 和非文件名的行）
    for line in new_lines:
        if line.startswith("#EXTINF"):
            # 暂时不处理，后面重新生成
            continue
        if line.strip() in deleted_set:
            continue
        final_lines.append(line)
    # 重新添加 EXTINF 和文件名（保持顺序）
    for ts in filtered_ts:
        # 获取 ts 文件时长（可选，可以用 ffprobe 获取，这里用默认 4 秒）
        # 简单处理：默认 4 秒
        final_lines.append(f"#EXTINF:4.0,\n")
        final_lines.append(f"{ts}\n")
    # 更新 MEDIA-SEQUENCE（可选，不影响播放）
    # 直接写回
    with open(PLAYLIST_FILE, "w") as f:
        f.writelines(final_lines)

    # 添加新 ts 文件到末尾
    with open(PLAYLIST_FILE, "a") as f:
        for ts in ts_files_to_add:
            # 获取每个 ts 的实际时长（可以用 ffprobe，这里简单默认 4 秒）
            # 为了提高准确性，可调用 get_ts_duration(ts)
            duration = get_ts_duration(ts) if ts else 4.0
            f.write(f"#EXTINF:{duration:.3f},\n")
            # 存储相对路径（相对于 RECORD_DIR）
            rel_path = os.path.basename(ts)
            f.write(f"{rel_path}\n")

def get_ts_duration(ts_file):
    """使用 ffprobe 获取 ts 片段时长"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", ts_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return 4.0

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r") as f:
            return json.load(f)
    return []

def save_manifest(manifest):
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

def prune_old_files(manifest, new_ts_files):
    """
    检查文件夹总大小，如果超过上限则删除最旧的 ts 文件（及关联的临时 m3u8）
    返回：更新后的 manifest，以及被删除的 ts 文件列表
    """
    # 将新生成的 ts 文件加入 manifest（记录文件路径和大小）
    for ts in new_ts_files:
        size = os.path.getsize(ts)
        manifest.append({
            "path": ts,
            "size_bytes": size,
            "created_at": time.time()
        })
    # 按创建时间排序
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
            # 同时删除对应的临时 m3u8（如果有）
            base = os.path.splitext(oldest_path)[0].replace("_seg_", "_temp_")
            temp_m3u8 = base + ".m3u8"
            if os.path.exists(temp_m3u8):
                os.remove(temp_m3u8)
        total_size -= oldest["size_bytes"]

    return manifest, deleted_files

def main():
    print(f"[{datetime.now()}] 开始监控直播流...")
    print(f"当前文件夹总大小: {get_folder_size_bytes(RECORD_DIR)/(1024*1024):.2f} MB")
    print(f"上限: {MAX_TOTAL_BYTES/(1024*1024):.0f} MB")

    # 1. 录制并切片
    ts_files, temp_m3u8 = record_and_slice(M3U8_URL, RECORD_SECONDS)
    if not ts_files:
        print("录制失败，退出")
        sys.exit(1)

    # 2. 加载清单
    manifest = load_manifest()

    # 3. 根据大小限制删除旧文件
    updated_manifest, deleted_ts = prune_old_files(manifest, ts_files)

    # 4. 更新总播放列表（添加新 ts，移除已删除的 ts）
    update_master_playlist(ts_files, deleted_ts)

    # 5. 保存清单
    save_manifest(updated_manifest)

    # 6. 输出信息
    total_size_mb = sum(item["size_bytes"] for item in updated_manifest) / (1024*1024)
    print(f"清理完成。当前总大小: {total_size_mb:.2f} MB")
    print(f"新增 ts 文件数: {len(ts_files)}")
    print(f"总播放列表: {PLAYLIST_FILE}")

if __name__ == "__main__":
    main()