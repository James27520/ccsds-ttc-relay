import unittest
from .receive_health import ReceiveHealth


class ReceiveHealthTests(unittest.TestCase):
    def observe(self, h, samples, ms, **values):
        return h.observe(dict(samples=samples, uptime_ms=ms, **values))

    def test_real_low_interval_warns_then_recovers_without_reset(self):
        h = ReceiveHealth()
        self.observe(h, 968998912, 410860.584)
        r = self.observe(h, 977879040, 414729.146)
        self.assertEqual(r['level'], 'degraded')
        self.assertFalse(r['recover'])
        self.assertAlmostEqual(r['processed_rate_sps'], 2295460, delta=100)
        self.observe(h, 985379040, 417729.146)
        r = self.observe(h, 992879040, 420729.146)
        self.assertEqual(r['level'], 'healthy')
        self.assertFalse(r['loss_measured'])

    def test_persistent_2_36_msps_is_not_silently_accepted(self):
        h = ReceiveHealth()
        self.observe(h, 0, 0)
        for n in range(1, 5):
            r = self.observe(h, n*7080000, n*3000)
            self.assertEqual(r['level'], 'degraded')
            self.assertEqual(r['recover'], n == 4)

    def test_growth_and_full_buffer_have_explicit_loss_uncertainty(self):
        h = ReceiveHealth()
        self.observe(h, 0, 0)
        r = self.observe(h, 7500000, 3000, queue_samples=400000,
                         queue_capacity_samples=524288)
        self.assertEqual(r['level'], 'degraded')
        self.assertFalse(r['recover'])
        r = self.observe(h, 7800000, 3200, queue_samples=524288,
                         queue_capacity_samples=524288, queue_backpressure_events=1)
        self.assertTrue(r['recover'])
        self.assertTrue(r['continuity_uncertain'])
        self.assertFalse(r['loss_measured'])

    def test_counter_reset_invalid_and_nan_rejected(self):
        for value in [dict(samples=0, uptime_ms=10), dict(samples=101, uptime_ms=1),
                      dict(samples=101, uptime_ms=float('nan')),
                      dict(samples=101, uptime_ms=20, queue_samples=1),
                      dict(samples=True, uptime_ms=20)]:
            with self.subTest(value=value):
                h = ReceiveHealth()
                self.observe(h, 100, 10)
                with self.assertRaises(ValueError): h.observe(value)
