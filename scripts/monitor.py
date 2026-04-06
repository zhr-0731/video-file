#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import json
import time
import sys
from datetime import datetime

RECORD_DIR = "camera/recorder"
MANIFEST_FILE = os.path.join(RECORD_DIR, "manifest.json")
MAX_TOTAL_SECONDS = 48 * 3600
DEFAULT_RECORD_DURATION = 3600
# 先使用你抓包得到的完整 m3u8 地址进行测试（注意：会过期）
LIVE_PAGE_URL = "https://rvsh.jtw.sh.gov.cn/live/b4710c1c-27eb-4354-a18c-f20fa85f09fc_sub/index.m3u8?t=1933147233&k=0e2debebaffaca58"

def get_video_duration(filepath):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", filepath]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            return float(result.stdout.strip())
        except:
            pass
    return DEFAULT_RECORD_DURATION

def record_stream_from_page(page_url, duration=DEFAULT_RECORD_DURATION):
    os.makedirs(RECORD_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(RECORD_DIR, f"live_{timestamp}.mp4")
    
    cmd = [
        "yt-dlp",
        "-o", output_file,
        "--live-from-start",
        "--retries", "3",
        "--fragment-retries", "3",
        "--hls-use-mpegts",
        "--duration", str(duration),
        page_url
    ]
    print(f"[命令] {' '.join(cmd)}")
    sys.stdout.flush()
    
    try:
        # 捕获输出以便查看错误
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3700)
        print(f"[yt-dlp stdout]\n{result.stdout}")
        print(f"[yt-dlp stderr]\n{result.stderr}")
        if result.returncode != 0:
            print(f"yt-dlp 返回码 {result.returncode}")
            return None, 0
    except subprocess.TimeoutExpired:
        print("录制超时")
        return None, 0
    
    if not os.path.exists(output_file):
        print(f"错误: 输出文件未生成 {output_file}")
        return None, 0
    
    actual_duration = get_video_duration(output_file)
    print(f"录制完成: {output_file} (时长: {actual_duration:.1f}s)")
    return output_file, actual_duration

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r") as f:
            return json.load(f)
    return []

def save_manifest(manifest):
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

def prune_old_videos(manifest, new_file, new_duration):
    if new_file is None:
        return manifest, []
    manifest.append({
        "path": new_file,
        "duration": new_duration,
        "created_at": time.time()
    })
    manifest.sort(key=lambda x: x["created_at"])
    total_duration = sum(item["duration"] for item in manifest)
    deleted_files = []
    while total_duration > MAX_TOTAL_SECONDS and len(manifest) > 1:
        oldest = manifest.pop(0)
        if os.path.exists(oldest["path"]):
            os.remove(oldest["path"])
            deleted_files.append(oldest["path"])
            print(f"删除旧录像: {oldest['path']}")
        total_duration -= oldest["duration"]
    return manifest, deleted_files

def main():
    print(f"[{datetime.now()}] 开始监控直播流...")
    new_file, new_duration = record_stream_from_page(LIVE_PAGE_URL, DEFAULT_RECORD_DURATION)
    if new_file is None:
        print("录制失败，退出")
        sys.exit(1)
    manifest = load_manifest()
    updated_manifest, deleted_files = prune_old_videos(manifest, new_file, new_duration)
    save_manifest(updated_manifest)
    print("清理完成。")
    print(f"新增: {new_file}")
    if deleted_files:
        print(f"删除: {deleted_files}")

if __name__ == "__main__":
    main()
