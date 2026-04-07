#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import json
import time
import sys
from datetime import datetime

# ========== 配置 ==========
RECORD_DIR = "camera/recorder"
MANIFEST_FILE = os.path.join(RECORD_DIR, "manifest.json")
MAX_TOTAL_BYTES = 1 * 1024 * 1024 * 1024   # 1 GB
RECORD_SECONDS = 2000                        # 每次录制10分钟（可根据码率调整）
M3U8_URL = "https://rvsh.jtw.sh.gov.cn/live/b4710c1c-27eb-4354-a18c-f20fa85f09fc_sub/index.m3u8?t=1933147233&k=0e2debebaffaca58"
# ==========================

def get_file_size_mb(filepath):
    return os.path.getsize(filepath) / (1024 * 1024)

def get_folder_size_mb(folder):
    total = 0
    for dirpath, _, filenames in os.walk(folder):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total / (1024 * 1024)

def record_stream(m3u8_url, duration_sec):
    """使用 ffmpeg 录制，返回文件路径和文件大小（字节）"""
    os.makedirs(RECORD_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(RECORD_DIR, f"live_{timestamp}.mp4")

    cmd = [
        "ffmpeg", "-i", m3u8_url,
        "-t", str(duration_sec),
        "-c", "copy",
        "-y",
        output_file
    ]
    print(f"[命令] {' '.join(cmd)}")
    sys.stdout.flush()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_sec + 60)
        if result.returncode != 0:
            print(f"ffmpeg 错误: {result.stderr}")
            return None, 0
    except subprocess.TimeoutExpired:
        print("录制超时")
        return None, 0

    if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        print(f"文件未生成或为空: {output_file}")
        return None, 0

    file_size = os.path.getsize(output_file)
    print(f"录制完成: {output_file} ({file_size/(1024*1024):.2f} MB)")
    return output_file, file_size

def load_manifest():
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r") as f:
            return json.load(f)
    return []

def save_manifest(manifest):
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

def prune_old_files(manifest, new_file, new_size):
    """
    添加新文件后，确保总大小 <= MAX_TOTAL_BYTES
    删除最旧的录像直到满足条件
    """
    manifest.append({
        "path": new_file,
        "size_bytes": new_size,
        "created_at": time.time()
    })
    # 按创建时间升序排序（旧的在前）
    manifest.sort(key=lambda x: x["created_at"])

    total_size = sum(item["size_bytes"] for item in manifest)
    deleted_files = []

    while total_size > MAX_TOTAL_BYTES and len(manifest) > 1:
        oldest = manifest.pop(0)
        if os.path.exists(oldest["path"]):
            os.remove(oldest["path"])
            deleted_files.append(oldest["path"])
            print(f"删除旧录像: {oldest['path']} (释放 {oldest['size_bytes']/(1024*1024):.2f} MB)")
        total_size -= oldest["size_bytes"]

    if total_size > MAX_TOTAL_BYTES:
        print(f"警告: 总大小 {total_size/(1024*1024):.2f} MB 仍超过上限，但只剩一个文件，无法继续删除")

    return manifest, deleted_files

def main():
    print(f"[{datetime.now()}] 开始监控直播流...")
    print(f"当前文件夹大小: {get_folder_size_mb(RECORD_DIR):.2f} MB")
    print(f"上限: {MAX_TOTAL_BYTES/(1024*1024):.0f} MB")

    # 录制新视频
    new_file, new_size = record_stream(M3U8_URL, RECORD_SECONDS)
    if new_file is None:
        print("录制失败，退出")
        sys.exit(1)

    # 加载清单并清理
    manifest = load_manifest()
    updated_manifest, deleted_files = prune_old_files(manifest, new_file, new_size)
    save_manifest(updated_manifest)

    # 输出统计
    total_size_mb = sum(item["size_bytes"] for item in updated_manifest) / (1024*1024)
    print(f"清理完成。当前总大小: {total_size_mb:.2f} MB")
    print(f"新增文件: {new_file}")
    if deleted_files:
        print(f"删除文件: {', '.join(deleted_files)}")

if __name__ == "__main__":
    main()
