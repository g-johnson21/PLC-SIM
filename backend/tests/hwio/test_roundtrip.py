import math

from draco_sim.hwio import HwIo
from draco_sim.hwio import scaling
from draco_sim.hwio import thermocouple as tk
from draco_sim.hwio.core import (
    _LC_CARD_BITS,
    _LC_CARD_MVV,
    _PT_CARD_BITS,
    _PT_CARD_MA,
    _TC_CARD_BITS,
    _TC_CARD_MV,
)


def _half_lsb_eng(card_span, bits, eng_span, elec_span):
    lsb = card_span / (2**bits - 1)
    return 0.5 * lsb * (eng_span / elec_span)


def test_pressure_roundtrip_within_half_lsb(db):
    hw = HwIo(db)
    cases = {"PT1": 4000.0, "PT3": 904.0, "PT2": 1200.0}
    hw.set_physical(cases)
    hw.step(0.01)
    rb = hw.read_inputs()
    loop_span = hw.config.pt_loop_ma[1] - hw.config.pt_loop_ma[0]
    card_span = _PT_CARD_MA[1] - _PT_CARD_MA[0]
    for tag_name, truth in cases.items():
        tag = db.by_tag[tag_name]
        eng_span = tag.range[1] - tag.range[0]
        bound = _half_lsb_eng(card_span, _PT_CARD_BITS, eng_span, loop_span)
        err = abs(rb[tag_name] - truth)
        assert err <= bound + 1e-9, f"{tag_name}: err={err} bound={bound}"


def test_load_cell_roundtrip_within_half_lsb(db):
    hw = HwIo(db)
    cases = {"LC4": 68.8, "LC1": 1500.0, "LC_FUEL": 50.0}
    hw.set_physical(cases)
    hw.step(0.01)
    rb = hw.read_inputs()
    card_span = _LC_CARD_MVV[1] - _LC_CARD_MVV[0]
    for tag_name, truth in cases.items():
        tag = db.by_tag[tag_name]
        bound = _half_lsb_eng(card_span, _LC_CARD_BITS, tag.capacity_lbf, tag.rated_output_mv_per_v)
        err = abs(rb[tag_name] - truth)
        assert err <= bound + 1e-9, f"{tag_name}: err={err} bound={bound}"


def test_thermocouple_roundtrip_matches_its90_fit_residual_plus_quantisation(db):
    # Unlike the linear PT/LC cases, the NIST ITS-90 direct/inverse Type-K polynomials are two
    # SEPARATELY fitted functions (docs/hwio.md, "Known limitation"), so even at zero quantisation
    # E(T(E)) != E exactly. Reconstruct that predicted error via the same public primitives HwIo
    # uses internally (scaling.quantize + thermocouple), and pin the pipeline's actual output to it.
    hw = HwIo(db)
    truth_f = -297.0
    hw.set_physical({"TC1": truth_f})
    hw.step(0.01)
    actual_err_f = hw.read_inputs()["TC1"] - truth_f

    cfg = hw.config
    t_hot_c = (truth_f - 32.0) * 5.0 / 9.0
    cj_c = cfg.cold_junction_degc + cfg.cold_junction_accuracy_degc
    e_cj = tk.emf_from_temp_c(cj_c)
    e_true = tk.emf_from_temp_c(t_hot_c) - e_cj
    q, _code = scaling.quantize(e_true, *_TC_CARD_MV, _TC_CARD_BITS)
    predicted_recovered_c = tk.temp_c_from_emf(q + e_cj)
    predicted_err_f = (predicted_recovered_c * 9.0 / 5.0 + 32.0) - truth_f

    assert math.isclose(actual_err_f, predicted_err_f, abs_tol=1e-9)
    # Sanity check on the documented residual's order of magnitude (a fraction of a degree),
    # confirming it's the known fit-pair residual and not some much larger unrelated error.
    assert abs(actual_err_f) < 0.05, f"TC1 round-trip error {actual_err_f} is outside the expected ITS-90 ballpark"


def test_pt0_null_range_passthrough_is_exact(db):
    hw = HwIo(db)
    hw.set_physical({"PT0": 123.456})
    hw.step(0.01)
    assert hw.read_inputs()["PT0"] == 123.456
