#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
channel_detect.py -- 频谱信道检测（3588 侧的核心算法）

输入：一帧功率谱（dBFS）
输出：检测到的信道列表（中心频率、带宽、峰值、信噪比）

算法链
------
1. 噪声底估计   中位数法（对占空比 <50% 的信号鲁棒）
2. CFAR 检测    单元平均 CFAR，带保护单元，适应非平稳噪声
3. 形态学清理   开运算（先去孤立毛刺，再填小空洞）
4. 信道聚类     相邻超门限 bin 聚成一个信道
5. 参数提取     中心频率 / 带宽 / 峰值 / 平均功率 / SNR
6. 跨帧跟踪     给信道分配稳定 ID，报告出现与消失

为什么用 CFAR 而不是固定门限
---------------------------
固定门限在噪声底漂移时会大量虚警。CFAR 用**局部**噪声估计，
让虚警率保持恒定——这正是"信道占用检测"需要的性质。

依赖：numpy（RK3588 上已装 2.2.1）；没有 numpy 时自动退回纯 Python。
"""

import math

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


# =====================================================================
class Channel(object):
    def __init__(self, lo_bin, hi_bin, freq_lo, freq_hi, peak_dbfs,
                 peak_bin, mean_dbfs, noise_dbfs, snr_db, bw_hz):
        self.lo_bin = lo_bin
        self.hi_bin = hi_bin
        self.freq_lo = freq_lo
        self.freq_hi = freq_hi
        self.center_hz = (freq_lo + freq_hi) / 2.0
        self.bw_hz = bw_hz
        self.peak_dbfs = peak_dbfs
        self.peak_bin = peak_bin
        self.peak_hz = freq_lo + (peak_bin - lo_bin + 0.5) * (bw_hz / max(1, hi_bin - lo_bin + 1))
        self.mean_dbfs = mean_dbfs
        self.noise_dbfs = noise_dbfs
        self.snr_db = snr_db
        self.id = None          # 由跟踪器分配
        self.age = 0            # 连续出现帧数
        self.missed = 0         # 连续丢失帧数

    def __repr__(self):
        return ("<CH#%s %+.3fMHz bw=%.1fkHz peak=%.1fdBFS SNR=%.1fdB>"
                % (self.id, self.center_hz / 1e6, self.bw_hz / 1e3,
                   self.peak_dbfs, self.snr_db))


# =====================================================================
#  1. 噪声底估计
# =====================================================================
def estimate_noise_floor(bins, method="median"):
    """估计噪声底（dBFS）。

    median : 取中位数。信号占用 <50% 频谱时准确，最常用。
    mode   : 直方图众数。信号很多时更稳，但计算量大。
    min    : 取低分位数。最快，但会被强信号的旁瓣拉低。
    """
    if not bins:
        return -200.0
    n = len(bins)

    if method == "median":
        if HAVE_NUMPY:
            return float(np.median(bins))
        s = sorted(bins)
        m = n // 2
        return float(s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0)

    if method == "min":
        k = max(1, int(n * 0.10))
        if HAVE_NUMPY:
            a = np.sort(np.asarray(bins, dtype=float))
            return float(a[:k].mean())
        s = sorted(bins)
        return float(sum(s[:k]) / k)

    if method == "mode":
        # 1 dB 直方图，取最密集的那个 bin 的中心
        hist = {}
        for v in bins:
            hist[int(math.floor(v))] = hist.get(int(math.floor(v)), 0) + 1
        # 3 dB 滑窗平滑后取峰值
        keys = sorted(hist)
        best, bestv = keys[0], -1
        for k in keys:
            s = sum(hist.get(k + d, 0) for d in (-1, 0, 1))
            if s > bestv:
                bestv, best = s, k
        return float(best) + 0.5

    raise ValueError("未知方法: %s" % method)


# =====================================================================
#  2. CFAR 检测
# =====================================================================
def cfar_detect(bins, guard=2, ref=16, pfa=1e-3, noise_dbfs=None,
                global_cap_db=3.0):
    """单元平均 CFAR（环形边界）。

    返回 (mask, th)，mask[i]=True 表示第 i 个 bin 超门限。

    guard : 保护单元数（每侧）。防止信号能量漏进参考窗抬高门限。
    ref   : 参考单元数（每侧）。
    pfa   : 期望虚警率。门限因子 alpha = N*(pfa^(-1/N) - 1)，N=2*ref。

    global_cap_db —— **宽带信号的关键修正**
        当信道比参考窗还宽时，参考窗会被信道自身污染，噪声估计被抬高，
        导致宽带信号漏检。这里把局部估计**上限钳到全局噪声底 + global_cap_db**：
        如果局部窗明显高于全局底，那多半是信号而不是噪声。
        设 None 可关闭该修正。
    """
    n = len(bins)
    if n == 0:
        return [], []

    N = 2 * ref
    alpha = N * (pfa ** (-1.0 / N) - 1.0)
    alpha_db = 10.0 * math.log10(max(alpha, 1e-9))

    arr = np.asarray(bins, dtype=float) if HAVE_NUMPY else None

    if HAVE_NUMPY:
        # 全向量化：用前缀和一次性求所有 bin 的参考窗功率
        # （逐 bin 的 Python 循环在 1024 点上要 ~4 ms，向量化后 ~50 us）
        p = 10.0 ** (arr / 10.0)
        csum = np.concatenate(([0.0], np.cumsum(p)))
        idx = np.arange(n)
        lo = np.clip(idx - guard - ref, 0, n)
        hi = np.clip(idx - guard, 0, n)
        lo2 = np.clip(idx + guard + 1, 0, n)
        hi2 = np.clip(idx + guard + ref + 1, 0, n)
        s = (csum[hi] - csum[lo]) + (csum[hi2] - csum[lo2])
        cnt = (hi - lo) + (hi2 - lo2)
        cnt_safe = np.maximum(cnt, 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            noise_db = 10.0 * np.log10(np.maximum(s / cnt_safe, 1e-30))
        noise_db = np.where(cnt <= 0, -200.0, noise_db)
        if noise_dbfs is not None and global_cap_db is not None:
            noise_db = np.minimum(noise_db, noise_dbfs + global_cap_db)
        th = noise_db + alpha_db
        mask = arr > th
        return mask.tolist(), th.tolist()

    # 纯 Python 回退
    mask = [False] * n
    th = [-200.0] * n
    for i in range(n):
        vals = []
        for j in range(max(0, i - guard - ref), min(n, i - guard)):
            vals.append(10.0 ** (bins[j] / 10.0))
        for j in range(max(0, i + guard + 1), min(n, i + guard + ref + 1)):
            vals.append(10.0 ** (bins[j] / 10.0))
        if not vals:
            continue
        noise_db = 10.0 * math.log10(max(sum(vals) / len(vals), 1e-30))
        if noise_dbfs is not None and global_cap_db is not None:
            noise_db = min(noise_db, noise_dbfs + global_cap_db)
        th[i] = noise_db + alpha_db
        mask[i] = bins[i] > th[i]
    return mask, th


# =====================================================================
#  3. 形态学清理
# =====================================================================
def _dilate(mask, k):
    if k <= 0:
        return list(mask)
    if HAVE_NUMPY:
        m = np.asarray(mask, dtype=bool)
        out = m.copy()
        for s in range(1, k + 1):
            out[s:] |= m[:-s]
            out[:-s] |= m[s:]
        return out.tolist()
    n = len(mask)
    out = [False] * n
    for i in range(n):
        if any(mask[j] for j in range(max(0, i - k), min(n, i + k + 1))):
            out[i] = True
    return out


def _erode(mask, k):
    if k <= 0:
        return list(mask)
    if HAVE_NUMPY:
        m = np.asarray(mask, dtype=bool)
        out = m.copy()
        for s in range(1, k + 1):
            out[s:] &= m[:-s]
            out[:-s] &= m[s:]
        return out.tolist()
    n = len(mask)
    out = [False] * n
    for i in range(n):
        if all(mask[j] for j in range(max(0, i - k), min(n, i + k + 1))):
            out[i] = True
    return out


def clean_mask(mask, open_k=1, close_k=2):
    """开运算去孤立毛刺，闭运算填小空洞。"""
    if not mask:
        return mask
    m = _erode(mask, open_k) if open_k > 0 else list(mask)
    m = _dilate(m, open_k) if open_k > 0 else m
    m = _dilate(m, close_k) if close_k > 0 else m
    m = _erode(m, close_k) if close_k > 0 else m
    return m


# =====================================================================
#  4-5. 聚类 + 参数提取
# =====================================================================
def extract_channels(bins, mask, rbw_hz, noise_dbfs, min_bw_bins=1,
                     max_gap=1, center_hz=0.0):
    """把超门限的 bin 聚成信道。"""
    n = len(bins)
    chans = []
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        gap = 0
        while j + 1 < n:
            if mask[j + 1]:
                gap = 0
                j += 1
            elif gap < max_gap:
                gap += 1
                j += 1
            else:
                break
        # [i, j] 是一个信道
        seg = bins[i:j + 1]
        if len(seg) >= min_bw_bins:
            peak = max(seg)
            peak_bin = i + seg.index(peak)
            f_lo = (-n / 2.0 + i) * rbw_hz + center_hz
            f_hi = (-n / 2.0 + j + 1) * rbw_hz + center_hz
            # 功率均值（线性域平均，再回 dB）
            if HAVE_NUMPY:
                mean_p = float(np.mean(10.0 ** (np.asarray(seg) / 10.0)))
            else:
                mean_p = sum(10.0 ** (v / 10.0) for v in seg) / len(seg)
            mean_db = 10.0 * math.log10(max(mean_p, 1e-30))
            chans.append(Channel(i, j, f_lo, f_hi, peak, peak_bin, mean_db,
                                 noise_dbfs, peak - noise_dbfs,
                                 (j - i + 1) * rbw_hz))
        i = j + 1
    return chans


# =====================================================================
#  6. 跨帧跟踪
# =====================================================================
class ChannelTracker(object):
    """给信道分配稳定 ID，报告新出现和已消失的信道。

    匹配规则：中心频率最接近且在容差内。容差默认 5 个 bin 或 200 kHz 取大者。
    """

    def __init__(self, tol_hz=None, max_missed=3):
        self.chans = []               # 上一帧的信道（带 id）
        self.next_id = 1
        self.tol_hz = tol_hz
        self.max_missed = max_missed

    def update(self, channels, rbw_hz):
        tol = self.tol_hz if self.tol_hz else max(5 * rbw_hz, 2e5)

        for c in self.chans:
            c.matched = False
        appeared, gone = [], []

        for c in channels:
            best, bestd = None, tol
            for old in self.chans:
                if getattr(old, "matched", False):
                    continue
                d = abs(old.center_hz - c.center_hz)
                if d < bestd:
                    best, bestd = old, d
            if best is not None:
                best.matched = True
                c.id = best.id
                c.age = best.age + 1
                c.missed = 0
            else:
                c.id = self.next_id
                self.next_id += 1
                c.age = 1
                c.missed = 0
                appeared.append(c)

        for old in self.chans:
            if not getattr(old, "matched", False):
                old.missed += 1
                if old.missed >= self.max_missed:
                    gone.append(old)
                else:
                    channels.append(old)      # 还在宽限期内，保留

        self.chans = [c for c in channels if c.missed < self.max_missed]
        for c in self.chans:
            c.matched = False
        return appeared, gone


# =====================================================================
def detect(frame, guard=2, ref=16, pfa=1e-3, noise_method="median",
           clean=True, min_bw_bins=1, tracker=None):
    """对一帧做完整检测，返回 (channels, info)。"""
    bins = frame.bins
    noise = estimate_noise_floor(bins, noise_method)
    mask, th = cfar_detect(bins, guard=guard, ref=ref, pfa=pfa,
                           noise_dbfs=noise)
    if clean:
        mask = clean_mask(mask, open_k=1, close_k=2)
    chans = extract_channels(bins, mask, frame.rbw_hz, noise,
                             min_bw_bins=min_bw_bins,
                             center_hz=frame.center_hz)
    appeared, gone = ([], [])
    if tracker is not None:
        appeared, gone = tracker.update(chans, frame.rbw_hz)
    info = {"noise_dbfs": noise, "thresh": th, "mask": mask,
            "n_detected": len(chans), "appeared": appeared, "gone": gone}
    return chans, info


# =====================================================================
if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"E:\LDSDR_010\rk3588")
    from spectrum import synth_frame

    print("numpy:", HAVE_NUMPY)
    print("\n=== 造一帧含 3 个已知信道的频谱 ===")
    fs = 30720000
    n = 1024
    rbw = fs / n
    # 注意 synth_frame 的 width_bins 是「半宽」，实际占 2*w-1 个 bin
    truth = [(-6.0e6, 22, 5), (-1.5e6, 30, 2), (4.0e6, 18, 12)]
    fr = synth_frame(n=n, fs=fs, noise_dbfs=-60.0, carriers=truth,
                     avg_count=64, seed=42)
    print("  真值: " + ", ".join("%+.1fMHz SNR%.0fdB 占%dbin"
                                 % (f / 1e6, s, 2 * w - 1) for f, s, w in truth))
    print("  RBW = %.1f kHz" % (rbw / 1e3))

    trk = ChannelTracker()
    chans, info = detect(fr, tracker=trk)
    print("\n  噪声底估计 = %.2f dBFS（真值 -60.00）" % info["noise_dbfs"])
    print("  检测到 %d 个信道:" % len(chans))
    for c in chans:
        print("    %r" % c)

    print("\n=== 检测质量 ===")
    # synth_frame 把载波放在 bin = n/2 + f/rbw，而频率轴是 (-n/2+i)*rbw，
    # 两者正好抵消 -> 期望频率就是 f 本身
    for (f, s, w) in truth:
        near = [c for c in chans if abs(c.center_hz - f) < max(6 * rbw, 3e5)]
        if near:
            c = near[0]
            print("  %+.1fMHz: 命中, 测得 %+.3fMHz bw=%.0fkHz SNR=%.1fdB (真值 SNR%d bw%d)"
                  % (f / 1e6, c.center_hz / 1e6, c.bw_hz / 1e3, c.snr_db, s, w))
        else:
            print("  %+.1fMHz: **漏检** (真值 SNR%ddB bw%dbin)" % (f / 1e6, s, w))

    print("\n=== 跟踪：第 2 帧加入一个新信道 ===")
    truth2 = truth + [(8.0e6, 25, 3)]
    fr2 = synth_frame(n=n, fs=fs, noise_dbfs=-60.0, carriers=truth2,
                      avg_count=64, seed=43)
    chans2, info2 = detect(fr2, tracker=trk)
    print("  新出现: %s" % ([repr(c) for c in info2["appeared"]] or "无"))
    print("  消失  : %s" % ([repr(c) for c in info2["gone"]] or "无"))
    print("  当前 %d 个信道" % len(chans2))

    print("\n=== 虚警测试：纯噪声 20 帧 ===")
    fa = 0
    for k in range(20):
        f0 = synth_frame(n=n, fs=fs, noise_dbfs=-60.0, carriers=[], seed=100 + k)
        c0, _ = detect(f0, tracker=None)
        fa += len(c0)
    print("  纯噪声下共检出 %d 个（%.2f 个/帧，期望接近 0）" % (fa, fa / 20.0))
    print("\n完成。")
