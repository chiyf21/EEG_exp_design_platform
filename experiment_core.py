"""Core data model and planner for a motor-imagery experiment.

This module intentionally has no GUI or third-party dependency so it can be
tested and reused by a future PsychoPy/Qt presenter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import random
from typing import Any


VISUAL_TYPES = {"text", "blank", "image", "video"}


@dataclass
class Phase:
    name: str
    duration_s: float
    instruction: str = ""
    visual: dict[str, Any] = field(default_factory=lambda: {"type": "text", "value": ""})
    marker: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Phase":
        visual = data.get("visual") or {"type": "text", "value": data.get("instruction", "")}
        return cls(
            name=str(data.get("name", "未命名阶段")),
            duration_s=float(data.get("duration_s", 1)),
            instruction=str(data.get("instruction", "")),
            visual=dict(visual),
            marker=str(data.get("marker", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration_s": self.duration_s,
            "instruction": self.instruction,
            "visual": self.visual,
            "marker": self.marker,
        }

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("阶段名称不能为空")
        if not math.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError(f"阶段“{self.name}”的时长必须大于 0")
        visual_type = str(self.visual.get("type", "text"))
        if visual_type not in VISUAL_TYPES:
            raise ValueError(f"阶段“{self.name}”包含不支持的显示类型：{visual_type}")


@dataclass
class Unit:
    name: str
    weight: float = 1.0
    phases: list[Phase] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Unit":
        return cls(
            name=str(data.get("name", "未命名单元")),
            weight=float(data.get("weight", 1.0)),
            phases=[Phase.from_dict(item) for item in data.get("phases", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": self.weight,
            "phases": [phase.to_dict() for phase in self.phases],
        }

    @property
    def duration_s(self) -> float:
        return sum(phase.duration_s for phase in self.phases)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("单元实验名称不能为空")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError(f"单元“{self.name}”的比例/权重不能小于 0")
        if not self.phases:
            raise ValueError(f"单元“{self.name}”至少需要一个阶段")
        for phase in self.phases:
            phase.validate()
        if self.duration_s <= 0:
            raise ValueError(f"单元“{self.name}”的总时长必须大于 0")


@dataclass
class ExperimentConfig:
    name: str = "运动想象实验"
    header_title: str = "运动想象实验设计器"
    header_subtitle: str = "配置刺激序列 · 同步 EEG · 记录实验日志"
    total_duration_s: float = 900.0
    selection_mode: str = "weighted"
    units: list[Unit] = field(default_factory=list)
    lsl_stream_name: str = "MIExperimentMarkers"
    lsl_stream_type: str = "MITrigger"
    lsl_source_id: str = "mi-experiment-designer"
    output_dir: str = "sessions"
    speech_enabled: bool = False
    speech_rate: int = 170

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        return cls(
            name=str(data.get("name", "运动想象实验")),
            header_title=str(data.get("header_title", "运动想象实验设计器")),
            header_subtitle=str(data.get("header_subtitle", "配置刺激序列 · 同步 EEG · 记录实验日志")),
            total_duration_s=float(data.get("total_duration_s", 900)),
            selection_mode=str(data.get("selection_mode", "weighted")),
            units=[Unit.from_dict(item) for item in data.get("units", [])],
            lsl_stream_name=str(data.get("lsl_stream_name", "MIExperimentMarkers")),
            lsl_stream_type=str(data.get("lsl_stream_type", "MITrigger")),
            lsl_source_id=str(data.get("lsl_source_id", "mi-experiment-designer")),
            output_dir=str(data.get("output_dir", "sessions")),
            speech_enabled=bool(data.get("speech_enabled", False)),
            speech_rate=int(data.get("speech_rate", 170)),
        )

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "header_title": self.header_title,
            "header_subtitle": self.header_subtitle,
            "total_duration_s": self.total_duration_s,
            "selection_mode": self.selection_mode,
            "lsl_stream_name": self.lsl_stream_name,
            "lsl_stream_type": self.lsl_stream_type,
            "lsl_source_id": self.lsl_source_id,
            "output_dir": self.output_dir,
            "speech_enabled": self.speech_enabled,
            "speech_rate": self.speech_rate,
            "units": [unit.to_dict() for unit in self.units],
        }

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("实验名称不能为空")
        if not self.header_title.strip():
            raise ValueError("界面主标题不能为空")
        if not self.header_subtitle.strip():
            raise ValueError("界面副标题不能为空")
        if not self.lsl_stream_name.strip():
            raise ValueError("LSL stream name 不能为空")
        if not self.lsl_stream_type.strip():
            raise ValueError("LSL stream type 不能为空")
        if not 80 <= self.speech_rate <= 300:
            raise ValueError("语速必须在 80 到 300 之间")
        if not math.isfinite(self.total_duration_s) or self.total_duration_s <= 0:
            raise ValueError("总实验时长必须大于 0")
        if self.selection_mode not in {"weighted", "random"}:
            raise ValueError("selection_mode 只能是 weighted 或 random")
        if not self.units:
            raise ValueError("至少需要一个单元实验")
        if len({unit.name.strip() for unit in self.units}) != len(self.units):
            raise ValueError("单元实验名称不能重复")
        for unit in self.units:
            unit.validate()
        if not any(unit.weight > 0 for unit in self.units):
            raise ValueError("至少需要一个权重大于 0 的单元实验")
        durations = [unit.duration_s for unit in self.units]
        reference = durations[0]
        if any(not math.isclose(duration, reference, rel_tol=1e-9, abs_tol=1e-6) for duration in durations[1:]):
            raise ValueError("当前版本要求所有单元实验的总时长相同")
        if self.total_duration_s < reference:
            raise ValueError("总实验时长不能小于一个单元实验的时长")

    @property
    def unit_duration_s(self) -> float:
        if not self.units:
            return 0.0
        return self.units[0].duration_s

    @property
    def planned_trial_count(self) -> int:
        return max(1, int(self.total_duration_s // self.unit_duration_s)) if self.unit_duration_s else 0

    @property
    def planned_duration_s(self) -> float:
        return self.planned_trial_count * self.unit_duration_s

    def build_plan(self, rng: random.Random | None = None) -> list[Unit]:
        self.validate()
        rng = rng or random.Random()
        count = self.planned_trial_count
        eligible = [unit for unit in self.units if unit.weight > 0]
        if self.selection_mode == "random":
            weights = [unit.weight for unit in eligible]
            return [rng.choices(eligible, weights=weights, k=1)[0] for _ in range(count)]

        total_weight = sum(unit.weight for unit in eligible)
        raw_counts = [count * unit.weight / total_weight for unit in eligible]
        counts = [math.floor(value) for value in raw_counts]
        remainder = count - sum(counts)
        order = sorted(
            range(len(eligible)),
            key=lambda index: (raw_counts[index] - counts[index], rng.random()),
            reverse=True,
        )
        for index in order[:remainder]:
            counts[index] += 1
        plan = [unit for unit, unit_count in zip(eligible, counts) for _ in range(unit_count)]
        rng.shuffle(plan)
        return plan


def default_config() -> ExperimentConfig:
    def phase(name: str, duration_s: float, instruction: str, marker: str) -> Phase:
        return Phase(
            name=name,
            duration_s=duration_s,
            instruction=instruction,
            visual={"type": "text", "value": instruction},
            marker=marker,
        )

    def unit(name: str, instruction: str, marker: str) -> Unit:
        return Unit(
            name=name,
            weight=1.0,
            phases=[
                phase("准备", 3, "准备", "prepare"),
                phase("运动想象", 20, instruction, marker),
                phase("休息", 7, "休息", "rest"),
            ],
        )

    return ExperimentConfig(
        units=[
            unit("左手", "想象左手抓握", "left_hand"),
            unit("右手", "想象右手抓握", "right_hand"),
            unit("双脚", "想象双脚屈伸", "feet"),
        ]
    )


def self_check() -> None:
    config = default_config()
    config.validate()
    assert config.speech_enabled is False
    assert config.speech_rate == 170
    assert config.lsl_stream_type == "MITrigger"
    assert config.unit_duration_s == 30
    assert config.planned_trial_count == 30
    plan = config.build_plan(random.Random(7))
    assert len(plan) == 30
    assert {unit.name for unit in plan} == {"左手", "右手", "双脚"}

    config.selection_mode = "random"
    random_plan = config.build_plan(random.Random(7))
    assert len(random_plan) == 30

    encoded = json.dumps(config.to_dict(), ensure_ascii=False)
    restored = ExperimentConfig.from_dict(json.loads(encoded))
    assert restored.unit_duration_s == 30
    assert restored.speech_enabled is False
    assert restored.lsl_stream_type == "MITrigger"


if __name__ == "__main__":
    self_check()
    print("experiment_core self-check: ok")
