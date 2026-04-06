import subprocess
import os
import json
import time
from datetime import datetime

RECORD_DIR = "camera/recorder"
MANIFEST_FILE = os.path.join(RECORD_DIR, "manifest.json")
MAX_TOTAL_SECONDS = 48 * 3600
DEFAULT_RECORD_DURATION = 3600  # 每次录制1小时

def record_stream_from_page(page_url, duration=DEFAULT_RECORD_DURATION):
    """直接使用 yt-dlp 从网页地址录制，自动处理签名"""
    os.makedirs(RECORD_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(RECORD_DIR, f"live_{timestamp}.mp4")
    
    # yt-dlp 直接下载网页，它会自动找到 m3u8 并处理
    cmd = [
        "yt-dlp",
        "-o", output_file,
        "--live-from-start",
        "--retries", "10",
        "--fragment-retries", "10",
        "--hls-use-mpegts",
        "--duration", str(duration),
        page_url   # 直接传入直播网页地址
    ]
    subprocess.run(cmd, check=True)
    
    # 获取实际时长
    actual_duration = get_video_duration(output_file)
    return output_file, actual_duration

def get_video_duration(filepath):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", filepath]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return DEFAULT_RECORD_DURATION

# load_manifest, save_manifest, prune_old_videos 函数保持不变（之前提供的）

def main():
    print(f"[{datetime.now()}] 开始监控直播流...")
    page_url = "https://epsn.jtw.sh.gov.cn/wxgzh/html/ssjt.html"
    
    # 录制
    new_file, new_duration = record_stream_from_page(page_url, DEFAULT_RECORD_DURATION)
    print(f"录制完成: {new_file} (时长: {new_duration:.1f} 秒)")
    
    # 加载清单并清理旧文件
    manifest = load_manifest()
    updated_manifest, deleted_files = prune_old_videos(manifest, new_file, new_duration)
    save_manifest(updated_manifest)
    
    # 可选：输出变更
    print("需要提交的文件:", new_file)
    for df in deleted_files:
        print("删除:", df)
