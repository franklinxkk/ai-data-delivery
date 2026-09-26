#!/usr/bin/env python3
"""rebuild.py — 停服 → 新鲜度校验 → 构建 → 起服 → 就绪校验。

防旧包铁律：构建产物（artifact）的 mtime 必须新于全部源码文件，
否则视为旧包，强制重新构建（除非显式 --skip-build 且产物新鲜）。

用法示例：
    python3 rebuild.py \
        --project-dir /path/to/fde \
        --artifact /path/to/fde/target/fde-server.jar \
        --build-cmd "mvn -q package -DskipTests" \
        --start-cmd "java -jar target/fde-server.jar" \
        --health-url http://127.0.0.1:8080/health \
        --port 8080

退出码：0 = 服务已就绪；1 = 任一环节失败。
"""
import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

SOURCE_EXTS = {".java", ".kt", ".scala", ".xml", ".yaml", ".yml", ".properties",
               ".py", ".sql", ".json", ".gradle"}


def log(msg):
    print(f"[rebuild] {msg}", flush=True)


def newest_source_mtime(project_dir):
    """返回项目目录内最新源码文件的 mtime（无源码则返回 0）。"""
    newest = 0.0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in
                   ("target", "build", "dist", ".git", "node_modules", "__pycache__")]
        for f in files:
            if os.path.splitext(f)[1] in SOURCE_EXTS:
                p = os.path.join(root, f)
                newest = max(newest, os.path.getmtime(p))
    return newest


def artifact_fresh(artifact, project_dir):
    """产物存在且不旧于任何源码 → True。"""
    if not os.path.isfile(artifact):
        return False, "产物不存在"
    art_mtime = os.path.getmtime(artifact)
    src_mtime = newest_source_mtime(project_dir)
    if src_mtime > art_mtime:
        return False, (f"产物旧于源码（artifact={time.ctime(art_mtime)}，"
                       f"最新源码={time.ctime(src_mtime)}）——旧包风险")
    return True, "产物新鲜"


def stop_service(port=None, pid_file=None):
    """按 pid 文件或端口停掉旧服务，返回是否停掉了进程。"""
    killed = False
    if pid_file and os.path.isfile(pid_file):
        try:
            pid = int(open(pid_file).read().strip())
            os.kill(pid, signal.SIGTERM)
            log(f"按 pid 文件停止进程 {pid}")
            killed = True
        except (ValueError, ProcessLookupError, PermissionError) as e:
            log(f"pid 文件停止失败：{e}")
    if port:
        # 优先 fuser，退化 lsof；两者都不可用则跳过端口停服
        for cmd in (["fuser", "-k", f"{port}/tcp"],
                    ["sh", "-c", f"kill $(lsof -ti:{port}) 2>/dev/null"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
            except FileNotFoundError:
                continue
            if r.returncode == 0:
                log(f"已释放端口 {port}")
                killed = True
                break
    if killed:
        time.sleep(2)  # 等端口释放
    return killed


def wait_ready(health_url, timeout):
    """轮询就绪端点直到 200 或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser(description="停服→构建→起服→就绪校验，防旧包")
    ap.add_argument("--project-dir", required=True, help="源码项目根目录")
    ap.add_argument("--artifact", required=True, help="构建产物路径（如 jar）")
    ap.add_argument("--build-cmd", required=True, help="构建命令（在项目目录下执行）")
    ap.add_argument("--start-cmd", required=True, help="启动命令（在项目目录下执行）")
    ap.add_argument("--health-url", required=True, help="就绪校验 URL，返回 200 视为就绪")
    ap.add_argument("--port", type=int, default=None, help="服务端口（用于停旧服）")
    ap.add_argument("--pid-file", default=None, help="服务 pid 文件（优先于端口停服）")
    ap.add_argument("--timeout", type=int, default=120, help="就绪等待秒数")
    ap.add_argument("--skip-build", action="store_true",
                    help="跳过构建——仅在产物新鲜时允许，否则报错退出")
    ap.add_argument("--log-file", default=None, help="服务 stdout/stderr 日志路径")
    args = ap.parse_args()

    project_dir = os.path.abspath(args.project_dir)
    artifact = args.artifact if os.path.isabs(args.artifact) \
        else os.path.join(project_dir, args.artifact)

    # 1) 新鲜度校验（防旧包）
    fresh, reason = artifact_fresh(artifact, project_dir)
    log(f"产物新鲜度校验：{reason}")
    if args.skip_build and not fresh:
        log("错误：--skip-build 但产物不新鲜，拒绝使用旧包。去掉 --skip-build 重新构建。")
        return 1

    # 2) 停旧服
    stop_service(port=args.port, pid_file=args.pid_file)

    # 3) 构建
    if not args.skip_build:
        log(f"构建：{args.build_cmd}")
        r = subprocess.run(args.build_cmd, shell=True, cwd=project_dir)
        if r.returncode != 0:
            log(f"构建失败（exit={r.returncode}）")
            return 1
        if not os.path.isfile(artifact):
            log(f"构建成功但未找到产物：{artifact}")
            return 1
        log(f"构建完成：{artifact}")

    # 4) 起服（ detached ，日志落盘）
    log_path = args.log_file or os.path.join(project_dir, "service.log")
    log(f"启动：{args.start_cmd}（日志 → {log_path}）")
    logf = open(log_path, "ab")
    proc = subprocess.Popen(args.start_cmd, shell=True, cwd=project_dir,
                            stdout=logf, stderr=subprocess.STDOUT,
                            start_new_session=True)
    log(f"服务进程 pid={proc.pid}")

    # 5) 就绪校验
    log(f"等待就绪：{args.health_url}（最长 {args.timeout}s）")
    if wait_ready(args.health_url, args.timeout):
        log("服务已就绪 ✓")
        return 0
    log("就绪超时，服务日志末尾：")
    try:
        lines = open(log_path, errors="replace").read().splitlines()
        for line in lines[-20:]:
            print(f"    {line}")
    except OSError:
        pass
    return 1


if __name__ == "__main__":
    sys.exit(main())
