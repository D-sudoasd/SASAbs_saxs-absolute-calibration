import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import argparse
import sys
import numpy as np
import fabio
import pyFAI
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from pathlib import Path
import traceback
import math
import pandas as pd
import datetime
import re
import json
import concurrent.futures
import threading
from types import SimpleNamespace

try:
    from saxs_ui_kit import apply_ios_theme, promote_primary_buttons, toggle_theme, ToolTip
except Exception:
    def apply_ios_theme(root):
        return None

    def promote_primary_buttons(root):
        return None

    def toggle_theme(root):
        return None

    class ToolTip:
        def __init__(self, widget, text):
            self.widget = widget
            self.text = text

try:
    from saxs_core import load_session, session_geometry
except Exception:
    def load_session(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def session_geometry(session_payload):
        if not isinstance(session_payload, dict):
            return {}
        geom = session_payload.get("geometry", {})
        return geom if isinstance(geom, dict) else {}

try:
    import saxs_mpl_style
except Exception:
    class _SaxsMplStyleFallback:
        @staticmethod
        def apply_nature_style():
            return None

    saxs_mpl_style = _SaxsMplStyleFallback()

_SRC_DIR = Path(__file__).resolve().parent / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from saxsabs.core.calibration import estimate_k_factor_robust
except Exception:
    estimate_k_factor_robust = None

# --- 物理常数 ---
NIST_SRM3600_DATA = np.array([
    [0.008, 35.0], [0.010, 34.2], [0.020, 30.8], [0.030, 28.8], 
    [0.040, 27.5], [0.050, 26.8], [0.060, 26.3], [0.080, 25.4], 
    [0.100, 23.6], [0.120, 20.8], [0.150, 15.8], [0.180, 10.9],
    [0.200, 8.4],  [0.220, 6.5],  [0.250, 4.2]
])

# 30 keV 估算值
XCOM_30KEV = {
    "Ti": 1.17, "V": 1.54, "Al": 0.11, "Nb": 7.56, "Zr": 7.15,
    "Sn": 11.23, "Mo": 6.05, "Fe": 2.26, "Ni": 3.01, "Cr": 1.58, "Cu": 3.44
}

FLOAT_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
HC_KEV_A = 12.398419843320025  # E(keV) * lambda(A)
MONITOR_NORM_MODES = ("rate", "integrated")

class BL19B2_RobustApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BL19B2 SAXS Workstation v8.1 (Error Bars)")
        self.root.geometry("1280x900")
        
        # Apply Nature style globally
        saxs_mpl_style.apply_nature_style()
        
        self.set_style()
        self._tooltips = []
        
        # Top bar for theme toggle
        top_bar = ttk.Frame(self.root)
        top_bar.pack(fill="x", padx=10, pady=(10, 0))
        top_bar.columnconfigure(0, weight=1)
        ttk.Label(top_bar, text="SAXS Absolute Intensity Calibration", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(top_bar, text="🌓 切换深色/浅色模式", command=lambda: toggle_theme(self.root)).grid(row=0, column=1, sticky="e")
        
        # === 全局共享状态 ===
        self.global_vars = {
            "k_factor": tk.DoubleVar(value=1.0),
            "poni_path": tk.StringVar(),
            "bg_path": tk.StringVar(),
            "dark_path": tk.StringVar(),
            "bg_exp": tk.DoubleVar(value=1.0),
            "bg_i0": tk.DoubleVar(value=1.0),
            "bg_t": tk.DoubleVar(value=1.0),
            "monitor_mode": tk.StringVar(value="rate"),
            "apply_solid_angle": tk.BooleanVar(value=True),
            "k_solid_angle": tk.StringVar(value="unknown"),
        }
        self.session_geometry_fallback = {}

        # === 布局 ===
        self.nb = ttk.Notebook(root)
        self.nb.pack(expand=1, fill="both")

        self.tab1 = ttk.Frame(self.nb)
        self.tab2 = ttk.Frame(self.nb)
        self.tab3 = ttk.Frame(self.nb)
        self.tab_help = ttk.Frame(self.nb)

        self.nb.add(self.tab1, text="1. K-Factor Calibration (稳健标定)")
        self.nb.add(self.tab2, text="2. Batch Processing (2D运算+误差棒)")
        self.nb.add(self.tab3, text="3. External 1D -> Abs")
        self.nb.add(self.tab_help, text="4. Help (新手指南)")

        self.init_tab1_k_calc()
        self.init_tab2_batch()
        self.init_tab3_external_1d()
        self.init_tab_help()
        promote_primary_buttons(self.root)

    def set_style(self):
        apply_ios_theme(self.root)
        style = ttk.Style()
        try: style.theme_use("clam")
        except: pass
        style.configure("Bold.TLabel", font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 11, "bold"), foreground="#2c3e50")
        style.configure("Group.TLabelframe.Label", font=("Segoe UI", 9, "bold"), foreground="#2980b9")
        style.configure("Hint.TLabel", font=("Segoe UI", 8), foreground="#4f5b66")

    def add_tooltip(self, widget, text):
        if widget is None or not text:
            return
        self._tooltips.append(ToolTip(widget, text))

    def add_hint(self, parent, text, wraplength=420):
        lbl = ttk.Label(parent, text=f"注释: {text}", style="Hint.TLabel", justify="left", wraplength=wraplength)
        lbl.pack(fill="x", padx=3, pady=(1, 3))
        return lbl

    # =========================================================================
    # 核心解析器
    # =========================================================================
    def _norm_key(self, key):
        return str(key).strip().lower().replace("_", "").replace(" ", "")

    def _extract_float(self, value):
        if value is None:
            return None
        if isinstance(value, (int, float, np.number)):
            return float(value)

        s = str(value).strip()
        if not s:
            return None

        # 支持欧洲小数逗号，避免 "0,85" 无法解析
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")

        m = FLOAT_PATTERN.search(s)
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    def _normalize_transmission(self, trans, raw=None, key=None):
        if trans is None:
            return None
        t = float(trans)
        raw_s = str(raw).strip().lower() if raw is not None else ""
        key_s = self._norm_key(key) if key is not None else ""

        # 透过率归一化策略：
        # 1) 明确百分号/percent/pct -> 按百分数处理
        # 2) 1.0~2.0 视为轻微漂移，夹紧到 1.0（避免把 1.25 误判成 1.25%）
        # 3) 2.0~100 视作百分数字面量（如 85 -> 0.85）
        has_pct_hint = (
            "%" in raw_s
            or "percent" in raw_s
            or "pct" in raw_s
            or "percent" in key_s
            or "pct" in key_s
        )
        if has_pct_hint:
            t /= 100.0
        elif 1.0 < t <= 2.0:
            # 移除激进截断，保留物理真实性
            pass
        elif 2.0 < t <= 100.0:
            t /= 100.0
        return t

    def _assert_same_shape(self, a, b, a_name, b_name):
        if a.shape != b.shape:
            raise ValueError(f"Shape mismatch: {a_name}{a.shape} vs {b_name}{b.shape}")

    def get_monitor_mode(self):
        mode = str(self.global_vars["monitor_mode"].get()).strip().lower()
        if mode not in MONITOR_NORM_MODES:
            raise ValueError(f"I0 归一化模式仅支持: {', '.join(MONITOR_NORM_MODES)}")
        return mode

    def monitor_norm_formula(self, mode):
        if mode == "rate":
            return "exp * I0 * T"
        if mode == "integrated":
            return "I0 * T"
        raise ValueError(f"未知 I0 归一化模式: {mode}")

    def compute_norm_factor(self, exp, mon, trans, mode):
        if mon is None or trans is None:
            return np.nan
        try:
            mon_v = float(mon)
            trans_v = float(trans)
        except Exception:
            return np.nan

        if not (np.isfinite(mon_v) and np.isfinite(trans_v)):
            return np.nan
        if mon_v <= 0 or trans_v <= 0:
            return np.nan

        if mode == "rate":
            if exp is None:
                return np.nan
            try:
                exp_v = float(exp)
            except Exception:
                return np.nan
            if not np.isfinite(exp_v) or exp_v <= 0:
                return np.nan
            return exp_v * mon_v * trans_v

        if mode == "integrated":
            return mon_v * trans_v

        raise ValueError(f"未知 I0 归一化模式: {mode}")

    def parse_header(self, filepath, header_dict=None):
        meta = {}

        def add_meta(k, v):
            if k is None or v is None:
                return
            nk = self._norm_key(k)
            if nk:
                meta[nk] = str(v).strip()

        exp_keys = ["exposuretime", "counttime", "acqtime", "exposure", "time"]
        mon_keys = ["monitor", "beammonitor", "ionchamber", "mon", "i0", "flux"]
        trans_keys = ["sampletransmission", "transmission", "trans", "abs"]
        exp_exact_only = {"time"}
        mon_exact_only = {"mon", "i0"}
        trans_exact_only = {"abs"}

        def get_val(keys, exact_only=None):
            exact_only = set(exact_only or [])
            # 1) exact
            for k in keys:
                if k in meta:
                    return meta[k], k

            # 2) prefix/suffix（避免通配 contains 误命中）
            for mk, mv in meta.items():
                for k in keys:
                    if k in exact_only:
                        continue
                    if mk.startswith(k) or mk.endswith(k):
                        return mv, mk

            # 3) contains 仅用于较长关键字
            for mk, mv in meta.items():
                for k in keys:
                    if k in exact_only or len(k) < 6:
                        continue
                    if k in mk:
                        return mv, mk
            return None, None

        def has_keys():
            exp_raw, _ = get_val(exp_keys, exact_only=exp_exact_only)
            mon_raw, _ = get_val(mon_keys, exact_only=mon_exact_only)
            trans_raw, _ = get_val(trans_keys, exact_only=trans_exact_only)
            return (exp_raw is not None) and (mon_raw is not None) and (trans_raw is not None)

        # 优先读取 FabIO header（对 tiff/edf 更稳健）
        need_text_fallback = True
        if header_dict is not None:
            for k, v in header_dict.items():
                add_meta(k, v)
            need_text_fallback = not has_keys()
        else:
            try:
                img = fabio.open(filepath)
                for k, v in getattr(img, "header", {}).items():
                    add_meta(k, v)
                need_text_fallback = not has_keys()
            except Exception:
                need_text_fallback = True

        # 回退：从文件文本头提取
        if need_text_fallback:
            try:
                with open(filepath, "rb") as f:
                    head_bytes = f.read(65536)
                # 某些 TIFF 头字段由 NUL 分隔，先替换可降低键值粘连风险
                head_str = head_bytes.decode("utf-8", errors="ignore").replace("\x00", "\n")
                for line in head_str.splitlines():
                    line = line.strip().lstrip("#").strip()
                    if not line:
                        continue
                    parts = []
                    if "=" in line:
                        parts = line.split("=", 1)
                    elif ":" in line:
                        parts = line.split(":", 1)
                    else:
                        parts = line.split(None, 1)
                    if len(parts) == 2:
                        k = str(parts[0]).strip()
                        # 限制 key 形态，降低从二进制噪声中误解析的概率
                        if not re.match(r"^[A-Za-z_][A-Za-z0-9_\- ]{0,64}$", k):
                            continue
                        add_meta(k, parts[1])
            except Exception:
                pass

        exp_raw, exp_key = get_val(exp_keys, exact_only=exp_exact_only)
        mon_raw, _ = get_val(mon_keys, exact_only=mon_exact_only)
        trans_raw, trans_key = get_val(trans_keys, exact_only=trans_exact_only)

        exp = self._extract_float(exp_raw)
        mon = self._extract_float(mon_raw)
        trans = self._extract_float(trans_raw)

        # 时间单位兼容：ms/us 自动转为秒
        if exp is not None:
            exp_tag = f"{exp_key or ''} {exp_raw or ''}".lower()
            if "ms" in exp_tag:
                exp /= 1000.0
            elif "us" in exp_tag:
                exp /= 1_000_000.0

        trans = self._normalize_transmission(trans, raw=trans_raw, key=trans_key)
        return exp, mon, trans

    def normalize_header_dict(self, header_dict):
        meta = {}
        if not header_dict:
            return meta
        for k, v in header_dict.items():
            nk = self._norm_key(k)
            if nk:
                meta[nk] = str(v).strip()
        return meta

    def meta_get_raw(self, meta, keys):
        for k in keys:
            if k in meta:
                return meta[k], k
        for mk, mv in meta.items():
            for k in keys:
                if k in mk:
                    return mv, mk
        return None, None

    def value_with_unit_to_si(self, raw, target):
        val = self._extract_float(raw)
        if val is None:
            return None
        s = str(raw).lower() if raw is not None else ""

        if target == "distance_m":
            if "mm" in s:
                return val / 1000.0
            if "cm" in s:
                return val / 100.0
            if "um" in s or "micron" in s:
                return val / 1_000_000.0
            if "nm" in s:
                return val / 1_000_000_000.0
            if " m" in f" {s}" or s.endswith("m"):
                return val
            if val > 20:
                return val / 1000.0
            return val

        if target == "pixel_m":
            if "um" in s or "micron" in s:
                return val / 1_000_000.0
            if "mm" in s:
                return val / 1000.0
            if "nm" in s:
                return val / 1_000_000_000.0
            if " m" in f" {s}" or s.endswith("m"):
                return val
            if val > 10:
                return val / 1_000_000.0
            if val > 0.01:
                return val / 1000.0
            return val

        if target == "wavelength_a":
            if "nm" in s:
                return val * 10.0
            if "pm" in s:
                return val / 100.0
            if "m" in s and "mm" not in s and "um" not in s and "nm" not in s:
                return val * 1e10
            return val

        if target == "energy_kev":
            if "mev" in s:
                return val * 1000.0
            if "ev" in s and "kev" not in s:
                return val / 1000.0
            return val

        return val

    def extract_instrument_signature(self, filepath, header_dict=None, shape=None):
        meta = self.normalize_header_dict(header_dict)
        if not meta:
            try:
                img = fabio.open(filepath)
                meta = self.normalize_header_dict(getattr(img, "header", {}))
                if shape is None:
                    shape = tuple(img.data.shape)
            except Exception:
                pass

        wl_raw, _ = self.meta_get_raw(meta, ["wavelength", "lambda", "wave"])
        en_raw, _ = self.meta_get_raw(meta, ["energykev", "energy", "xrayenergy", "beamenergy"])
        dist_raw, _ = self.meta_get_raw(meta, ["detdistance", "distance", "sampledetdist", "camlength"])
        px1_raw, _ = self.meta_get_raw(meta, ["pixel1", "pixelsizey", "pixely", "ypixelsize"])
        px2_raw, _ = self.meta_get_raw(meta, ["pixel2", "pixelsizex", "pixelx", "xpixelsize"])
        det_raw, _ = self.meta_get_raw(meta, ["detector", "detectorname", "detector_model"])

        wl_a = self.value_with_unit_to_si(wl_raw, "wavelength_a")
        en_kev = self.value_with_unit_to_si(en_raw, "energy_kev")
        dist_m = self.value_with_unit_to_si(dist_raw, "distance_m")
        px1_m = self.value_with_unit_to_si(px1_raw, "pixel_m")
        px2_m = self.value_with_unit_to_si(px2_raw, "pixel_m")

        if wl_a is None and en_kev and en_kev > 0:
            wl_a = HC_KEV_A / en_kev
        if en_kev is None and wl_a and wl_a > 0:
            en_kev = HC_KEV_A / wl_a

        return {
            "distance_m": dist_m,
            "pixel1_m": px1_m,
            "pixel2_m": px2_m,
        }

    def relative_diff(self, a, b):
        if a is None or b is None:
            return None
        if not (np.isfinite(a) and np.isfinite(b)):
            return None
        den = max(abs(a), 1e-12)
        return abs(a - b) / den

    def normalize_azimuth_deg(self, angle_deg):
        a = float(angle_deg)
        if not np.isfinite(a):
            raise ValueError(f"角度非法: {angle_deg}")
        return ((a + 180.0) % 360.0) - 180.0

    def resolve_sector_range(self, sec_min, sec_max):
        s1 = self.normalize_azimuth_deg(sec_min)
        s2 = self.normalize_azimuth_deg(sec_max)
        span = (s2 - s1 + 360.0) % 360.0
        if np.isclose(span, 0.0, atol=1e-9):
            raise ValueError("扇区角度范围无效：sec_min 与 sec_max 不能相同（模360）。")

        wrap = s1 > s2
        if wrap:
            segments = [(s1, 180.0), (-180.0, s2)]
        else:
            segments = [(s1, s2)]
        return s1, s2, wrap, segments

    def build_sector_mask(self, chi_deg, sec_min, sec_max):
        s1, s2, wrap, _ = self.resolve_sector_range(sec_min, sec_max)
        chi = np.asarray(chi_deg, dtype=np.float64)
        if wrap:
            mask = (chi >= s1) | (chi <= s2)
        else:
            mask = (chi >= s1) & (chi <= s2)
        return mask, s1, s2, wrap

    def _sector_value_token(self, value):
        s = f"{float(value):.3f}".rstrip("0").rstrip(".")
        if s in {"", "-0"}:
            s = "0"
        s = s.replace("-", "m").replace("+", "p").replace(".", "p")
        return s

    def sector_folder_name(self, idx, sec_min, sec_max):
        return f"sector_{int(idx):02d}_{self._sector_value_token(sec_min)}_to_{self._sector_value_token(sec_max)}"

    def parse_sector_specs(self, text, fallback_pair=None):
        raw = str(text).strip() if text is not None else ""
        pairs = []

        if raw:
            norm = (
                raw.replace("，", ",")
                .replace("；", ";")
                .replace("：", ":")
                .replace("～", "~")
                .replace("→", "->")
                .replace("至", "to")
            )
            pat = re.compile(
                r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(?:~|,|:|->|to)\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
                re.IGNORECASE,
            )
            for m in pat.finditer(norm):
                pairs.append((float(m.group(1)), float(m.group(2))))

            if not pairs:
                nums = [float(x) for x in FLOAT_PATTERN.findall(norm)]
                if len(nums) >= 2 and len(nums) % 2 == 0:
                    pairs = list(zip(nums[::2], nums[1::2]))

        if not pairs:
            if raw:
                raise ValueError(
                    "未解析到扇区范围。可用示例：-25~25;45~65 或 -25,25 45,65。"
                )
            if fallback_pair is not None:
                a, b = fallback_pair
                pairs = [(float(a), float(b))]
            else:
                raise ValueError("未提供扇区范围。")

        specs = []
        seen = set()
        for a, b in pairs:
            s1, s2, wrap, segments = self.resolve_sector_range(a, b)
            sig = (round(float(s1), 6), round(float(s2), 6))
            if sig in seen:
                continue
            seen.add(sig)
            idx = len(specs) + 1
            specs.append({
                "index": idx,
                "input_min": float(a),
                "input_max": float(b),
                "sec_min": float(s1),
                "sec_max": float(s2),
                "wrap": bool(wrap),
                "segments": list(segments),
                "label": f"[{s1:.2f},{s2:.2f}]",
                "key": self.sector_folder_name(idx, s1, s2),
            })

        if not specs:
            raise ValueError("扇区解析后为空，请检查输入。")
        return specs

    def get_t2_sector_specs(self):
        txt = self.t2_sector_ranges_text.get().strip() if hasattr(self, "t2_sector_ranges_text") else ""
        fallback = (float(self.t2_sec_min.get()), float(self.t2_sec_max.get()))
        return self.parse_sector_specs(txt, fallback_pair=fallback)

    def merge_integrate1d_results(self, results):
        if not results:
            raise ValueError("无可合并积分结果。")

        r0 = np.asarray(results[0].radial, dtype=np.float64)
        if r0.size < 2:
            raise ValueError("积分结果点数不足。")

        sum_w = np.zeros_like(r0, dtype=np.float64)
        sum_iw = np.zeros_like(r0, dtype=np.float64)
        sum_sw2 = np.zeros_like(r0, dtype=np.float64)
        has_sigma = False

        for res in results:
            rr = np.asarray(res.radial, dtype=np.float64)
            if rr.shape != r0.shape or not np.allclose(rr, r0, rtol=1e-7, atol=1e-12, equal_nan=False):
                raise ValueError("分段扇区积分的 q 网格不一致，无法合并。")

            i = np.asarray(res.intensity, dtype=np.float64)
            w = getattr(res, "count", None)
            if w is None:
                w = np.where(np.isfinite(i), 1.0, 0.0)
            else:
                w = np.asarray(w, dtype=np.float64)
                if w.shape != r0.shape:
                    w = np.where(np.isfinite(i), 1.0, 0.0)
                w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
                w = np.maximum(w, 0.0)

            i_num = np.nan_to_num(i, nan=0.0, posinf=0.0, neginf=0.0)
            sum_iw += i_num * w
            sum_w += w

            sigma = getattr(res, "sigma", None)
            if sigma is not None:
                s = np.asarray(sigma, dtype=np.float64)
                if s.shape == r0.shape:
                    term = np.nan_to_num(s, nan=0.0, posinf=0.0, neginf=0.0) * w
                    sum_sw2 += term * term
                    has_sigma = True

        i_merge = np.divide(sum_iw, sum_w, out=np.full_like(sum_iw, np.nan), where=sum_w > 0)
        sigma_merge = None
        if has_sigma:
            sigma_merge = np.divide(
                np.sqrt(sum_sw2),
                sum_w,
                out=np.full_like(sum_w, np.nan),
                where=sum_w > 0,
            )

        return SimpleNamespace(
            radial=r0,
            intensity=i_merge,
            sigma=sigma_merge,
            count=sum_w,
        )

    def integrate1d_sector(self, ai, img, npt, sec_min, sec_max, **kwargs):
        s1, s2, wrap, segments = self.resolve_sector_range(sec_min, sec_max)

        if len(segments) == 1:
            res = ai.integrate1d(
                img,
                npt,
                unit="q_A^-1",
                azimuth_range=segments[0],
                **kwargs,
            )
            return res, s1, s2, wrap

        parts = []
        for seg in segments:
            parts.append(
                ai.integrate1d(
                    img,
                    npt,
                    unit="q_A^-1",
                    azimuth_range=seg,
                    **kwargs,
                )
            )
        res = self.merge_integrate1d_results(parts)
        return res, s1, s2, wrap

    def check_instrument_consistency(self, file_paths, poni_path=None, tol_pct=0.5):
        if not file_paths:
            return []
        tol = max(float(tol_pct), 0.01) / 100.0
        sigs = []
        for fp in file_paths:
            try:
                img = fabio.open(fp)
                d = img.data
                sig = self.extract_instrument_signature(fp, header_dict=getattr(img, "header", {}), shape=d.shape)
                sigs.append(sig)
            except Exception as e:
                sigs.append({"path": str(fp), "shape": None, "error": str(e)})

        ref = sigs[0]
        fallback = self.session_geometry_fallback if isinstance(self.session_geometry_fallback, dict) else {}
        if fallback:
            for key in ("wavelength_a", "distance_m", "pixel1_m", "pixel2_m", "energy_kev"):
                if ref.get(key) is None and fallback.get(key) is not None:
                    ref[key] = fallback.get(key)

        issues = []
        for s in sigs[1:]:
            p = Path(s.get("path", "")).name
            if "error" in s:
                issues.append(f"{p}: 无法读取文件头 ({s['error']})")
                continue

            if ref.get("shape") and s.get("shape") and ref["shape"] != s["shape"]:
                issues.append(f"{p}: 图像尺寸不一致 {s['shape']} != {ref['shape']}")

            if ref.get("detector") and s.get("detector") and ref["detector"] != s["detector"]:
                issues.append(f"{p}: 探测器型号不一致 {s['detector']} != {ref['detector']}")

            for key, label in [
                ("energy_kev", "能量(keV)"),
                ("wavelength_a", "波长(A)"),
                ("distance_m", "样探距(m)"),
                ("pixel1_m", "pixel1(m)"),
                ("pixel2_m", "pixel2(m)"),
            ]:
                rd = self.relative_diff(s.get(key), ref.get(key))
                if rd is not None and rd > tol:
                    issues.append(
                        f"{p}: {label} 偏差 {rd*100:.3f}% 超过阈值 {tol*100:.3f}%"
                    )

        if poni_path:
            try:
                ai = pyFAI.load(poni_path)
                ai_wl_a = ai.wavelength * 1e10 if getattr(ai, "wavelength", None) else None
                if ai_wl_a and ref.get("wavelength_a"):
                    rd = self.relative_diff(ai_wl_a, ref["wavelength_a"])
                    if rd is not None and rd > tol:
                        issues.append(
                            f"poni 波长与样品头信息不一致: {ai_wl_a:.6g} A vs {ref['wavelength_a']:.6g} A"
                        )
            except Exception as e:
                issues.append(f"无法读取 poni 做一致性检查: {e}")

        return issues

    def build_output_stem_map(self, files):
        name_count = {}
        for fp in files:
            stem = Path(fp).stem
            name_count[stem] = name_count.get(stem, 0) + 1

        used = set()
        out = {}
        for fp in files:
            p = Path(fp)
            stem = p.stem
            if name_count[stem] == 1:
                candidate = stem
            else:
                candidate = f"{p.parent.name}_{stem}"

            if candidate in used:
                idx = 2
                while f"{candidate}_{idx}" in used:
                    idx += 1
                candidate = f"{candidate}_{idx}"

            used.add(candidate)
            out[fp] = candidate
        return out

    def mode_output_path(self, save_dirs, mode, out_stem):
        ext = ".chi" if mode == "radial_chi" else ".dat"
        return save_dirs[mode] / f"{out_stem}{ext}"

    def build_sample_output_targets(self, context, out_stem):
        targets = []
        for mode in context["selected_modes"]:
            if mode != "1d_sector":
                targets.append((mode, self.mode_output_path(context["save_dirs"], mode, out_stem)))
                continue

            if context.get("sector_save_each", True):
                for spec in context.get("sector_specs", []):
                    d = context.get("sector_save_dirs", {}).get(spec["key"])
                    if d is None:
                        continue
                    targets.append((f"1d_sector{spec['label']}", d / f"{out_stem}.dat"))

            if context.get("sector_save_combined", False):
                d = context.get("sector_combined_dir", None)
                if d is not None:
                    targets.append(("1d_sector_sum", d / f"{out_stem}.dat"))
        return targets

    def save_profile_table(self, out_path, x, i_abs, i_err, x_label):
        # Origin-friendly text table: first row is column names, tab-separated.
        df = pd.DataFrame({
            x_label: np.asarray(x, dtype=np.float64),
            "I_abs_cm^-1": np.asarray(i_abs, dtype=np.float64),
            "Error_cm^-1": np.asarray(i_err, dtype=np.float64),
        })
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.to_csv(
            out_path,
            sep="\t",
            index=False,
            encoding="utf-8-sig",
            na_rep="",
            float_format="%.10g",
        )

    def load_optional_array(self, path, name):
        if not path:
            return None
        p = Path(path)
        if p.suffix.lower() == ".npy":
            arr = np.load(path)
        else:
            arr = fabio.open(path).data
        if arr is None:
            raise ValueError(f"{name} 文件无法读取: {path}")
        return np.asarray(arr)

    def profile_health_issue(self, i_abs):
        arr = np.asarray(i_abs, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if arr.size < 50:
            return None
        non_pos_frac = float(np.mean(arr <= 0))
        if non_pos_frac >= 0.98:
            return (
                f"积分结果异常：非正值比例 {non_pos_frac*100:.1f}% "
                "(疑似过扣背景或归一化设置错误)"
            )
        return None

    def build_reference_library(self, paths):
        refs = []
        for p in list(dict.fromkeys(paths or [])):
            try:
                img = fabio.open(p)
                data = np.asarray(img.data)
                exp, mon, trans = self.parse_header(p, header_dict=getattr(img, "header", {}))
                refs.append({
                    "path": str(p),
                    "shape": tuple(data.shape),
                    "exp": exp,
                    "mon": mon,
                    "trans": trans,
                    "mtime": Path(p).stat().st_mtime if Path(p).exists() else None,
                })
            except Exception:
                continue
        return refs

    def reference_score(self, sample_meta, ref_meta, kind="bg"):
        score = 0.0
        used = 0.0

        se, re = sample_meta.get("exp"), ref_meta.get("exp")
        sm, rm = sample_meta.get("mon"), ref_meta.get("mon")
        st, rt = sample_meta.get("trans"), ref_meta.get("trans")
        stime, rtime = sample_meta.get("mtime"), ref_meta.get("mtime")

        if se and re and se > 0 and re > 0:
            score += self.relative_diff(se, re) * 1.0
            used += 1.0
        if sm and rm and sm > 0 and rm > 0:
            score += self.relative_diff(sm, rm) * 0.8
            used += 0.8
        if kind == "bg" and st and rt and st > 0 and rt > 0:
            score += abs(st - rt) * 1.5
            used += 1.5
        if stime and rtime:
            dt_h = abs(stime - rtime) / 3600.0
            score += min(dt_h / 24.0, 3.0) * 0.5
            used += 0.5

        if used == 0:
            return 1e9
        return score / used

    def select_best_reference(self, sample_meta, refs, kind="bg"):
        if not refs:
            return None, None
        same_shape = [r for r in refs if r.get("shape") == sample_meta.get("shape")]
        pool = same_shape if same_shape else refs
        scored = []
        for r in pool:
            scored.append((self.reference_score(sample_meta, r, kind=kind), r))
        scored.sort(key=lambda x: x[0])
        return scored[0][1], scored[0][0]

    # =========================================================================
    # TAB 1: K-Factor Calibration
    # =========================================================================
    def init_tab1_k_calc(self):
        p = self.tab1
        left_panel = ttk.Frame(p, width=400)
        left_panel.pack(side="left", fill="y", padx=5, pady=5)

        # 流程提示
        f_guide = ttk.LabelFrame(left_panel, text="快速流程（新手）", style="Group.TLabelframe")
        f_guide.pack(fill="x", pady=5)
        guide_text = (
            "① 选择标准样/本底/暗场/几何文件\n"
            "② 核对自动读取的 Time、I0、T\n"
            "③ 填写标准样厚度(mm)\n"
            "④ 点击运行标定，得到 K 因子\n"
            "⑤ 查看报告中的 Std Dev 与点数"
        )
        lbl_guide = ttk.Label(f_guide, text=guide_text, justify="left", style="Hint.TLabel")
        lbl_guide.pack(fill="x", padx=4, pady=3)
        self.add_tooltip(lbl_guide, "按 1~5 步执行，基本不会漏关键参数。")

        # 1. 文件区
        f_files = ttk.LabelFrame(left_panel, text="1. 标定文件（必须）", style="Group.TLabelframe")
        f_files.pack(fill="x", pady=5)
        self.add_hint(
            f_files,
            "标准样建议用玻璃碳（GC）；背景/暗场/poni 应与样品保持同一实验几何与能量。",
        )
        
        self.t1_files = {
            "std": tk.StringVar(), "bg": self.global_vars["bg_path"],
            "dark": self.global_vars["dark_path"], "poni": self.global_vars["poni_path"]
        }

        row_std = self.add_file_row(f_files, "标准样 (GC):", self.t1_files["std"], "*.tif", self.on_load_std_t1)
        self.add_tooltip(row_std["entry"], "用于绝对强度标定的标准样二维图像（推荐 GC）。")
        self.add_tooltip(row_std["button"], "点击选择标准样文件。")

        row_bg = self.add_file_row(f_files, "背景图像:", self.t1_files["bg"], "*.tif", self.on_load_bg_t1)
        self.add_tooltip(row_bg["entry"], "空样品/空气或本底散射图像，用于 2D 本底扣除。")
        self.add_tooltip(row_bg["button"], "点击选择背景图像。")

        row_dark = self.add_file_row(f_files, "暗场图像:", self.t1_files["dark"], "*.tif")
        self.add_tooltip(row_dark["entry"], "探测器暗电流/本底噪声图像。")
        self.add_tooltip(row_dark["button"], "点击选择暗场图像。")

        row_poni = self.add_file_row(f_files, "几何文件 (.poni):", self.t1_files["poni"], "*.poni")
        self.add_tooltip(row_poni["entry"], "pyFAI 几何标定文件，决定 q 转换精度。")
        self.add_tooltip(row_poni["button"], "点击选择 .poni 文件。")

        # 2. 物理参数
        f_phys = ttk.LabelFrame(left_panel, text="2. 物理参数（核心输入）", style="Group.TLabelframe")
        f_phys.pack(fill="x", pady=5)
        self.add_hint(
            f_phys,
            "Time(s)=曝光时间；I0=入射强度监测值；T=透过率(0~1)。归一化按下方 I0 语义选择公式。",
        )
        f_phys_grid = ttk.Frame(f_phys)
        f_phys_grid.pack(fill="x")
        
        self.t1_params = {
            "std_exp": tk.DoubleVar(value=1.0), "std_i0": tk.DoubleVar(value=1.0),
            "std_t": tk.DoubleVar(value=1.0), "std_thk": tk.DoubleVar(value=1.0),
            "bg_exp": self.global_vars["bg_exp"], "bg_i0": self.global_vars["bg_i0"], "bg_t": self.global_vars["bg_t"]
        }
        
        headers = ["Time(s)", "I0(Mon)", "Trans(T)", "Thk(mm)"]
        for i, h in enumerate(headers):
            ttk.Label(f_phys_grid, text=h, font=("Arial", 8)).grid(row=0, column=i+1)
        
        ttk.Label(f_phys_grid, text="Std:", style="Bold.TLabel").grid(row=1, column=0, pady=2)
        e_std_exp = self.add_grid_entry(f_phys_grid, self.t1_params["std_exp"], 1, 1)
        e_std_i0 = self.add_grid_entry(f_phys_grid, self.t1_params["std_i0"], 1, 2)
        e_std_t = self.add_grid_entry(f_phys_grid, self.t1_params["std_t"], 1, 3)
        e_std_thk = self.add_grid_entry(f_phys_grid, self.t1_params["std_thk"], 1, 4)
        
        ttk.Label(f_phys_grid, text="BG:", style="Bold.TLabel").grid(row=2, column=0, pady=2)
        e_bg_exp = self.add_grid_entry(f_phys_grid, self.t1_params["bg_exp"], 2, 1)
        e_bg_i0 = self.add_grid_entry(f_phys_grid, self.t1_params["bg_i0"], 2, 2)
        e_bg_t = self.add_grid_entry(f_phys_grid, self.t1_params["bg_t"], 2, 3)
        ttk.Label(f_phys_grid, text="-").grid(row=2, column=4)

        norm_row = ttk.Frame(f_phys)
        norm_row.pack(fill="x", pady=(3, 0))
        ttk.Label(norm_row, text="I0 语义:").pack(side="left")
        cb_norm_t1 = ttk.Combobox(
            norm_row,
            textvariable=self.global_vars["monitor_mode"],
            width=11,
            state="readonly",
            values=MONITOR_NORM_MODES,
        )
        cb_norm_t1.pack(side="left", padx=(4, 6))
        lbl_norm_hint_t1 = ttk.Label(
            norm_row,
            text="rate: exp*I0*T | integrated: I0*T",
            style="Hint.TLabel",
        )
        lbl_norm_hint_t1.pack(side="left")
        cb_solid_t1 = ttk.Checkbutton(
            norm_row,
            text="SolidAngle修正",
            variable=self.global_vars["apply_solid_angle"],
        )
        cb_solid_t1.pack(side="left", padx=(8, 0))

        self.add_tooltip(e_std_exp, "标准样曝光时间（秒）。")
        self.add_tooltip(e_std_i0, "标准样 I0（监测器读数）。")
        self.add_tooltip(e_std_t, "标准样透过率，建议在 0~1 之间。")
        self.add_tooltip(e_std_thk, "标准样厚度（mm），用于体积归一化。")
        self.add_tooltip(e_bg_exp, "背景图曝光时间（秒）。")
        self.add_tooltip(e_bg_i0, "背景图 I0（监测器读数）。")
        self.add_tooltip(e_bg_t, "背景图透过率。")
        self.add_tooltip(cb_norm_t1, "rate: I0 是每秒计数率；integrated: I0 是曝光积分计数。")
        self.add_tooltip(lbl_norm_hint_t1, "请按线站实际输出选择。选错会引入曝光时间相关系统误差。")
        self.add_tooltip(cb_solid_t1, "Tab1标定与Tab2批处理共用此设置。两者必须一致，否则 K 因子无效。")

        # 3. 操作按钮
        btn_row = ttk.Frame(left_panel)
        btn_row.pack(fill="x", pady=10)
        btn_cal = ttk.Button(btn_row, text=">>> 运行 K 因子标定（稳健模式） <<<", command=self.run_calibration)
        btn_cal.pack(side="left", fill="x", expand=True, ipady=5)
        btn_hist = ttk.Button(btn_row, text="K 历史", command=self.open_k_history)
        btn_hist.pack(side="left", padx=(6, 0))
        self.add_tooltip(btn_cal, "执行 2D 扣背景 + 1D 积分 + NIST 匹配，自动写入 K 因子。")
        self.add_tooltip(btn_hist, "查看历史 K 因子趋势，监控仪器漂移。")

        # 4. 报告
        f_rep = ttk.LabelFrame(left_panel, text="分析报告（建议重点看 Std Dev）", style="Group.TLabelframe")
        f_rep.pack(fill="both", expand=True, pady=5)
        self.txt_report = tk.Text(f_rep, font=("Consolas", 9), height=15, width=40)
        self.txt_report.pack(fill="both", expand=True)
        self.add_tooltip(
            self.txt_report,
            "会显示标定关键指标：K、有效点数、Q 重叠区间和离散度。"
        )

        # --- 右侧图形 ---
        right_panel = ttk.Frame(p)
        right_panel.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        lbl_plot_tip = ttk.Label(
            right_panel,
            text="图示说明：黑虚线=净信号；蓝线=K 校正后；红圈=NIST 参考点",
            style="Hint.TLabel",
        )
        lbl_plot_tip.pack(anchor="w", pady=(0, 2))
        self.fig1 = Figure(figsize=(6, 5), dpi=100)
        self.ax1 = self.fig1.add_subplot(111)
        self.canvas1 = FigureCanvasTkAgg(self.fig1, master=right_panel)
        self.canvas1.get_tk_widget().pack(fill="both", expand=True)
        self.toolbar1 = NavigationToolbar2Tk(self.canvas1, right_panel)
        self.toolbar1.update()
        self.add_tooltip(lbl_plot_tip, "若蓝线与红点趋势一致，通常说明 K 标定质量较好。")

    # =========================================================================
    # TAB 2: Batch Processing
    # =========================================================================
    def init_tab2_batch(self):
        p = self.tab2
        
        self.t2_files = []
        self.t2_mu = tk.DoubleVar(value=20.2)
        self.t2_calc_mode = tk.StringVar(value="auto") 
        self.t2_fixed_thk = tk.DoubleVar(value=1.0)
        self.t2_ref_mode = tk.StringVar(value="fixed")
        self.t2_error_model = tk.StringVar(value="azimuthal")
        self.t2_apply_solid_angle = self.global_vars["apply_solid_angle"]
        self.t2_polarization = tk.DoubleVar(value=0.0)
        self.t2_output_root = tk.StringVar(value="")
        self.t2_mask_path = tk.StringVar()
        self.t2_flat_path = tk.StringVar()
        self.t2_resume_enabled = tk.BooleanVar(value=True)
        self.t2_overwrite = tk.BooleanVar(value=False)
        self.t2_workers = tk.IntVar(value=1)
        self.t2_strict_instrument = tk.BooleanVar(value=True)
        self.t2_instr_tol_pct = tk.DoubleVar(value=0.5)
        self.t2_bg_candidates = []
        self.t2_dark_candidates = []
        self.t2_bg_lib_info = tk.StringVar(value="BG库: 0")
        self.t2_dark_lib_info = tk.StringVar(value="Dark库: 0")
        
        self.t2_mode_full = tk.BooleanVar(value=True)
        self.t2_mode_sector = tk.BooleanVar(value=False)
        self.t2_mode_chi = tk.BooleanVar(value=False)
        self.t2_sec_min = tk.DoubleVar(value=-20)
        self.t2_sec_max = tk.DoubleVar(value=20)
        self.t2_sector_ranges_text = tk.StringVar(value="")
        self.t2_sector_save_each = tk.BooleanVar(value=True)
        self.t2_sector_save_combined = tk.BooleanVar(value=False)
        self.t2_rad_qmin = tk.DoubleVar(value=0.5)
        self.t2_rad_qmax = tk.DoubleVar(value=2.5)

        # 流程提示
        f_guide = ttk.LabelFrame(p, text="批处理工作流（推荐顺序）", style="Group.TLabelframe")
        f_guide.pack(fill="x", padx=10, pady=(8, 3))
        guide = (
            "① 先确认 K 因子和 BG/暗场/poni 已就绪\n"
            "② 选择厚度逻辑（自动/固定）\n"
            "③ 选择一个或多个积分模式（可同时勾选）\n"
            "④ 添加样品文件并点击预检查\n"
            "⑤ 启动批处理并查看 batch_report.csv"
        )
        lbl_guide = ttk.Label(f_guide, text=guide, justify="left", style="Hint.TLabel")
        lbl_guide.pack(fill="x", padx=4, pady=3)
        self.add_tooltip(lbl_guide, "先预检查再正式跑批，可显著减少中途失败。")

        # --- Settings ---
        top_frame = ttk.Frame(p)
        top_frame.pack(fill="x", padx=10, pady=5)
        
        # 1. Global
        c1 = ttk.LabelFrame(top_frame, text="1. 全局配置", style="Group.TLabelframe")
        c1.pack(side="left", fill="y", padx=5)
        self.add_hint(c1, "K 因子来自 Tab1 标定结果。I0 语义决定归一化公式；BG 路径仅用于快速确认。", wraplength=300)
        c1_grid = ttk.Frame(c1)
        c1_grid.pack(fill="x")
        ttk.Label(c1_grid, text="K 因子:").grid(row=0, column=0, sticky="e")
        e_k = ttk.Entry(c1_grid, textvariable=self.global_vars["k_factor"], width=10)
        e_k.grid(row=0, column=1, padx=5)
        ttk.Label(c1_grid, text="背景文件:").grid(row=1, column=0, sticky="e")
        lbl_bg = ttk.Label(c1_grid, textvariable=self.global_vars["bg_path"], width=20, foreground="gray")
        lbl_bg.grid(row=1, column=1, padx=5)
        ttk.Label(c1_grid, text="I0 语义:").grid(row=2, column=0, sticky="e")
        cb_norm_t2 = ttk.Combobox(
            c1_grid,
            textvariable=self.global_vars["monitor_mode"],
            width=11,
            state="readonly",
            values=MONITOR_NORM_MODES,
        )
        cb_norm_t2.grid(row=2, column=1, padx=5, pady=(2, 0), sticky="w")
        lbl_norm_hint_t2 = ttk.Label(c1_grid, text="rate: exp*I0*T / integrated: I0*T", style="Hint.TLabel")
        lbl_norm_hint_t2.grid(row=3, column=0, columnspan=2, sticky="w", padx=2)
        self.add_tooltip(e_k, "绝对强度比例因子。必须大于 0。")
        self.add_tooltip(lbl_bg, "当前启用的背景图路径（由 Tab1 共享）。")
        self.add_tooltip(cb_norm_t2, "全局生效：rate 表示 I0 为计数率；integrated 表示 I0 为积分计数。")
        self.add_tooltip(lbl_norm_hint_t2, "该设置会影响标定与批处理的所有归一化因子。")

        # 2. Thickness
        c2 = ttk.LabelFrame(top_frame, text="2. 厚度策略", style="Group.TLabelframe")
        c2.pack(side="left", fill="y", padx=5)
        self.add_hint(c2, "自动模式: d=-ln(T)/mu；固定模式: 所有样品使用同一厚度(mm)。", wraplength=320)
        
        r1 = ttk.Frame(c2); r1.pack(anchor="w")
        rb_auto = ttk.Radiobutton(r1, text="自动厚度 (d = -ln(T)/μ)", variable=self.t2_calc_mode, value="auto")
        rb_auto.pack(side="left")
        lbl_mu = ttk.Label(r1, text=" μ(cm⁻¹):")
        lbl_mu.pack(side="left")
        e_mu = ttk.Entry(r1, textvariable=self.t2_mu, width=6)
        e_mu.pack(side="left")
        btn_est = ttk.Button(r1, text="μ估算", command=self.open_mu_tool, width=8)
        btn_est.pack(side="left", padx=2)
        
        r2 = ttk.Frame(c2); r2.pack(anchor="w")
        rb_fix = ttk.Radiobutton(r2, text="固定厚度 (mm):", variable=self.t2_calc_mode, value="fixed")
        rb_fix.pack(side="left")
        e_fix = ttk.Entry(r2, textvariable=self.t2_fixed_thk, width=6)
        e_fix.pack(side="left")

        self.add_tooltip(rb_auto, "适合每个样品都具有可靠透过率 T 的情况。")
        self.add_tooltip(e_mu, "线性衰减系数 mu，单位 cm^-1，必须大于 0。")
        self.add_tooltip(btn_est, "按合金成分估算 mu（30 keV 经验）。")
        self.add_tooltip(rb_fix, "透过率不稳定或缺失时，建议改为固定厚度。")
        self.add_tooltip(e_fix, "所有样品统一厚度值，单位 mm。")
        self.add_tooltip(lbl_mu, "mu 越大，按同样 T 算出的厚度越小。")
        
        # 3. Integration
        c3 = ttk.LabelFrame(top_frame, text="3. 积分模式（2D 扣背景后）", style="Group.TLabelframe")
        c3.pack(side="left", fill="y", padx=5)
        self.add_hint(c3, "可多选并一次性输出到不同文件夹：全环/扇区/织构可同时运行。", wraplength=320)
        c3_grid = ttk.Frame(c3)
        c3_grid.pack(fill="x")

        cb_full = ttk.Checkbutton(c3_grid, text="I-Q 全环", variable=self.t2_mode_full)
        cb_full.grid(row=0, column=0, sticky="w")
        f_sec = ttk.Frame(c3_grid); f_sec.grid(row=1, column=0, sticky="w")
        cb_sec = ttk.Checkbutton(f_sec, text="I-Q 扇区", variable=self.t2_mode_sector)
        cb_sec.pack(side="left")
        ttk.Label(f_sec, text=" [").pack(side="left")
        e_sec_min = ttk.Entry(f_sec, textvariable=self.t2_sec_min, width=4)
        e_sec_min.pack(side="left")
        ttk.Label(f_sec, text=",").pack(side="left")
        e_sec_max = ttk.Entry(f_sec, textvariable=self.t2_sec_max, width=4)
        e_sec_max.pack(side="left")
        ttk.Label(f_sec, text="] deg").pack(side="left")
        btn_sec_preview = ttk.Button(f_sec, text="预览I-Q", width=8, command=self.preview_iq_window_t2)
        btn_sec_preview.pack(side="left", padx=(4, 0))

        f_sec_multi = ttk.Frame(c3_grid); f_sec_multi.grid(row=2, column=0, sticky="w")
        ttk.Label(f_sec_multi, text=" 多扇区:").pack(side="left")
        e_sec_multi = ttk.Entry(f_sec_multi, textvariable=self.t2_sector_ranges_text, width=26)
        e_sec_multi.pack(side="left")
        ttk.Label(f_sec_multi, text=" 例:-25~25;45~65").pack(side="left")
        cb_sec_each = ttk.Checkbutton(f_sec_multi, text="分扇区分别保存", variable=self.t2_sector_save_each)
        cb_sec_each.pack(side="left", padx=(6, 0))
        cb_sec_sum = ttk.Checkbutton(f_sec_multi, text="扇区合并保存", variable=self.t2_sector_save_combined)
        cb_sec_sum.pack(side="left", padx=(4, 0))

        f_tex = ttk.Frame(c3_grid); f_tex.grid(row=3, column=0, sticky="w")
        cb_tex = ttk.Checkbutton(f_tex, text="I-chi 织构", variable=self.t2_mode_chi)
        cb_tex.pack(side="left")
        ttk.Label(f_tex, text=" Q[").pack(side="left")
        e_qmin = ttk.Entry(f_tex, textvariable=self.t2_rad_qmin, width=4)
        e_qmin.pack(side="left")
        ttk.Label(f_tex, text=",").pack(side="left")
        e_qmax = ttk.Entry(f_tex, textvariable=self.t2_rad_qmax, width=4)
        e_qmax.pack(side="left")
        ttk.Label(f_tex, text="] A⁻¹").pack(side="left")
        btn_chi_preview = ttk.Button(f_tex, text="预览I-chi", width=10, command=self.preview_ichi_window_t2)
        btn_chi_preview.pack(side="left", padx=(4, 0))

        self.add_tooltip(cb_full, "对各向同性样品优先推荐。可与其他模式同时勾选。")
        self.add_tooltip(cb_sec, "仅对指定方位角扇区积分，突出方向性结构。可多选并行输出。")
        self.add_tooltip(e_sec_min, "扇区起始角（度）。支持跨 ±180°（例如 170 到 -170）。")
        self.add_tooltip(e_sec_max, "扇区结束角（度）。与起始角相同（模360）无效。")
        self.add_tooltip(btn_sec_preview, "弹出2D窗口预览 I-Q 积分区域（扇区或全环），用于确认选区。")
        self.add_tooltip(e_sec_multi, "多扇区列表。支持 `-25~25;45~65`、`-25,25 45,65` 等格式；留空时使用上方单扇区。")
        self.add_tooltip(cb_sec_each, "每个扇区输出到独立子文件夹（sector_XX_*）。")
        self.add_tooltip(cb_sec_sum, "将所有扇区按像素权重合并成一条 I-Q，并单独输出。")
        self.add_tooltip(cb_tex, "在给定 q 范围内输出 I 随方位角 chi 的分布。可与 I-Q 同时输出。")
        self.add_tooltip(e_qmin, "织构分析 q 最小值（A^-1）。")
        self.add_tooltip(e_qmax, "织构分析 q 最大值（A^-1），需大于 q_min。")
        self.add_tooltip(btn_chi_preview, "弹出2D窗口预览 I-chi 使用的 q 环带范围。")

        # 4. 修正与执行策略
        adv_frame = ttk.Frame(p)
        adv_frame.pack(fill="x", padx=10, pady=(2, 4))

        c4 = ttk.LabelFrame(adv_frame, text="4. 修正参数", style="Group.TLabelframe")
        c4.pack(side="left", fill="x", expand=True, padx=5)
        self.add_hint(c4, "建议开启 solid angle。可选 mask/flat/polarization 与误差模型。", wraplength=480)

        c4_row1 = ttk.Frame(c4); c4_row1.pack(fill="x", pady=2)
        cb_solid = ttk.Checkbutton(c4_row1, text="应用 Solid Angle 修正", variable=self.t2_apply_solid_angle)
        cb_solid.pack(side="left")
        ttk.Label(c4_row1, text="误差模型:").pack(side="left", padx=(8, 2))
        cb_err = ttk.Combobox(c4_row1, textvariable=self.t2_error_model, width=10, state="readonly")
        cb_err["values"] = ("azimuthal", "poisson", "none")
        cb_err.pack(side="left")
        ttk.Label(c4_row1, text="Polarization(-1~1):").pack(side="left", padx=(8, 2))
        e_pol = ttk.Entry(c4_row1, textvariable=self.t2_polarization, width=6)
        e_pol.pack(side="left")

        row_mask = self.add_file_row(c4, "Mask 文件:", self.t2_mask_path, "*.tif *.tiff *.edf *.npy")
        row_flat = self.add_file_row(c4, "Flat 文件:", self.t2_flat_path, "*.tif *.tiff *.edf *.npy")

        self.add_tooltip(cb_solid, "必须与 Tab1 标定时保持一致。若不一致程序会阻断批处理。")
        self.add_tooltip(cb_err, "azimuthal: 方位离散；poisson: 计数统计；none: 不计算误差。")
        self.add_tooltip(e_pol, "偏振因子，通常在 -1 到 1。0 表示不偏振。")
        self.add_tooltip(row_mask["entry"], "掩膜图：非零像素视为无效区域。")
        self.add_tooltip(row_flat["entry"], "平场校正图（可选）。")

        c5 = ttk.LabelFrame(adv_frame, text="5. 参考匹配与执行", style="Group.TLabelframe")
        c5.pack(side="left", fill="x", expand=True, padx=5)
        self.add_hint(c5, "可固定 BG/Dark，或按元数据自动匹配最接近的 BG/Dark。", wraplength=480)

        row_ref = ttk.Frame(c5); row_ref.pack(fill="x")
        rb_ref_fixed = ttk.Radiobutton(row_ref, text="固定 BG/Dark", variable=self.t2_ref_mode, value="fixed")
        rb_ref_fixed.pack(side="left")
        rb_ref_auto = ttk.Radiobutton(row_ref, text="自动匹配 BG/Dark", variable=self.t2_ref_mode, value="auto")
        rb_ref_auto.pack(side="left", padx=(8, 0))

        row_lib = ttk.Frame(c5); row_lib.pack(fill="x", pady=2)
        btn_bg_lib = ttk.Button(row_lib, text="选择 BG 库", command=self.add_bg_library_files)
        btn_bg_lib.pack(side="left")
        btn_dark_lib = ttk.Button(row_lib, text="选择 Dark 库", command=self.add_dark_library_files)
        btn_dark_lib.pack(side="left", padx=(5, 0))
        btn_clear_lib = ttk.Button(row_lib, text="清空库", command=self.clear_reference_libraries)
        btn_clear_lib.pack(side="left", padx=(5, 0))

        row_lib_info = ttk.Frame(c5); row_lib_info.pack(fill="x")
        ttk.Label(row_lib_info, textvariable=self.t2_bg_lib_info, style="Hint.TLabel").pack(side="left")
        ttk.Label(row_lib_info, textvariable=self.t2_dark_lib_info, style="Hint.TLabel").pack(side="left", padx=(10, 0))

        row_exec = ttk.Frame(c5); row_exec.pack(fill="x", pady=2)
        ttk.Label(row_exec, text="并行线程:").pack(side="left")
        e_workers = ttk.Entry(row_exec, textvariable=self.t2_workers, width=4)
        e_workers.pack(side="left")
        cb_resume = ttk.Checkbutton(row_exec, text="断点续跑(跳过已存在输出)", variable=self.t2_resume_enabled)
        cb_resume.pack(side="left", padx=(8, 0))
        cb_overwrite = ttk.Checkbutton(row_exec, text="强制覆盖输出", variable=self.t2_overwrite)
        cb_overwrite.pack(side="left", padx=(8, 0))

        row_strict = ttk.Frame(c5); row_strict.pack(fill="x")
        cb_strict = ttk.Checkbutton(row_strict, text="严格仪器一致性校验", variable=self.t2_strict_instrument)
        cb_strict.pack(side="left")
        ttk.Label(row_strict, text="阈值(%):").pack(side="left", padx=(8, 2))
        e_tol = ttk.Entry(row_strict, textvariable=self.t2_instr_tol_pct, width=5)
        e_tol.pack(side="left")

        self.add_tooltip(rb_ref_fixed, "全批次统一使用 Tab1 指定的 BG/Dark。")
        self.add_tooltip(rb_ref_auto, "按曝光/I0/T/时间与样品最接近原则自动选 BG 和 Dark。")
        self.add_tooltip(btn_bg_lib, "选择可供自动匹配的背景文件集合。")
        self.add_tooltip(btn_dark_lib, "选择可供自动匹配的暗场文件集合。")
        self.add_tooltip(btn_clear_lib, "清空 BG/Dark 库。")
        self.add_tooltip(e_workers, "并行线程数，1 表示串行。建议 1~8。")
        self.add_tooltip(cb_resume, "已存在输出文件时自动跳过，支持中断后续跑。")
        self.add_tooltip(cb_overwrite, "忽略已存在输出并重新计算。")
        self.add_tooltip(cb_strict, "检查能量/波长/距离/像素/尺寸一致性，不一致则停止。")
        self.add_tooltip(e_tol, "一致性阈值百分比，例如 0.5 表示 0.5%。")

        # --- List ---
        mid_frame = ttk.LabelFrame(p, text="样品队列", style="Group.TLabelframe")
        mid_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.add_hint(mid_frame, "可一次添加多个文件。建议先点“预检查”，确认头信息与厚度计算是否正常。")
        
        tb = ttk.Frame(mid_frame); tb.pack(fill="x")
        btn_add = ttk.Button(tb, text="添加文件", command=self.add_batch_files)
        btn_add.pack(side="left")
        btn_clear = ttk.Button(tb, text="清空队列", command=self.clear_batch_files)
        btn_clear.pack(side="left")
        btn_check = ttk.Button(tb, text="预检查", command=self.dry_run, style="Accent.TButton")
        btn_check.pack(side="right", padx=10)
        self.add_tooltip(btn_add, "支持多选 TIFF 文件。")
        self.add_tooltip(btn_clear, "清空队列，不会删除磁盘文件。")
        self.add_tooltip(btn_check, "批量检查每个文件的 exp/mon/T 和厚度可用性。")

        self.t2_queue_info = tk.StringVar(value="队列文件: 0")
        lbl_queue = ttk.Label(mid_frame, textvariable=self.t2_queue_info, style="Hint.TLabel")
        lbl_queue.pack(anchor="w", padx=5, pady=(2, 0))

        self.lb_batch = tk.Listbox(mid_frame, height=8)
        self.lb_batch.pack(fill="both", expand=True, padx=5, pady=5)
        self.add_tooltip(self.lb_batch, "显示当前待处理样品列表。")

        # --- Action ---
        bot_frame = ttk.Frame(p)
        bot_frame.pack(fill="x", padx=10, pady=10)
        btn_run = ttk.Button(bot_frame, text=">>> 开始稳健批处理（2D 扣背景 + 误差棒） <<<", command=self.run_batch)
        btn_run.pack(fill="x", ipady=5)
        self.prog_bar = ttk.Progressbar(bot_frame, mode="determinate")
        self.prog_bar.pack(fill="x", pady=5)
        row_out_dir = self.add_dir_row(bot_frame, "输出根目录:", self.t2_output_root)
        self.add_tooltip(btn_run, "执行批处理。单文件失败不会中断整批。")
        self.add_tooltip(self.prog_bar, "显示批处理进度。")
        self.add_tooltip(row_out_dir["entry"], "可选。不填时默认输出到样品所在目录。")

        self.t2_out_hint_var = tk.StringVar(value="输出目录将自动创建: processed_robust_1d_full")
        lbl_out = ttk.Label(bot_frame, textvariable=self.t2_out_hint_var, style="Hint.TLabel")
        lbl_out.pack(anchor="w")
        self.add_tooltip(lbl_out, "输出文件与 batch_report.csv 会写入该目录。")

        self.t2_mode_full.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_mode_sector.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_mode_chi.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_sector_ranges_text.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_sector_save_each.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_sector_save_combined.trace_add("write", lambda *_: self.refresh_queue_status())
        self.t2_output_root.trace_add("write", lambda *_: self.refresh_queue_status())
        self.refresh_queue_status()

    # =========================================================================
    # TAB 3: External 1D -> Absolute Intensity
    # =========================================================================
    def init_tab3_external_1d(self):
        p = self.tab3

        self.t3_files = []
        self.t3_pipeline_mode = tk.StringVar(value="scaled")
        self.t3_corr_mode = tk.StringVar(value="k_over_d")
        self.t3_fixed_thk = tk.DoubleVar(value=1.0)
        self.t3_x_mode = tk.StringVar(value="auto")
        self.t3_meta_csv_path = tk.StringVar()
        self.t3_bg1d_path = tk.StringVar()
        self.t3_dark1d_path = tk.StringVar()
        self.t3_output_root = tk.StringVar(value="")
        self.t3_use_meta_thk = tk.BooleanVar(value=True)
        self.t3_sample_exp = tk.DoubleVar(value=1.0)
        self.t3_sample_i0 = tk.DoubleVar(value=1.0)
        self.t3_sample_t = tk.DoubleVar(value=1.0)
        self.t3_bg_exp = tk.DoubleVar(value=1.0)
        self.t3_bg_i0 = tk.DoubleVar(value=1.0)
        self.t3_bg_t = tk.DoubleVar(value=1.0)
        self.t3_sync_bg_from_global = tk.BooleanVar(value=True)
        self.t3_bg_exp.set(self.global_vars["bg_exp"].get())
        self.t3_bg_i0.set(self.global_vars["bg_i0"].get())
        self.t3_bg_t.set(self.global_vars["bg_t"].get())
        self.t3_resume_enabled = tk.BooleanVar(value=True)
        self.t3_overwrite = tk.BooleanVar(value=False)
        self.t3_queue_info = tk.StringVar(value="队列文件: 0")
        self.t3_out_hint = tk.StringVar(value="输出目录将自动创建: processed_external_1d_abs")

        f_guide = ttk.LabelFrame(p, text="外部 1D 绝对强度校正流程", style="Group.TLabelframe")
        f_guide.pack(fill="x", padx=10, pady=(8, 3))
        guide = (
            "① 先在 Tab1 得到可信 K 因子\n"
            "② 选择流程：仅比例缩放 / 原始1D完整校正\n"
            "③ 导入外部1D文件（原始模式还需 BG1D/Dark1D 与参数）\n"
            "④ 选择校正公式（K/d 或 K）与 X 轴类型\n"
            "⑤ 先预检查，再批量输出绝对强度表格"
        )
        lbl_guide = ttk.Label(f_guide, text=guide, justify="left", style="Hint.TLabel")
        lbl_guide.pack(fill="x", padx=4, pady=3)
        self.add_tooltip(lbl_guide, "适合你在 pyFAI/其他软件完成积分后，仅在本程序做绝对标定。")

        top = ttk.Frame(p)
        top.pack(fill="x", padx=10, pady=5)

        c1 = ttk.LabelFrame(top, text="1. 全局与公式", style="Group.TLabelframe")
        c1.pack(side="left", fill="y", padx=5)
        self.add_hint(c1, "K 来自 Tab1。先选流程，再选公式。原始1D流程会用到 exp/I0/T 与 BG1D/Dark1D。", wraplength=380)

        c1_grid = ttk.Frame(c1)
        c1_grid.pack(fill="x")
        ttk.Label(c1_grid, text="K 因子:").grid(row=0, column=0, sticky="e")
        e_k = ttk.Entry(c1_grid, textvariable=self.global_vars["k_factor"], width=10)
        e_k.grid(row=0, column=1, padx=5, pady=1, sticky="w")
        ttk.Label(c1_grid, text="流程:").grid(row=1, column=0, sticky="e")
        rb_scaled = ttk.Radiobutton(
            c1_grid, text="仅比例缩放", variable=self.t3_pipeline_mode, value="scaled"
        )
        rb_scaled.grid(row=1, column=1, sticky="w")
        rb_raw = ttk.Radiobutton(
            c1_grid, text="原始1D完整校正", variable=self.t3_pipeline_mode, value="raw"
        )
        rb_raw.grid(row=2, column=1, sticky="w")

        rb_kd = ttk.Radiobutton(
            c1_grid,
            text="外部1D未除厚度: I_abs = I_rel * K / d",
            variable=self.t3_corr_mode,
            value="k_over_d",
        )
        rb_kd.grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 1))
        ttk.Label(c1_grid, text="固定厚度(mm):").grid(row=4, column=0, sticky="e")
        e_thk = ttk.Entry(c1_grid, textvariable=self.t3_fixed_thk, width=8)
        e_thk.grid(row=4, column=1, padx=5, pady=1, sticky="w")

        rb_k = ttk.Radiobutton(
            c1_grid,
            text="外部1D已除厚度: I_abs = I_rel * K",
            variable=self.t3_corr_mode,
            value="k_only",
        )
        rb_k.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 1))

        ttk.Label(c1_grid, text="X轴类型:").grid(row=6, column=0, sticky="e")
        cb_x = ttk.Combobox(c1_grid, textvariable=self.t3_x_mode, width=12, state="readonly")
        cb_x["values"] = ("auto", "q_A^-1", "chi_deg")
        cb_x.grid(row=6, column=1, padx=5, pady=1, sticky="w")
        ttk.Label(c1_grid, text="I0语义:", style="Hint.TLabel").grid(row=7, column=0, sticky="e")
        ttk.Label(c1_grid, textvariable=self.global_vars["monitor_mode"], style="Hint.TLabel").grid(row=7, column=1, sticky="w")

        self.add_tooltip(e_k, "必须 >0。优先使用 Tab1 最新标定值。")
        self.add_tooltip(rb_scaled, "适合外部1D已做过本底/归一化，仅需绝对强度映射。")
        self.add_tooltip(rb_raw, "适合外部1D是原始积分强度，需要在本页完成1D级扣本底和归一化。")
        self.add_tooltip(rb_kd, "适用于外部积分结果仍是相对强度（尚未除厚度）。")
        self.add_tooltip(e_thk, "仅在 K/d 模式下使用。单位 mm。")
        self.add_tooltip(rb_k, "适用于外部积分结果已经做了厚度归一化。")
        self.add_tooltip(cb_x, "auto 会根据列名/后缀推断 Q_A^-1 或 Chi_deg。")

        c2 = ttk.LabelFrame(top, text="2. 执行策略", style="Group.TLabelframe")
        c2.pack(side="left", fill="y", padx=5)
        self.add_hint(c2, "建议先预检查。可断点续跑，避免重复覆盖。", wraplength=320)
        row_exec = ttk.Frame(c2)
        row_exec.pack(fill="x")
        cb_resume = ttk.Checkbutton(c2, text="断点续跑(跳过已存在输出)", variable=self.t3_resume_enabled)
        cb_resume.pack(anchor="w")
        cb_overwrite = ttk.Checkbutton(c2, text="强制覆盖输出", variable=self.t3_overwrite)
        cb_overwrite.pack(anchor="w")
        ttk.Label(
            row_exec,
            text="支持格式: .dat .txt .chi .csv（列至少包含 X 与 I；Error 可选）",
            style="Hint.TLabel",
            wraplength=320,
            justify="left",
        ).pack(anchor="w")
        self.add_tooltip(cb_resume, "输出存在时跳过，适合大批量中断后继续。")
        self.add_tooltip(cb_overwrite, "忽略已存在结果并重算。")

        c3 = ttk.LabelFrame(top, text="3. 原始1D校正参数（raw流程）", style="Group.TLabelframe")
        c3.pack(side="left", fill="y", padx=5)
        self.add_hint(
            c3,
            "仅当流程=原始1D完整校正时生效。可直接使用 Tab2 的 batch_report.csv 或 metadata.csv。",
            wraplength=420,
        )

        row_meta = self.add_file_row(c3, "Metadata CSV:", self.t3_meta_csv_path, "*.csv")
        row_bg = self.add_file_row(c3, "BG 1D 文件:", self.t3_bg1d_path, "*.dat *.txt *.chi *.csv")
        row_dark = self.add_file_row(c3, "Dark 1D 文件:", self.t3_dark1d_path, "*.dat *.txt *.chi *.csv")

        row_meta_ops = ttk.Frame(c3)
        row_meta_ops.pack(fill="x", pady=(1, 1))
        btn_meta_from_batch = ttk.Button(
            row_meta_ops,
            text="由 Tab2 报告生成 metadata",
            command=self.t3_make_meta_from_batch_report,
        )
        btn_meta_from_batch.pack(side="left", padx=(3, 0))

        self.add_tooltip(row_meta["entry"], "可选。支持 metadata.csv，或直接选择 Tab2 的 batch_report.csv。")
        self.add_tooltip(row_bg["entry"], "必填（raw流程）。与样品同积分方式得到的 BG 1D。")
        self.add_tooltip(row_dark["entry"], "可选。未提供则按 0 处理。")
        self.add_tooltip(btn_meta_from_batch, "从 Tab2 的 batch_report.csv 一键生成 Tab3 可用 metadata.csv，并自动回填路径。")

        cb_meta_thk = ttk.Checkbutton(c3, text="优先使用 metadata 中的 thk_mm", variable=self.t3_use_meta_thk)
        cb_meta_thk.pack(anchor="w", padx=3, pady=(2, 1))
        self.add_tooltip(cb_meta_thk, "开启后，若某样品 metadata 含 thk_mm，则覆盖固定厚度。")
        cb_sync_bg = ttk.Checkbutton(
            c3,
            text="BG参数跟随 Tab1 全局(bg_exp/bg_i0/bg_t)",
            variable=self.t3_sync_bg_from_global,
            command=self.on_t3_sync_bg_toggle,
        )
        cb_sync_bg.pack(anchor="w", padx=3, pady=(0, 1))
        self.add_tooltip(cb_sync_bg, "开启后 Tab3 的 BG 参数会随 Tab1/全局变化自动更新，避免陈旧值。")

        f_sample = ttk.Frame(c3)
        f_sample.pack(fill="x", pady=(2, 1))
        ttk.Label(f_sample, text="样品固定参数 exp/i0/T:", style="Hint.TLabel").grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Label(f_sample, text="exp").grid(row=1, column=0, sticky="e")
        ttk.Entry(f_sample, textvariable=self.t3_sample_exp, width=7).grid(row=1, column=1, padx=2)
        ttk.Label(f_sample, text="i0").grid(row=1, column=2, sticky="e")
        ttk.Entry(f_sample, textvariable=self.t3_sample_i0, width=7).grid(row=1, column=3, padx=2)
        ttk.Label(f_sample, text="T").grid(row=1, column=4, sticky="e")
        ttk.Entry(f_sample, textvariable=self.t3_sample_t, width=7).grid(row=1, column=5, padx=2)

        f_bg = ttk.Frame(c3)
        f_bg.pack(fill="x", pady=(2, 1))
        ttk.Label(f_bg, text="BG固定参数 exp/i0/T:", style="Hint.TLabel").grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Label(f_bg, text="exp").grid(row=1, column=0, sticky="e")
        self.t3_bg_entry_exp = ttk.Entry(f_bg, textvariable=self.t3_bg_exp, width=7)
        self.t3_bg_entry_exp.grid(row=1, column=1, padx=2)
        ttk.Label(f_bg, text="i0").grid(row=1, column=2, sticky="e")
        self.t3_bg_entry_i0 = ttk.Entry(f_bg, textvariable=self.t3_bg_i0, width=7)
        self.t3_bg_entry_i0.grid(row=1, column=3, padx=2)
        ttk.Label(f_bg, text="T").grid(row=1, column=4, sticky="e")
        self.t3_bg_entry_t = ttk.Entry(f_bg, textvariable=self.t3_bg_t, width=7)
        self.t3_bg_entry_t.grid(row=1, column=5, padx=2)

        mid = ttk.LabelFrame(p, text="外部 1D 文件队列", style="Group.TLabelframe")
        mid.pack(fill="both", expand=True, padx=10, pady=5)
        self.add_hint(mid, "建议先点“预检查”确认每个文件的列解析情况。")

        tb = ttk.Frame(mid)
        tb.pack(fill="x")
        btn_add = ttk.Button(tb, text="添加1D文件", command=self.add_external_1d_files)
        btn_add.pack(side="left")
        btn_clear = ttk.Button(tb, text="清空队列", command=self.clear_external_1d_files)
        btn_clear.pack(side="left", padx=(4, 0))
        btn_check = ttk.Button(tb, text="预检查", command=self.dry_run_external_1d)
        btn_check.pack(side="right")
        self.add_tooltip(btn_add, "支持多选外部积分结果文件。")
        self.add_tooltip(btn_clear, "仅清空队列，不删除磁盘文件。")
        self.add_tooltip(btn_check, "检查列识别、点数和坐标类型推断。")

        ttk.Label(mid, textvariable=self.t3_queue_info, style="Hint.TLabel").pack(anchor="w", padx=5, pady=(2, 0))
        self.lb_ext1d = tk.Listbox(mid, height=9)
        self.lb_ext1d.pack(fill="both", expand=True, padx=5, pady=5)
        self.add_tooltip(self.lb_ext1d, "当前待转换的外部1D文件列表。")

        bot = ttk.Frame(p)
        bot.pack(fill="x", padx=10, pady=10)
        btn_run = ttk.Button(bot, text=">>> 开始外部1D绝对强度校正 <<<", command=self.run_external_1d_batch)
        btn_run.pack(fill="x", ipady=5)
        self.t3_prog_bar = ttk.Progressbar(bot, mode="determinate")
        self.t3_prog_bar.pack(fill="x", pady=5)
        row_out_dir = self.add_dir_row(bot, "输出根目录:", self.t3_output_root)
        ttk.Label(bot, textvariable=self.t3_out_hint, style="Hint.TLabel").pack(anchor="w")
        self.add_tooltip(btn_run, "将外部1D相对强度按选定公式批量转换为绝对强度。")
        self.add_tooltip(self.t3_prog_bar, "显示外部1D批处理进度。")
        self.add_tooltip(row_out_dir["entry"], "可选。不填时默认输出到首个输入文件所在目录。")

        self.global_vars["bg_exp"].trace_add("write", self.on_global_bg_changed_for_t3)
        self.global_vars["bg_i0"].trace_add("write", self.on_global_bg_changed_for_t3)
        self.global_vars["bg_t"].trace_add("write", self.on_global_bg_changed_for_t3)
        self.t3_output_root.trace_add("write", lambda *_: self.refresh_external_1d_status())
        self.on_t3_sync_bg_toggle()
        self.refresh_external_1d_status()

    def add_external_1d_files(self):
        fs = filedialog.askopenfilenames(
            filetypes=[("1D Files", "*.dat *.txt *.chi *.csv"), ("All Files", "*.*")]
        )
        for f in fs:
            if f not in self.t3_files:
                self.t3_files.append(f)
                self.lb_ext1d.insert(tk.END, Path(f).name)
        self.refresh_external_1d_status()

    def clear_external_1d_files(self):
        self.t3_files = []
        self.lb_ext1d.delete(0, tk.END)
        self.refresh_external_1d_status()

    def refresh_external_1d_status(self):
        if hasattr(self, "t3_queue_info"):
            total = len(getattr(self, "t3_files", []))
            uniq = len(dict.fromkeys(getattr(self, "t3_files", [])))
            if total == uniq:
                self.t3_queue_info.set(f"队列文件: {uniq}")
            else:
                self.t3_queue_info.set(f"队列文件: {total}（去重后 {uniq}）")

        if hasattr(self, "t3_out_hint"):
            custom_root = self.t3_output_root.get().strip() if hasattr(self, "t3_output_root") else ""
            if custom_root:
                self.t3_out_hint.set(
                    f"输出目录将写入: {custom_root}\\processed_external_1d_abs "
                    f"(报告: {custom_root}\\processed_external_1d_reports)"
                )
            else:
                self.t3_out_hint.set("输出目录将自动创建: processed_external_1d_abs（默认位于首个样品目录）")

    def sync_t3_bg_params_from_global(self):
        if not hasattr(self, "global_vars"):
            return
        try:
            self.t3_bg_exp.set(float(self.global_vars["bg_exp"].get()))
            self.t3_bg_i0.set(float(self.global_vars["bg_i0"].get()))
            self.t3_bg_t.set(float(self.global_vars["bg_t"].get()))
        except Exception:
            pass

    def on_global_bg_changed_for_t3(self, *_):
        if hasattr(self, "t3_sync_bg_from_global") and bool(self.t3_sync_bg_from_global.get()):
            self.sync_t3_bg_params_from_global()

    def on_t3_sync_bg_toggle(self):
        follow = bool(self.t3_sync_bg_from_global.get()) if hasattr(self, "t3_sync_bg_from_global") else False
        if follow:
            self.sync_t3_bg_params_from_global()
        state = "disabled" if follow else "normal"
        for w in [
            getattr(self, "t3_bg_entry_exp", None),
            getattr(self, "t3_bg_entry_i0", None),
            getattr(self, "t3_bg_entry_t", None),
        ]:
            if w is not None:
                try:
                    w.configure(state=state)
                except Exception:
                    pass

    def read_external_1d_profile(self, path):
        dfs = []
        errs = []
        read_trials = [
            {"sep": None, "engine": "python", "comment": "#"},
            {"sep": r"[,\s;]+", "engine": "python", "comment": "#"},
            {"sep": r"[,\s;]+", "engine": "python", "comment": "#", "header": None},
        ]

        for kw in read_trials:
            try:
                df = pd.read_csv(path, **kw)
                if df is not None and not df.empty and df.shape[1] >= 2:
                    dfs.append(df)
            except Exception as e:
                errs.append(str(e))

        if not dfs:
            raise ValueError(f"无法解析文件: {Path(path).name} ({'; '.join(errs[:2])})")

        best = None
        best_pts = -1

        for df in dfs:
            numeric_cols = {}
            for col in df.columns:
                s = pd.to_numeric(df[col], errors="coerce")
                arr = s.to_numpy(dtype=np.float64, na_value=np.nan)
                cnt = int(np.isfinite(arr).sum())
                if cnt >= 3:
                    numeric_cols[col] = s

            if len(numeric_cols) < 2:
                continue

            cols = list(numeric_cols.keys())

            def pick(tokens, used):
                for c in cols:
                    if c in used:
                        continue
                    name = str(c).strip().lower().replace("_", "").replace(" ", "")
                    if any(t in name for t in tokens):
                        return c
                return None

            x_col = pick(["q", "chi", "radial", "2theta", "x"], set()) or cols[0]
            i_col = pick(["intensity", "irel", "iabs", "signal", "count", "i"], {x_col})
            if i_col is None:
                i_col = next((c for c in cols if c != x_col), None)
            if i_col is None:
                continue

            err_col = pick(["error", "sigma", "std", "unc"], {x_col, i_col})
            if err_col is None and len(cols) >= 3:
                err_col = next((c for c in cols if c not in {x_col, i_col}), None)

            x = pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
            i_rel = pd.to_numeric(df[i_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
            mask = np.isfinite(x) & np.isfinite(i_rel)
            if int(mask.sum()) < 3:
                continue

            x = x[mask]
            i_rel = i_rel[mask]
            if err_col is not None:
                err = pd.to_numeric(df[err_col], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)[mask]
                err = np.where(np.isfinite(err), err, np.nan)
            else:
                err = np.full_like(i_rel, np.nan, dtype=np.float64)

            order = np.argsort(x)
            x = x[order]
            i_rel = i_rel[order]
            err = err[order]

            pts = int(x.size)
            if pts > best_pts:
                best_pts = pts
                best = {
                    "x": x,
                    "i_rel": i_rel,
                    "err_rel": err,
                    "x_col": str(x_col),
                    "i_col": str(i_col),
                    "err_col": str(err_col) if err_col is not None else "",
                }

        if best is None:
            raise ValueError(f"无法从 {Path(path).name} 识别有效数值列（至少需要 X 和 I 两列）")
        return best

    def _regularize_xy_triplet(self, x, y, e=None, min_points=3, name="profile"):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        if e is None:
            e = np.full_like(y, np.nan, dtype=np.float64)
        else:
            e = np.asarray(e, dtype=np.float64)

        if x.shape != y.shape:
            raise ValueError(f"{name}: x/y 形状不一致。")
        if e.shape != x.shape:
            e = np.full_like(y, np.nan, dtype=np.float64)

        mask = np.isfinite(x) & np.isfinite(y)
        x = x[mask]
        y = y[mask]
        e = e[mask]
        if x.size < min_points:
            raise ValueError(f"{name}: 有效点数不足（<{min_points}）。")

        order = np.argsort(x)
        x = x[order]
        y = y[order]
        e = e[order]

        # Collapse duplicate x values by averaging to build a stable monotonic grid.
        ux, inv = np.unique(x, return_inverse=True)
        if ux.size != x.size:
            y_sum = np.zeros_like(ux, dtype=np.float64)
            cnt = np.zeros_like(ux, dtype=np.float64)
            e_sum = np.zeros_like(ux, dtype=np.float64)
            e_cnt = np.zeros_like(ux, dtype=np.float64)
            for i, g in enumerate(inv):
                y_sum[g] += y[i]
                cnt[g] += 1.0
                if np.isfinite(e[i]):
                    e_sum[g] += e[i]
                    e_cnt[g] += 1.0
            y = y_sum / np.clip(cnt, 1.0, None)
            e = np.where(e_cnt > 0, e_sum / np.clip(e_cnt, 1.0, None), np.nan)
            x = ux

        if x.size < min_points:
            raise ValueError(f"{name}: 去重后有效点数不足（<{min_points}）。")
        return x, y, e

    def infer_external_x_label(self, path, profile):
        mode = self.t3_x_mode.get().strip().lower()
        if mode == "q_a^-1":
            return "Q_A^-1"
        if mode == "chi_deg":
            return "Chi_deg"

        name = f"{profile.get('x_col', '')}".lower()
        fname = Path(path).name.lower()
        if ("chi" in name) or fname.endswith(".chi"):
            return "Chi_deg"
        return "Q_A^-1"

    def parse_mode_outputs(self, outputs_raw):
        if outputs_raw is None:
            return []
        if isinstance(outputs_raw, (int, float, np.number)) and not np.isfinite(outputs_raw):
            return []

        s = str(outputs_raw).strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return []

        out = []
        for part in s.split("|"):
            item = str(part).strip()
            if not item:
                continue
            m = re.match(
                r"^(1d_full|1d_sector(?:\[[^\]]+\])?|1d_sector_sum|radial_chi)\s*:\s*(.+)$",
                item,
                flags=re.IGNORECASE,
            )
            if m:
                item = m.group(2).strip()
            item = re.sub(r"\(existing\)\s*$", "", item, flags=re.IGNORECASE).strip()
            if item:
                out.append(item)
        return out

    def collect_external_meta_rows(self, df):
        if df is None or df.empty:
            return [], {}

        col_map = {}
        for c in df.columns:
            col_map[self._norm_key(c)] = c

        def pick(names):
            for n in names:
                if n in col_map:
                    return col_map[n]
            return None

        file_col = pick(["file", "filename", "name", "path", "sample", "samplename"])
        outputs_col = pick(["outputs", "output", "result", "results"])
        if file_col is None and outputs_col is None:
            raise ValueError("metadata CSV 缺少文件列（file/filename/name/path）或输出列（outputs）。")

        exp_col = pick(["exp", "exposure", "exposuretime", "exposures", "counttime", "time", "exposures"])
        mon_col = pick(["i0", "mon", "monitor", "beammonitor", "flux"])
        trans_col = pick(["trans", "transmission", "sampletransmission", "abs"])
        thk_mm_col = pick(["thkmm", "thicknessmm", "thickness", "dmm", "calcthkmm", "fixedthicknessmm"])
        thk_cm_col = pick(["thkcm", "thicknesscm", "dcm"])

        out_map = {}
        rows = []
        for _, row in df.iterrows():
            names = []

            if file_col is not None:
                raw_file = str(row.get(file_col, "")).strip()
                if raw_file:
                    names.append(raw_file)
            if outputs_col is not None:
                names.extend(self.parse_mode_outputs(row.get(outputs_col)))

            uniq_names = []
            seen = set()
            for nm in names:
                nm_s = str(nm).strip()
                if not nm_s:
                    continue
                nk = nm_s.lower()
                if nk in seen:
                    continue
                seen.add(nk)
                uniq_names.append(nm_s)

            if not uniq_names:
                continue

            raw_exp = row.get(exp_col) if exp_col is not None else None
            raw_mon = row.get(mon_col) if mon_col is not None else None
            raw_trans = row.get(trans_col) if trans_col is not None else None
            raw_thk_mm = row.get(thk_mm_col) if thk_mm_col is not None else None
            raw_thk_cm = row.get(thk_cm_col) if thk_cm_col is not None else None

            exp = self._extract_float(raw_exp)
            mon = self._extract_float(raw_mon)
            trans = self._extract_float(raw_trans)
            if trans is not None:
                trans = self._normalize_transmission(trans, raw=raw_trans, key=trans_col)

            thk_mm = self._extract_float(raw_thk_mm)
            if thk_mm is None:
                thk_cm = self._extract_float(raw_thk_cm)
                if thk_cm is not None:
                    thk_mm = thk_cm * 10.0

            meta = {"exp": exp, "mon": mon, "trans": trans, "thk_mm": thk_mm}
            for nm in uniq_names:
                p = Path(nm)
                aliases = {str(nm).lower(), p.name.lower(), p.stem.lower()}
                for a in aliases:
                    if a:
                        out_map[a] = meta
                rows.append({
                    "file": str(nm).strip(),
                    "exp": exp if exp is not None else np.nan,
                    "i0": mon if mon is not None else np.nan,
                    "trans": trans if trans is not None else np.nan,
                    "thk_mm": thk_mm if thk_mm is not None else np.nan,
                })

        if rows:
            df_rows = pd.DataFrame(rows)
            if "file" in df_rows.columns:
                df_rows["file"] = df_rows["file"].astype(str).str.strip()
                df_rows = df_rows[df_rows["file"] != ""]
                df_rows["_k"] = df_rows["file"].str.lower()
                df_rows = df_rows.drop_duplicates(subset=["_k"], keep="last").drop(columns=["_k"])
            rows = df_rows.to_dict("records")

        return rows, out_map

    def export_tab3_metadata_from_report(self, report_csv_path, stamp=None):
        report_path = Path(report_csv_path)
        if not report_path.exists():
            raise FileNotFoundError(f"未找到报告文件: {report_path}")

        try:
            df = pd.read_csv(report_path, sep=None, engine="python")
        except Exception:
            df = pd.read_csv(report_path)

        rows, _ = self.collect_external_meta_rows(df)
        if not rows:
            raise ValueError("未从报告中提取到可用 metadata 行。")

        out_df = pd.DataFrame(rows)
        for c in ["file", "exp", "i0", "trans", "thk_mm"]:
            if c not in out_df.columns:
                out_df[c] = np.nan
        out_df = out_df[["file", "exp", "i0", "trans", "thk_mm"]]

        out_df["file"] = out_df["file"].astype(str).str.strip()
        out_df = out_df[out_df["file"] != ""]
        if out_df.empty:
            raise ValueError("metadata 行为空：未识别到文件名。")

        out_df["_k"] = out_df["file"].str.lower()
        out_df = out_df.drop_duplicates(subset=["_k"], keep="last").drop(columns=["_k"])
        out_df = out_df.sort_values("file").reset_index(drop=True)

        if not stamp:
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        out_dir = report_path.parent
        out_stamp = out_dir / f"metadata_for_tab3_{stamp}.csv"
        out_latest = out_dir / "metadata.csv"
        out_df.to_csv(out_stamp, index=False, encoding="utf-8-sig")
        out_df.to_csv(out_latest, index=False, encoding="utf-8-sig")
        return out_stamp, out_latest, int(len(out_df))

    def t3_make_meta_from_batch_report(self):
        try:
            report_path = filedialog.askopenfilename(
                filetypes=[("Batch Report", "batch_report_*.csv"), ("CSV", "*.csv"), ("All Files", "*.*")]
            )
            if not report_path:
                return
            out_stamp, out_latest, n_rows = self.export_tab3_metadata_from_report(report_path)
            self.t3_meta_csv_path.set(str(out_latest))
            messagebox.showinfo(
                "metadata 已生成",
                (
                    f"已从报告生成 metadata。\n"
                    f"行数: {n_rows}\n"
                    f"时间戳文件: {out_stamp.name}\n"
                    f"默认文件: {out_latest.name}\n"
                    f"Tab3 将使用: {out_latest}"
                ),
            )
        except Exception as e:
            messagebox.showerror("生成 metadata 失败", f"{e}\n{traceback.format_exc()}")

    def load_external_meta_map(self, csv_path):
        if not csv_path:
            return {}

        try:
            df = pd.read_csv(csv_path, sep=None, engine="python")
        except Exception:
            df = pd.read_csv(csv_path)

        if df is None or df.empty:
            return {}
        _, out_map = self.collect_external_meta_rows(df)
        return out_map

    def get_external_meta_for_file(self, meta_map, file_path):
        if not meta_map:
            return None
        p = Path(file_path)

        def norm_path(s):
            return str(s).strip().replace("\\", "/").lower()

        full_key = norm_path(file_path)
        if full_key in meta_map:
            return meta_map[full_key]

        # 兼容 metadata 使用相对路径（例如 sector_01/sample.dat），而实际文件是绝对路径。
        suffix_hits = []
        for k in meta_map.keys():
            ks = norm_path(k)
            if "/" not in ks:
                continue
            if full_key.endswith("/" + ks) or full_key.endswith(ks):
                suffix_hits.append((len(ks), k))
        if suffix_hits:
            suffix_hits.sort(reverse=True)
            return meta_map[suffix_hits[0][1]]

        candidates = [p.name.lower(), p.stem.lower()]
        for c in candidates:
            if c in meta_map:
                return meta_map[c]
        return None

    def parse_external_1d_header_meta(self, file_path):
        meta = {}
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for _ in range(200):
                    line = f.readline()
                    if not line:
                        break
                    s = line.strip()
                    if not s:
                        continue
                    if not s.startswith(("#", ";", "//")):
                        break
                    s = s.lstrip("#;/ ").strip()
                    if not s:
                        continue
                    if "=" in s:
                        k, v = s.split("=", 1)
                    elif ":" in s:
                        k, v = s.split(":", 1)
                    else:
                        parts = s.split(None, 1)
                        if len(parts) != 2:
                            continue
                        k, v = parts
                    nk = self._norm_key(k)
                    if nk:
                        meta[nk] = v.strip()
        except Exception:
            return {"exp": None, "mon": None, "trans": None, "thk_mm": None}

        exp_raw, exp_key = self.meta_get_raw(meta, ["exposuretime", "counttime", "acqtime", "exposure", "time", "exp"])
        mon_raw, _ = self.meta_get_raw(meta, ["monitor", "beammonitor", "ionchamber", "mon", "i0", "flux"])
        trans_raw, trans_key = self.meta_get_raw(meta, ["sampletransmission", "transmission", "trans", "abs"])
        thk_raw, _ = self.meta_get_raw(meta, ["thkmm", "thicknessmm", "thickness", "dmm"])

        exp = self._extract_float(exp_raw)
        if exp is not None:
            tag = f"{exp_key or ''} {exp_raw or ''}".lower()
            if "ms" in tag:
                exp /= 1000.0
            elif "us" in tag:
                exp /= 1_000_000.0
        mon = self._extract_float(mon_raw)
        trans = self._extract_float(trans_raw)
        if trans is not None:
            trans = self._normalize_transmission(trans, raw=trans_raw, key=trans_key)
        thk_mm = self._extract_float(thk_raw)

        return {"exp": exp, "mon": mon, "trans": trans, "thk_mm": thk_mm}

    def align_profile_to_x(self, x_target, ref_profile, name):
        x = np.asarray(x_target, dtype=np.float64)
        if not np.all(np.isfinite(x)):
            raise ValueError(f"{name} 目标 x 网格包含非有限值。")

        xr, yr, er = self._regularize_xy_triplet(
            ref_profile["x"],
            ref_profile["i_rel"],
            ref_profile.get("err_rel"),
            min_points=2,
            name=name,
        )

        if xr.size == x.size and np.allclose(xr, x, rtol=1e-7, atol=1e-9, equal_nan=False):
            y = yr
            e = er
        else:
            y = np.interp(x, xr, yr, left=np.nan, right=np.nan)
            finite_err = np.isfinite(er)
            if np.sum(finite_err) >= 2:
                e = np.interp(x, xr[finite_err], er[finite_err], left=np.nan, right=np.nan)
            else:
                e = np.full_like(y, np.nan)

        outside = int(np.sum(~np.isfinite(y)))
        return y, e, outside

    def resolve_external_sample_params(self, file_path, meta_map, monitor_mode):
        meta = self.get_external_meta_for_file(meta_map, file_path)
        hmeta = self.parse_external_1d_header_meta(file_path)

        exp = None
        mon = None
        trans = None
        thk_mm_meta = None
        source = "fixed"

        if meta is not None:
            if meta.get("exp") is not None:
                exp = meta["exp"]
            if meta.get("mon") is not None:
                mon = meta["mon"]
            if meta.get("trans") is not None:
                trans = meta["trans"]
            thk_mm_meta = meta.get("thk_mm")
            source = "meta"

        if hmeta is not None:
            if exp is None and hmeta.get("exp") is not None:
                exp = hmeta["exp"]
                if source != "meta":
                    source = "header"
            if mon is None and hmeta.get("mon") is not None:
                mon = hmeta["mon"]
                if source != "meta":
                    source = "header"
            if trans is None and hmeta.get("trans") is not None:
                trans = hmeta["trans"]
                if source != "meta":
                    source = "header"
            if thk_mm_meta is None and hmeta.get("thk_mm") is not None:
                thk_mm_meta = hmeta["thk_mm"]
                if source == "fixed":
                    source = "header"

        if exp is None:
            exp = self.t3_sample_exp.get()
        if mon is None:
            mon = self.t3_sample_i0.get()
        if trans is None:
            trans = self.t3_sample_t.get()

        norm = self.compute_norm_factor(exp, mon, trans, monitor_mode)
        return {
            "exp": exp,
            "mon": mon,
            "trans": trans,
            "norm": norm,
            "thk_mm_meta": thk_mm_meta,
            "source": source,
        }

    def dry_run_external_1d(self):
        if not self.t3_files:
            messagebox.showinfo("预检查", "队列为空，请先添加外部1D文件。")
            return

        rows = []
        files = list(dict.fromkeys(self.t3_files))
        pipeline_mode = self.t3_pipeline_mode.get().strip().lower()
        mode = self.t3_corr_mode.get()
        k = float(self.global_vars["k_factor"].get())
        thk_mm = float(self.t3_fixed_thk.get())
        monitor_mode = self.get_monitor_mode()
        warnings = []

        if k <= 0:
            warnings.append("K 因子 <= 0。")
        if mode == "k_over_d" and thk_mm <= 0:
            warnings.append("K/d 模式下固定厚度必须 > 0 mm。")

        meta_map = {}
        bg_prof = None
        dark_prof = None
        bg_norm = np.nan
        if pipeline_mode == "raw":
            meta_path = self.t3_meta_csv_path.get().strip()
            if meta_path:
                try:
                    meta_map = self.load_external_meta_map(meta_path)
                except Exception as e:
                    warnings.append(f"metadata CSV 读取失败: {e}")
            else:
                warnings.append("raw流程未提供 metadata CSV，将全部使用固定样品参数。")

            bg_path = self.t3_bg1d_path.get().strip()
            if not bg_path:
                warnings.append("raw流程缺少 BG 1D 文件。")
            else:
                try:
                    bg_prof = self.read_external_1d_profile(bg_path)
                except Exception as e:
                    warnings.append(f"BG 1D 读取失败: {e}")

            dark_path = self.t3_dark1d_path.get().strip()
            if dark_path:
                try:
                    dark_prof = self.read_external_1d_profile(dark_path)
                except Exception as e:
                    warnings.append(f"Dark 1D 读取失败: {e}")

            bg_norm = self.compute_norm_factor(
                self.t3_bg_exp.get(), self.t3_bg_i0.get(), self.t3_bg_t.get(), monitor_mode
            )
            if (not np.isfinite(bg_norm) or bg_norm <= 0) and bg_path:
                bg_h = self.parse_external_1d_header_meta(bg_path)
                bg_norm = self.compute_norm_factor(bg_h.get("exp"), bg_h.get("mon"), bg_h.get("trans"), monitor_mode)
            if not np.isfinite(bg_norm) or bg_norm <= 0:
                warnings.append("BG 归一化因子 <=0，请检查 BG exp/i0/T。")

        for fp in files:
            try:
                prof = self.read_external_1d_profile(fp)
                x_label = self.infer_external_x_label(fp, prof)
                status = "正常"
                reason = ""
                norm_s = np.nan
                thk_used = np.nan
                meta_src = "-"
                outside_bg = 0
                outside_dark = 0

                if pipeline_mode == "raw":
                    sp = self.resolve_external_sample_params(fp, meta_map, monitor_mode)
                    norm_s = sp["norm"]
                    meta_src = sp["source"]
                    if not np.isfinite(norm_s) or norm_s <= 0:
                        status = "失败"
                        reason = "样品归一化因子无效（exp/i0/T）"
                    else:
                        if mode == "k_over_d":
                            thk_use_mm = thk_mm
                            if self.t3_use_meta_thk.get() and sp["thk_mm_meta"] is not None:
                                thk_use_mm = float(sp["thk_mm_meta"])
                            thk_used = thk_use_mm / 10.0 if np.isfinite(thk_use_mm) else np.nan
                            if not np.isfinite(thk_used) or thk_used <= 0:
                                status = "失败"
                                reason = "厚度无效（固定厚度或metadata thk_mm）"
                        else:
                            thk_used = np.nan

                        if status == "正常" and bg_prof is not None:
                            _, _, outside_bg = self.align_profile_to_x(prof["x"], bg_prof, "BG")
                        if status == "正常" and dark_prof is not None:
                            _, _, outside_dark = self.align_profile_to_x(prof["x"], dark_prof, "Dark")

                rows.append({
                    "File": Path(fp).name,
                    "Points": len(prof["x"]),
                    "XCol": prof.get("x_col", ""),
                    "ICol": prof.get("i_col", ""),
                    "ErrCol": prof.get("err_col", ""),
                    "XLabel": x_label,
                    "Norm_s": norm_s,
                    "Thk_cm": thk_used,
                    "MetaSrc": meta_src,
                    "BG_OutsidePts": outside_bg,
                    "Dark_OutsidePts": outside_dark,
                    "Status": status,
                    "Reason": reason,
                })
            except Exception as e:
                rows.append({
                    "File": Path(fp).name,
                    "Points": 0,
                    "XCol": "",
                    "ICol": "",
                    "ErrCol": "",
                    "XLabel": "",
                    "Norm_s": np.nan,
                    "Thk_cm": np.nan,
                    "MetaSrc": "-",
                    "BG_OutsidePts": 0,
                    "Dark_OutsidePts": 0,
                    "Status": "失败",
                    "Reason": str(e),
                })

        top = tk.Toplevel(self.root)
        top.title("外部1D预检查结果")
        txt = tk.Text(top, font=("Consolas", 9))
        txt.pack(fill="both", expand=True)
        txt.insert(tk.END, f"K 因子: {k}\n")
        txt.insert(tk.END, f"流程: {pipeline_mode}\n")
        txt.insert(tk.END, f"校正模式: {mode}\n")
        txt.insert(tk.END, f"固定厚度(mm): {thk_mm}\n")
        txt.insert(tk.END, f"X轴模式: {self.t3_x_mode.get()}\n")
        if pipeline_mode == "raw":
            txt.insert(tk.END, f"I0语义: {monitor_mode} (norm={self.monitor_norm_formula(monitor_mode)})\n")
            txt.insert(tk.END, f"BG_Norm: {bg_norm if np.isfinite(bg_norm) else 'NaN'}\n")
        txt.insert(tk.END, "-" * 80 + "\n")
        if warnings:
            txt.insert(tk.END, "[预检查警告]\n")
            for w in warnings:
                txt.insert(tk.END, f"- {w}\n")
            txt.insert(tk.END, "-" * 80 + "\n")
        else:
            txt.insert(tk.END, "[预检查通过] 参数未见明显问题。\n")
            txt.insert(tk.END, "-" * 80 + "\n")
        txt.insert(tk.END, pd.DataFrame(rows).to_string(index=False))

    def run_external_1d_batch(self):
        try:
            if not self.t3_files:
                raise ValueError("队列为空：请先添加外部1D文件。")

            files = list(dict.fromkeys(self.t3_files))
            if len(files) < len(self.t3_files):
                self.t3_files = files
                self.lb_ext1d.delete(0, tk.END)
                for f in self.t3_files:
                    self.lb_ext1d.insert(tk.END, Path(f).name)
                self.refresh_external_1d_status()

            k = float(self.global_vars["k_factor"].get())
            if not np.isfinite(k) or k <= 0:
                raise ValueError("K 因子无效（必须 > 0）。")

            pipeline_mode = self.t3_pipeline_mode.get().strip().lower()
            if pipeline_mode not in ("scaled", "raw"):
                raise ValueError(f"未知流程模式: {pipeline_mode}")

            corr_mode = self.t3_corr_mode.get().strip().lower()
            if corr_mode not in ("k_over_d", "k_only"):
                raise ValueError(f"未知校正模式: {corr_mode}")

            fixed_thk_mm = float(self.t3_fixed_thk.get())
            if corr_mode == "k_over_d" and fixed_thk_mm <= 0:
                raise ValueError("K/d 模式下固定厚度必须 > 0 mm。")

            fixed_thk_cm = fixed_thk_mm / 10.0 if corr_mode == "k_over_d" else np.nan
            scale_factor_global = (k / fixed_thk_cm) if corr_mode == "k_over_d" else k
            monitor_mode = self.get_monitor_mode()

            meta_map = {}
            bg_prof = None
            dark_prof = None
            bg_norm = np.nan
            if pipeline_mode == "raw":
                meta_path = self.t3_meta_csv_path.get().strip()
                if meta_path:
                    meta_map = self.load_external_meta_map(meta_path)

                bg_path = self.t3_bg1d_path.get().strip()
                if not bg_path:
                    raise ValueError("raw流程必须提供 BG 1D 文件。")
                bg_prof = self.read_external_1d_profile(bg_path)

                dark_path = self.t3_dark1d_path.get().strip()
                if dark_path:
                    dark_prof = self.read_external_1d_profile(dark_path)

                bg_norm = self.compute_norm_factor(
                    self.t3_bg_exp.get(), self.t3_bg_i0.get(), self.t3_bg_t.get(), monitor_mode
                )
                if (not np.isfinite(bg_norm) or bg_norm <= 0) and bg_path:
                    bg_h = self.parse_external_1d_header_meta(bg_path)
                    bg_norm = self.compute_norm_factor(bg_h.get("exp"), bg_h.get("mon"), bg_h.get("trans"), monitor_mode)
                if not np.isfinite(bg_norm) or bg_norm <= 0:
                    raise ValueError("raw流程下 BG 归一化因子无效，请检查 BG exp/i0/T。")

            custom_out_root = self.t3_output_root.get().strip() if hasattr(self, "t3_output_root") else ""
            if custom_out_root:
                out_root = Path(custom_out_root).expanduser()
                out_root.mkdir(parents=True, exist_ok=True)
            else:
                out_root = Path(files[0]).parent
            out_dir = out_root / "processed_external_1d_abs"
            report_dir = out_root / "processed_external_1d_reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            report_dir.mkdir(parents=True, exist_ok=True)

            resume = bool(self.t3_resume_enabled.get())
            overwrite = bool(self.t3_overwrite.get())
            stem_map = self.build_output_stem_map(files)

            self.t3_prog_bar["maximum"] = len(files)
            self.t3_prog_bar["value"] = 0

            rows = []
            ok = 0
            skip = 0
            fail = 0
            processed = 0

            for idx, fp in enumerate(files):
                fname = Path(fp).name
                reason = ""
                outputs = ""
                points = 0
                x_label = ""
                scale_factor = scale_factor_global if pipeline_mode == "scaled" else np.nan
                thk_cm_used = fixed_thk_cm if pipeline_mode == "scaled" else np.nan
                norm_s = np.nan
                meta_source = "-"
                outside_bg = 0
                outside_dark = 0
                try:
                    prof = self.read_external_1d_profile(fp)
                    points = len(prof["x"])
                    x_label = self.infer_external_x_label(fp, prof)
                    ext = ".chi" if x_label == "Chi_deg" else ".dat"
                    out_path = out_dir / f"{stem_map[fp]}{ext}"

                    if resume and (not overwrite) and out_path.exists():
                        status = "已跳过"
                        reason = "输出已存在"
                        outputs = out_path.name
                        skip += 1
                    else:
                        if pipeline_mode == "scaled":
                            scale_factor = scale_factor_global
                            thk_cm_used = fixed_thk_cm
                            i_abs = np.asarray(prof["i_rel"], dtype=np.float64) * scale_factor
                            err_abs = np.asarray(prof["err_rel"], dtype=np.float64) * abs(scale_factor)
                        else:
                            sp = self.resolve_external_sample_params(fp, meta_map, monitor_mode)
                            norm_s = sp["norm"]
                            meta_source = sp["source"]
                            if not np.isfinite(norm_s) or norm_s <= 0:
                                raise ValueError("样品归一化因子无效（exp/i0/T）")

                            if corr_mode == "k_over_d":
                                thk_use_mm = fixed_thk_mm
                                if self.t3_use_meta_thk.get() and sp["thk_mm_meta"] is not None:
                                    thk_use_mm = float(sp["thk_mm_meta"])
                                thk_cm_used = float(thk_use_mm) / 10.0
                                if not np.isfinite(thk_cm_used) or thk_cm_used <= 0:
                                    raise ValueError("厚度无效（固定厚度或metadata thk_mm）")
                                scale_factor = k / thk_cm_used
                            else:
                                thk_cm_used = np.nan
                                scale_factor = k

                            s_i = np.asarray(prof["i_rel"], dtype=np.float64)
                            s_e = np.asarray(prof["err_rel"], dtype=np.float64)
                            x = np.asarray(prof["x"], dtype=np.float64)

                            bg_i, bg_e, outside_bg = self.align_profile_to_x(x, bg_prof, "BG")
                            if dark_prof is not None:
                                d_i, d_e, outside_dark = self.align_profile_to_x(x, dark_prof, "Dark")
                            else:
                                d_i = np.zeros_like(s_i)
                                d_e = np.full_like(s_i, np.nan)

                            net = (s_i - d_i) / norm_s - (bg_i - d_i) / bg_norm

                            if np.all(~np.isfinite(net)):
                                raise ValueError("净信号全部为无效值，无法输出。")

                            if np.any(np.isfinite(s_e)) or np.any(np.isfinite(bg_e)) or np.any(np.isfinite(d_e)):
                                s_term = (np.nan_to_num(s_e, nan=0.0) / norm_s) ** 2
                                bg_term = (np.nan_to_num(bg_e, nan=0.0) / bg_norm) ** 2
                                d_term = (np.nan_to_num(d_e, nan=0.0) * (1.0 / norm_s + 1.0 / bg_norm)) ** 2
                                net_err = np.sqrt(s_term + bg_term + d_term)
                                net_err[~np.isfinite(net)] = np.nan
                            else:
                                net_err = np.full_like(net, np.nan)

                            i_abs = net * scale_factor
                            err_abs = net_err * abs(scale_factor)

                            issue = self.profile_health_issue(i_abs)
                            if issue:
                                raise ValueError(issue)

                        self.save_profile_table(out_path, prof["x"], i_abs, err_abs, x_label)
                        status = "成功"
                        outputs = out_path.name
                        ok += 1

                except Exception as e:
                    status = "失败"
                    reason = str(e)
                    fail += 1

                rows.append({
                    "Index": idx,
                    "File": fname,
                    "Status": status,
                    "Reason": reason,
                    "Points": points,
                    "XLabel": x_label,
                    "PipelineMode": pipeline_mode,
                    "CorrMode": corr_mode,
                    "K": k,
                    "Thickness_cm": thk_cm_used if np.isfinite(thk_cm_used) else np.nan,
                    "Norm_s": norm_s if np.isfinite(norm_s) else np.nan,
                    "BG_Norm": bg_norm if np.isfinite(bg_norm) else np.nan,
                    "MetaSource": meta_source,
                    "BG_OutsidePts": outside_bg,
                    "Dark_OutsidePts": outside_dark,
                    "ScaleFactor": scale_factor,
                    "Output": outputs,
                })

                processed += 1
                self.t3_prog_bar["value"] = processed
                self.root.update_idletasks()

            rows.sort(key=lambda x: x.get("Index", 0))
            for r in rows:
                r.pop("Index", None)

            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            report_path = report_dir / f"external1d_report_{stamp}.csv"
            pd.DataFrame(rows).to_csv(report_path, index=False, encoding="utf-8-sig")

            meta = {
                "timestamp": stamp,
                "files_total": len(files),
                "k_factor": k,
                "pipeline_mode": pipeline_mode,
                "corr_mode": corr_mode,
                "scale_factor_global": scale_factor_global,
                "fixed_thickness_mm": fixed_thk_mm if corr_mode == "k_over_d" else None,
                "x_mode": self.t3_x_mode.get(),
                "monitor_mode": monitor_mode,
                "monitor_norm_formula": self.monitor_norm_formula(monitor_mode),
                "meta_csv": self.t3_meta_csv_path.get().strip(),
                "bg_1d_path": self.t3_bg1d_path.get().strip(),
                "dark_1d_path": self.t3_dark1d_path.get().strip(),
                "bg_norm": float(bg_norm) if np.isfinite(bg_norm) else None,
                "resume_enabled": resume,
                "overwrite": overwrite,
                "output_root": str(out_root),
                "output_root_custom": bool(custom_out_root),
                "output_dir": str(out_dir),
                "report_csv": str(report_path),
                "summary": {"success": ok, "skipped": skip, "failed": fail},
            }
            meta_path = report_dir / f"external1d_meta_{stamp}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            messagebox.showinfo(
                "外部1D校正完成",
                (
                    "外部1D绝对强度校正完成。\n"
                    f"成功: {ok}\n"
                    f"跳过: {skip}\n"
                    f"失败: {fail}\n"
                    f"输出目录: {out_dir}\n"
                    f"报告: {report_path.name}\n"
                    f"元数据: {meta_path.name}"
                ),
            )

        except Exception as e:
            messagebox.showerror("外部1D校正错误", f"{e}\n{traceback.format_exc()}")

    def init_tab_help(self):
        p = self.tab_help

        head = ttk.LabelFrame(p, text="程序帮助（新手版）", style="Group.TLabelframe")
        head.pack(fill="x", padx=10, pady=(8, 4))
        ttk.Label(
            head,
            text=(
                "目标：先在 Tab1 得到可靠 K 因子，再在 Tab2 做稳健批处理。\n"
                "建议：第一次使用先完整看一遍“快速上手”和“常见错误”。"
            ),
            justify="left",
            style="Hint.TLabel",
        ).pack(fill="x", padx=5, pady=4)

        bar = ttk.Frame(p)
        bar.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(bar, text="帮助文本（可滚动）：", style="Bold.TLabel").pack(side="left")

        text_wrap = ttk.Frame(p)
        text_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        y_scroll = ttk.Scrollbar(text_wrap, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        txt = tk.Text(
            text_wrap,
            font=("Consolas", 10),
            wrap="word",
            yscrollcommand=y_scroll.set,
            padx=8,
            pady=8,
        )
        txt.pack(side="left", fill="both", expand=True)
        y_scroll.config(command=txt.yview)

        help_text = """
==============================
BL19B2 SAXS Workstation 使用帮助
==============================

[一] 程序做什么
1. Tab1：用标准样（推荐 GC）做 K 因子标定。
2. Tab2：把 2D 图像批处理成绝对强度 1D 结果（含误差列）。
3. Tab3：把外部软件积分后的 1D 相对强度批量转换为绝对强度。
4. 输出包含报告文件，便于复现实验流程。

----------------------------------------
[二] 第一次使用的最短路径（建议按顺序）
----------------------------------------
Step 1. 先做 Tab1 标定（只需一组 Std/BG/Dark/poni）
1) 选择文件：标准样、背景、暗场、poni。
2) 检查 Time/I0/T 是否自动带入正确（必要时手工改）。
3) 选择 I0 语义：
   - rate：I0 是每秒计数率，归一化用 exp * I0 * T
   - integrated：I0 是积分计数，归一化用 I0 * T
4) 填标准样厚度(mm)，点击“运行 K 因子标定”。
5) 重点看报告中的：
   - Points Used（越多越稳）
   - Std Dev（越小越稳）
   - Q overlap（要有足够重叠区间）
6) 标定成功后，K 会自动写入全局并保存历史。

Step 2. 再做 Tab2 批处理
1) 确认 K 因子 > 0；BG/Dark/poni 路径正确。
2) 选择厚度策略：
   - 自动厚度：d = -ln(T)/mu
   - 固定厚度：所有样品同一厚度
3) 选择积分模式（可多选）：
   - I-Q 全环
   - I-Q 扇区（支持多扇区：如 -25~25;45~65）
   - I-chi 织构（q 区间）
4) 选择修正项（推荐）：
   - 开启 Solid Angle
   - 误差模型选 azimuthal（常用）
   - 有掩膜就加载 Mask
   - 注意：Tab2 的 Solid Angle 必须与 Tab1 标定时一致，否则 K 因子不可直接使用
5) 参考模式：
   - 固定 BG/Dark（新手推荐，最稳定）
   - 自动匹配 BG/Dark（高级用法）
6) 先点“预检查”，确认没有关键警告。
7) 如需集中管理结果，可在底部“输出根目录”指定自定义路径。
8) 点击“开始稳健批处理”。

Step 3. 如果你已在外部软件完成积分（可选）
1) 进入 Tab3，导入外部 1D 文件（.dat/.txt/.chi/.csv）。
2) 选择流程：
   - 仅比例缩放：外部1D已完成本底/归一化
   - 原始1D完整校正：外部1D是原始积分结果，需要提供 BG1D/Dark1D 和 exp/I0/T
   - metadata 来源优先级：metadata.csv > 文件注释头 > Tab3 固定参数
   - BG固定参数默认跟随 Tab1 全局；可取消“BG参数跟随”后手动覆盖
   - metadata.csv 可以直接用 Tab2 的 batch_report.csv，或点“由 Tab2 报告生成 metadata”
3) 选择公式：
   - K/d：外部 1D 还未除厚度
   - K：外部 1D 已除厚度
4) 先预检查，再批量运行。
5) 如需集中管理结果，可在底部“输出根目录”指定自定义路径。

----------------------------------------
[三] 核心参数解释（新手必看）
----------------------------------------
1) Time(s)
   曝光时间。若 I0 语义是 rate，Time 会参与归一化；若是 integrated，不参与。

2) I0(Mon)
   入射强度监测值。请确认是“计数率”还是“积分计数”，并与 I0 语义一致。

3) Trans(T)
   透过率，推荐范围 (0, 1]。
   程序会对 1~2 的值做保护处理（视为漂移并夹到 1.0），
   仅对明确百分号或明显百分数字面量（>2）才按百分数换算。

4) mu（自动厚度模式）
   单位 cm^-1。mu 错会导致厚度和绝对强度整体偏差。

5) Polarization
   范围 [-1, 1]。不确定时先用 0。

6) 扇区角度（Tab2 azimuth_range）
   程序使用 pyFAI chi 定义：
   - 0° 向右
   - +90° 向下
   - -90° 向上
   - ±180° 向左
   支持跨 ±180° 扇区，例如 sec_min=170, sec_max=-170。
   多扇区可在“多扇区”中写为 `-25~25;45~65`（留空则使用单扇区输入框）。
   可点击“预览I-Q”在2D图上确认全环/多扇区积分区域。

----------------------------------------
[四] 程序内置的防错机制（你会看到的告警）
----------------------------------------
1) BG_Norm 与样品 Norm_s 量级异常
   若差异过大，固定 BG 模式会直接阻断，避免“过扣背景导致全负值”。

2) 积分结果健康检查
   若某条输出几乎全为非正值，模式会被判失败并提示检查归一化/BG。

3) 仪器一致性检查
   可检查能量、波长、距离、像素、尺寸是否一致。

----------------------------------------
[五] 常见问题与处理
----------------------------------------
Q1：整条曲线几乎全负？
A1：
  - 先看 batch_report 里的 Norm_s 和 BG_Norm 是否同量级。
  - 检查 BG 的 Time/I0/T 是否填写正确。
  - 检查 I0 语义（rate/integrated）是否选错。
  - 用“固定 BG/Dark + 预检查”先跑通。

Q2：为什么程序提示缺少 exp/mon/trans？
A2：
  - 头字段没读到或命名不标准。
  - 可手工在界面填入参数（尤其是 Tab1）。
  - 建议先用少量样品 dry_run 验证。

Q3：I-chi 结果看起来不对？
A3：
  - 检查 qmin/qmax 是否合理。
  - 程序已对 radial q 单位做兼容处理，但仍需确认 q 区间与物理预期一致。
  - 可点击“预览I-chi”在2D图上核对 q 环带范围。

Q4：Origin 导入不方便？
A4：
  - 当前输出是表头+制表符格式（TSV风格），列名包含坐标、I_abs、Error，直接按列导入。

Q5：pyFAI 导出的 1D 文件能直接读出 exp/I0/T 吗？
A5：
  - 多数情况下只能稳定读出 X/I/(可选Error) 列。
  - exp/I0/T 是否可读，取决于文件注释头是否写入了这些字段。
  - 程序会尝试从注释头读取；若读不到，请提供 metadata CSV 或固定参数。

Q6：metadata.csv 从哪来？
A6：
  - 推荐直接使用 Tab2 输出目录（默认样品目录，或你设置的自定义输出根目录）`processed_robust_reports` 中自动生成的：
    `metadata_for_tab3_*.csv` 或 `metadata.csv`。
  - 也可在 Tab3 点“由 Tab2 报告生成 metadata”，从 `batch_report_*.csv` 一键生成。

Q7：Tab2 扇区角度不确定怎么办？
A7：
  - 在 Tab2 扇区输入框旁点击“预览I-Q”。
  - 弹窗会叠加单扇区/多扇区掩膜与边界线，并显示角度定义（0°右、+90°下）。

----------------------------------------
[六] 输出文件说明
----------------------------------------
1) Tab1 输出
   - calibration_check.csv：标定后的参考曲线（含误差列）
   - k_factor_history.csv：K 历史与关键参数

2) Tab2 输出
   （根目录默认在样品目录，也可在 Tab2 底部自定义）
   - processed_robust_1d_full/*.dat
   - processed_robust_1d_sector/*.dat（单扇区）
   - processed_robust_1d_sector/sector_*/*.dat（多扇区分别保存）
   - processed_robust_1d_sector_combined/*.dat（扇区合并保存，若勾选）
   - processed_robust_radial_chi/*.chi
   每个文件均为：坐标列 + I_abs_cm^-1 + Error_cm^-1
   - processed_robust_reports/batch_report_*.csv
   - processed_robust_reports/metadata_for_tab3_*.csv
   - processed_robust_reports/metadata.csv
   - processed_robust_reports/run_meta_*.json

3) Tab3 输出
   （根目录默认在首个输入文件目录，也可在 Tab3 底部自定义）
   - processed_external_1d_abs/*.dat 或 *.chi
   - processed_external_1d_reports/external1d_report_*.csv
   - processed_external_1d_reports/external1d_meta_*.json

----------------------------------------
[七] 新手执行检查清单（每次开跑前）
----------------------------------------
[ ] K 因子来自最近一次可信标定（Tab1）
[ ] I0 语义确认无误（rate 或 integrated）
[ ] BG/Dark/poni 来自同一实验条件
[ ] 先做预检查（dry_run）再正式批处理
[ ] 看 batch_report：成功/失败原因是否合理

----------------------------------------
[八] 推荐工作习惯（减少返工）
----------------------------------------
1) 先用 3~5 个样品试跑，确认流程正确再全量跑。
2) 批处理时优先开启断点续跑，避免中断后重算全部。
3) 每批次保留 run_meta 与 batch_report，方便追溯与审稿说明。

（帮助页版本：v2，适配 Tab2->Tab3 直连 metadata 流程）
"""

        txt.insert(tk.END, help_text.strip() + "\n")
        txt.config(state="disabled")

        def copy_help():
            self.root.clipboard_clear()
            self.root.clipboard_append(help_text.strip() + "\n")
            self.root.update()
            messagebox.showinfo("Help", "帮助文本已复制到剪贴板。")

        btn_copy = ttk.Button(bar, text="复制帮助文本", command=copy_help)
        btn_copy.pack(side="right")
        self.add_tooltip(btn_copy, "复制完整帮助内容，方便发给同事或存档。")

    # =========================================================================
    # Logic: K-Calibration (ROBUST + Error)
    # =========================================================================
    def run_calibration(self):
        try:
            files = {k: v.get() for k, v in self.t1_files.items()}
            if not all(files.values()): raise ValueError("文件不完整：请先选择标准样、背景、暗场和 poni。")
            p = {k: v.get() for k, v in self.t1_params.items()}
            if p["std_thk"] <= 0: raise ValueError("标准样厚度必须 > 0 mm。")
            monitor_mode = self.get_monitor_mode()
            apply_solid_angle = bool(self.global_vars["apply_solid_angle"].get())

            self.report("开始标定（稳健模式）...")
            self.report(f"I0 归一化模式: {monitor_mode} (norm={self.monitor_norm_formula(monitor_mode)})")
            self.report(f"SolidAngle 修正: {'ON' if apply_solid_angle else 'OFF'}")
            
            ai = pyFAI.load(files["poni"])
            d_std = fabio.open(files["std"]).data.astype(np.float64)
            d_bg = fabio.open(files["bg"]).data.astype(np.float64)
            d_dark = fabio.open(files["dark"]).data.astype(np.float64)
            self._assert_same_shape(d_std, d_bg, "std", "bg")
            self._assert_same_shape(d_std, d_dark, "std", "dark")

            # --- 2D Subtraction (Physics Correct) ---
            norm_std = self.compute_norm_factor(
                p["std_exp"], p["std_i0"], p["std_t"], monitor_mode
            )
            norm_bg = self.compute_norm_factor(
                p["bg_exp"], p["bg_i0"], p["bg_t"], monitor_mode
            )
            
            if norm_std <= 0 or norm_bg <= 0: raise ValueError("归一化因子 <= 0，请检查 Time/I0/T。")
            norm_ratio = norm_bg / max(norm_std, 1e-12)
            if norm_ratio < 0.01 or norm_ratio > 100.0:
                self.report(
                    f"[警告] 标定中 BG_Norm 与 Std_Norm 量级差异过大 "
                    f"(BG/Std={norm_ratio:.3g})，请复核 BG 的 Time/I0/T 与 I0 语义。"
                )
            
            # Net Signal 2D (Intensity/sec/unit_flux)
            img_net = (d_std - d_dark)/norm_std - (d_bg - d_dark)/norm_bg
            
            # Integrate (Enable Error Propagation via Azimuthal Variance)
            # error_model="azimuthal" computes the sigma (std dev) of pixels in bin
            res = ai.integrate1d(
                img_net,
                1000,
                unit="q_A^-1",
                error_model="azimuthal",
                correctSolidAngle=apply_solid_angle,
            )

            q = np.asarray(res.radial, dtype=np.float64)
            i_1d = np.asarray(res.intensity, dtype=np.float64)
            if q.size < 3:
                raise ValueError("积分结果点数过少，无法完成标定。")

            thk_cm = p["std_thk"] / 10.0
            i_net_vol = i_1d / thk_cm

            # Extract Error (Azimuthal StdDev scaled by thickness)
            if getattr(res, "sigma", None) is None:
                sigma_net_vol = np.full_like(i_net_vol, np.nan)
            else:
                sigma_net_vol = np.asarray(res.sigma, dtype=np.float64) / thk_cm
            
            q_nist, i_nist = NIST_SRM3600_DATA[:,0], NIST_SRM3600_DATA[:,1]
            mask = (q_nist >= 0.01) & (q_nist <= 0.2)
            q_ref_all = q_nist[mask]
            i_ref_all = i_nist[mask]
            q_min = max(np.nanmin(q), np.nanmin(q_ref_all))
            q_max = min(np.nanmax(q), np.nanmax(q_ref_all))
            q_mask = (q_ref_all >= q_min) & (q_ref_all <= q_max)
            q_ref = q_ref_all[q_mask]
            i_ref = i_ref_all[q_mask]
            if q_ref.size < 3:
                raise ValueError("与 NIST 参考曲线的 q 重叠区间不足，无法可靠标定。")

            if estimate_k_factor_robust is not None:
                k_res = estimate_k_factor_robust(
                    q_meas=q,
                    i_meas_per_cm=i_net_vol,
                    q_ref=q_ref,
                    i_ref=i_ref,
                    q_window=(0.01, 0.2),
                    positive_floor=1e-9,
                    min_points=3,
                )
                k_val = float(k_res.k_factor)
                k_std = float(k_res.k_std)
                q_min = float(k_res.q_min_overlap)
                q_max = float(k_res.q_max_overlap)
                ratios_used = np.asarray(k_res.ratios_used, dtype=np.float64)
                points_total = int(k_res.points_total)
            else:
                # Interpolate
                i_meas_interp = np.interp(q_ref, q, i_net_vol)

                # --- 正值+有限值筛选 ---
                valid_idx = np.isfinite(i_meas_interp) & (i_meas_interp > 1e-9)
                if np.sum(valid_idx) < 3:
                    raise ValueError("扣背景后信号过弱或为负，无法标定。")

                ratios = i_ref[valid_idx] / i_meas_interp[valid_idx]
                ratios = ratios[np.isfinite(ratios) & (ratios > 0)]
                if ratios.size < 3:
                    raise ValueError("有效比值点数不足，无法稳健估计 K。")

                # 基于 MAD 的稳健离群点过滤
                r_med = np.nanmedian(ratios)
                r_mad = np.nanmedian(np.abs(ratios - r_med))
                ratios_used = ratios
                if np.isfinite(r_mad) and r_mad > 0:
                    robust_sigma = 1.4826 * r_mad
                    inlier = np.abs(ratios - r_med) <= 3.0 * robust_sigma
                    if np.sum(inlier) >= 3:
                        ratios_used = ratios[inlier]

                k_val = np.nanmedian(ratios_used)
                k_std = np.nanstd(ratios_used)
                points_total = len(q_ref)

            if k_val <= 0: raise ValueError(f"计算得到的 K <= 0 ({k_val})，请检查本底缩放和参数。")

            self.global_vars["k_factor"].set(k_val)
            self.global_vars["k_solid_angle"].set("on" if apply_solid_angle else "off")
            
            # Report
            self.report("-" * 30)
            self.report("标定成功（稳健估计）")
            self.report(f"K-Factor: {k_val:.4f}")
            self.report(f"Q overlap : {q_min:.4f} to {q_max:.4f} A^-1")
            self.report(f"Points Used: {len(ratios_used)}/{points_total}")
            rel_std = (k_std / k_val * 100) if k_val != 0 else np.nan
            self.report(f"Std Dev : {k_std:.4f} ({rel_std:.1f}%)")
            self.report("-" * 30)
            
            # Plot
            self.ax1.clear()
            self.ax1.loglog(q, i_net_vol, 'k--', alpha=0.4, label="Measured Net")
            self.ax1.loglog(q, i_net_vol * k_val, 'b-', label="Corrected")
            self.ax1.loglog(q_ref, i_ref, 'ro', mfc='none', label="NIST SRM3600")
            self.ax1.set_xlabel("q ($A^{-1}$)")
            self.ax1.set_ylabel("Absolute Intensity ($cm^{-1}$)")
            self.ax1.set_title(f"K={k_val:.2f}")
            self.ax1.legend()
            self.canvas1.draw()
            
            # Save Check File with Error
            save_path = Path(files["std"]).parent / "calibration_check.csv"
            # We save the full profile with error bars
            df = pd.DataFrame({
                "Q": q,
                "I_Abs": i_net_vol * k_val,
                "Error": sigma_net_vol * k_val
            })
            df.to_csv(save_path, index=False)
            self.report(f"Saved profile: {save_path.name}")

            self.append_k_history(
                files=files,
                params=p,
                monitor_mode=monitor_mode,
                apply_solid_angle=apply_solid_angle,
                k_val=k_val,
                k_std=k_std,
                points_used=len(ratios_used),
                q_min=q_min,
                q_max=q_max,
            )
            self.report("K history updated.")
            
        except Exception as e:
            messagebox.showerror("标定错误", str(e))
            self.report(f"[ERROR] {str(e)}")

    def append_k_history(self, files, params, monitor_mode, apply_solid_angle, k_val, k_std, points_used, q_min, q_max):
        hist_path = Path(__file__).resolve().parent / "k_factor_history.csv"
        std_norm = self.compute_norm_factor(
            params.get("std_exp", np.nan),
            params.get("std_i0", np.nan),
            params.get("std_t", np.nan),
            monitor_mode,
        )
        bg_norm = self.compute_norm_factor(
            params.get("bg_exp", np.nan),
            params.get("bg_i0", np.nan),
            params.get("bg_t", np.nan),
            monitor_mode,
        )
        row = {
            "Timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "Norm_Mode": monitor_mode,
            "Norm_Formula": self.monitor_norm_formula(monitor_mode),
            "SolidAngle_On": bool(apply_solid_angle),
            "K_Factor": float(k_val),
            "K_Std": float(k_std),
            "RelStd_pct": float((k_std / k_val * 100) if k_val else np.nan),
            "PointsUsed": int(points_used),
            "Q_Min": float(q_min),
            "Q_Max": float(q_max),
            "Std_File": files.get("std", ""),
            "BG_File": files.get("bg", ""),
            "Dark_File": files.get("dark", ""),
            "Poni_File": files.get("poni", ""),
            "Std_Thk_mm": float(params.get("std_thk", np.nan)),
            "Std_Norm": float(std_norm) if np.isfinite(std_norm) else np.nan,
            "BG_Norm": float(bg_norm) if np.isfinite(bg_norm) else np.nan,
        }
        df_row = pd.DataFrame([row])
        if hist_path.exists():
            try:
                old = pd.read_csv(hist_path)
                out = pd.concat([old, df_row], ignore_index=True)
            except Exception:
                out = df_row
        else:
            out = df_row
        out.to_csv(hist_path, index=False, encoding="utf-8-sig")

    def open_k_history(self):
        hist_path = Path(__file__).resolve().parent / "k_factor_history.csv"
        if not hist_path.exists():
            messagebox.showinfo("K 历史", "尚无 K 历史记录，请先运行一次标定。")
            return

        try:
            df = pd.read_csv(hist_path)
            if df.empty:
                messagebox.showinfo("K 历史", "历史文件为空。")
                return
        except Exception as e:
            messagebox.showerror("K 历史", f"读取历史失败: {e}")
            return

        top = tk.Toplevel(self.root)
        top.title("K 因子历史趋势")
        top.geometry("980x640")

        upper = ttk.Frame(top)
        upper.pack(fill="both", expand=True)
        lower = ttk.Frame(top)
        lower.pack(fill="both", expand=True)

        fig = Figure(figsize=(7.2, 3.4), dpi=100)
        ax = fig.add_subplot(111)
        x = np.arange(len(df))
        y = pd.to_numeric(df["K_Factor"], errors="coerce").to_numpy(dtype=np.float64)
        e = pd.to_numeric(df.get("K_Std", np.nan), errors="coerce").to_numpy(dtype=np.float64)

        if np.any(np.isfinite(e)):
            ax.errorbar(x, y, yerr=e, fmt="o-", capsize=3, label="K ± Std")
        else:
            ax.plot(x, y, "o-", label="K")
        ax.set_xlabel("Run Index")
        ax.set_ylabel("K Factor")
        ax.set_title("K Drift Monitor")
        ax.grid(alpha=0.3)
        ax.legend()

        canvas = FigureCanvasTkAgg(fig, master=upper)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()

        txt = tk.Text(lower, font=("Consolas", 9))
        txt.pack(fill="both", expand=True)
        show_cols = [c for c in ["Timestamp", "Norm_Mode", "SolidAngle_On", "K_Factor", "K_Std", "RelStd_pct", "PointsUsed", "Q_Min", "Q_Max"] if c in df.columns]
        txt.insert(tk.END, df[show_cols].to_string(index=False))

    def report(self, msg):
        if hasattr(self, "txt_report"):
            self.txt_report.insert(tk.END, msg + "\n")
            self.txt_report.see(tk.END)

    def log(self, msg):
        print(msg)
        self.report(msg)

    def get_selected_modes(self):
        modes = []
        if hasattr(self, "t2_mode_full") and self.t2_mode_full.get():
            modes.append("1d_full")
        if hasattr(self, "t2_mode_sector") and self.t2_mode_sector.get():
            modes.append("1d_sector")
        if hasattr(self, "t2_mode_chi") and self.t2_mode_chi.get():
            modes.append("radial_chi")
        return modes

    def add_bg_library_files(self):
        fs = filedialog.askopenfilenames(filetypes=[("Image", "*.tif *.tiff *.edf *.cbf")])
        for f in fs:
            if f not in self.t2_bg_candidates:
                self.t2_bg_candidates.append(f)
        self.t2_bg_lib_info.set(f"BG库: {len(self.t2_bg_candidates)}")

    def add_dark_library_files(self):
        fs = filedialog.askopenfilenames(filetypes=[("Image", "*.tif *.tiff *.edf *.cbf")])
        for f in fs:
            if f not in self.t2_dark_candidates:
                self.t2_dark_candidates.append(f)
        self.t2_dark_lib_info.set(f"Dark库: {len(self.t2_dark_candidates)}")

    def clear_reference_libraries(self):
        self.t2_bg_candidates = []
        self.t2_dark_candidates = []
        self.t2_bg_lib_info.set("BG库: 0")
        self.t2_dark_lib_info.set("Dark库: 0")

    def process_sample_task(self, idx, fpath, out_stem, context):
        logs = []
        mode_stats = {m: {"ok": 0, "fail": 0, "skip": 0} for m in context["selected_modes"]}

        def log_line(msg):
            logs.append(msg)

        def load_data(path):
            if context["parallel"]:
                return fabio.open(path).data.astype(np.float64)
            with context["cache_lock"]:
                if path in context["image_cache"]:
                    return context["image_cache"][path]
            d = fabio.open(path).data.astype(np.float64)
            with context["cache_lock"]:
                context["image_cache"][path] = d
            return d

        fname = Path(fpath).name
        exp = np.nan
        mon = np.nan
        trans = np.nan
        thk_cm = np.nan
        norm_s = np.nan
        bg_norm_used = np.nan
        bg_path_used = ""
        dark_path_used = ""
        bg_score = np.nan
        dark_score = np.nan
        outputs = []
        mode_errors = []
        status = "失败"
        reason = ""

        try:
            if context["resume"] and (not context["overwrite"]):
                expected_targets = self.build_sample_output_targets(context, out_stem)
                if expected_targets and all(p.exists() for _, p in expected_targets):
                    for mode_tag, p in expected_targets:
                        mode_key = "1d_sector" if mode_tag.startswith("1d_sector") else mode_tag
                        mode_stats[mode_key]["skip"] += 1
                        outputs.append(f"{mode_tag}:{p.name}(existing)")
                    status = "已跳过"
                    reason = "所有模式输出已存在"
                    log_line(f"[跳过] {fname}: 所有输出已存在")
                    row = {
                        "Index": idx,
                        "File": fname,
                        "Status": status,
                        "Reason": reason,
                        "Norm_Mode": context["monitor_mode"],
                        "Exposure_s": exp,
                        "Monitor": mon,
                        "Trans": trans,
                        "Thk_cm": thk_cm,
                        "Norm_s": norm_s,
                        "BG_Norm": bg_norm_used,
                        "BG_Used": bg_path_used,
                        "Dark_Used": dark_path_used,
                        "BG_Score": bg_score,
                        "Dark_Score": dark_score,
                        "ModesSelected": ",".join(context["selected_modes"]),
                        "Outputs": " | ".join(outputs),
                    }
                    return {"row": row, "logs": logs, "mode_stats": mode_stats}

            ai = context["ai_shared"] if not context["parallel"] else pyFAI.load(context["poni_path"])
            sample = fabio.open(fpath)
            d_s = sample.data.astype(np.float64)
            sample_header = getattr(sample, "header", {})

            exp, mon, trans = self.parse_header(fpath, header_dict=sample_header)
            monitor_mode = context["monitor_mode"]
            missing = []
            if mon is None:
                missing.append("mon")
            if trans is None:
                missing.append("trans")
            if monitor_mode == "rate" and exp is None:
                missing.append("exp")
            if missing:
                raise ValueError(f"文件头缺少关键字段: {', '.join(missing)}")

            exp = float(exp) if exp is not None else np.nan
            mon = float(mon)
            trans = float(trans)
            if not (np.isfinite(mon) and np.isfinite(trans) and (np.isfinite(exp) or monitor_mode == "integrated")):
                raise ValueError("文件头参数存在非法值（非有限数）")
            if monitor_mode == "rate" and exp <= 0:
                raise ValueError(f"曝光时间非法: exp={exp}")
            if mon <= 0:
                raise ValueError(f"I0 非法: mon={mon}")
            if not (0 < trans <= 1):
                raise ValueError(f"透过率超范围 (0,1]: {trans}")

            sample_meta = {
                "exp": exp if np.isfinite(exp) else None,
                "mon": mon,
                "trans": trans,
                "mtime": Path(fpath).stat().st_mtime if Path(fpath).exists() else None,
                "shape": tuple(d_s.shape),
            }

            if context["ref_mode"] == "fixed":
                d_bg = context["fixed_bg_data"]
                d_dark = context["fixed_dark_data"]
                bg_norm = context["fixed_bg_norm"]
                bg_path_used = context["fixed_bg_path"]
                dark_path_used = context["fixed_dark_path"]
            else:
                bg_ref, bg_score = self.select_best_reference(sample_meta, context["bg_library"], kind="bg")
                dark_ref, dark_score = self.select_best_reference(sample_meta, context["dark_library"], kind="dark")
                if bg_ref is None or dark_ref is None:
                    raise ValueError("自动匹配失败：BG/Dark 库为空或不兼容")

                bg_path_used = bg_ref["path"]
                dark_path_used = dark_ref["path"]
                d_bg = load_data(bg_path_used)
                d_dark = load_data(dark_path_used)
                bg_norm = self.compute_norm_factor(
                    bg_ref.get("exp"),
                    bg_ref.get("mon"),
                    bg_ref.get("trans"),
                    monitor_mode,
                )
                if not np.isfinite(bg_norm) or bg_norm <= 0:
                    bg_norm = context["fixed_bg_norm"]
                    log_line(f"[警告] {fname}: 匹配到的 BG 头参数不完整，回退全局 BG 归一化因子")

            self._assert_same_shape(d_s, d_bg, "sample", "bg")
            self._assert_same_shape(d_s, d_dark, "sample", "dark")
            bg_norm_used = bg_norm

            mask_arr = context["mask_arr"]
            flat_arr = context["flat_arr"]
            if mask_arr is not None and tuple(mask_arr.shape) != tuple(d_s.shape):
                raise ValueError(f"Mask 尺寸不匹配: {mask_arr.shape} vs {d_s.shape}")
            if flat_arr is not None and tuple(flat_arr.shape) != tuple(d_s.shape):
                raise ValueError(f"Flat 尺寸不匹配: {flat_arr.shape} vs {d_s.shape}")

            # --- Thickness Logic ---
            if context["calc_mode"] == "auto":
                if trans >= 0.999 or trans <= 0.001:
                    raise ValueError(f"透过率不适合自动厚度计算: {trans}")
                thk_cm = -math.log(trans) / context["mu"]
            else:
                thk_cm = context["fixed_thk_cm"]
            if not np.isfinite(thk_cm) or thk_cm <= 0:
                raise ValueError(f"厚度计算结果非法: {thk_cm}")

            norm_s = self.compute_norm_factor(exp if np.isfinite(exp) else None, mon, trans, monitor_mode)
            if not np.isfinite(norm_s) or norm_s <= 0:
                raise ValueError(f"样品归一化因子非法: {norm_s}")

            img_bg_net = (d_bg - d_dark) / bg_norm
            img_net = (d_s - d_dark) / norm_s - img_bg_net

            integ_kwargs_common = {
                "correctSolidAngle": context["apply_solid_angle"],
            }
            if context["error_model"] != "none":
                integ_kwargs_common["error_model"] = context["error_model"]
            if mask_arr is not None:
                integ_kwargs_common["mask"] = mask_arr
            if flat_arr is not None:
                integ_kwargs_common["flat"] = flat_arr
            if context["polarization"] is not None:
                integ_kwargs_common["polarization_factor"] = context["polarization"]

            mode_success = 0
            mode_skip = 0
            scale_factor = context["k_factor"] / thk_cm
            expected_total = len(self.build_sample_output_targets(context, out_stem))
            if expected_total <= 0:
                expected_total = len(context["selected_modes"])

            for mode in context["selected_modes"]:
                out_path = self.mode_output_path(context["save_dirs"], mode, out_stem)
                try:
                    if mode != "1d_sector" and context["resume"] and (not context["overwrite"]) and out_path.exists():
                        outputs.append(f"{mode}:{out_path.name}(existing)")
                        mode_stats[mode]["skip"] += 1
                        mode_skip += 1
                        continue

                    if mode == "1d_full":
                        res = ai.integrate1d(
                            img_net,
                            1000,
                            unit="q_A^-1",
                            **integ_kwargs_common,
                        )
                        i_abs = np.asarray(res.intensity, dtype=np.float64) * scale_factor
                        if getattr(res, "sigma", None) is None:
                            i_err = np.full_like(i_abs, np.nan)
                        else:
                            i_err = np.asarray(res.sigma, dtype=np.float64) * scale_factor
                        issue = self.profile_health_issue(i_abs)
                        if issue:
                            raise ValueError(issue)
                        self.save_profile_table(out_path, res.radial, i_abs, i_err, "Q_A^-1")
                        outputs.append(f"{mode}:{out_path.name}")
                        mode_stats[mode]["ok"] += 1
                        mode_success += 1

                    elif mode == "1d_sector":
                        sector_specs = context["sector_specs"]
                        save_each = bool(context.get("sector_save_each", True))
                        save_sum = bool(context.get("sector_save_combined", False))
                        sector_results = {}
                        multi_sector = len(sector_specs) > 1

                        sum_out_path = None
                        sum_need_write = False
                        if save_sum:
                            sum_out_path = context["sector_combined_dir"] / f"{out_stem}.dat"
                            if context["resume"] and (not context["overwrite"]) and sum_out_path.exists():
                                outputs.append(f"1d_sector_sum:{sum_out_path.name}(existing)")
                                mode_stats[mode]["skip"] += 1
                                mode_skip += 1
                            else:
                                sum_need_write = True

                        for spec in sector_specs:
                            spec_tag = f"1d_sector{spec['label']}"
                            each_out_path = None
                            need_each_write = False
                            if save_each:
                                each_dir = context["sector_save_dirs"].get(spec["key"])
                                if each_dir is None:
                                    mode_stats[mode]["fail"] += 1
                                    mode_errors.append(f"{spec_tag}: 缺少输出目录映射")
                                    continue
                                each_out_path = each_dir / f"{out_stem}.dat"
                                each_disp = (
                                    f"{each_out_path.parent.name}/{each_out_path.name}"
                                    if multi_sector else each_out_path.name
                                )
                                if context["resume"] and (not context["overwrite"]) and each_out_path.exists():
                                    outputs.append(f"{spec_tag}:{each_disp}(existing)")
                                    mode_stats[mode]["skip"] += 1
                                    mode_skip += 1
                                else:
                                    need_each_write = True

                            need_result = need_each_write or sum_need_write
                            if not need_result:
                                continue

                            try:
                                res, sec_min_n, sec_max_n, sec_wrap = self.integrate1d_sector(
                                    ai,
                                    img_net,
                                    1000,
                                    spec["sec_min"],
                                    spec["sec_max"],
                                    **integ_kwargs_common,
                                )
                                sector_results[spec["key"]] = res

                                if need_each_write and each_out_path is not None:
                                    i_abs = np.asarray(res.intensity, dtype=np.float64) * scale_factor
                                    if getattr(res, "sigma", None) is None:
                                        i_err = np.full_like(i_abs, np.nan)
                                    else:
                                        i_err = np.asarray(res.sigma, dtype=np.float64) * scale_factor
                                    issue = self.profile_health_issue(i_abs)
                                    if issue:
                                        raise ValueError(issue)
                                    self.save_profile_table(each_out_path, res.radial, i_abs, i_err, "Q_A^-1")
                                    outputs.append(f"{spec_tag}:{each_disp}")
                                    mode_stats[mode]["ok"] += 1
                                    mode_success += 1

                                if sec_wrap:
                                    log_line(
                                        f"[提示] {fname} {spec['label']}: 跨±180°，按 [{sec_min_n:.2f},180] 与 [-180,{sec_max_n:.2f}] 合并积分"
                                    )
                            except Exception as sector_err:
                                mode_stats[mode]["fail"] += 1
                                mode_errors.append(f"{spec_tag}: {sector_err}")

                        if sum_need_write and sum_out_path is not None:
                            missing = [s for s in sector_specs if s["key"] not in sector_results]
                            if missing:
                                miss_lbl = ",".join([m["label"] for m in missing[:3]])
                                if len(missing) > 3:
                                    miss_lbl += ",..."
                                mode_stats[mode]["fail"] += 1
                                mode_errors.append(f"1d_sector_sum: 扇区结果不完整，无法合并 ({miss_lbl})")
                            else:
                                try:
                                    merge = self.merge_integrate1d_results(
                                        [sector_results[s["key"]] for s in sector_specs]
                                    )
                                    i_abs = np.asarray(merge.intensity, dtype=np.float64) * scale_factor
                                    if getattr(merge, "sigma", None) is None:
                                        i_err = np.full_like(i_abs, np.nan)
                                    else:
                                        i_err = np.asarray(merge.sigma, dtype=np.float64) * scale_factor
                                    issue = self.profile_health_issue(i_abs)
                                    if issue:
                                        raise ValueError(issue)
                                    self.save_profile_table(sum_out_path, merge.radial, i_abs, i_err, "Q_A^-1")
                                    outputs.append(f"1d_sector_sum:{sum_out_path.name}")
                                    mode_stats[mode]["ok"] += 1
                                    mode_success += 1
                                except Exception as sum_err:
                                    mode_stats[mode]["fail"] += 1
                                    mode_errors.append(f"1d_sector_sum: {sum_err}")

                    elif mode == "radial_chi":
                        qmin = context["qmin"]
                        qmax = context["qmax"]
                        try:
                            res = ai.integrate_radial(
                                img_net,
                                360,
                                unit="chi_deg",
                                radial_unit="q_A^-1",
                                radial_range=(qmin, qmax),
                                **integ_kwargs_common,
                            )
                        except TypeError as radial_err:
                            if "radial_unit" not in str(radial_err):
                                raise
                            # 兼容旧版 pyFAI: 默认 radial_range 单位是 q_nm^-1
                            res = ai.integrate_radial(
                                img_net,
                                360,
                                unit="chi_deg",
                                radial_range=(qmin * 10.0, qmax * 10.0),
                                **integ_kwargs_common,
                            )
                            log_line(f"[警告] {fname}: pyFAI 不支持 radial_unit，q 区间已按 A^-1->nm^-1 转换")
                        i_abs = np.asarray(res.intensity, dtype=np.float64) * scale_factor
                        if getattr(res, "sigma", None) is None:
                            i_err = np.full_like(i_abs, np.nan)
                        else:
                            i_err = np.asarray(res.sigma, dtype=np.float64) * scale_factor
                        issue = self.profile_health_issue(i_abs)
                        if issue:
                            raise ValueError(issue)
                        self.save_profile_table(out_path, res.radial, i_abs, i_err, "Chi_deg")
                        outputs.append(f"{mode}:{out_path.name}")
                        mode_stats[mode]["ok"] += 1
                        mode_success += 1

                    else:
                        raise ValueError(f"不支持的积分模式: {mode}")

                except Exception as mode_err:
                    mode_stats[mode]["fail"] += 1
                    mode_errors.append(f"{mode}: {mode_err}")

            if mode_skip == expected_total and mode_success == 0 and not mode_errors:
                status = "已跳过"
                reason = "所有模式输出已存在"
                log_line(f"[跳过] {fname}: 所有输出已存在")
            elif mode_success > 0 and not mode_errors:
                status = "成功"
                log_line(f"[成功] {fname} -> {', '.join(outputs)}")
            elif mode_success > 0:
                status = "部分成功"
                reason = " | ".join(mode_errors)
                log_line(f"[部分成功] {fname} -> {', '.join(outputs)}")
                log_line(f"[模式失败] {fname}: {reason}")
            else:
                status = "失败"
                reason = " | ".join(mode_errors) if mode_errors else "无输出"
                log_line(f"[失败] {fname}: {reason}")

        except Exception as file_err:
            status = "失败"
            reason = str(file_err)
            log_line(f"[失败] {fname}: {reason}")

        row = {
            "Index": idx,
            "File": fname,
            "Status": status,
            "Reason": reason,
            "Norm_Mode": context["monitor_mode"],
            "Exposure_s": exp,
            "Monitor": mon,
            "Trans": trans,
            "Thk_cm": thk_cm,
            "Norm_s": norm_s,
            "BG_Norm": bg_norm_used,
            "BG_Used": bg_path_used,
            "Dark_Used": dark_path_used,
            "BG_Score": bg_score,
            "Dark_Score": dark_score,
            "ModesSelected": ",".join(context["selected_modes"]),
            "Outputs": " | ".join(outputs),
        }
        return {"row": row, "logs": logs, "mode_stats": mode_stats}

    # =========================================================================
    # Logic: Batch (2D Subtraction Kernel + Error)
    # =========================================================================
    def run_batch(self):
        try:
            if not self.t2_files: raise ValueError("队列为空：请先添加样品文件。")
            k = float(self.global_vars["k_factor"].get())
            bg_p = self.global_vars["bg_path"].get()
            dk_p = self.global_vars["dark_path"].get()
            poni = self.global_vars["poni_path"].get()
            
            if k <= 0: raise ValueError("K 因子无效（必须 > 0）。")
            if not all([bg_p, dk_p, poni]): raise ValueError("缺少背景/暗场/poni 文件。")
            monitor_mode = self.get_monitor_mode()
            self.log(f"[配置] I0 归一化模式: {monitor_mode} (norm={self.monitor_norm_formula(monitor_mode)})")
            self.log(f"[配置] SolidAngle 修正: {'ON' if bool(self.t2_apply_solid_angle.get()) else 'OFF'}")

            files = list(dict.fromkeys(self.t2_files))
            if len(files) < len(self.t2_files):
                self.log(f"[提示] 队列去重：移除重复文件 {len(self.t2_files) - len(files)} 个")
                self.t2_files = files
                self.lb_batch.delete(0, tk.END)
                for f in self.t2_files:
                    self.lb_batch.insert(tk.END, Path(f).name)
                self.refresh_queue_status()

            selected_modes = self.get_selected_modes()
            if not selected_modes:
                raise ValueError("未选择积分模式：请至少勾选一种（全环/扇区/织构）。")

            apply_solid_angle = bool(self.t2_apply_solid_angle.get())
            k_solid_state = str(self.global_vars["k_solid_angle"].get()).strip().lower()
            if k_solid_state in ("on", "off"):
                k_solid_bool = (k_solid_state == "on")
                if apply_solid_angle != k_solid_bool:
                    raise ValueError(
                        "SolidAngle 设置与 K 因子标定状态不一致："
                        f"K 使用 {'ON' if k_solid_bool else 'OFF'}，当前批处理为 {'ON' if apply_solid_angle else 'OFF'}。"
                        "请切换为一致设置，或重新运行 Tab1 标定。"
                    )
            else:
                self.log("[警告] 当前 K 因子缺少 SolidAngle 状态信息，无法自动校验一致性。建议重新标定 K。")

            ai = pyFAI.load(poni)
            if "radial_chi" in selected_modes and not hasattr(ai, "integrate_radial"):
                raise RuntimeError("当前 pyFAI 不支持 integrate_radial，请取消织构模式或升级 pyFAI。")
            sector_specs = []
            sector_save_each = bool(self.t2_sector_save_each.get())
            sector_save_combined = bool(self.t2_sector_save_combined.get())
            if "1d_sector" in selected_modes:
                sector_specs = self.get_t2_sector_specs()
                if not sector_save_each and not sector_save_combined:
                    raise ValueError("已启用扇区模式，但未选择任何扇区输出（请勾选“分扇区分别保存”或“扇区合并保存”）。")
                sec_brief = "; ".join([f"{s['index']}:{s['label']}" for s in sector_specs[:6]])
                if len(sector_specs) > 6:
                    sec_brief += "; ..."
                self.log(f"[配置] 扇区列表({len(sector_specs)}): {sec_brief}")
            if "radial_chi" in selected_modes and self.t2_rad_qmin.get() >= self.t2_rad_qmax.get():
                raise ValueError("织构 q 范围无效：qmin 必须 < qmax。")

            fixed_dark_data = fabio.open(dk_p).data.astype(np.float64)
            fixed_bg_data = fabio.open(bg_p).data.astype(np.float64)
            self._assert_same_shape(fixed_bg_data, fixed_dark_data, "bg", "dark")
            fixed_bg_norm = self.compute_norm_factor(
                self.global_vars["bg_exp"].get(),
                self.global_vars["bg_i0"].get(),
                self.global_vars["bg_t"].get(),
                monitor_mode,
            )
            if not np.isfinite(fixed_bg_norm) or fixed_bg_norm <= 0:
                raise ValueError("背景归一化因子 <= 0，请检查 BG 的 Time/I0/T。")

            ref_mode = self.t2_ref_mode.get()
            if ref_mode not in ("fixed", "auto"):
                raise ValueError(f"未知参考模式: {ref_mode}")

            # 防止 BG 归一化因子量级异常导致过扣背景（例如 T 被误判成百分数）
            probe_norms = []
            for fp in files[: min(20, len(files))]:
                try:
                    e, m, t = self.parse_header(fp)
                    n = self.compute_norm_factor(e, m, t, monitor_mode)
                    if np.isfinite(n) and n > 0:
                        probe_norms.append(float(n))
                except Exception:
                    continue
            if probe_norms:
                med_sample_norm = float(np.nanmedian(np.asarray(probe_norms, dtype=np.float64)))
                if np.isfinite(med_sample_norm) and med_sample_norm > 0:
                    bg_ratio = fixed_bg_norm / med_sample_norm
                    if bg_ratio < 0.01 or bg_ratio > 100.0:
                        msg = (
                            "BG_Norm 与样品 Norm_s 量级差异过大 "
                            f"(BG/样品中位={bg_ratio:.3g}, BG_Norm={fixed_bg_norm:.6g}, "
                            f"SampleMed={med_sample_norm:.6g})，请检查 BG 的 Time/I0/T、I0 语义或头字段映射。"
                        )
                        if ref_mode == "fixed":
                            raise ValueError(msg)
                        self.log(f"[警告] {msg}")

            bg_library = self.build_reference_library(self.t2_bg_candidates)
            dark_library = self.build_reference_library(self.t2_dark_candidates)
            if ref_mode == "auto":
                if not bg_library:
                    raise ValueError("自动匹配模式下 BG 库为空。")
                if not dark_library:
                    raise ValueError("自动匹配模式下 Dark 库为空。")

            if self.t2_strict_instrument.get():
                tol_pct = self.t2_instr_tol_pct.get()
                issues = self.check_instrument_consistency(files, poni_path=poni, tol_pct=tol_pct)
                if issues:
                    preview = "\n".join(issues[:10])
                    tail = "\n..." if len(issues) > 10 else ""
                    raise ValueError(f"仪器一致性检查失败（前10项）:\n{preview}{tail}")

            mask_arr = self.load_optional_array(self.t2_mask_path.get().strip(), "Mask")
            if mask_arr is not None:
                mask_arr = np.asarray(mask_arr) != 0
            flat_arr = self.load_optional_array(self.t2_flat_path.get().strip(), "Flat")
            if flat_arr is not None:
                flat_arr = np.asarray(flat_arr, dtype=np.float64)

            pol = self.t2_polarization.get()
            if not np.isfinite(pol) or pol < -1.0 or pol > 1.0:
                raise ValueError("Polarization 因子必须在 [-1, 1]。")
            error_model = self.t2_error_model.get().strip().lower()
            if error_model not in ("azimuthal", "poisson", "none"):
                raise ValueError("误差模型仅支持 azimuthal / poisson / none。")

            custom_out_root = self.t2_output_root.get().strip() if hasattr(self, "t2_output_root") else ""
            if custom_out_root:
                out_root = Path(custom_out_root).expanduser()
                out_root.mkdir(parents=True, exist_ok=True)
                self.log(f"[配置] 输出根目录(自定义): {out_root}")
            else:
                out_root = Path(files[0]).parent
                self.log(f"[配置] 输出根目录(默认样品目录): {out_root}")
            save_dirs = {}
            sector_save_dirs = {}
            sector_combined_dir = None
            for mode in selected_modes:
                if mode == "1d_sector":
                    base = out_root / "processed_robust_1d_sector"
                    base.mkdir(exist_ok=True)
                    save_dirs[mode] = base
                    if sector_save_each:
                        multi = len(sector_specs) > 1
                        for spec in sector_specs:
                            d = base / spec["key"] if multi else base
                            d.mkdir(exist_ok=True)
                            sector_save_dirs[spec["key"]] = d
                    if sector_save_combined:
                        sector_combined_dir = out_root / "processed_robust_1d_sector_combined"
                        sector_combined_dir.mkdir(exist_ok=True)
                else:
                    d = out_root / f"processed_robust_{mode}"
                    d.mkdir(exist_ok=True)
                    save_dirs[mode] = d
            report_dir = out_root / "processed_robust_reports"
            report_dir.mkdir(exist_ok=True)
            stem_map = self.build_output_stem_map(files)

            self.prog_bar["maximum"] = len(files)
            self.prog_bar["value"] = 0
            mu = self.t2_mu.get()
            if self.t2_calc_mode.get() == "auto" and mu <= 0:
                raise ValueError("自动厚度模式要求 mu > 0。")
            if self.t2_calc_mode.get() == "fixed" and self.t2_fixed_thk.get() <= 0:
                raise ValueError("固定厚度必须 > 0 mm。")
            fixed_thk_cm = self.t2_fixed_thk.get() / 10.0

            try:
                workers = max(1, int(self.t2_workers.get()))
            except Exception:
                raise ValueError("并行线程数必须为正整数。")
            overwrite = bool(self.t2_overwrite.get())
            resume = bool(self.t2_resume_enabled.get())

            context = {
                "selected_modes": selected_modes,
                "save_dirs": save_dirs,
                "poni_path": poni,
                "ai_shared": ai,
                "parallel": workers > 1,
                "cache_lock": threading.Lock(),
                "image_cache": {},
                "k_factor": k,
                "monitor_mode": monitor_mode,
                "calc_mode": self.t2_calc_mode.get(),
                "mu": mu,
                "fixed_thk_cm": fixed_thk_cm,
                "fixed_bg_data": fixed_bg_data,
                "fixed_dark_data": fixed_dark_data,
                "fixed_bg_norm": fixed_bg_norm,
                "fixed_bg_path": bg_p,
                "fixed_dark_path": dk_p,
                "ref_mode": ref_mode,
                "bg_library": bg_library,
                "dark_library": dark_library,
                "mask_arr": mask_arr,
                "flat_arr": flat_arr,
                "error_model": error_model,
                "apply_solid_angle": bool(self.t2_apply_solid_angle.get()),
                "polarization": float(pol),
                "sector_specs": sector_specs,
                "sector_save_each": sector_save_each,
                "sector_save_combined": sector_save_combined,
                "sector_save_dirs": sector_save_dirs,
                "sector_combined_dir": sector_combined_dir,
                "qmin": float(self.t2_rad_qmin.get()),
                "qmax": float(self.t2_rad_qmax.get()),
                "overwrite": overwrite,
                "resume": resume,
            }

            rows = []
            sample_success = 0
            sample_partial = 0
            sample_fail = 0
            sample_skip = 0
            mode_ok_count = {m: 0 for m in selected_modes}
            mode_fail_count = {m: 0 for m in selected_modes}
            mode_skip_count = {m: 0 for m in selected_modes}

            tasks = [(idx, fpath, stem_map[fpath]) for idx, fpath in enumerate(files)]
            processed = 0

            if workers == 1:
                for idx, fpath, out_stem in tasks:
                    result = self.process_sample_task(idx, fpath, out_stem, context)
                    rows.append(result["row"])
                    for line in result["logs"]:
                        self.log(line)

                    for m in selected_modes:
                        mode_ok_count[m] += result["mode_stats"][m]["ok"]
                        mode_fail_count[m] += result["mode_stats"][m]["fail"]
                        mode_skip_count[m] += result["mode_stats"][m]["skip"]

                    st = result["row"]["Status"]
                    if st == "成功":
                        sample_success += 1
                    elif st == "部分成功":
                        sample_partial += 1
                    elif st == "已跳过":
                        sample_skip += 1
                    else:
                        sample_fail += 1

                    processed += 1
                    self.prog_bar["value"] = processed
                    self.root.update_idletasks()
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = {
                        ex.submit(self.process_sample_task, idx, fpath, out_stem, context): (idx, fpath)
                        for idx, fpath, out_stem in tasks
                    }
                    for fut in concurrent.futures.as_completed(futures):
                        result = fut.result()
                        rows.append(result["row"])
                        for line in result["logs"]:
                            self.log(line)

                        for m in selected_modes:
                            mode_ok_count[m] += result["mode_stats"][m]["ok"]
                            mode_fail_count[m] += result["mode_stats"][m]["fail"]
                            mode_skip_count[m] += result["mode_stats"][m]["skip"]

                        st = result["row"]["Status"]
                        if st == "成功":
                            sample_success += 1
                        elif st == "部分成功":
                            sample_partial += 1
                        elif st == "已跳过":
                            sample_skip += 1
                        else:
                            sample_fail += 1

                        processed += 1
                        self.prog_bar["value"] = processed
                        self.root.update_idletasks()

            rows.sort(key=lambda x: x.get("Index", 0))
            for r in rows:
                r.pop("Index", None)

            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            report_path = report_dir / f"batch_report_{stamp}.csv"
            pd.DataFrame(rows).to_csv(report_path, index=False, encoding="utf-8-sig")

            tab3_meta_stamp = None
            tab3_meta_latest = None
            tab3_meta_rows = 0
            try:
                tab3_meta_stamp, tab3_meta_latest, tab3_meta_rows = self.export_tab3_metadata_from_report(
                    report_path,
                    stamp=stamp,
                )
            except Exception as e:
                self.log(f"[警告] 自动导出 Tab3 metadata 失败: {e}")

            meta_path = report_dir / f"run_meta_{stamp}.json"
            output_dirs_meta = {}
            for m in selected_modes:
                if m != "1d_sector":
                    output_dirs_meta[m] = str(save_dirs[m])
                    continue
                output_dirs_meta["1d_sector_base"] = str(save_dirs[m])
                if sector_save_each:
                    output_dirs_meta["1d_sector_each"] = {
                        spec["label"]: str(sector_save_dirs.get(spec["key"], save_dirs[m]))
                        for spec in sector_specs
                    }
                if sector_save_combined and sector_combined_dir is not None:
                    output_dirs_meta["1d_sector_sum"] = str(sector_combined_dir)

            meta = {
                "timestamp": stamp,
                "selected_modes": selected_modes,
                "files_total": len(files),
                "workers": workers,
                "k_factor": k,
                "monitor_mode": monitor_mode,
                "norm_formula": self.monitor_norm_formula(monitor_mode),
                "calc_mode": self.t2_calc_mode.get(),
                "mu_cm^-1": mu,
                "fixed_thickness_mm": self.t2_fixed_thk.get(),
                "reference_mode": ref_mode,
                "fixed_bg_path": bg_p,
                "fixed_dark_path": dk_p,
                "bg_library_count": len(bg_library),
                "dark_library_count": len(dark_library),
                "error_model": error_model,
                "correct_solid_angle": bool(self.t2_apply_solid_angle.get()),
                "k_solid_angle_state": str(self.global_vars["k_solid_angle"].get()),
                "polarization_factor": pol,
                "mask_path": self.t2_mask_path.get().strip(),
                "flat_path": self.t2_flat_path.get().strip(),
                "resume_enabled": resume,
                "overwrite": overwrite,
                "strict_instrument": bool(self.t2_strict_instrument.get()),
                "instrument_tol_pct": float(self.t2_instr_tol_pct.get()),
                "sector_specs": sector_specs,
                "sector_save_each": sector_save_each,
                "sector_save_combined": sector_save_combined,
                "output_root": str(out_root),
                "output_root_custom": bool(custom_out_root),
                "output_dirs": output_dirs_meta,
                "report_csv": str(report_path),
                "tab3_metadata_csv": str(tab3_meta_stamp) if tab3_meta_stamp else None,
                "tab3_metadata_latest": str(tab3_meta_latest) if tab3_meta_latest else None,
                "tab3_metadata_rows": int(tab3_meta_rows),
                "sample_summary": {
                    "success": sample_success,
                    "partial": sample_partial,
                    "skipped": sample_skip,
                    "failed": sample_fail,
                },
                "mode_summary": {
                    m: {"ok": mode_ok_count[m], "skip": mode_skip_count[m], "fail": mode_fail_count[m]}
                    for m in selected_modes
                },
                "versions": {
                    "numpy": np.__version__,
                    "pandas": pd.__version__,
                    "pyFAI": getattr(pyFAI, "__version__", "unknown"),
                    "fabio": getattr(fabio, "__version__", "unknown"),
                },
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            mode_summary = "\n".join(
                [f"{m}: 成功{mode_ok_count[m]} / 跳过{mode_skip_count[m]} / 失败{mode_fail_count[m]}" for m in selected_modes]
            )
            dir_lines = []
            for m in selected_modes:
                if m != "1d_sector":
                    dir_lines.append(f"{m} -> {save_dirs[m]}")
                    continue
                if sector_save_each:
                    if len(sector_specs) > 1:
                        dir_lines.append(f"1d_sector(each) -> {save_dirs[m]}/sector_*")
                    else:
                        dir_lines.append(f"1d_sector(each) -> {save_dirs[m]}")
                if sector_save_combined and sector_combined_dir is not None:
                    dir_lines.append(f"1d_sector_sum -> {sector_combined_dir}")
            dir_summary = "\n".join(dir_lines)

            messagebox.showinfo(
                "批处理完成",
                (
                    "稳健批处理完成。\n"
                    f"样品成功: {sample_success}\n"
                    f"样品部分成功: {sample_partial}\n"
                    f"样品已跳过: {sample_skip}\n"
                    f"样品失败: {sample_fail}\n"
                    f"模式统计:\n{mode_summary}\n"
                    f"输出目录:\n{dir_summary}\n"
                    f"报告: {report_path.name}\n"
                    f"Tab3 metadata: {tab3_meta_stamp.name if tab3_meta_stamp else '导出失败'}\n"
                    f"元数据: {meta_path.name}"
                ),
            )

        except Exception as e:
            messagebox.showerror("批处理错误", f"{e}\n{traceback.format_exc()}")

    # --- Helpers ---
    def refresh_queue_status(self):
        if hasattr(self, "t2_queue_info"):
            total = len(getattr(self, "t2_files", []))
            uniq = len(dict.fromkeys(getattr(self, "t2_files", [])))
            if uniq == total:
                self.t2_queue_info.set(f"队列文件: {uniq}")
            else:
                self.t2_queue_info.set(f"队列文件: {total}（去重后 {uniq}）")

        if hasattr(self, "t2_out_hint_var"):
            modes = self.get_selected_modes()
            if not modes:
                self.t2_out_hint_var.set("输出目录: 未选择积分模式")
            else:
                dirs = []
                for m in modes:
                    if m != "1d_sector":
                        dirs.append(f"processed_robust_{m}")
                        continue
                    dirs.append("processed_robust_1d_sector")
                    if hasattr(self, "t2_sector_save_combined") and self.t2_sector_save_combined.get():
                        dirs.append("processed_robust_1d_sector_combined")
                sec_note = ""
                if "1d_sector" in modes:
                    try:
                        n_sec = len(self.get_t2_sector_specs())
                        sec_note = f"（扇区数={n_sec}）"
                    except Exception:
                        sec_note = "（扇区配置待确认）"
                custom_root = self.t2_output_root.get().strip() if hasattr(self, "t2_output_root") else ""
                if custom_root:
                    self.t2_out_hint_var.set(
                        f"输出目录将写入 {custom_root}: {', '.join(dirs)}{sec_note}"
                    )
                else:
                    self.t2_out_hint_var.set(f"输出目录将自动创建: {', '.join(dirs)}{sec_note}")

    def dry_run(self):
        if not self.t2_files: return
        files = list(dict.fromkeys(self.t2_files))
        rows = []
        mu = self.t2_mu.get()
        monitor_mode = self.get_monitor_mode()
        mode = self.t2_calc_mode.get()
        selected_modes = self.get_selected_modes()
        warnings = []
        inst_issues = []
        sample_norms = []
        bg_norm = self.compute_norm_factor(
            self.global_vars["bg_exp"].get(),
            self.global_vars["bg_i0"].get(),
            self.global_vars["bg_t"].get(),
            monitor_mode,
        )

        if not selected_modes:
            warnings.append("未选择积分模式（至少勾选一种）。")
        sector_specs = []
        if "1d_sector" in selected_modes:
            try:
                sector_specs = self.get_t2_sector_specs()
                if not self.t2_sector_save_each.get() and not self.t2_sector_save_combined.get():
                    warnings.append("扇区模式未勾选任何输出（分别保存/合并保存）。")
            except Exception as e:
                warnings.append(f"扇区角度范围无效：{e}")
        if "radial_chi" in selected_modes and self.t2_rad_qmin.get() >= self.t2_rad_qmax.get():
            warnings.append("织构 q 范围无效：qmin 必须 < qmax。")
        if mode == "auto" and mu <= 0:
            warnings.append("自动厚度模式下 mu 必须 > 0。")
        if self.t2_calc_mode.get() == "fixed" and self.t2_fixed_thk.get() <= 0:
            warnings.append("固定厚度必须 > 0 mm。")
        if self.t2_ref_mode.get() == "auto":
            if not self.t2_bg_candidates:
                warnings.append("自动匹配模式下 BG 库为空。")
            if not self.t2_dark_candidates:
                warnings.append("自动匹配模式下 Dark 库为空。")
        if self.t2_strict_instrument.get():
            inst_issues = self.check_instrument_consistency(
                files,
                poni_path=self.global_vars["poni_path"].get(),
                tol_pct=self.t2_instr_tol_pct.get(),
            )
            if inst_issues:
                warnings.append(f"仪器一致性发现 {len(inst_issues)} 项问题（见下方详情）。")

        bg_library = self.build_reference_library(self.t2_bg_candidates) if self.t2_ref_mode.get() == "auto" else []
        dark_library = self.build_reference_library(self.t2_dark_candidates) if self.t2_ref_mode.get() == "auto" else []

        for fp in files:
            e, m, t = self.parse_header(fp)
            stat = "正常"
            d_mm = np.nan
            bg_match = "-"
            dark_match = "-"

            missing = []
            if m is None:
                missing.append("MON")
            if t is None:
                missing.append("T")
            if monitor_mode == "rate" and e is None:
                missing.append("EXP")

            if missing:
                stat = f"缺少文件头字段: {','.join(missing)}"
            else:
                if e is not None:
                    e = float(e)
                m = float(m)
                t = float(t)
                n = self.compute_norm_factor(e if e is not None else None, m, t, monitor_mode)
                if np.isfinite(n) and n > 0:
                    sample_norms.append(float(n))
                if monitor_mode == "rate" and e <= 0:
                    stat = "错误: EXP <= 0"
                elif m <= 0:
                    stat = "错误: MON <= 0"
                elif not (0 < t <= 1):
                    stat = "错误: T 超出 (0,1]"
                elif mode == "auto":
                    if mu <= 0:
                        stat = "错误: MU <= 0"
                    elif t >= 0.999 or t <= 0.001:
                        stat = "错误: T 不适合自动厚度"
                    else:
                        d_mm = (-math.log(t) / mu) * 10.0
                else:
                    d_mm = self.t2_fixed_thk.get()

            if self.t2_ref_mode.get() == "auto":
                try:
                    img = fabio.open(fp)
                    smeta = {
                        "exp": e if (e is not None and np.isfinite(e)) else None,
                        "mon": m if m is not None else None,
                        "trans": t if t is not None else None,
                        "mtime": Path(fp).stat().st_mtime if Path(fp).exists() else None,
                        "shape": tuple(img.data.shape),
                    }
                    bg_ref, _ = self.select_best_reference(smeta, bg_library, kind="bg")
                    dk_ref, _ = self.select_best_reference(smeta, dark_library, kind="dark")
                    bg_match = Path(bg_ref["path"]).name if bg_ref else "无匹配"
                    dark_match = Path(dk_ref["path"]).name if dk_ref else "无匹配"
                except Exception:
                    bg_match = "匹配失败"
                    dark_match = "匹配失败"

            rows.append({
                "File": Path(fp).name,
                "Exp_s": e if e is not None else np.nan,
                "Mon": m if m is not None else np.nan,
                "Trans": t if t is not None else np.nan,
                "CalcThk_mm": round(d_mm, 4) if np.isfinite(d_mm) else np.nan,
                "BG匹配": bg_match,
                "Dark匹配": dark_match,
                "Status": stat,
            })

        if np.isfinite(bg_norm) and bg_norm > 0 and sample_norms:
            med_sample_norm = float(np.nanmedian(np.asarray(sample_norms, dtype=np.float64)))
            if np.isfinite(med_sample_norm) and med_sample_norm > 0:
                ratio = bg_norm / med_sample_norm
                if ratio < 0.01 or ratio > 100.0:
                    warnings.append(
                        "BG_Norm 与样品 Norm_s 量级差异过大 "
                        f"(BG/样品中位={ratio:.3g}, BG_Norm={bg_norm:.6g}, SampleMed={med_sample_norm:.6g})。"
                    )
        
        top = tk.Toplevel(self.root)
        top.title("批处理预检查结果")
        txt = tk.Text(top, font=("Consolas",9)); txt.pack(fill="both", expand=True)
        txt.insert(tk.END, f"I0 归一化模式: {monitor_mode} (norm={self.monitor_norm_formula(monitor_mode)})\n")
        txt.insert(tk.END, f"积分模式: {','.join(selected_modes) if selected_modes else '无'}\n")
        if "1d_sector" in selected_modes:
            txt.insert(
                tk.END,
                f"扇区输出: each={'ON' if self.t2_sector_save_each.get() else 'OFF'}, "
                f"sum={'ON' if self.t2_sector_save_combined.get() else 'OFF'}\n",
            )
            if sector_specs:
                sec_short = "; ".join([f"{s['index']}:{s['label']}" for s in sector_specs[:8]])
                if len(sector_specs) > 8:
                    sec_short += "; ..."
                txt.insert(tk.END, f"扇区列表: {sec_short}\n")
        txt.insert(tk.END, f"参考模式: {self.t2_ref_mode.get()}\n")
        txt.insert(tk.END, f"误差模型: {self.t2_error_model.get()}\n")
        txt.insert(tk.END, f"并行线程: {self.t2_workers.get()}\n")
        txt.insert(tk.END, "-"*80 + "\n")
        if warnings:
            txt.insert(tk.END, "[预检查警告]\n")
            for w in warnings:
                txt.insert(tk.END, f"- {w}\n")
            if inst_issues:
                for issue in inst_issues[:20]:
                    txt.insert(tk.END, f"  * {issue}\n")
                if len(inst_issues) > 20:
                    txt.insert(tk.END, "  * ...\n")
        else:
            txt.insert(tk.END, "[预检查通过] 未发现明显配置问题。\n")
        txt.insert(tk.END, "-"*80 + "\n")
        txt.insert(tk.END, pd.DataFrame(rows).to_string(index=False))

    def get_t2_preview_sample_path(self):
        # 优先使用列表当前选中项；未选中时使用队列第一个；仍为空则弹文件选择。
        try:
            sel = self.lb_batch.curselection() if hasattr(self, "lb_batch") else ()
            if sel:
                idx = int(sel[0])
                if 0 <= idx < len(self.t2_files):
                    return self.t2_files[idx]
        except Exception:
            pass

        if getattr(self, "t2_files", None):
            fs = list(dict.fromkeys(self.t2_files))
            if fs:
                return fs[0]

        return filedialog.askopenfilename(
            filetypes=[("Image", "*.tif *.tiff *.edf *.cbf"), ("All Files", "*.*")]
        )

    def _compute_t2_chi_map_deg(self, ai, shape):
        # 与 pyFAI azimuth_range 定义一致：0°右、+90°下、-90°上、±180°左
        try:
            chi_rad = np.asarray(ai.center_array(shape, unit="chi_rad"), dtype=np.float64)
        except Exception:
            chi_rad = np.asarray(ai.chiArray(shape), dtype=np.float64)
        chi_deg = np.rad2deg(chi_rad)
        chi_deg = ((chi_deg + 180.0) % 360.0) - 180.0
        return chi_deg

    def _compute_t2_q_map_a_inv(self, ai, shape):
        # 优先显式 A^-1；旧版兼容退回 qArray(nm^-1) 再 /10。
        try:
            q_map = np.asarray(ai.center_array(shape, unit="q_A^-1"), dtype=np.float64)
            return q_map, "q_A^-1"
        except Exception:
            q_map = np.asarray(ai.qArray(shape), dtype=np.float64) / 10.0
            return q_map, "q_nm^-1/10"

    def _get_t2_preview_context(self):
        sample_path = self.get_t2_preview_sample_path()
        if not sample_path:
            return None

        poni_path = self.global_vars["poni_path"].get().strip()
        if not poni_path:
            raise ValueError("请先在 Tab1/Tab2 设置 poni 文件。")

        ai = pyFAI.load(poni_path)
        data = fabio.open(sample_path).data.astype(np.float64)
        if data.ndim != 2:
            raise ValueError(f"样品图像维度错误: {data.shape}")

        valid_mask = np.isfinite(data)
        mask_path = self.t2_mask_path.get().strip() if hasattr(self, "t2_mask_path") else ""
        if mask_path:
            mask_arr = np.asarray(self.load_optional_array(mask_path, "Mask")) != 0
            if mask_arr.shape != data.shape:
                raise ValueError(f"Mask 尺寸不匹配: mask{mask_arr.shape} vs image{data.shape}")
            valid_mask &= ~mask_arr

        finite = data[valid_mask]
        if finite.size == 0:
            raise ValueError("可用图像像素为空（可能被 mask 全部屏蔽）。")

        lo = float(np.nanpercentile(finite, 1.0))
        hi = float(np.nanpercentile(finite, 99.5))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo = float(np.nanmin(finite))
            hi = float(np.nanmax(finite))
            if hi <= lo:
                hi = lo + 1.0
        show_img = np.clip(data, lo, hi)
        show_img = np.where(np.isfinite(show_img), show_img, lo)

        try:
            cy = float(ai.poni1 / ai.pixel1)
            cx = float(ai.poni2 / ai.pixel2)
            if not (np.isfinite(cy) and np.isfinite(cx)):
                raise ValueError("center invalid")
        except Exception:
            cy = (data.shape[0] - 1) / 2.0
            cx = (data.shape[1] - 1) / 2.0

        return {
            "sample_path": sample_path,
            "ai": ai,
            "data": data,
            "valid_mask": valid_mask,
            "show_img": show_img,
            "cx": cx,
            "cy": cy,
        }

    def preview_iq_window_t2(self):
        try:
            ctx = self._get_t2_preview_context()
            if ctx is None:
                return

            use_sector = bool(self.t2_mode_sector.get())
            sector_specs = []
            chi_deg = None

            if use_sector:
                sector_specs = self.get_t2_sector_specs()
                chi_deg = self._compute_t2_chi_map_deg(ctx["ai"], ctx["data"].shape)
                iq_mask = np.zeros_like(ctx["valid_mask"], dtype=bool)
                for spec in sector_specs:
                    m, _, _, _ = self.build_sector_mask(chi_deg, spec["sec_min"], spec["sec_max"])
                    iq_mask |= m
                iq_mask = iq_mask & ctx["valid_mask"]
                sec_desc = "; ".join([f"S{s['index']}{s['label']}" for s in sector_specs[:6]])
                if len(sector_specs) > 6:
                    sec_desc += "; ..."
                mode_desc = f"扇区模式({len(sector_specs)}): {sec_desc}"
            else:
                iq_mask = np.asarray(ctx["valid_mask"], dtype=bool)
                mode_desc = "全环 (有效像素)"

            if not np.any(iq_mask):
                raise ValueError("I-Q 预览区域为空，请检查扇区范围或 mask。")

            top = tk.Toplevel(self.root)
            top.title(f"I-Q 2D预览 - {Path(ctx['sample_path']).name}")
            info = ttk.Label(
                top,
                text=(
                    f"样品: {Path(ctx['sample_path']).name} | 模式: {mode_desc} | 覆盖像素: {np.mean(iq_mask)*100:.2f}%\n"
                    "角度定义（pyFAI chi）：0°向右，+90°向下，-90°向上，±180°向左。"
                ),
                justify="left",
                style="Hint.TLabel",
            )
            info.pack(fill="x", padx=8, pady=(8, 4))

            fig = Figure(figsize=(7.2, 6.0), dpi=100)
            ax = fig.add_subplot(111)
            im = ax.imshow(ctx["show_img"], cmap="gray", origin="upper", interpolation="nearest")
            ov = np.ma.masked_where(~iq_mask, np.ones_like(ctx["show_img"]))
            ax.imshow(ov, cmap="autumn", origin="upper", interpolation="nearest", alpha=0.28, vmin=0.0, vmax=1.0)

            ax.plot(ctx["cx"], ctx["cy"], marker="+", color="cyan", ms=12, mew=2, label="Beam center")
            if use_sector:
                ray_len = float(max(ctx["data"].shape) * 0.75)
                palette = [
                    "#00d1ff", "#ff4d4d", "#3cb371", "#ff8c00", "#9370db",
                    "#ffd700", "#20b2aa", "#dc143c", "#1e90ff", "#8b4513",
                ]
                for i, spec in enumerate(sector_specs):
                    color = palette[i % len(palette)]
                    for j, ang_deg in enumerate([spec["sec_min"], spec["sec_max"]]):
                        ang = math.radians(float(ang_deg))
                        x2 = ctx["cx"] + math.cos(ang) * ray_len
                        y2 = ctx["cy"] + math.sin(ang) * ray_len
                        lbl = None
                        if j == 0 and i < 8:
                            lbl = f"S{spec['index']} {spec['label']}"
                        ax.plot(
                            [ctx["cx"], x2],
                            [ctx["cy"], y2],
                            color=color,
                            lw=1.5,
                            ls="-" if j == 0 else "--",
                            label=lbl,
                        )

            ax.set_title("Tab2 I-Q 积分区域预览")
            ax.set_xlabel("Pixel X")
            ax.set_ylabel("Pixel Y")
            ax.legend(loc="upper right", fontsize=8)

            cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            cb.set_label("Intensity (clipped)")

            canvas = FigureCanvasTkAgg(fig, master=top)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=6)
            canvas.draw()
            toolbar = NavigationToolbar2Tk(canvas, top)
            toolbar.update()

        except Exception as e:
            messagebox.showerror("I-Q 预览错误", f"{e}\n{traceback.format_exc()}")

    def preview_ichi_window_t2(self):
        try:
            ctx = self._get_t2_preview_context()
            if ctx is None:
                return

            qmin = float(self.t2_rad_qmin.get())
            qmax = float(self.t2_rad_qmax.get())
            if not (np.isfinite(qmin) and np.isfinite(qmax) and qmin < qmax):
                raise ValueError("I-chi 预览 q 范围无效：qmin 必须 < qmax。")

            q_map, q_src = self._compute_t2_q_map_a_inv(ctx["ai"], ctx["data"].shape)
            q_mask = np.isfinite(q_map) & (q_map >= qmin) & (q_map <= qmax) & ctx["valid_mask"]
            if not np.any(q_mask):
                raise ValueError("I-chi q 环带为空，请检查 q 范围、poni 或 mask。")

            top = tk.Toplevel(self.root)
            top.title(f"I-chi 2D预览 - {Path(ctx['sample_path']).name}")
            info = ttk.Label(
                top,
                text=(
                    f"样品: {Path(ctx['sample_path']).name} | q区间: [{qmin:.4g}, {qmax:.4g}] A^-1 | "
                    f"覆盖像素: {np.mean(q_mask)*100:.2f}%\n"
                    f"q 映射单位: {q_src}（用于对应 Tab2 radial_chi 的 q 选区）。"
                ),
                justify="left",
                style="Hint.TLabel",
            )
            info.pack(fill="x", padx=8, pady=(8, 4))

            fig = Figure(figsize=(7.2, 6.0), dpi=100)
            ax = fig.add_subplot(111)
            im = ax.imshow(ctx["show_img"], cmap="gray", origin="upper", interpolation="nearest")
            ov = np.ma.masked_where(~q_mask, np.ones_like(ctx["show_img"]))
            ax.imshow(ov, cmap="spring", origin="upper", interpolation="nearest", alpha=0.30, vmin=0.0, vmax=1.0)

            ax.plot(ctx["cx"], ctx["cy"], marker="+", color="cyan", ms=12, mew=2, label="Beam center")
            try:
                contours = ax.contour(
                    q_map,
                    levels=[qmin, qmax],
                    colors=["#00d1ff", "#ff4d4d"],
                    linewidths=1.2,
                )
                if contours is not None:
                    ax.clabel(contours, inline=True, fontsize=8, fmt=lambda v: f"{v:.3g} A^-1")
            except Exception:
                pass

            ax.set_title("Tab2 I-chi (q环带) 预览")
            ax.set_xlabel("Pixel X")
            ax.set_ylabel("Pixel Y")
            ax.legend(loc="upper right", fontsize=8)

            cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            cb.set_label("Intensity (clipped)")

            canvas = FigureCanvasTkAgg(fig, master=top)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=6)
            canvas.draw()
            toolbar = NavigationToolbar2Tk(canvas, top)
            toolbar.update()

        except Exception as e:
            messagebox.showerror("I-chi 预览错误", f"{e}\n{traceback.format_exc()}")

    def preview_sector_window_t2(self):
        # 兼容旧按钮/旧调用入口：转到 I-Q 预览
        self.preview_iq_window_t2()

    def open_mu_tool(self):
        top = tk.Toplevel(self.root); top.title("合金 μ 估算器 (30 keV)")
        entries = {}
        defaults = {"Ti":64, "Nb":24, "Zr":4, "Sn":8}
        
        ttk.Label(top, text="质量分数 (wt%)", font=("Arial", 9, "bold")).grid(row=0, columnspan=2, pady=5)
        
        for i, (k,v) in enumerate(defaults.items()):
            ttk.Label(top, text=k).grid(row=i+1, column=0, padx=5)
            e = ttk.Entry(top, width=5); e.insert(0, v); e.grid(row=i+1, column=1, padx=5)
            entries[k] = e
            
        ttk.Label(top, text="密度 rho (g/cm3):").grid(row=6, column=0)
        e_rho = ttk.Entry(top, width=5); e_rho.insert(0, "5.4"); e_rho.grid(row=6, column=1)
        
        def c():
            try:
                w_tot = sum([float(e.get()) for e in entries.values()])
                if abs(w_tot-100) > 1: messagebox.showwarning("警告", f"总 wt% = {w_tot}")
                mu_m = sum([float(e.get())/100 * XCOM_30KEV.get(k,0) for k,e in entries.items()])
                res = mu_m * float(e_rho.get())
                self.t2_mu.set(round(res, 2)); top.destroy()
            except Exception as e:
                messagebox.showerror("输入错误", f"μ 估算失败: {e}")
        ttk.Button(top, text="应用到批处理", command=c).grid(row=7, columnspan=2, pady=10)

    def add_file_row(self, p, l, v, pat, cmd=None):
        f = ttk.Frame(p); f.pack(fill="x", pady=1)
        lbl = ttk.Label(f, text=l, width=15, anchor="e")
        lbl.pack(side="left")
        ent = ttk.Entry(f, textvariable=v)
        ent.pack(side="left", fill="x", expand=True)
        def b():
            fp = filedialog.askopenfilename(filetypes=[("File", pat)])
            if fp: v.set(fp); cmd(fp) if cmd else None
        btn = ttk.Button(f, text="...", width=3, command=b)
        btn.pack(side="left")
        return {"frame": f, "label": lbl, "entry": ent, "button": btn}

    def add_dir_row(self, p, l, v):
        f = ttk.Frame(p); f.pack(fill="x", pady=1)
        lbl = ttk.Label(f, text=l, width=15, anchor="e")
        lbl.pack(side="left")
        ent = ttk.Entry(f, textvariable=v)
        ent.pack(side="left", fill="x", expand=True)
        def b():
            dp = filedialog.askdirectory()
            if dp:
                v.set(dp)
        btn = ttk.Button(f, text="...", width=3, command=b)
        btn.pack(side="left")
        return {"frame": f, "label": lbl, "entry": ent, "button": btn}

    def add_grid_entry(self, p, v, r, c):
        e = ttk.Entry(p, textvariable=v, width=8, justify="center")
        e.grid(row=r, column=c, padx=2, pady=2)
        return e

    def on_load_std_t1(self, fp):
        e, m, t = self.parse_header(fp)
        if e is not None: self.t1_params["std_exp"].set(e)
        if m is not None: self.t1_params["std_i0"].set(m)
        if t is not None: self.t1_params["std_t"].set(t)
    def on_load_bg_t1(self, fp):
        e, m, t = self.parse_header(fp)
        if e is not None: self.t1_params["bg_exp"].set(e)
        if m is not None: self.t1_params["bg_i0"].set(m)
        if t is not None: self.t1_params["bg_t"].set(t)

    def add_batch_files(self):
        fs = filedialog.askopenfilenames(filetypes=[("TIFF", "*.tif *.tiff")])
        for f in fs:
            if f not in self.t2_files:
                self.t2_files.append(f)
                self.lb_batch.insert(tk.END, Path(f).name)
        self.refresh_queue_status()
    def clear_batch_files(self):
        self.t2_files = []; self.lb_batch.delete(0, tk.END)
        self.refresh_queue_status()

    def apply_session(self, session_path: str):
        try:
            sess = load_session(session_path)
        except Exception as e:
            messagebox.showerror("Session Error", f"Failed to read session:\n{e}")
            return

        notes = []
        geom = session_geometry(sess)
        if geom:
            px_mm = geom.get("px_mm")
            wl_a = geom.get("wl_A")
            dist_mm = geom.get("dist_mm")
            self.session_geometry_fallback = {
                "wavelength_a": float(wl_a) if wl_a is not None else None,
                "distance_m": (float(dist_mm) / 1000.0) if dist_mm is not None else None,
                "pixel1_m": (float(px_mm) / 1000.0) if px_mm is not None else None,
                "pixel2_m": (float(px_mm) / 1000.0) if px_mm is not None else None,
                "energy_kev": (HC_KEV_A / float(wl_a)) if (wl_a is not None and float(wl_a) > 0) else None,
            }
            notes.append("Session geometry loaded (used as consistency fallback when headers are missing).")

        # Optional calibration paths from session payload (forward-compatible)
        cal = sess.get("calibration", {}) if isinstance(sess.get("calibration", {}), dict) else {}
        candidate_paths = {
            "poni": str(cal.get("poni_path", sess.get("poni_path", ""))).strip(),
            "bg": str(cal.get("bg_path", sess.get("bg_path", ""))).strip(),
            "dark": str(cal.get("dark_path", sess.get("dark_path", ""))).strip(),
            "std": str(cal.get("std_path", sess.get("std_path", ""))).strip(),
        }
        if candidate_paths["poni"] and Path(candidate_paths["poni"]).is_file():
            self.global_vars["poni_path"].set(candidate_paths["poni"])
            notes.append(f"PONI loaded from session: {Path(candidate_paths['poni']).name}")
        if candidate_paths["bg"] and Path(candidate_paths["bg"]).is_file():
            self.global_vars["bg_path"].set(candidate_paths["bg"])
            notes.append(f"Background loaded from session: {Path(candidate_paths['bg']).name}")
        if candidate_paths["dark"] and Path(candidate_paths["dark"]).is_file():
            self.global_vars["dark_path"].set(candidate_paths["dark"])
            notes.append(f"Dark loaded from session: {Path(candidate_paths['dark']).name}")
        if candidate_paths["std"] and Path(candidate_paths["std"]).is_file():
            self.t1_files["std"].set(candidate_paths["std"])
            self.on_load_std_t1(candidate_paths["std"])
            notes.append(f"Std image loaded from session std_path: {Path(candidate_paths['std']).name}")

        data_path = str(sess.get("data_path", "")).strip()
        if data_path:
            p = Path(data_path)
            if p.is_file() and p.suffix.lower() in (".tif", ".tiff"):
                self.t1_files["std"].set(str(p))
                self.on_load_std_t1(str(p))
                notes.append(f"Std image loaded from session: {p.name}")
            elif p.is_file():
                notes.append(f"Session data is not TIFF, skipped for Std: {p.name}")
            else:
                notes.append(f"Session data path not found: {data_path}")

        if not notes:
            notes.append("Session loaded.")
        messagebox.showinfo("Session Loaded", "\n".join(notes))


SAXSAbsWorkbenchApp = BL19B2_RobustApp


def main(argv=None):
    parser = argparse.ArgumentParser(description="SAXSAbs Workbench")
    parser.add_argument("--session", type=str, default="", help="Path to session json")
    args = parser.parse_args(argv)

    root = tk.Tk()
    app = SAXSAbsWorkbenchApp(root)
    if args.session:
        root.after(80, lambda: app.apply_session(args.session))
    root.mainloop()

if __name__ == "__main__":
    main()
