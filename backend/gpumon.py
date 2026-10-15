"""Vendor-agnostic per-GPU utilization for the sysmon widget. Pure stdlib.

Windows: the WDDM performance counters (what Task Manager uses) — works for
Intel / AMD / NVIDIA alike, including iGPUs driven through Vulkan.
  - adapters: DXGI EnumAdapters1 (name, vendor, dedicated mem, LUID); the
    software "Basic Render Driver" is skipped.
  - usage: PDH "\\GPU Engine(*)\\Utilization Percentage" — summed per engine
    across processes, adapter usage = busiest engine (Task Manager's rule).
  - memory: PDH "\\GPU Adapter Memory(*)\\{Dedicated,Shared} Usage" (bytes).
Linux: AMD via sysfs gpu_busy_percent, NVIDIA via nvidia-smi. Intel iGPU
usage on Linux needs root (intel_gpu_top) — not offered.

Ordering: integrated GPUs first (index 0 = the iGPU), then discrete, each in
the OS enumeration order. sample() is blocking — call it from a worker thread.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

_INTEGRATED_MAX_DEDICATED = 1 << 30  # < 1 GiB dedicated VRAM = integrated


def _sort_key(g):
    return (0 if g.get("integrated") else 1, g["_order"])


def _public(gpus):
    out = []
    for g in sorted(gpus, key=_sort_key):
        out.append({k: v for k, v in g.items() if not k.startswith("_")})
    return out


# --------------------------------------------------------------- Windows ----
class _WinGpuMon:
    def __init__(self):
        import ctypes
        import ctypes.wintypes as wt

        self.ct = ctypes
        self.adapters = self._enum_adapters()
        pdh = ctypes.windll.pdh
        self.pdh = pdh
        self.query = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) != 0:
            raise OSError("PdhOpenQuery failed")
        self.counters = {}
        for key, path in (
            ("util", r"\GPU Engine(*)\Utilization Percentage"),
            ("ded", r"\GPU Adapter Memory(*)\Dedicated Usage"),
            ("shared", r"\GPU Adapter Memory(*)\Shared Usage"),
        ):
            h = ctypes.c_void_p()
            if pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(h)) == 0:
                self.counters[key] = h
        if "util" not in self.counters:
            raise OSError("GPU Engine counters unavailable")

        class _Val(ctypes.Structure):
            _fields_ = [("CStatus", wt.DWORD), ("d", ctypes.c_double)]

        class _Item(ctypes.Structure):
            _fields_ = [("name", ctypes.c_wchar_p), ("v", _Val)]

        self._Item = _Item
        pdh.PdhCollectQueryData(self.query)  # rate counters need a baseline

    def _enum_adapters(self):
        ct = self.ct
        wt = ct.wintypes

        class LUID(ct.Structure):
            _fields_ = [("Low", wt.DWORD), ("High", wt.LONG)]

        class DESC1(ct.Structure):
            _fields_ = [
                ("Description", ct.c_wchar * 128),
                ("VendorId", ct.c_uint),
                ("DeviceId", ct.c_uint),
                ("SubSysId", ct.c_uint),
                ("Revision", ct.c_uint),
                ("DedicatedVideoMemory", ct.c_size_t),
                ("DedicatedSystemMemory", ct.c_size_t),
                ("SharedSystemMemory", ct.c_size_t),
                ("AdapterLuid", LUID),
                ("Flags", ct.c_uint),
            ]

        class GUID(ct.Structure):
            _fields_ = [
                ("a", ct.c_uint32),
                ("b", ct.c_uint16),
                ("c", ct.c_uint16),
                ("d", ct.c_ubyte * 8),
            ]

        def vcall(obj, idx, restype, *argtypes):
            vtbl = ct.cast(ct.cast(obj, ct.POINTER(ct.c_void_p))[0], ct.POINTER(ct.c_void_p))
            return ct.WINFUNCTYPE(restype, ct.c_void_p, *argtypes)(vtbl[idx])

        # IID_IDXGIFactory1 {770aae78-f26f-4dba-a829-253c83d1b387}
        iid = GUID(0x770AAE78, 0xF26F, 0x4DBA,
                   (ct.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
        factory = ct.c_void_p()
        if ct.windll.dxgi.CreateDXGIFactory1(ct.byref(iid), ct.byref(factory)) != 0:
            raise OSError("CreateDXGIFactory1 failed")
        adapters = {}
        try:
            i = 0
            while i < 16:
                ad = ct.c_void_p()
                # IDXGIFactory1::EnumAdapters1 = vtable slot 12
                if vcall(factory, 12, ct.c_long, ct.c_uint, ct.POINTER(ct.c_void_p))(
                    factory, i, ct.byref(ad)
                ) != 0:
                    break
                d = DESC1()
                # IDXGIAdapter1::GetDesc1 = slot 10; IUnknown::Release = slot 2
                vcall(ad, 10, ct.c_long, ct.POINTER(DESC1))(ad, ct.byref(d))
                vcall(ad, 2, ct.c_ulong)(ad)
                if not (d.Flags & 2):  # DXGI_ADAPTER_FLAG_SOFTWARE
                    luid = "0x%08x_0x%08x" % (d.AdapterLuid.High & 0xFFFFFFFF, d.AdapterLuid.Low)
                    if luid not in adapters:  # one entry per physical adapter
                        adapters[luid] = {
                            "name": d.Description.strip(),
                            "integrated": d.DedicatedVideoMemory < _INTEGRATED_MAX_DEDICATED,
                            "_order": i,
                        }
                i += 1
        finally:
            vcall(factory, 2, ct.c_ulong)(factory)
        return adapters

    def _array(self, key):
        ct = self.ct
        h = self.counters.get(key)
        if h is None:
            return []
        size, count = ct.wintypes.DWORD(0), ct.wintypes.DWORD(0)
        fmt = 0x00000200 | 0x00008000  # PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        self.pdh.PdhGetFormattedCounterArrayW(h, fmt, ct.byref(size), ct.byref(count), None)
        if not size.value:
            return []
        buf = (ct.c_byte * size.value)()
        if self.pdh.PdhGetFormattedCounterArrayW(h, fmt, ct.byref(size), ct.byref(count), buf) != 0:
            return []
        items = ct.cast(buf, ct.POINTER(self._Item))
        return [(items[k].name or "", items[k].v.d) for k in range(count.value)
                if items[k].v.CStatus in (0, 1)]  # PDH_CSTATUS_VALID_DATA / NEW_DATA

    _LUID_RE = re.compile(r"luid_(0x[0-9a-f]+)_(0x[0-9a-f]+)_phys_(\d+)(?:_eng_(\d+))?", re.I)

    def _luid(self, m):
        return "0x%08x_0x%08x" % (int(m.group(1), 16), int(m.group(2), 16))

    def sample(self):
        if self.pdh.PdhCollectQueryData(self.query) != 0:
            return None
        engines = {}
        for name, val in self._array("util"):
            m = self._LUID_RE.search(name)
            if m:
                k = (self._luid(m), m.group(3), m.group(4))
                engines[k] = engines.get(k, 0.0) + val
        util = {}
        for (luid, _phys, _eng), v in engines.items():
            util[luid] = max(util.get(luid, 0.0), v)
        mem = {}
        for key in ("ded", "shared"):
            for name, val in self._array(key):
                m = self._LUID_RE.search(name)
                if m:
                    mem[self._luid(m)] = mem.get(self._luid(m), 0.0) + val
        gpus = []
        for luid, a in self.adapters.items():
            u = util.get(luid)
            gpus.append({
                **a,
                "util": None if u is None else max(0.0, min(100.0, u)),
                "mem_gb": round(mem[luid] / 2**30, 2) if luid in mem else None,
            })
        return _public(gpus)


# ----------------------------------------------------------------- Linux ----
_nvsmi = None


def _nvidia_rows():
    global _nvsmi
    if _nvsmi is None:
        _nvsmi = shutil.which("nvidia-smi") or ""
    if not _nvsmi:
        return []
    try:
        out = subprocess.run(
            [_nvsmi, "--query-gpu=name,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:
        return []
    rows = []
    for i, line in enumerate(out.splitlines()):
        vals = [v.strip() for v in line.split(",")]
        if len(vals) < 3:
            continue
        try:
            util = float(vals[1])
        except ValueError:
            util = None
        try:
            mem = round(float(vals[2]) / 1024, 2)
        except ValueError:
            mem = None
        rows.append({"name": vals[0], "integrated": False, "util": util,
                     "mem_gb": mem, "_order": 100 + i})
    return rows


def _linux_sample():
    gpus = []
    for i, path in enumerate(sorted(glob.glob("/sys/class/drm/card[0-9]*/device/gpu_busy_percent"))):
        dev = os.path.dirname(path)
        try:
            with open(path) as f:
                util = float(f.read().strip())
        except Exception:
            continue
        integrated = True
        try:
            with open(os.path.join(dev, "mem_info_vram_total")) as f:
                integrated = int(f.read().strip()) < _INTEGRATED_MAX_DEDICATED
        except Exception:
            pass
        mem = None
        try:
            with open(os.path.join(dev, "mem_info_vram_used")) as f:
                mem = round(int(f.read().strip()) / 2**30, 2)
        except Exception:
            pass
        gpus.append({"name": "AMD GPU", "integrated": integrated, "util": util,
                     "mem_gb": mem, "_order": i})
    gpus.extend(_nvidia_rows())
    return _public(gpus)


# ------------------------------------------------------------------ API -----
_mon = None
_failed = False


def sample():
    """List of {name, integrated, util (0-100|None), mem_gb (|None)}, iGPU
    first. [] when no GPU source exists. Never raises."""
    global _mon, _failed
    try:
        if os.name == "nt":
            if _failed:
                return []
            if _mon is None:
                try:
                    _mon = _WinGpuMon()
                except Exception:
                    _failed = True
                    return []
            return _mon.sample() or []
        return _linux_sample()
    except Exception:
        return []
