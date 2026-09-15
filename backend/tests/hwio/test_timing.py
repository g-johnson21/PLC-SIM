import math

from draco_sim.hwio import HwIo, HwIoConfig


def _expected_refresh_steps(period_s, dt_s, n_steps):
    """Mirror HwIo.step's own due-check (t += dt; due if t - last_refresh >= period) so the
    expected refresh points are derived, not hand-counted, for whatever period/dt is under test.
    """
    t = 0.0
    last = -math.inf
    idxs = []
    for i in range(n_steps):
        t += dt_s
        if t - last >= period_s:
            idxs.append(i)
            last = t
    return idxs


def _observed_change_steps(hw, tag, values, dt_s):
    prev = None
    changed = []
    for i, v in enumerate(values):
        hw.set_physical({tag: v})
        hw.step(dt_s)
        rb = hw.read_inputs()[tag]
        if prev is None or rb != prev:
            changed.append(i)
        prev = rb
    return changed


def test_ni9211_refresh_period_is_1_over_14_second(db):
    hw = HwIo(db)
    dt = 0.01
    n = 30
    values = [-297.0 + i * 1.0 for i in range(n)]
    observed = _observed_change_steps(hw, "TC1", values, dt)
    expected = _expected_refresh_steps(1.0 / 14.0, dt, n)
    assert observed == expected
    assert expected == [0, 8, 16, 24]  # ~7-8 steps of 10 ms, per the acceptance brief


def test_ni9208_high_speed_refresh_period_is_2ms(db):
    hw = HwIo(db, config=HwIoConfig(ni9208_mode="high_speed"))
    dt = 0.0007
    n = 10
    values = [1000.0 + i * 50.0 for i in range(n)]
    observed = _observed_change_steps(hw, "PT1", values, dt)
    expected = _expected_refresh_steps(0.002, dt, n)
    assert observed == expected
    assert len(expected) >= 2


def test_ni9208_high_res_refresh_period_is_52ms_times_channels_in_scan(db):
    hw = HwIo(db, config=HwIoConfig(ni9208_mode="high_res"))
    n_channels = len(db.for_module("NI-9208", 0))  # PT1 lives on module index 0
    period = 0.052 * n_channels
    dt = 0.05
    n = 15
    values = [1000.0 + i * 100.0 for i in range(n)]
    observed = _observed_change_steps(hw, "PT1", values, dt)
    expected = _expected_refresh_steps(period, dt, n)
    assert observed == expected
    assert len(expected) >= 2  # actually exercise a hold-then-refresh transition


def test_ni9237_refreshes_effectively_every_step(db):
    # 50 kS/s/ch simultaneous is far above any reasonable scan/step rate, so with dt >> 1/50000 s
    # every step should see a fresh conversion -- no held/stale value.
    hw = HwIo(db)
    dt = 0.01
    n = 5
    values = [500.0 + i * 10.0 for i in range(n)]
    observed = _observed_change_steps(hw, "LC1", values, dt)
    assert observed == list(range(n))
