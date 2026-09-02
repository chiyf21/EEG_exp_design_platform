"""Cross-platform GUI for configuring and running a motor-imagery experiment."""

from __future__ import annotations

import csv
from datetime import datetime
import json
import math
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from experiment_core import ExperimentConfig, Phase, Unit, default_config


try:
    from pylsl import StreamInfo, StreamOutlet, local_clock
except ImportError:  # The GUI can still be designed/tested without LSL installed.
    StreamInfo = StreamOutlet = local_clock = None


try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None


try:
    import cv2
except ImportError:
    cv2 = None


SELECTION_LABELS = {
    "weighted": "按比例（权重配额）",
    "random": "随机（按权重抽取）",
}


def format_seconds(value: float) -> str:
    if math.isclose(value, round(value)):
        return f"{int(round(value))} s"
    return f"{value:.2f} s"


def display_visual(phase: Phase) -> tuple[str, str]:
    visual = phase.visual or {}
    return str(visual.get("type", "text")), str(visual.get("value", phase.instruction))


class PhaseDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, phase: Phase | None = None):
        super().__init__(parent)
        self.title("编辑阶段")
        self.resizable(False, False)
        self.result: Phase | None = None
        phase = phase or Phase("新阶段", 1, "", {"type": "text", "value": ""}, "")

        self.name_var = tk.StringVar(value=phase.name)
        self.duration_var = tk.StringVar(value=str(phase.duration_s))
        self.instruction_var = tk.StringVar(value=phase.instruction)
        visual_type, visual_value = display_visual(phase)
        self.visual_type_var = tk.StringVar(value=visual_type)
        self.visual_value_var = tk.StringVar(value=visual_value)
        self.marker_var = tk.StringVar(value=phase.marker)

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        fields = [
            ("阶段名称", self.name_var),
            ("时长（秒）", self.duration_var),
            ("指令说明", self.instruction_var),
            ("LSL marker 标签（可选）", self.marker_var),
        ]
        for row, (label, variable) in enumerate(fields):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=variable, width=42).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

        ttk.Label(body, text="显示类型").grid(row=4, column=0, sticky="w", pady=4)
        visual_combo = ttk.Combobox(
            body,
            textvariable=self.visual_type_var,
            values=("text", "blank", "image", "video"),
            state="readonly",
            width=12,
        )
        visual_combo.grid(row=4, column=1, sticky="w", pady=4)
        visual_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_visual_hint())

        ttk.Label(body, text="显示内容/媒体路径").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=self.visual_value_var, width=42).grid(row=5, column=1, sticky="ew", pady=4)
        ttk.Button(body, text="选择文件", command=self._choose_file).grid(row=5, column=2, padx=(6, 0), pady=4)
        self.visual_hint = ttk.Label(body, text="")
        self.visual_hint.grid(row=6, column=1, columnspan=2, sticky="w")

        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="确定", command=self._accept).pack(side="right")
        self._update_visual_hint()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_visibility()

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[
                ("图片", "*.png *.jpg *.jpeg *.bmp *.gif"),
                ("视频", "*.mp4 *.avi *.mov *.mkv"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.visual_value_var.set(path)

    def _update_visual_hint(self) -> None:
        hints = {
            "text": "在屏幕中央显示文本；为空时使用“指令说明”。",
            "blank": "黑屏/空白屏。",
            "image": "需要安装 Pillow；支持 PNG/JPG/BMP/GIF。",
            "video": "需要安装 OpenCV；原型按帧播放，不处理音频。",
        }
        self.visual_hint.configure(text=hints.get(self.visual_type_var.get(), ""))

    def _accept(self) -> None:
        try:
            name = self.name_var.get().strip()
            duration = float(self.duration_var.get())
            instruction = self.instruction_var.get()
            visual_type = self.visual_type_var.get()
            visual_value = self.visual_value_var.get()
            phase = Phase(
                name=name,
                duration_s=duration,
                instruction=instruction,
                visual={"type": visual_type, "value": visual_value},
                marker=self.marker_var.get().strip(),
            )
            phase.validate()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("阶段参数无效", str(exc), parent=self)
            return
        self.result = phase
        self.destroy()


class UnitDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, unit: Unit | None = None):
        super().__init__(parent)
        self.title("编辑单元实验")
        self.geometry("760x420")
        self.result: Unit | None = None
        self.phases: list[Phase] = list(unit.phases) if unit else []
        unit = unit or Unit("新单元", 1.0, [])

        self.name_var = tk.StringVar(value=unit.name)
        self.weight_var = tk.StringVar(value=str(unit.weight))

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        top = ttk.Frame(body)
        top.pack(fill="x")
        ttk.Label(top, text="单元名称").pack(side="left")
        ttk.Entry(top, textvariable=self.name_var, width=24).pack(side="left", padx=(6, 18))
        ttk.Label(top, text="比例/权重").pack(side="left")
        ttk.Entry(top, textvariable=self.weight_var, width=10).pack(side="left", padx=6)

        ttk.Label(body, text="阶段序列（总时长必须与其他单元相同）").pack(anchor="w", pady=(14, 4))
        table_frame = ttk.Frame(body)
        table_frame.pack(fill="both", expand=True)
        columns = ("order", "name", "duration", "instruction", "visual")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {"order": "#", "name": "阶段", "duration": "时长", "instruction": "指令", "visual": "显示"}
        widths = {"order": 40, "name": 130, "duration": 80, "instruction": 260, "visual": 100}
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self._edit_phase())

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(8, 0))
        for label, command in (
            ("添加阶段", self._add_phase),
            ("编辑阶段", self._edit_phase),
            ("删除阶段", self._delete_phase),
            ("上移", lambda: self._move_phase(-1)),
            ("下移", lambda: self._move_phase(1)),
        ):
            ttk.Button(controls, text=label, command=command).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="取消", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(controls, text="确定", command=self._accept).pack(side="right")

        self._refresh()
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.wait_visibility()

    def _refresh(self, select_index: int | None = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, phase in enumerate(self.phases):
            visual_type, _ = display_visual(phase)
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(index + 1, phase.name, format_seconds(phase.duration_s), phase.instruction, visual_type),
            )
        if select_index is not None and 0 <= select_index < len(self.phases):
            self.tree.selection_set(str(select_index))
            self.tree.focus(str(select_index))

    def _selected_index(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _add_phase(self) -> None:
        dialog = PhaseDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.phases.append(dialog.result)
            self._refresh(len(self.phases) - 1)

    def _edit_phase(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        dialog = PhaseDialog(self, self.phases[index])
        self.wait_window(dialog)
        if dialog.result:
            self.phases[index] = dialog.result
            self._refresh(index)

    def _delete_phase(self) -> None:
        index = self._selected_index()
        if index is not None:
            del self.phases[index]
            self._refresh(min(index, len(self.phases) - 1))

    def _move_phase(self, delta: int) -> None:
        index = self._selected_index()
        target = index + delta if index is not None else None
        if index is None or target is None or not 0 <= target < len(self.phases):
            return
        self.phases[index], self.phases[target] = self.phases[target], self.phases[index]
        self._refresh(target)

    def _accept(self) -> None:
        try:
            unit = Unit(self.name_var.get().strip(), float(self.weight_var.get()), list(self.phases))
            unit.validate()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("单元参数无效", str(exc), parent=self)
            return
        self.result = unit
        self.destroy()


class LslMarker:
    def __init__(self, stream_name: str, source_id: str, status: Callable[[str], None]):
        self.status = status
        self.outlet = None
        self.enabled = False
        if StreamInfo is None:
            self.status("LSL 未安装：实验仍可本地运行，但不会发送 marker")
            return
        try:
            info = StreamInfo(stream_name, "Markers", 1, 0, "string", source_id)
            self.outlet = StreamOutlet(info)
            self.enabled = True
            self.status(f"LSL marker 流已创建：{stream_name}")
        except Exception as exc:  # Hardware/runtime setup must not crash the GUI.
            self.status(f"LSL 初始化失败：{exc}")

    def emit(self, payload: dict[str, Any]) -> float | None:
        if not self.outlet:
            return None
        timestamp = local_clock()
        self.outlet.push_sample([json.dumps(payload, ensure_ascii=False, separators=(",", ":"))], timestamp=timestamp)
        return timestamp


class SessionLog:
    def __init__(self, output_dir: Path, config: ExperimentConfig):
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = output_dir / f"session_{stamp}.csv"
        self.file = self.path.open("w", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(
            self.file,
            fieldnames=(
                "wall_time",
                "lsl_timestamp",
                "actual_elapsed_s",
                "scheduled_elapsed_s",
                "event",
                "trial_index",
                "unit",
                "phase_index",
                "phase",
                "marker",
            ),
        )
        self.writer.writeheader()
        self.file.flush()

    def write(self, **row: Any) -> None:
        self.writer.writerow({key: row.get(key, "") for key in self.writer.fieldnames})
        self.file.flush()

    def close(self) -> None:
        self.file.close()


class VisualRenderer:
    """Small extension point: register another renderer by visual type."""

    def show(self, canvas: tk.Canvas, phase: Phase, width: int, height: int, root: tk.Misc) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass


class TextRenderer(VisualRenderer):
    def show(self, canvas: tk.Canvas, phase: Phase, width: int, height: int, root: tk.Misc) -> None:
        _, value = display_visual(phase)
        canvas.create_text(width // 2, height // 2, text=value or phase.instruction, fill="white", font=("Arial", 42), width=max(300, width - 160))


class BlankRenderer(VisualRenderer):
    def show(self, canvas: tk.Canvas, phase: Phase, width: int, height: int, root: tk.Misc) -> None:
        return


class ImageRenderer(VisualRenderer):
    def show(self, canvas: tk.Canvas, phase: Phase, width: int, height: int, root: tk.Misc) -> None:
        if Image is None:
            raise RuntimeError("图片显示需要安装 Pillow")
        _, path = display_visual(phase)
        image = Image.open(path).convert("RGB")
        image.thumbnail((max(100, width - 120), max(100, height - 180)))
        photo = ImageTk.PhotoImage(image)
        canvas._mi_image = photo
        canvas.create_image(width // 2, height // 2, image=photo)


class VideoRenderer(VisualRenderer):
    def __init__(self) -> None:
        self.cap = None
        self.after_id: str | None = None
        self.canvas: tk.Canvas | None = None
        self.root: tk.Misc | None = None

    def show(self, canvas: tk.Canvas, phase: Phase, width: int, height: int, root: tk.Misc) -> None:
        if cv2 is None or Image is None:
            raise RuntimeError("视频显示需要安装 opencv-python 和 Pillow")
        self.stop()
        _, path = display_visual(phase)
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开视频：{path}")
        self.canvas, self.root = canvas, root
        self._next_frame(width, height)

    def _next_frame(self, width: int, height: int) -> None:
        if not self.cap or not self.canvas or not self.root:
            return
        ok, frame = self.cap.read()
        if not ok:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
        if ok:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame)
            image.thumbnail((max(100, width - 120), max(100, height - 180)))
            photo = ImageTk.PhotoImage(image)
            self.canvas._mi_video_image = photo
            self.canvas.create_image(width // 2, height // 2, image=photo)
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        delay = max(10, min(100, int(1000 / fps)))
        self.after_id = self.root.after(delay, lambda: self._next_frame(width, height))

    def stop(self) -> None:
        if self.root and self.after_id:
            self.root.after_cancel(self.after_id)
        self.after_id = None
        if self.cap:
            self.cap.release()
        self.cap = None


class PresentationWindow:
    def __init__(self, parent: tk.Misc, config: ExperimentConfig, plan: list[Unit], base_dir: Path, on_done: Callable[[Path | None], None]):
        self.parent = parent
        self.config = config
        self.plan = plan
        self.base_dir = base_dir
        self.on_done = on_done
        self.window = tk.Toplevel(parent)
        self.window.title(config.name)
        self.window.attributes("-fullscreen", True)
        self.window.configure(bg="black")
        self.window.protocol("WM_DELETE_WINDOW", self.stop)
        self.window.bind("<Escape>", lambda _event: self.stop())

        self.canvas = tk.Canvas(self.window, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.info = tk.Label(self.window, bg="#111111", fg="#cccccc", font=("Arial", 12), padx=10, pady=5)
        self.info.place(x=12, y=12)
        self.window.update_idletasks()

        self.renderers: dict[str, VisualRenderer] = {
            "text": TextRenderer(),
            "blank": BlankRenderer(),
            "image": ImageRenderer(),
            "video": VideoRenderer(),
        }
        self.marker = LslMarker(config.lsl_stream_name, config.lsl_source_id, self._set_status)
        output_dir = Path(config.output_dir)
        if not output_dir.is_absolute():
            output_dir = base_dir / output_dir
        self.log = SessionLog(output_dir, config)
        self.session_start = time.perf_counter()
        self.current_trial = 0
        self.current_phase = 0
        self.phase_deadline = self.session_start
        self.phase_scheduled_start = 0.0
        self.running = True
        self._emit("experiment/start", scheduled_elapsed_s=0.0)
        self._start_unit()
        self.window.after(10, self._tick)

    def register_renderer(self, visual_type: str, renderer: VisualRenderer) -> None:
        self.renderers[visual_type] = renderer

    def _set_status(self, text: str) -> None:
        self.info.configure(text=text)

    def _resolve_media_path(self, value: str) -> str:
        path = Path(value).expanduser()
        return str(path if path.is_absolute() else self.base_dir / path)

    def _emit(self, event: str, scheduled_elapsed_s: float, phase: Phase | None = None) -> None:
        actual_elapsed = time.perf_counter() - self.session_start
        unit = self.plan[self.current_trial] if self.plan and self.current_trial < len(self.plan) else None
        payload: dict[str, Any] = {
            "event": event,
            "experiment": self.config.name,
            "trial_index": self.current_trial,
            "unit": unit.name if unit else "",
            "phase_index": self.current_phase if phase else "",
            "phase": phase.name if phase else "",
            "marker": phase.marker if phase else "",
            "scheduled_elapsed_s": round(scheduled_elapsed_s, 6),
            "actual_elapsed_s": round(actual_elapsed, 6),
        }
        if phase and phase.marker:
            payload["instruction_marker"] = phase.marker
        lsl_timestamp = self.marker.emit(payload)
        self.log.write(
            wall_time=datetime.now().isoformat(timespec="milliseconds"),
            lsl_timestamp="" if lsl_timestamp is None else f"{lsl_timestamp:.9f}",
            actual_elapsed_s=f"{actual_elapsed:.6f}",
            scheduled_elapsed_s=f"{scheduled_elapsed_s:.6f}",
            event=event,
            trial_index=self.current_trial,
            unit=unit.name if unit else "",
            phase_index=self.current_phase if phase else "",
            phase=phase.name if phase else "",
            marker=phase.marker if phase else "",
        )

    def _start_unit(self) -> None:
        if self.current_trial >= len(self.plan):
            self._finish()
            return
        unit = self.plan[self.current_trial]
        self.current_phase = 0
        self._emit("unit/start", self.current_trial * self.config.unit_duration_s)
        self._start_phase()

    def _start_phase(self) -> None:
        unit = self.plan[self.current_trial]
        phase = unit.phases[self.current_phase]
        self.phase_scheduled_start = self.current_trial * self.config.unit_duration_s + sum(
            item.duration_s for item in unit.phases[: self.current_phase]
        )
        self.phase_deadline = self.session_start + self.phase_scheduled_start + phase.duration_s
        self.canvas.delete("all")
        for renderer in self.renderers.values():
            renderer.stop()
        visual_type, visual_value = display_visual(phase)
        if visual_type in {"image", "video"}:
            phase = Phase(phase.name, phase.duration_s, phase.instruction, {"type": visual_type, "value": self._resolve_media_path(visual_value)}, phase.marker)
        try:
            renderer = self.renderers.get(visual_type)
            if renderer is None:
                raise RuntimeError(f"未注册显示类型：{visual_type}")
            renderer.show(self.canvas, phase, self.window.winfo_width(), self.window.winfo_height(), self.window)
        except Exception as exc:
            self.canvas.create_text(
                self.window.winfo_width() // 2,
                self.window.winfo_height() // 2,
                text=f"媒体显示失败\n{exc}",
                fill="#ff6666",
                font=("Arial", 26),
            )
        self.canvas.update_idletasks()
        self._emit("phase/start", self.phase_scheduled_start, phase)

    def _tick(self) -> None:
        if not self.running:
            return
        now = time.perf_counter()
        while self.running and now >= self.phase_deadline:
            unit = self.plan[self.current_trial]
            phase = unit.phases[self.current_phase]
            self._emit("phase/end", self.phase_scheduled_start + phase.duration_s, phase)
            self.current_phase += 1
            if self.current_phase < len(unit.phases):
                self._start_phase()
            else:
                self._emit("unit/end", (self.current_trial + 1) * self.config.unit_duration_s)
                self.current_trial += 1
                self._start_unit()
            now = time.perf_counter()
        if self.running:
            remaining = max(0.0, self.phase_deadline - now)
            unit = self.plan[self.current_trial]
            phase = unit.phases[self.current_phase]
            self.info.configure(text=f"第 {self.current_trial + 1}/{len(self.plan)} 个单元   |   {phase.name}   |   {remaining:.1f}s   |   Esc 停止")
            self.window.after(10, self._tick)

    def _finish(self) -> None:
        if not self.running:
            return
        self.running = False
        self._emit("experiment/end", self.config.planned_duration_s)
        path = self.log.path
        self._close()
        messagebox.showinfo("实验完成", f"实验已完成。\n日志：{path}", parent=self.parent)
        self.on_done(path)

    def stop(self) -> None:
        if not self.running:
            return
        if not messagebox.askyesno("停止实验", "确定要停止当前实验吗？", parent=self.window):
            return
        self.running = False
        self._emit("experiment/aborted", time.perf_counter() - self.session_start)
        path = self.log.path
        self._close()
        self.on_done(path)

    def _close(self) -> None:
        for renderer in self.renderers.values():
            renderer.stop()
        self.log.close()
        self.window.destroy()


class ExperimentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("运动想象实验设计器")
        self.root.geometry("1040x720")
        self.root.minsize(900, 620)
        self._configure_theme()
        self.config = default_config()
        self.config_path: Path | None = None
        self.base_dir = Path.cwd()
        self._build_ui()
        self._load_form()
        self._refresh_units()

    def _configure_theme(self) -> None:
        self.colors = {
            "bg": "#F4F6FA",
            "card": "#FFFFFF",
            "navy": "#172238",
            "blue": "#356AE6",
            "blue_dark": "#2855C4",
            "text": "#1D2939",
            "muted": "#667085",
            "border": "#D9E1EE",
            "soft_blue": "#EAF0FF",
            "green": "#12B76A",
        }
        self.root.configure(bg=self.colors["bg"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["card"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=self.colors["card"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=self.colors["card"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        style.configure("Card.TLabelframe", background=self.colors["card"], foreground=self.colors["text"], bordercolor=self.colors["border"], relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=self.colors["card"], foreground=self.colors["text"], font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", padding=(8, 6), fieldbackground="#FFFFFF", foreground=self.colors["text"])
        style.configure("TCombobox", padding=(7, 5), fieldbackground="#FFFFFF", foreground=self.colors["text"])
        style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")])
        style.configure("TButton", padding=(12, 7), font=("Segoe UI", 9), foreground=self.colors["text"])
        style.configure("Secondary.TButton", padding=(12, 7), background="#E8EDF6", foreground=self.colors["text"], font=("Segoe UI", 9))
        style.map("Secondary.TButton", background=[("active", "#DCE5F4"), ("pressed", "#D2DDF0")])
        style.configure("Accent.TButton", padding=(18, 9), background=self.colors["blue"], foreground="#FFFFFF", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", self.colors["blue_dark"]), ("pressed", self.colors["blue_dark"])])
        style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=self.colors["text"], rowheight=36, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#EEF2F8", foreground=self.colors["muted"], relief="flat", padding=(8, 8), font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", self.colors["blue"])], foreground=[("selected", "#FFFFFF")])
        style.configure("TNotebook", background=self.colors["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background="#E7ECF5", foreground=self.colors["muted"], padding=(18, 9), font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", self.colors["card"])], foreground=[("selected", self.colors["blue"])])
        style.configure("Status.TLabel", background="#EAF0FF", foreground="#2F559F", padding=(10, 7), font=("Segoe UI", 9))

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = tk.Frame(self.root, bg=self.colors["navy"], height=92)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)
        title_box = tk.Frame(header, bg=self.colors["navy"])
        title_box.grid(row=0, column=0, sticky="nsw", padx=28, pady=16)
        tk.Label(title_box, text="MI", bg=self.colors["blue"], fg="white", font=("Segoe UI", 12, "bold"), width=4, height=2).pack(side="left", padx=(0, 14))
        title_text = tk.Frame(title_box, bg=self.colors["navy"])
        title_text.pack(side="left", anchor="center")
        tk.Label(title_text, text="运动想象实验设计器", bg=self.colors["navy"], fg="white", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(title_text, text="配置刺激序列 · 同步 EEG · 记录实验日志", bg=self.colors["navy"], fg="#AAB7CE", font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        ttk.Button(header, text="▶  开始实验", style="Accent.TButton", command=self._start_experiment).grid(row=0, column=1, padx=28, pady=24)

        toolbar = tk.Frame(self.root, bg=self.colors["bg"])
        toolbar.grid(row=1, column=0, sticky="ew", padx=24, pady=(14, 0))
        ttk.Label(toolbar, text="实验配置", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Label(toolbar, text="  先配置单元实验，再开始呈现", style="Muted.TLabel").pack(side="left", padx=(6, 0))
        actions = ttk.Frame(toolbar)
        actions.pack(side="right")
        for text, command in (("新建", self._new_config), ("打开配置", self._open_config), ("保存", self._save_config), ("另存为", self._save_as)):
            ttk.Button(actions, text=text, style="Secondary.TButton", command=command).pack(side="left", padx=(6, 0))

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=2, column=0, sticky="nsew", padx=24, pady=(12, 16))
        general = ttk.Frame(notebook, style="App.TFrame", padding=16)
        library = ttk.Frame(notebook, style="App.TFrame", padding=16)
        lsl = ttk.Frame(notebook, style="App.TFrame", padding=16)
        notebook.add(general, text="实验设置")
        notebook.add(library, text="单元实验库")
        notebook.add(lsl, text="LSL / 输出")

        self.name_var = tk.StringVar()
        self.total_minutes_var = tk.StringVar()
        self.selection_var = tk.StringVar()
        settings_card = ttk.LabelFrame(general, text="基础设置", style="Card.TLabelframe", padding=18)
        settings_card.pack(anchor="nw", fill="x")
        settings_card.columnconfigure(1, weight=1)
        form = ttk.Frame(settings_card, style="Card.TFrame")
        form.grid(row=0, column=0, sticky="ew")
        ttk.Label(form, text="实验名称", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=7)
        ttk.Entry(form, textvariable=self.name_var, width=44).grid(row=0, column=1, sticky="w", pady=6)
        ttk.Label(form, text="总实验时间（分钟）", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=7)
        ttk.Entry(form, textvariable=self.total_minutes_var, width=12).grid(row=1, column=1, sticky="w", pady=6)
        ttk.Label(form, text="单元抽取方式", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=7)
        ttk.Combobox(form, textvariable=self.selection_var, values=tuple(SELECTION_LABELS.values()), state="readonly", width=26).grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(form, text="按比例模式会先分配配额并打乱顺序；随机模式每次独立抽取。", style="CardMuted.TLabel").grid(row=3, column=1, sticky="w", pady=(2, 0))

        self.summary_var = tk.StringVar()
        summary_card = ttk.LabelFrame(general, text="计划摘要", style="Card.TLabelframe", padding=18)
        summary_card.pack(anchor="nw", fill="x", pady=(14, 0))
        ttk.Label(summary_card, textvariable=self.summary_var, style="Card.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(summary_card, text="当前版本要求各单元总时长相同；总时长不足一个整单元的余数会被忽略。", style="CardMuted.TLabel").pack(anchor="w", pady=(7, 0))

        library.rowconfigure(0, weight=1)
        library.columnconfigure(0, weight=1)
        library_card = ttk.LabelFrame(library, text="可用单元实验", style="Card.TLabelframe", padding=12)
        library_card.grid(row=0, column=0, columnspan=2, sticky="nsew")
        library_card.rowconfigure(0, weight=1)
        library_card.columnconfigure(0, weight=1)
        columns = ("name", "duration", "weight", "phases")
        self.unit_tree = ttk.Treeview(library_card, columns=columns, show="headings", selectmode="browse")
        self.unit_tree.tag_configure("alternate", background="#F8FAFD")
        for column, heading, width in (("name", "名称", 230), ("duration", "单元时长", 130), ("weight", "权重", 100), ("phases", "阶段数", 100)):
            self.unit_tree.heading(column, text=heading)
            self.unit_tree.column(column, width=width, anchor="w")
        self.unit_tree.grid(row=0, column=0, sticky="nsew")
        library_scroll = ttk.Scrollbar(library_card, orient="vertical", command=self.unit_tree.yview)
        library_scroll.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.unit_tree.configure(yscrollcommand=library_scroll.set)
        self.unit_tree.bind("<Double-1>", lambda _event: self._edit_unit())
        unit_buttons = ttk.Frame(library)
        unit_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
        for text, command in (("添加单元", self._add_unit), ("编辑单元", self._edit_unit), ("删除单元", self._delete_unit)):
            ttk.Button(unit_buttons, text=text, style="Secondary.TButton", command=command).pack(side="left", padx=(0, 6))
        ttk.Label(unit_buttons, text="双击表格行也可以编辑", style="Muted.TLabel").pack(side="left", padx=(8, 0))

        self.lsl_name_var = tk.StringVar()
        self.lsl_source_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        lsl_card = ttk.LabelFrame(lsl, text="同步与日志", style="Card.TLabelframe", padding=18)
        lsl_card.pack(anchor="nw", fill="x")
        lsl_form = ttk.Frame(lsl_card, style="Card.TFrame")
        lsl_form.pack(anchor="nw", fill="x")
        for row, (label, variable, width) in enumerate((("LSL stream name", self.lsl_name_var, 44), ("LSL source id", self.lsl_source_var, 44), ("日志目录", self.output_dir_var, 44))):
            ttk.Label(lsl_form, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(lsl_form, textvariable=variable, width=width).grid(row=row, column=1, sticky="w", pady=6)
        ttk.Label(lsl_card, text="发送内容：单通道 string marker，内容为 JSON；详见 README。", style="CardMuted.TLabel").pack(anchor="w", pady=(12, 0))

        self.status_var = tk.StringVar(value="就绪")
        status_bar = tk.Frame(self.root, bg="#EAF0FF", height=34)
        status_bar.grid(row=3, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        tk.Label(status_bar, text="●", bg="#EAF0FF", fg=self.colors["green"], font=("Segoe UI", 10)).pack(side="left", padx=(16, 5))
        ttk.Label(status_bar, textvariable=self.status_var, style="Status.TLabel", anchor="w").pack(side="left", fill="x", expand=True)

    def _load_form(self) -> None:
        self.name_var.set(self.config.name)
        self.total_minutes_var.set(f"{self.config.total_duration_s / 60:g}")
        self.selection_var.set(SELECTION_LABELS.get(self.config.selection_mode, SELECTION_LABELS["weighted"]))
        self.lsl_name_var.set(self.config.lsl_stream_name)
        self.lsl_source_var.set(self.config.lsl_source_id)
        self.output_dir_var.set(self.config.output_dir)
        self._update_summary()

    def _refresh_units(self) -> None:
        for item in self.unit_tree.get_children():
            self.unit_tree.delete(item)
        for index, unit in enumerate(self.config.units):
            tags = ("alternate",) if index % 2 else ()
            self.unit_tree.insert("", "end", iid=str(index), values=(unit.name, format_seconds(unit.duration_s), unit.weight, len(unit.phases)), tags=tags)
        self._update_summary()

    def _update_summary(self) -> None:
        if not hasattr(self, "summary_var"):
            return
        if not self.config.units:
            self.summary_var.set("尚未添加单元实验")
            return
        duration = self.config.unit_duration_s
        if duration:
            count = max(1, int((self.config.total_duration_s / duration) // 1))
            actual = count * duration
            self.summary_var.set(f"单元时长：{format_seconds(duration)}    计划单元数：{count}    实际呈现：{format_seconds(actual)}")

    def _sync_form(self) -> None:
        self.config.name = self.name_var.get().strip()
        self.config.total_duration_s = float(self.total_minutes_var.get()) * 60
        label_to_mode = {label: mode for mode, label in SELECTION_LABELS.items()}
        self.config.selection_mode = label_to_mode[self.selection_var.get()]
        self.config.lsl_stream_name = self.lsl_name_var.get().strip()
        self.config.lsl_source_id = self.lsl_source_var.get().strip()
        self.config.output_dir = self.output_dir_var.get().strip() or "sessions"

    def _new_config(self) -> None:
        self.config = default_config()
        self.config_path = None
        self.base_dir = Path.cwd()
        self._load_form()
        self._refresh_units()

    def _open_config(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            self.config = ExperimentConfig.load(path)
            self.config.validate()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("打开失败", str(exc), parent=self.root)
            return
        self.config_path = Path(path)
        self.base_dir = self.config_path.parent
        self._load_form()
        self._refresh_units()
        self.status_var.set(f"已打开：{path}")

    def _save_config(self) -> None:
        if self.config_path is None:
            self._save_as()
            return
        self._write_config(self.config_path)

    def _save_as(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON 配置", "*.json")])
        if path:
            self.config_path = Path(path)
            self.base_dir = self.config_path.parent
            self._write_config(self.config_path)

    def _write_config(self, path: Path) -> None:
        try:
            self._sync_form()
            self.config.validate()
            self.config.save(path)
            self.status_var.set(f"已保存：{path}")
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)

    def _selected_unit_index(self) -> int | None:
        selection = self.unit_tree.selection()
        return int(selection[0]) if selection else None

    def _add_unit(self) -> None:
        dialog = UnitDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result:
            self.config.units.append(dialog.result)
            self._refresh_units()

    def _edit_unit(self) -> None:
        index = self._selected_unit_index()
        if index is None:
            return
        dialog = UnitDialog(self.root, self.config.units[index])
        self.root.wait_window(dialog)
        if dialog.result:
            self.config.units[index] = dialog.result
            self._refresh_units()

    def _delete_unit(self) -> None:
        index = self._selected_unit_index()
        if index is not None and messagebox.askyesno("删除单元", f"确定删除“{self.config.units[index].name}”吗？", parent=self.root):
            del self.config.units[index]
            self._refresh_units()

    def _start_experiment(self) -> None:
        try:
            self._sync_form()
            self.config.validate()
            plan = self.config.build_plan()
        except (ValueError, KeyError) as exc:
            messagebox.showerror("无法开始实验", str(exc), parent=self.root)
            return
        if self.config.planned_duration_s < self.config.total_duration_s:
            extra = self.config.total_duration_s - self.config.planned_duration_s
            if not messagebox.askyesno("时长提示", f"总时长会剩余 {extra:.2f} 秒未使用，继续吗？", parent=self.root):
                return
        self.root.withdraw()
        PresentationWindow(self.root, self.config, plan, self.base_dir, self._experiment_done)

    def _experiment_done(self, log_path: Path | None) -> None:
        self.root.deiconify()
        if log_path:
            self.status_var.set(f"实验结束，日志：{log_path}")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("clam")
    except tk.TclError:
        pass
    ExperimentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
