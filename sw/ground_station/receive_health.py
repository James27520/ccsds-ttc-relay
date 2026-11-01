"""Rate/backlog health, separate from device identity and RF configuration.

Counters establish progress, never proof of lossless ADC capture. A bounded
queue absorbs scheduling bursts; persistent deficits still require recovery.
"""
import math


class ReceiveHealth:
    def __init__(self):
        self.anchor = None
        self.last = None
        self.bad_ms = self.good_ms = 0
        self.level = 'warming'
        self.rate = None
        self.backpressure = 0
        self.continuity_uncertain = False

    def observe(self, status):
        samples, uptime = status['samples'], status.get('uptime_ms', 0)
        if (type(samples) is not int or samples < 0 or type(uptime) not in (int, float)
                or not math.isfinite(uptime) or uptime < 0):
            raise ValueError('板端采样计数或时间无效')
        if self.last and (samples < self.last[0] or uptime < self.last[1]):
            raise ValueError('板端采样计数或时间回退，接收会话已失效')
        self.last = samples, uptime
        queued = status.get('queue_samples', 0)
        capacity = status.get('queue_capacity_samples', 0)
        pressure = status.get('queue_backpressure_events', 0)
        if any(type(x) is not int or x < 0 for x in (queued, capacity, pressure)) or queued > capacity:
            raise ValueError('板端接收缓冲统计无效')
        if pressure < self.backpressure:
            raise ValueError('板端缓冲计数回退')
        new_pressure = pressure > self.backpressure
        self.backpressure = pressure
        if new_pressure:
            self.continuity_uncertain = True
        reason = '正在建立接收基线'
        recover = False
        if self.anchor is None:
            self.anchor = samples, uptime
        elif uptime-self.anchor[1] >= 3000:
            elapsed = uptime-self.anchor[1]
            self.rate = (samples-self.anchor[0])*1000/elapsed
            self.anchor = samples, uptime
            # A three-second count has at most one partial block/window of
            # quantization. Warn at 2.45 MSPS, before the former 2.30 MSPS
            # disconnect boundary; require sustained evidence for recovery.
            slow = self.rate < 2450000
            backlog = bool(capacity and queued >= capacity//2)
            if slow or backlog or new_pressure:
                self.bad_ms += elapsed
                self.good_ms = 0
                self.level = 'degraded'
                recover = self.bad_ms >= 12000
            else:
                self.good_ms += elapsed
                self.bad_ms = 0
                if self.level == 'warming' or self.good_ms >= 6000:
                    self.level = 'healthy'
            reason = (f'处理 {self.rate/1e6:.3f} MSPS / 目标 2.500；'
                      f'缓冲 {queued/2500:.1f} ms')
        if new_pressure:
            # The upstream DMA has no sequence counter. Backpressure means
            # continuity is uncertain, not an invented number of lost samples.
            self.level = 'degraded'
            recover = True
            reason = '采集缓冲已满，上游连续性未确认'
        return dict(level=self.level, reason=reason, recover=recover,
                    processed_rate_sps=self.rate, queue_samples=queued,
                    queue_capacity_samples=capacity, queue_backpressure_events=pressure,
                    continuity_uncertain=self.continuity_uncertain, loss_measured=False)
