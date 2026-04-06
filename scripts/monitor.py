import os
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

# 配置
RECORD_DIR = "camera/recorder"
MANIFEST_FILE = os.path.join(RECORD_DIR, "manifest.json")
MAX_TOTAL_SECONDS = 48 * 3600  # 48 小时 = 172800 秒
DEFAULT_RECORD_DURATION = 3600  # 每次录制 1 小时（可根据需要调整）

def get_video_duration(filepath):
    """使用 ffprobe 获取视频实际时长（秒）"""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    else:
        print(f"无法获取 {filepath} 的时长，使用默认值 {DEFAULT_RECORD_DURATION} 秒")
        return DEFAULT_RECORD_DURATION

def record_stream(m3u8_url, duration=DEFAULT_RECORD_DURATION):
    """录制直播流，返回生成的文件路径和实际时长"""
    os.makedirs(RECORD_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(RECORD_DIR, f"live_{timestamp}.mp4")
    
    cmd = [
        "yt-dlp",
        "-o", output_file,
        "--live-from-start",
        "--retries", "10",
        "--fragment-retries", "10",
        "--hls-use-mpegts",
        "--duration", str(duration),   # 限制录制时长
        m3u8_url
    ]
    subprocess.run(cmd, check=True)
    
    # 获取实际时长
    actual_duration = get_video_duration(output_file)
    return output_file, actual_duration

def load_manifest():
    """加载已有清单，如果文件不存在则返回空列表"""
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, "r") as f:
            return json.load(f)
    return []

def save_manifest(manifest):
    """保存清单到文件"""
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

def prune_old_videos(manifest, new_file, new_duration):
    """添加新文件后，检查总时长，删除旧视频直到满足阈值"""
    # 将新文件加入清单
    manifest.append({
        "path": new_file,
        "duration": new_duration,
        "created_at": time.time()
    })
    
    # 按创建时间升序排序
    manifest.sort(key=lambda x: x["created_at"])
    
    # 计算当前总时长
    total_duration = sum(item["duration"] for item in manifest)
    
    # 如果总时长超过阈值，删除最旧的视频
    deleted_files = []
    while total_duration > MAX_TOTAL_SECONDS and len(manifest) > 1:
        oldest = manifest.pop(0)  # 移除最旧的
        file_to_delete = oldest["path"]
        if os.path.exists(file_to_delete):
            os.remove(file_to_delete)
            deleted_files.append(file_to_delete)
            print(f"删除旧录像: {file_to_delete}")
        total_duration -= oldest["duration"]
    
    # 如果仍然超过阈值（例如只有一个文件且超过48小时），那就不删了，保留它
    if total_duration > MAX_TOTAL_SECONDS:
        print(f"警告: 总时长 {total_duration/3600:.1f}h 仍超过阈值，但只剩一个文件，无法继续删除")
    
    return manifest, deleted_files

def main():
    print(f"[{datetime.now()}] 开始监控直播流...")
    
    # 1. 获取最新的 m3u8 地址（根据你的实际逻辑实现）
    m3u8_url = get_live_m3u8()   # 请使用之前实现的函数
    if not m3u8_url:
        print("获取 m3u8 地址失败")
        return
    
    # 2. 录制新视频
    new_file, new_duration = record_stream(m3u8_url, DEFAULT_RECORD_DURATION)
    print(f"录制完成: {new_file} (时长: {new_duration:.1f} 秒)")
    
    # 3. 加载现有清单
    manifest = load_manifest()
    
    # 4. 删除旧视频并更新清单
    updated_manifest, deleted_files = prune_old_videos(manifest, new_file, new_duration)
    
    # 5. 保存清单
    save_manifest(updated_manifest)
    
    # 6. 输出变更信息，供后续 git commit 使用
    print("需要提交的文件:")
    print(f"  新增: {new_file}")
    for df in deleted_files:
        print(f"  删除: {df}")
    print(f"  更新: {MANIFEST_FILE}")
    
    # 可选：将变更列表写入一个临时文件，供 action 的后续步骤使用
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
        f.write(f"new_file={new_file}\n")
        f.write(f"deleted_files={'|'.join(deleted_files)}\n")

# 这里需要你根据实际网页实现 get_live_m3u8 函数
def get_live_m3u8():
    """模拟浏览器获取最新的 m3u8 地址（示例占位）"""
    # 请替换为你自己的实现
    return "https://english-livetx.cgtn.com/hls/yypdyyctzb_hd.m3u8"

if __name__ == "__main__":
    main()
