import os
import json
import time
import tempfile
import fcntl
import requests
import asyncio
import math
import collections
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager

load_dotenv()

INVENTORY_FILE = os.path.join(os.path.dirname(__file__), "inventory.json")

# 文件锁，保护 inventory.json 的并发读写
_inventory_lock = asyncio.Lock()

def load_data():
    """加载库存数据。若文件不存在，则从 example 初始化或创建默认结构。"""
    if not os.path.exists(INVENTORY_FILE):
        example_file = INVENTORY_FILE + ".example"
        if os.path.exists(example_file):
            print(f"📦 初始化: 从 {os.path.basename(example_file)} 创建 inventory.json")
            try:
                with open(example_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                save_data(data) # 自动创建初始文件
                return data
            except Exception as e:
                print(f"⚠️ 无法从示例初始化库存: {e}")
        
        # 兜底：创建空结构
        default_data = {"items": [], "groups": {}}
        save_data(default_data)
        return default_data

    try:
        with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)  # 共享锁（读锁）
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
        
        if isinstance(data, list):
            # Migration: Convert list to object format
            return {"items": data, "groups": {}}
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ [数据加载异常] inventory.json 读取失败: {e}")
        return {"items": [], "groups": {}}


def save_data(data):
    """原子写入：先写临时文件再 rename，防止并发写入导致数据损坏"""
    dir_name = os.path.dirname(INVENTORY_FILE)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp", prefix="inventory_")
        with os.fdopen(fd, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)  # 排他锁（写锁）
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # 确保数据落盘
            fcntl.flock(f, fcntl.LOCK_UN)
        os.rename(tmp_path, INVENTORY_FILE)  # 原子替换
    except Exception as e:
        print(f"❌ [数据保存异常] inventory.json 写入失败: {e}")
        # 清理可能残留的临时文件
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)

# --- Constants and Configuration ---
HA_URL = os.getenv("HA_URL", "http://192.168.2.200:8123")
HA_TOKEN = os.getenv("HA_TOKEN")
TEMP_ENTITY_ID = os.getenv("TEMP_ENTITY_ID", "sensor.miaomiaoce_t2_aabf_temperature")

COUNT_ENTITY = "sensor.fang_jian_duo_mu_biao_lei_da_dang_qian_ren_shu"
TARGETS = [1, 2, 3]
ENTITIES = {
    t: {
        "x": f"sensor.fang_jian_duo_mu_biao_lei_da_mu_biao_{t}_xzhou",
        "y": f"sensor.fang_jian_duo_mu_biao_lei_da_mu_biao_{t}_yzhou",
        "v": f"sensor.fang_jian_duo_mu_biao_lei_da_mu_biao_{t}_su_du"
    } for t in TARGETS
}

# Calibration Parameters (可通过 .env 覆盖)
RADAR_X = float(os.getenv("RADAR_X", "0.0"))
RADAR_Y = float(os.getenv("RADAR_Y", "0.5"))
RADAR_ROTATION = math.radians(float(os.getenv("RADAR_ROTATION", "135.0")))
RADAR_SWAP_XY = os.getenv("RADAR_SWAP_XY", "true").lower() in ("true", "1", "yes")
RADAR_SCALE = float(os.getenv("RADAR_SCALE", "1.2"))
RADAR_MIRROR_X = os.getenv("RADAR_MIRROR_X", "true").lower() in ("true", "1", "yes")
RADAR_MIRROR_Y = os.getenv("RADAR_MIRROR_Y", "false").lower() in ("true", "1", "yes")

# [PROACTIVE CONFIG]
AGENT_API_URL = "http://localhost:8642/v1/chat/completions"
AGENT_TOKEN = os.getenv("API_SERVER_KEY", "your_token_here")


# --- ZONES CONFIGURATION ---
# display: 前端显示的视觉边框
# active:  逻辑判定的感应区域（略大于显示区，补偿漂移）



# --- Zone Configuration (Externalized) ---
def load_zones():
    import json
    base_path = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_path, "zones.json")
    example_path = os.path.join(base_path, "zones.json.example")
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading zones.json: {e}")
    
    if os.path.exists(example_path):
        print("Using zones.json.example as fallback.")
        try:
            with open(example_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading zones.json.example: {e}")
            
    return {}

ZONES = load_zones()


# --- Global State ---
current_data = {"targets": [], "count": 0}
TRAIL_HISTORY = collections.deque(maxlen=1000)
current_zone = None
zone_start_time = 0
current_threshold = 0   # 动态阈值，随提醒次数增加
last_trigger_time = {} # Cooldown per zone
last_temp = "未知"    # 最近获取的室内温度

# --- Logic Functions ---

def trigger_agent_proactive(zone_id, duration_sec):
    """雷达发现情况，通知语音终端进行处理"""
    now = time.time()
    if now - last_trigger_time.get(zone_id, 0) < 120: # 120s 冷却
        return

    desc = ZONES[zone_id]["desc"]
    curr_time = time.strftime("%H:%M")
    ctx_prompt = f"[系统感知] 现在是 {curr_time}，室内温度 {last_temp}℃。用户已经在 {desc} 持续居留超过 {int(duration_sec/60)} 分钟了。请主动发出一句简短贴心的问候或建议。"
    
    try:
        # 委托给语音终端处理
        resp = requests.post("http://localhost:8000/v1/audio/proactive", json={"input": ctx_prompt}, timeout=5)
        if resp.status_code == 200:
            print(f"🚀 [主动感知] 已通知语音终端处理区域事件: {zone_id}")
            last_trigger_time[zone_id] = now
            return True
        else:
            print(f"❌ 语音终端拒绝请求: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ 与语音终端通讯异常: {e}")
        return False

def safe_float(val, default=0.0):
    try:
        if val in [None, "unknown", "unavailable", ""]:
            return default
        return float(val)
    except (ValueError, TypeError):
        return default

def update_ha_states():
    global current_zone, zone_start_time, last_temp, current_threshold, current_data
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(f"{HA_URL}/api/states", headers=headers, timeout=1)
        if resp.status_code == 200:
            state_map = {s['entity_id']: s['state'] for s in resp.json()}
            data = []
            
            # 安全转义人数
            reported_count = int(safe_float(state_map.get(COUNT_ENTITY)))
            
            if TEMP_ENTITY_ID in state_map:
                last_temp = state_map[TEMP_ENTITY_ID]

            for idx, t in enumerate(TARGETS):
                x = state_map.get(ENTITIES[t]["x"], "unknown")
                y = state_map.get(ENTITIES[t]["y"], "unknown")
                v = state_map.get(ENTITIES[t]["v"], 0)
                
                if x not in ["unknown", "unavailable"] and y not in ["unknown", "unavailable"]:
                    try:
                        orig_lx, orig_ly = safe_float(x)/1000.0, safe_float(y)/1000.0
                        lx, ly = (orig_ly, orig_lx) if RADAR_SWAP_XY else (orig_lx, orig_ly)
                        rx = lx * math.cos(RADAR_ROTATION) - ly * math.sin(RADAR_ROTATION)
                        ry = lx * math.sin(RADAR_ROTATION) + ly * math.cos(RADAR_ROTATION)
                        mx, my = (-1.0 if RADAR_MIRROR_X else 1.0), (-1.0 if RADAR_MIRROR_Y else 1.0)
                        final_x, final_y = (rx * RADAR_SCALE * mx) + RADAR_X, (ry * RADAR_SCALE * my) + RADAR_Y

                        point = {"id": t, "x": final_x, "y": final_y, "v": float(v)/100.0}
                        data.append(point)
                        
                        if idx == 0:
                            TRAIL_HISTORY.append(point)
                            found_zone = None
                            for zid, zconfig in ZONES.items():
                                z_active = zconfig["active"]
                                if z_active["x"][0] <= final_x <= z_active["x"][1] and z_active["y"][0] <= final_y <= z_active["y"][1]:
                                    found_zone = zid
                                    break
                            
                            now = time.time()
                            if found_zone == current_zone:
                                if current_zone in ["STUDY", "SOFA"]:
                                    stay_duration = now - zone_start_time
                                    if stay_duration > current_threshold:
                                        if trigger_agent_proactive(current_zone, stay_duration):
                                            zone_start_time = now
                                            current_threshold += 300
                                            print(f"📈 [增加延迟] 下次提醒将增加到 {int(current_threshold/60)} 分钟")
                                else:
                                    # Reset timer if staying in non-proactive zone
                                    pass
                            else:
                                current_zone = found_zone
                                zone_start_time = now
                                if current_zone in ["STUDY", "SOFA"]:
                                    current_threshold = ZONES[current_zone]["threshold"]
                                    print(f"📍 [区域切换] 进入感知区 {current_zone}，初始阈值 {int(current_threshold/60)} 分钟")
                                else:
                                    current_threshold = 0
                                    if current_zone:
                                        print(f"📍 [区域切换] 进入观察区 {current_zone} (不主动提醒)")
                    except Exception as e:
                        print(f"⚠️ [逻辑错误] 处理目标 {t} 时发生异常: {e}")
            current_data = {"targets": data, "count": reported_count}
            return current_data
    except Exception as e:
        print(f"🚨 [HA通讯错误] 无法获取状态: {e}")
    current_data = {"targets": [], "count": 0}
    return current_data

async def radar_background_task():
    """独立于前端的后台感知任务"""
    print("🛰️ [系统] 雷达感知后台任务已启动")
    while True:
        try:
            await asyncio.to_thread(update_ha_states)
        except Exception as e:
            print(f"❌ 后台任务异常: {e}")
        await asyncio.sleep(0.15)

# --- FastAPI Lifecycle & App Initialization ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动后台任务
    task = asyncio.create_task(radar_background_task())
    yield
    # 清理逻辑
    task.cancel()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routes ---

@app.get("/")
async def get_radar_view():
    html_path = os.path.join(os.path.dirname(__file__), "radar_view.html")
    return FileResponse(html_path)

@app.get("/api/radar/zones")
async def get_radar_zones():
    return ZONES

@app.get("/api/radar/stream")
async def stream_radar():
    async def event_generator():
        # 1. Send history first
        if TRAIL_HISTORY:
            history_data = {"type": "history", "points": list(TRAIL_HISTORY)}
            yield f"data: {json.dumps(history_data)}\n\n"

        # 2. Start live streaming
        while True:
            data = current_data.copy()
            data["type"] = "live"
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(0.2)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Inventory Endpoints ---

@app.get("/api/inventory")
async def get_inventory():
    data = load_data()
    items = data.get("items", [])
    # Dynamically inject zone information
    for item in items:
        ix, iy = item.get("x"), item.get("y")
        item["zone"] = "UNKNOWN"
        item["zone_label"] = "未知区域"
        if ix is not None and iy is not None:
            for zid, zconfig in ZONES.items():
                z_active = zconfig["active"]
                if z_active["x"][0] <= ix <= z_active["x"][1] and z_active["y"][0] <= iy <= z_active["y"][1]:
                    item["zone"] = zid
                    item["zone_label"] = zconfig.get("label", zid)
                    break
    return items

@app.post("/api/inventory")
async def add_inventory_item(item: dict):
    data = load_data()
    if "id" not in item:
        item["id"] = f"inv_{int(time.time() * 1000)}"
    data["items"].append(item)
    save_data(data)
    return item

@app.put("/api/inventory/{item_id}")
async def update_inventory_item(item_id: str, updated_item: dict):
    data = load_data()
    items = data.get("items", [])
    target_item = None
    for i, item in enumerate(items):
        if item.get("id") == item_id:
            items[i].update(updated_item)
            target_item = items[i]
            break
    
    if target_item:
        # SYNC LOGIC: If item belongs to a group, update all other members
        gid = target_item.get("groupId")
        if gid:
            for item in items:
                if item.get("groupId") == gid and item.get("id") != item_id:
                    item["x"] = target_item["x"]
                    item["y"] = target_item["y"]
        
        save_data(data)
        return target_item
    return {"error": "Item not found"}

@app.get("/api/groups")
async def get_groups():
    data = load_data()
    return data.get("groups", {})

@app.put("/api/groups/{group_id}")
async def update_group(group_id: str, group_data: dict):
    data = load_data()
    if "groups" not in data: data["groups"] = {}
    data["groups"][group_id] = group_data
    save_data(data)
    return data["groups"][group_id]

@app.delete("/api/inventory/{item_id}")
async def delete_inventory_item(item_id: str):
    data = load_data()
    data["items"] = [item for item in data.get("items", []) if item.get("id") != item_id]
    save_data(data)
    return {"status": "deleted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8008)
