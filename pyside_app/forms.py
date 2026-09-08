"""Translate Qt fields into the existing validated request models."""
from dataclasses import replace
from pathlib import Path

from automation import EggRunRequest, SIDReverseRunRequest, TidRngRequest, TidStarterFlowRequest
from automation.tid_search import parse_target_tids
from assets.game_text import SPECIES_ZH_TO_EN, LOCATION_ZH_TO_EN
from rng.tenlines_utils import get_species_id
from .diagnostics import parse_integer


def species_id(value):
    text = value.strip()
    number = int(text) if text.isascii() and text.isdigit() else get_species_id(SPECIES_ZH_TO_EN.get(text, text))
    if not 1 <= number <= 386:
        raise ValueError("请填写有效的中文名、英文名或全国图鉴编号 1–386")
    return number


class FormReader:
    def __init__(self, window):
        self.w = window
        self.f = window.fields

    def text(self, key):
        widget = self.f[key]
        return widget.currentText() if hasattr(widget, "currentText") else widget.text()

    def integer(self, key):
        return parse_integer(self.text(key), self.f[key].accessibleName() or key)

    def selected_integer(self, key):
        widget = self.f[key]
        return parse_integer(str(widget.currentData()), widget.accessibleName() or key)

    def index(self, key):
        return self.f[key].currentIndex()

    def expansion(self):
        if not self.w.advanced_check.isChecked():
            return {}
        fields = [f"expansion_{i}_{axis}" for i in range(1, 4) for axis in ("seed", "adv")]
        if self.f["layers"].value() == 3 and all(not self.text(key).strip() for key in fields):
            # A portable config may inherit defaults before a script pack is
            # selected. Keep None so the generator reads its own template.
            return {}
        return dict(reverse_expansion_layers=self.f["layers"].value(),
            reverse_expansion_seed_tolerances=tuple(self.integer(f"expansion_{i}_seed") for i in range(1, 4)),
            reverse_expansion_frame_half_widths=tuple(self.integer(f"expansion_{i}_adv") for i in range(1, 4)))

    def egg(self, *, require_ack=True):
        if require_ack and not self.w.egg_ack.isChecked():
            raise ValueError("请先确认孵蛋前置条件")
        parents = self.w.egg_parent_widgets
        request = EggRunRequest(game=self.w.game_code(), seed_mode=self.index("egg_seed_mode") - 1,
            target_seed=self.text("egg_seed"), held_advances=self.integer("egg_held"),
            pickup_advances=self.integer("egg_pickup"), species_id=species_id(self.text("egg_species")),
            compatibility=self.selected_integer("egg_compatibility"), parent_a_gender=parents[0][0].currentText(),
            parent_b_gender=parents[1][0].currentText(), parent_a_ivs=tuple(s.value() for s in parents[0][1:]),
            parent_b_ivs=tuple(s.value() for s in parents[1][1:]),
            start_from_prepared_254=self.index("egg_start") == 1,
            home_buffer_adaptive_threshold=self.w.home_buffer_check.isChecked(),
            seed_startup_scheme=self.index("seed_startup") if self.w.advanced_check.isChecked() else 0,
            seed_calibration_scheme=self.index("seed_calibration") if self.w.advanced_check.isChecked() else 2,
            update_precalibration=self.w.precalibration_check.isChecked(), debug_log_output=self.index("output_log"), **self.expansion())
        request.validate()
        return request

    def sid(self):
        if not self.w.sid_ack.isChecked():
            raise ValueError("请确认队伍顺序、宝可梦资料、努力值和糖果位置")
        count = self.f["sid_count"].value()
        rows = self.w.sid_party_widgets
        request = SIDReverseRunRequest(tid=self.integer("sid_tid"), party_count=count,
            game="fr_nx" if self.index("sid_game") == 0 else "lg_nx", nx_model=self.index("sid_nx") + 1,
            max_candies=self.f["sid_candies"].value(), recognition_threshold=self.f["sid_threshold"].value(),
            home_buffer_adaptive_threshold=self.w.home_buffer_check.isChecked(),
            dex_overrides=tuple(species_id(row[0].text()) if i < count else 0 for i, row in enumerate(rows)),
            initial_levels=tuple(parse_integer(row[1].text(), f"队伍第 {i + 1} 只 · 初始等级") if i < count else 1 for i, row in enumerate(rows)),
            source_types=tuple(row[2].currentIndex() if i < count else 0 for i, row in enumerate(rows)),
            locations=tuple(LOCATION_ZH_TO_EN.get(row[3].text().strip(), row[3].text().strip()) if i < count else "" for i, row in enumerate(rows)),
            effort_values=tuple(tuple(s.value() for s in row[4:]) if i < count else (0,) * 6 for i, row in enumerate(rows)))
        request.validate()
        return request

    def tid(self):
        w = self.w
        any_tid = w.tid_flow_check.isChecked() and self.index("tid_mode") == 1 and w.tid_any_check.isChecked()
        integer_fields = {
            "op_fixed_delay": "tid_op_delay", "f1_fixed_delay": "tid_f1_delay", "f2_fixed_delay": "tid_f2_delay", "f3_fixed_delay": "tid_f3_delay",
            "close_game_delay": "tid_close", "home_buffer_delay": "tid_home", "op_correction": "tid_op_correction",
            "target_sid": "tid_sid", "sid_advance_correction": "tid_sid_correction", "select_correction": "tid_select",
            "f2_candidate_range": "tid_f2_candidate", "f1_candidate_range": "tid_f1_candidate",
            "denoise_need_hit": "tid_hits", "denoise_try_window": "tid_window", "image_threshold": "tid_threshold",
            "near_tid_distance": "tid_near_distance", "near_tid_hits": "tid_near_hits",
        }
        for axis in ("op", "f1", "f2"):
            integer_fields.update({f"{axis}_target_frame": f"tid_{axis}_target", f"{axis}_start": f"tid_{axis}_start",
                f"{axis}_rng_range": f"tid_{axis}_radius", f"{axis}_max_range": f"tid_{axis}_range",
                f"auto_{axis}_rng_range": f"tid_auto_{axis}_range"})
        values = {name: self.integer(key) for name, key in integer_fields.items()}
        values.update(dict(language=self.text("tid_language"), mode=1 - self.index("tid_mode"),
            calibration_check=w.tid_calibration_check.isChecked(), gender=self.index("tid_gender"), nx_model=self.index("tid_nx") + 1,
            target_tid=0 if any_tid else self.integer("tid_target"), player_name=self.text("tid_name"),
            sound=self.index("tid_sound"), button_mode=self.index("tid_button"), seed_button=self.index("tid_seed_button"),
            name_entry_button=self.index("tid_name_entry"), sid_random=self.index("tid_sid_mode") == 1,
            home_buffer_adaptive_threshold=w.home_buffer_check.isChecked(),
            additional_target_tids=() if any_tid else parse_target_tids(self.text("tid_additional_targets")),
            auto_rng=w.tid_auto_rng_check.isChecked() and not any_tid))
        values.update({name: check.isChecked() for name, check in zip(("same_id", "sequential_id", "include_65535", "single_digit_id"), w.tid_special_checks)})
        request = TidRngRequest(**values)
        request.validate()
        state = getattr(w, "tid_state", None)
        return state.effective_request(request) if state else request

    def flow(self, request):
        if not self.w.tid_flow_check.isChecked():
            return None
        expansion = {"starter_" + key: value for key, value in self.expansion().items()}
        flow = TidStarterFlowRequest(tid_request=replace(request, calibration_check=False),
            version=self.text("tid_game"), starter=self.text("starter_species"),
            starter_min_advances=self.integer("starter_min"), starter_max_advances=self.integer("starter_max"),
            sid_retry_radius=self.integer("starter_retry"), starter_sound=self.index("starter_sound"),
            starter_button_mode=self.index("starter_button"), starter_seed_button=self.index("starter_seed_button"),
            accept_any_tid=request.mode == 0 and self.w.tid_any_check.isChecked(),
            any_tid_require_denoise=self.w.tid_denoise_check.isChecked(),
            starter_seed_startup_scheme=self.index("seed_startup") if self.w.advanced_check.isChecked() else 0,
            starter_template_name=self.w.current_template(), update_precalibration=self.w.precalibration_check.isChecked(),
            starter_debug_log_output=self.index("output_log"),
            starter_frame_parity_scheme=1 - self.index("parity") if self.w.advanced_check.isChecked() else 1,
            **expansion)
        flow.validate()
        return flow
