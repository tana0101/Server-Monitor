# app.py
import eventlet
eventlet.monkey_patch()

import json
import threading
import time
import traceback
from collections import deque
from datetime import datetime

import paramiko
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO

# --- CONFIG ---
SERVERS_FILE = "servers.json"
POLL_INTERVAL = 5  # seconds
HISTORY_LEN = 200  # keep last N datapoints per server

# --- Global store ---
# metrics_store[server_name] = {
#   "last_update": ts,
#   "cpu_load": 0.12,
#   "mem_total_mb": 16000, "mem_used_mb": 8200,
#   "disks": [...], "disk_total_bytes": int, "disk_used_bytes": int, "disk_used_pct": float,
#   "gpus": [{"name": "...","util": 50.0,"mem_total": 24576,"mem_used": 1234}, ...],
#   "history": {"gpus": [deque([...]), deque([...]), ...]}  # per-GPU util history
# }
metrics_store = {}

app = Flask(__name__)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    ping_interval=15,   # 每 15s 發送心跳
    ping_timeout=30     # 30s 沒回應就斷線重連
)


# --- SSH helpers ---
def ssh_run_command(client: paramiko.SSHClient, cmd: str, timeout=10):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    return out, err


def connect_ssh(server_info):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    port = server_info.get("port", 22)
    username = server_info["username"]
    
    if "private_key" in server_info:
        client.connect(
            server_info["host"],
            port=port,
            username=username,
            key_filename=server_info["private_key"],
            timeout=10
        )
    else:
        client.connect(
            server_info["host"],
            port=port,
            username=username,
            password=server_info.get("password"),
            timeout=10
        )
    return client


# --- Parsers ---
def _read_cpu_idle_total_line(line: str):
    """
    解析 /proc/stat 第一行：'cpu  user nice system idle iowait irq softirq steal guest guest_nice'
    回傳 (idle_all, total)；idle_all = idle + iowait；total = 全部欄位加總（含 steal 等）
    """
    parts = line.strip().split()
    if not parts or parts[0] != "cpu":
        return None, None
    nums = []
    for x in parts[1:]:
        try:
            nums.append(int(x))
        except Exception:
            nums.append(0)
    # 安全取值
    idle   = nums[3] if len(nums) > 3 else 0
    iowait = nums[4] if len(nums) > 4 else 0
    idle_all = idle + iowait
    total = sum(nums)
    return idle_all, total

def get_cpu_usage_percent(client, interval=0.5):
    """
    以 interval 秒為窗口，計算 CPU 使用率百分比。
    使用 (1 - (idle2-idle1)/(total2-total1)) * 100。
    """
    out1, _ = ssh_run_command(client, "head -n1 /proc/stat")
    idle1, total1 = _read_cpu_idle_total_line(out1)
    if idle1 is None or total1 is None:
        return None
    time.sleep(interval)
    out2, _ = ssh_run_command(client, "head -n1 /proc/stat")
    idle2, total2 = _read_cpu_idle_total_line(out2)
    if idle2 is None or total2 is None:
        return None
    totald = total2 - total1
    idled  = idle2 - idle1
    if totald <= 0:
        return None
    usage = (1.0 - (idled / totald)) * 100.0
    return round(usage, 2)

def parse_free(out):
    try:
        for line in out.splitlines():
            if line.lower().startswith("mem:") or line.lower().startswith("mem "):
                toks = line.split()
                total = int(toks[1])
                used = int(toks[2])
                return total, used
    except Exception:
        pass
    return None, None


def parse_df_bytes(out):
    """
    Parse `df -P -B1 -x tmpfs -x devtmpfs -x squashfs` (bytes).
    Returns (disks, total_bytes, used_bytes).
    """
    disks = []
    lines = out.strip().splitlines()
    if not lines:
        return disks, 0, 0

    for line in lines[1:]:
        toks = line.split()
        if len(toks) < 6:
            continue

        filesystem = toks[0]
        size = toks[1]
        used = toks[2]
        avail = toks[3]
        percent = toks[4]
        mount = " ".join(toks[5:])  # mount point 可能包含空白

        # 可選：再防呆排除 loop device（通常已被 -x squashfs 擋掉）
        if filesystem.startswith("/dev/loop"):
            continue

        try:
            size_i = int(size)
            used_i = int(used)
            avail_i = int(avail)
        except Exception:
            # 有些奇怪行無法轉數字，略過
            continue

        disks.append({
            "filesystem": filesystem,
            "size_bytes": size_i,
            "used_bytes": used_i,
            "avail_bytes": avail_i,
            "percent": percent,
            "mount": mount
        })

    total = sum(d["size_bytes"] for d in disks)
    used = sum(d["used_bytes"] for d in disks)
    return disks, total, used


def parse_nvidia_smi(out):
    # CSV 欄位：uuid,name,utilization.gpu,memory.total,memory.used,power.draw,power.limit (no units)
    gpus = []
    if not out:
        return gpus

    def to_float_safe(x):
        x = (x or "").strip()
        if x.upper() == "N/A" or x == "":
            return None
        try:
            return float(x)
        except Exception:
            return None

    for l in out.splitlines():
        parts = [p.strip() for p in l.split(",")]
        # 兼容舊版：可能只有前 5 欄
        uuid = parts[0] if len(parts) > 0 else ""
        name = parts[1] if len(parts) > 1 else ""
        util = to_float_safe(parts[2]) if len(parts) > 2 else None
        memt = to_float_safe(parts[3]) if len(parts) > 3 else None
        memu = to_float_safe(parts[4]) if len(parts) > 4 else None
        pdraw = to_float_safe(parts[5]) if len(parts) > 5 else None
        plimit = to_float_safe(parts[6]) if len(parts) > 6 else None

        gpus.append({
            "uuid": uuid,
            "name": name,
            "util": util,           # %
            "mem_total": memt,      # MB
            "mem_used": memu,       # MB
            "power_draw": pdraw,    # W
            "power_limit": plimit   # W
        })
    return gpus


def parse_nvidia_procs(out):
    """
    Parse: nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader,nounits
    Return: list of {gpu_uuid, pid(int), proc(str), mem_used(float)}
    """
    rows = []
    if not out:
        return rows
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            gpu_uuid, pid, pname, used_mem = parts[:4]
            try:
                pid = int(pid)
                used_mem = float(used_mem)
            except Exception:
                continue
            rows.append({
                "gpu_uuid": gpu_uuid,
                "pid": pid,
                "proc": pname,
                "mem_used": used_mem
            })
    return rows

def human_bytes(n):
    # for quick display (front端也會顯示細項, 這裡提供總覽)
    if n is None:
        return "-"
    for unit in ['B','KB','MB','GB','TB','PB']:
        if n < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}EB"


# --- Poll loop ---
def ensure_gpu_history(name, gpu_count):
    hist = metrics_store[name].setdefault("history", {})
    # create a deque per GPU
    ghist = hist.setdefault("gpus", [])
    # extend or shrink to match gpu_count
    while len(ghist) < gpu_count:
        ghist.append(deque(maxlen=HISTORY_LEN))
    while len(ghist) > gpu_count:
        ghist.pop()

user_fullname_cache = {}

def get_fullname_for_user(client, username):
    if username in user_fullname_cache:
        return user_fullname_cache[username]
    out, _ = ssh_run_command(client, f"getent passwd {username} | cut -d: -f5")
    fullname = out.strip() if out else ""
    user_fullname_cache[username] = fullname
    return fullname

def poll_server_loop(server_info):
    name = server_info.get("name") or server_info["host"]
    metrics_store.setdefault(name, {})
    while True:
        try:
            client = None
            try:
                client = connect_ssh(server_info)
            except Exception as e:
                err_msg = f"SSH connect error: {e}"
                # 標註離線狀態
                metrics_store[name]["online"] = False
                metrics_store[name]["last_error"] = err_msg

                # 推播統一結構，明確告知離線
                socketio.emit("server_update", {
                    "name": name,
                    "online": False,
                    "error": err_msg,
                    "metrics": None
                })
                time.sleep(POLL_INTERVAL)
                continue

            # 即時 CPU 使用率 (%)
            cpu_usage_pct = get_cpu_usage_percent(client, interval=0.5)
            
            # Memory (MB)
            out_free, _ = ssh_run_command(client, "free -m")
            mem_total, mem_used = parse_free(out_free)

            # Disks (bytes, aggregated)
            out_df, _ = ssh_run_command(client, "df -P -B1 -x tmpfs -x devtmpfs -x squashfs")
            disks, disk_total_b, disk_used_b = parse_df_bytes(out_df)
            disk_used_pct = round(disk_used_b / disk_total_b * 100, 2) if disk_total_b > 0 else None

            # GPUs
            out_gpu, err_gpu = ssh_run_command(
                client,
                "nvidia-smi --query-gpu=uuid,name,utilization.gpu,memory.total,memory.used,power.draw,power.limit --format=csv,noheader,nounits"
            )
            gpus = parse_nvidia_smi(out_gpu) if out_gpu and not err_gpu else []


            # GPU processes（所有 GPU）
            out_procs, _ = ssh_run_command(
                client,
                "nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader,nounits || true"
            )
            procs = parse_nvidia_procs(out_procs)
            
            # 把 pid -> user 一次查出（避免逐一 ps 太慢）
            out_ps, _ = ssh_run_command(client, "ps -eo pid=,user=")
            pid2user = {}
            for line in out_ps.splitlines():
                try:
                    pid_str, user = line.strip().split(None, 1)
                    pid2user[int(pid_str)] = user.strip()
                except Exception:
                    continue
                
            # 以 uuid 分組後「掛」回 gpus
            uuid2idx = {g.get("uuid"): i for i, g in enumerate(gpus)}
            for g in gpus:
                g["procs"] = []
            
            for r in procs:
                idx = uuid2idx.get(r["gpu_uuid"])
                if idx is None:
                    continue
                user = pid2user.get(r["pid"], "?")
                fullname = get_fullname_for_user(client, user) if user not in ("?", "") else ""
                r["user"] = user
                r["fullname"] = fullname
                gpus[idx]["procs"].append(r)

            # 也可以排序一下（記憶體使用量由大到小）
            for g in gpus:
                g["procs"].sort(key=lambda x: x["mem_used"], reverse=True)
            
            ts = datetime.utcnow().isoformat() + "Z"
            rec = {
                "last_update": ts,
                "cpu_usage_pct": cpu_usage_pct,   
                "mem_total_mb": mem_total,
                "mem_used_mb": mem_used,
                "disks": disks,
                "disk_total_bytes": disk_total_b,
                "disk_used_bytes": disk_used_b,
                "disk_used_pct": disk_used_pct,
                "disk_total_h": human_bytes(disk_total_b),
                "disk_used_h": human_bytes(disk_used_b),
                "gpus": gpus
            }

            # update store
            metrics_store[name]["online"] = True
            metrics_store[name]["last_error"] = None
            metrics_store[name].update(rec)

            # history per GPU util
            # history per GPU memory (MB)
            ensure_gpu_history(name, len(gpus))
            for idx, g in enumerate(gpus):
                metrics_store[name]["history"]["gpus"][idx].append({
                    "ts": ts,
                    "mem_used": g.get("mem_used", 0.0),   # MB
                    "mem_total": g.get("mem_total", 0.0)  # MB
                })

            # push realtime
            socketio.emit("server_update", {
                "name": name,
                "online": True,
                "error": None,
                "metrics": rec
            })
            client.close()
        except Exception as e:
            # 👉 外層出錯同樣代表本次採集失敗，必須明確標為離線
            err_msg = f"poll error: {e}\n{traceback.format_exc()}"
            metrics_store[name]["online"] = False
            metrics_store[name]["last_error"] = err_msg
            
            socketio.emit("server_update", {
                "name": name,
                "online": False,
                "error": err_msg,
                "metrics": None
            })
        finally:
            # 👉 確保無論成功或報錯，SSH 連線都會被乾淨關閉
            if client:
                try:
                    client.close()
                except Exception:
                    pass
        time.sleep(POLL_INTERVAL)


# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/servers")
def api_servers():
    snapshot = {}
    for k, v in metrics_store.items():
        is_online = v.get("online", False)
        history = v.get("history", {})
        gpu_hist = history.get("gpus", [])
        
        snapshot[k] = {
            "online": is_online,
            "last_error": v.get("last_error"),
            "last_update": v.get("last_update"),
            "cpu_usage_pct": v.get("cpu_usage_pct"),
            "mem_total_mb": v.get("mem_total_mb"),
            "mem_used_mb": v.get("mem_used_mb"),
            "disks": v.get("disks"),
            "disk_total_bytes": v.get("disk_total_bytes"),
            "disk_used_bytes": v.get("disk_used_bytes"),
            "disk_used_pct": v.get("disk_used_pct"),
            "disk_total_h": v.get("disk_total_h"),
            "disk_used_h": v.get("disk_used_h"),
            "gpus": v.get("gpus"),
            "history": {
                "gpus": [list(d) for d in gpu_hist]
            }
        }
    return jsonify(snapshot)


def start_pollers():
    with open(SERVERS_FILE, "r") as f:
        servers = json.load(f)
    for s in servers:
        name = s.get("name") or s["host"]
        metrics_store.setdefault(name, {})
        t = threading.Thread(target=poll_server_loop, args=(s,), daemon=True)
        t.start()


if __name__ == "__main__":
    start_pollers()
    socketio.run(app, host="0.0.0.0", port=5000, use_reloader=False)
