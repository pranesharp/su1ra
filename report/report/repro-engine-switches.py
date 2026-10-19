"""Verify the two independent engine switches (engine_vulkan / engine_igpu):
hard on/off env in auto+gpu modes, all-off block in cpu, settings round-trip.
Run with APPDATA redirected (done below) so the real DB is untouched.
"""
import os, sys, tempfile, shutil
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="su1ra-enginesw-")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store
store.init_db()

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails.append(name)

import ollama
from fastapi.testclient import TestClient
import main
client = TestClient(main.app)

def env():
    return ollama.engine_env()

# fresh DB: both switches default off
store.set_setting("engine", "gpu")
check("gpu + both off -> both 0",
      env() == {"OLLAMA_VULKAN": "0", "OLLAMA_IGPU_ENABLE": "0"}, str(env()))

# the friend's RX 580 case: vulkan on, igpu off
store.set_setting("engine_vulkan", "1")
check("gpu + vulkan only -> VULKAN=1 IGPU=0",
      env() == {"OLLAMA_VULKAN": "1", "OLLAMA_IGPU_ENABLE": "0"}, str(env()))

# the owner's Arrow Lake case: both on (iGPU is the only gpu)
store.set_setting("engine_igpu", "1")
check("gpu + both on -> VULKAN=1 IGPU=1",
      env() == {"OLLAMA_VULKAN": "1", "OLLAMA_IGPU_ENABLE": "1"}, str(env()))

# igpu without vulkan: legal but pointless — switches stay independent
store.set_setting("engine_vulkan", "0")
check("gpu + igpu only -> VULKAN=0 IGPU=1",
      env() == {"OLLAMA_VULKAN": "0", "OLLAMA_IGPU_ENABLE": "1"}, str(env()))

# switches apply in AUTO mode too (hard switches, not gpu-mode-only)
store.set_setting("engine", "auto")
store.set_setting("engine_vulkan", "1")
store.set_setting("engine_igpu", "0")
check("auto + vulkan only -> same as gpu",
      env() == {"OLLAMA_VULKAN": "1", "OLLAMA_IGPU_ENABLE": "0"}, str(env()))
store.set_setting("engine_vulkan", "0")
check("auto + both off -> explicit 0s (not stock defaults)",
      env() == {"OLLAMA_VULKAN": "0", "OLLAMA_IGPU_ENABLE": "0"}, str(env()))

# cpu still hides every backend regardless of the switches
store.set_setting("engine", "cpu")
store.set_setting("engine_vulkan", "1")
store.set_setting("engine_igpu", "1")
check("cpu ignores switches -> all off",
      env() == {"CUDA_VISIBLE_DEVICES": "-1", "HIP_VISIBLE_DEVICES": "-1",
                "ROCR_VISIBLE_DEVICES": "-1", "OLLAMA_VULKAN": "0",
                "GGML_VK_VISIBLE_DEVICES": "-1"}, str(env()))

# settings API round-trip for the new key
client = client
r = client.patch("/api/settings", json={"engine_igpu": True})
check("PATCH engine_igpu=true", r.status_code == 200)
r = client.get("/api/settings")
check("GET engine_igpu true", r.json().get("engine_igpu") is True, str(r.json().get("engine_igpu")))
r = client.patch("/api/settings", json={"engine_igpu": False})
check("PATCH engine_igpu=false", r.status_code == 200)
r = client.get("/api/settings")
check("GET engine_igpu false", r.json().get("engine_igpu") is False)
r = client.patch("/api/settings", json={})
check("PATCH empty -> 422 nothing to update", r.status_code == 422)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL: {fails}'}")
sys.exit(1 if fails else 0)
