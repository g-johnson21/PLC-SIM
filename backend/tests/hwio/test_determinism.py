from draco_sim.hwio import HwIo, HwIoConfig


def test_seeded_noise_is_deterministic_across_instances(db):
    cfg_kwargs = dict(pressure_noise_density_ma=0.01, seed=42)
    hw_a = HwIo(db, config=HwIoConfig(**cfg_kwargs))
    hw_b = HwIo(db, config=HwIoConfig(**cfg_kwargs))

    series_a, series_b = [], []
    for _ in range(20):
        hw_a.set_physical({"PT1": 3000.0})
        hw_b.set_physical({"PT1": 3000.0})
        hw_a.step(0.01)
        hw_b.step(0.01)
        series_a.append(hw_a.read_inputs()["PT1"])
        series_b.append(hw_b.read_inputs()["PT1"])

    assert series_a == series_b


def test_noise_is_actually_injected_relative_to_a_noiseless_control(db):
    hw_noisy = HwIo(db, config=HwIoConfig(pressure_noise_density_ma=0.01, seed=42))
    hw_clean = HwIo(db, config=HwIoConfig(seed=42))

    noisy_vals, clean_vals = [], []
    for _ in range(20):
        hw_noisy.set_physical({"PT1": 3000.0})
        hw_clean.set_physical({"PT1": 3000.0})
        hw_noisy.step(0.01)
        hw_clean.step(0.01)
        noisy_vals.append(hw_noisy.read_inputs()["PT1"])
        clean_vals.append(hw_clean.read_inputs()["PT1"])

    assert len(set(clean_vals)) == 1  # constant physical, zero noise -> constant reading
    assert len(set(noisy_vals)) > 1  # same physical, noise enabled -> varies
