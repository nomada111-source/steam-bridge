"""Device picker + start/stop controls + status log."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..app import BridgeApp
from ..hid_device import DeviceInfo


def _decode_path(p: bytes) -> str:
    try:
        return p.decode("ascii", errors="replace")
    except Exception:
        return str(p)


def _slug(s: str) -> str:
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch.lower())
        elif ch in " _-":
            out.append("_")
    return "".join(out) or "capture"


def _dump_frame(label: str, fr: bytes) -> list[str]:
    out = [f"--- {label}  ({len(fr)} bytes) ---"]
    for off in range(0, len(fr), 16):
        chunk = fr[off:off + 16]
        hex_bytes = " ".join(f"{b:02x}" for b in chunk)
        ascii_bytes = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{off:04x}  {hex_bytes:<48}  {ascii_bytes}")
    return out


def _diff_summary(baseline: list[bytes], recent: list[bytes]) -> list[str]:
    """Per-byte report: for each offset, list which values were seen across
    baseline vs recent. Helps spot which byte encodes a button without us
    needing to know which exact frame the press is in.
    """
    out: list[str] = ["offset  baseline_values            recent_values             same?"]
    max_len = max(max(len(b) for b in baseline), max(len(r) for r in recent))
    for off in range(max_len):
        base_vals = sorted({b[off] for b in baseline if off < len(b)})
        rec_vals = sorted({r[off] for r in recent if off < len(r)})
        if base_vals == rec_vals:
            continue  # byte didn't change relative to idle — skip
        bs = " ".join(f"{v:02x}" for v in base_vals[:8])
        rs = " ".join(f"{v:02x}" for v in rec_vals[:8])
        out.append(f"  0x{off:02x}    {bs:<26} {rs:<26} no")
    if len(out) == 1:
        out.append("  (no byte differed — did you press anything before clicking Dump?)")
    return out


class DevicePanel(QWidget):
    profile_changed = Signal(str)

    def __init__(self, app: BridgeApp, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._devices: list[DeviceInfo] = []

        root = QVBoxLayout(self)

        # --- Device group ---
        dev_box = QGroupBox("Steam Controller")
        dev_layout = QVBoxLayout(dev_box)

        row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_devices)
        row.addWidget(QLabel("Device:"))
        row.addWidget(self.device_combo, 1)
        row.addWidget(self.refresh_btn)
        dev_layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Bridge")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        self.wake_btn = QPushButton("Wake / Disable Lizard")
        self.wake_btn.setToolTip(
            "Broadcasts the disable-lizard / enable-raw-input commands to every "
            "Valve HID interface. Use if pressing controller buttons types letters."
        )
        self.wake_btn.clicked.connect(self._on_wake)
        self.scan_btn = QPushButton("Scan interfaces")
        self.scan_btn.setToolTip(
            "Opens each Valve HID interface for ~1 second and reports which "
            "ones stream input. Run with the controller in hand and press "
            "buttons while it runs."
        )
        self.scan_btn.clicked.connect(self._on_scan)
        self.dump_btn = QPushButton("Dump first frames")
        self.dump_btn.setToolTip(
            "Writes the first 12 raw HID frames received since Start to "
            "first_frames.txt. Useful when the parser doesn't recognise "
            "the report format."
        )
        self.dump_btn.clicked.connect(self._on_dump_frames)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.wake_btn)
        btn_row.addWidget(self.scan_btn)
        btn_row.addWidget(self.dump_btn)
        btn_row.addStretch(1)
        dev_layout.addLayout(btn_row)

        self.frame_label = QLabel("Frames: idle")
        self.frame_label.setStyleSheet("color: #888;")
        dev_layout.addWidget(self.frame_label)

        # D-pad keyboard fallback toggle. The new Steam Controller often
        # reverts to emitting D-pad as keyboard arrows even after we send
        # the disable-lizard command — this hooks Windows arrow keys and
        # forwards them to the virtual Xbox D-pad instead.
        self.dpad_kbd_chk = QCheckBox(
            "Capture D-pad from keyboard arrows (suppresses arrows to other apps)"
        )
        self.dpad_kbd_chk.setChecked(True)
        self.dpad_kbd_chk.setToolTip(
            "The new Steam Controller often emits the D-pad as keyboard "
            "arrow keys regardless of HID mode. When this is ON the bridge "
            "intercepts arrow-key presses and forwards them to the virtual "
            "Xbox D-pad, AND blocks them from reaching other windows. "
            "Turn off if you need arrow keys for other apps while the bridge runs."
        )
        self.dpad_kbd_chk.toggled.connect(self._app.set_dpad_keyboard_capture)
        dev_layout.addWidget(self.dpad_kbd_chk)

        # Inline capture row — no popup, so a controller-emitted Enter
        # keystroke can't dismiss it. Type the label, then hold the button
        # on the controller, then click Capture.
        cap_row = QHBoxLayout()
        cap_row.addWidget(QLabel("Capture label:"))
        self.capture_label_edit = QLineEdit()
        self.capture_label_edit.setPlaceholderText("e.g. A  /  B  /  RT  /  LX+")
        self.capture_label_edit.setMaximumWidth(220)
        self.capture_btn = QPushButton("Capture now (button held)")
        self.capture_btn.setToolTip(
            "Steps: (1) type a label, (2) press and HOLD the button on the "
            "controller, (3) click this with the other hand. Captures ~30 "
            "frames immediately and diffs them vs the idle baseline."
        )
        self.capture_btn.clicked.connect(self._on_capture_pressed)
        self.capture_delayed_btn = QPushButton("Capture in 3s")
        self.capture_delayed_btn.setToolTip(
            "Same as Capture now, but with a 3-second countdown. Use this "
            "for buttons that send keyboard events (D-pad arrow keys, etc.) "
            "and would steal focus from the app. Click this, then immediately "
            "press and hold the button — the snapshot fires automatically."
        )
        self.capture_delayed_btn.clicked.connect(self._on_capture_delayed)
        cap_row.addWidget(self.capture_label_edit)
        cap_row.addWidget(self.capture_btn)
        cap_row.addWidget(self.capture_delayed_btn)
        cap_row.addStretch(1)
        dev_layout.addLayout(cap_row)

        # --- Profile group ---
        prof_box = QGroupBox("Profile")
        prof_layout = QHBoxLayout(prof_box)
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.load_profile_btn = QPushButton("Load")
        self.save_profile_btn = QPushButton("Save")
        self.load_profile_btn.clicked.connect(self._on_load_profile)
        self.save_profile_btn.clicked.connect(self._on_save_profile)
        prof_layout.addWidget(QLabel("Active:"))
        prof_layout.addWidget(self.profile_combo, 1)
        prof_layout.addWidget(self.load_profile_btn)
        prof_layout.addWidget(self.save_profile_btn)

        # --- Status log ---
        log_box = QGroupBox("Status")
        log_layout = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        log_layout.addWidget(self.log)

        root.addWidget(dev_box)
        root.addWidget(prof_box)
        root.addWidget(log_box, 1)

        # Hook BridgeApp status callbacks.
        self._app.on_status(self.append_log)

        # Initial population.
        self.refresh_devices()
        self.refresh_profiles()
        self.append_log(self._app.gamepad.status)

        # Live frame counter — refreshed once per second while bridging so
        # the user can immediately tell whether HID data is flowing.
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(1000)
        self._frame_timer.timeout.connect(self._refresh_frame_label)
        self._frame_timer.start()
        self._last_total = 0

    def _refresh_frame_label(self) -> None:
        if not self._app.is_running():
            self.frame_label.setText("Frames: idle")
            self.frame_label.setStyleSheet("color: #888;")
            self._last_total = 0
            return
        total = self._app.frames_total
        decoded = self._app.frames_decoded
        rejected = self._app.frames_rejected
        rate = total - self._last_total
        self._last_total = total
        if total == 0:
            txt = ("Frames: 0 — no HID data yet. Press a button on the "
                   "controller. If this stays at 0 the controller is asleep "
                   "or stuck in lizard mode.")
            color = "#e07b3c"
        elif decoded == 0:
            txt = (f"Frames: {total} received, 0 decoded ({rate}/s). "
                   "Wrong interface or wrong report layout — try a different "
                   "endpoint from the dropdown.")
            color = "#e07b3c"
        else:
            txt = f"Frames: {decoded} decoded / {total} received ({rate}/s, {rejected} rejected)"
            color = "#5cb85c"
        self.frame_label.setText(txt)
        self.frame_label.setStyleSheet(f"color: {color};")

    # ---- public ----

    def append_log(self, msg: str) -> None:
        # Called from BridgeApp threads; use invokeMethod-safe path. Qt's
        # QPlainTextEdit.appendPlainText is thread-safe when called from
        # any thread because the underlying signal is queued via the GUI
        # event loop — but to be safe we still keep this lightweight.
        self.log.appendPlainText(msg)

    def refresh_devices(self) -> None:
        from .. import settings

        all_devices = self._app.list_devices()
        # Drop the keyboard-usage collections — Windows blocks raw HID access
        # to those for security reasons, so they're never the right pick.
        useful = [
            d for d in all_devices
            if not (d.usage_page == 0x0001 and d.usage == 0x0006)
        ]
        self._devices = useful or all_devices
        self.device_combo.clear()
        if not self._devices:
            self.device_combo.addItem("(no Valve HID devices found)")
            self.device_combo.setEnabled(False)
            self.start_btn.setEnabled(False)
            return
        self.device_combo.setEnabled(True)
        self.start_btn.setEnabled(True)

        # Pick order: 1) last-known-good path saved by Scan, 2) heuristic.
        saved_path = settings.get("last_good_device_path")
        autopick = self._app.autopick_device()
        autopick_idx = 0
        for i, d in enumerate(self._devices):
            self.device_combo.addItem(d.label, userData=i)
            if saved_path and _decode_path(d.path) == saved_path:
                autopick_idx = i
                saved_path = None  # consumed; don't override on later matches
            elif autopick is not None and d.path == autopick.path and saved_path is None:
                autopick_idx = i
        self.device_combo.setCurrentIndex(autopick_idx)

    def refresh_profiles(self) -> None:
        from ..profile import list_profiles

        names = list_profiles()
        if "default" not in names:
            names = ["default"] + names
        active = self._app.profile.name
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        if active in names:
            self.profile_combo.setCurrentText(active)
        else:
            self.profile_combo.setCurrentText("default")

    # ---- slots ----

    def _on_start(self) -> None:
        from .. import settings
        # If we've never confirmed a good interface, scan first so the
        # user doesn't have to think about it.
        if not settings.get("last_good_device_path"):
            self.append_log(
                "No remembered interface yet — running a quick scan first. "
                "Press buttons on the controller during the scan."
            )
            self._on_scan()
        idx = self.device_combo.currentData()
        if idx is None or not isinstance(idx, int):
            return
        device = self._devices[idx]
        self._app.start(device)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.refresh_btn.setEnabled(False)
        self.device_combo.setEnabled(False)

    def _on_stop(self) -> None:
        self._app.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.refresh_btn.setEnabled(True)
        self.device_combo.setEnabled(True)

    def _on_capture_delayed(self) -> None:
        """Countdown then capture. Use for buttons that send keyboard events
        (D-pad arrow keys, etc.) where focus theft would block a normal
        capture-on-click flow.
        """
        from PySide6.QtCore import QTimer

        if not self._app.is_running():
            self.append_log("Bridge not running — press Start first.")
            return
        label = self.capture_label_edit.text().strip()
        if not label:
            self.append_log("Type a label first (e.g. 'DPAD_UP').")
            return

        self.append_log(f"Capturing '{label}' in 3 seconds — hold the button NOW.")
        self.capture_delayed_btn.setEnabled(False)

        def step(n: int) -> None:
            if n > 0:
                self.append_log(f"  {n}...")
                QTimer.singleShot(1000, lambda: step(n - 1))
            else:
                self.append_log("  GO — capturing.")
                self._on_capture_pressed()
                self.capture_delayed_btn.setEnabled(True)

        QTimer.singleShot(1000, lambda: step(2))

    def _on_capture_pressed(self) -> None:
        """Snapshot frames *now*, while the user is holding a button.

        Workflow (no popup so a controller-emitted Enter can't dismiss it):
          1. User types a label in the Capture row.
          2. User holds the button on the controller.
          3. User clicks Capture with the other hand.
        We snapshot the rolling buffer immediately — the latest frames
        contain the button-down state.
        """
        from pathlib import Path

        if not self._app.is_running():
            self.append_log("Bridge not running — press Start first.")
            return

        label = self.capture_label_edit.text().strip()
        if not label:
            self.append_log("Type a label in the Capture field first (e.g. 'A').")
            return

        # Snapshot the rolling buffer right now — these are the most recent
        # 120 frames (~0.5 s) and the user's button is held throughout.
        held_frames = self._app.recent_frames[-30:]
        baseline = list(self._app.baseline_frames)

        if not held_frames or not baseline:
            self.append_log("Not enough frames captured. Try again after pressing Start.")
            return

        out_path = Path(__file__).resolve().parent.parent.parent / f"capture_{_slug(label)}.txt"
        lines = [
            f"# capture: '{label}'",
            f"# baseline frames: {len(baseline)} (captured immediately after Start)",
            f"# held frames: {len(held_frames)} (most recent — should be while pressed)",
            "",
        ]
        # Per-byte: distinguish bytes that CHANGED (button-like) from those
        # that just drift (IMU). Mark a byte as a button candidate when:
        #   - baseline set ∩ held set is empty (cleanly disjoint), OR
        #   - held set adds a value that's never in baseline.
        lines.append("=== byte-level diff (offsets where values changed) ===")
        lines.append("offset  baseline range            held range              classification")
        max_len = max(max(len(b) for b in baseline), max(len(h) for h in held_frames))
        candidates: list[tuple[int, int]] = []  # (offset, sample_value)
        for off in range(max_len):
            base = sorted({b[off] for b in baseline if off < len(b)})
            held = sorted({h[off] for h in held_frames if off < len(h)})
            if base == held:
                continue
            disjoint = not (set(base) & set(held))
            kind = "BUTTON?" if disjoint else "drift?"
            bs = " ".join(f"{v:02x}" for v in base[:8])
            hs = " ".join(f"{v:02x}" for v in held[:8])
            lines.append(f"  0x{off:02x}    {bs:<26} {hs:<26} {kind}")
            if disjoint:
                candidates.append((off, held[0]))

        # Bit-level analysis on candidates: which bit flipped between
        # baseline and held? Useful for digital buttons.
        if candidates:
            lines += ["", "=== bit-level for BUTTON? candidates ==="]
            for off, _ in candidates:
                base_or = 0
                for b in baseline:
                    if off < len(b):
                        base_or |= b[off]
                held_or = 0
                for h in held_frames:
                    if off < len(h):
                        held_or |= h[off]
                # bits set in held that are NEVER set in baseline
                exclusive = held_or & ~base_or
                bits = [i for i in range(8) if exclusive & (1 << i)]
                lines.append(
                    f"  byte 0x{off:02x}: baseline_or=0x{base_or:02x}  "
                    f"held_or=0x{held_or:02x}  new_bits={bits}"
                )

        # Sample frames for context.
        lines += ["", "=== one baseline frame ==="]
        lines.extend(_dump_frame("baseline[0]", baseline[0]))
        lines += ["", "=== one held frame ==="]
        lines.extend(_dump_frame(f"held[{len(held_frames)-1}] (latest)", held_frames[-1]))

        out_path.write_text("\n".join(lines), encoding="utf-8")
        self.append_log(f"'{label}' capture saved to {out_path}")
        if candidates:
            self.append_log(
                f"BUTTON? candidates: " +
                ", ".join(f"0x{o:02x}" for o, _ in candidates)
            )
        else:
            self.append_log("No cleanly-disjoint byte found — only drifty changes "
                            "(IMU). Was the button actually being held when you "
                            "clicked? Try again, hold it firmly through the click.")

    def _on_dump_frames(self) -> None:
        """Write a baseline (idle) + recent (button-down) frame dump and a
        per-byte diff between them, so we can identify which bytes encode
        what. The user is expected to:
          1. Start the bridge with hands off the controller (baseline captured).
          2. Press / hold the button(s) they want to identify.
          3. Click 'Dump frames' — the rolling buffer has the latest ~120
             frames including the button-down state.
        """
        from pathlib import Path
        baseline = list(self._app.baseline_frames)
        recent = self._app.recent_frames
        if not recent:
            self.append_log("No frames captured yet — press Start first.")
            return
        out = Path(__file__).resolve().parent.parent.parent / "frames_dump.txt"
        lines = [
            f"# decoded={self._app.frames_decoded} / total={self._app.frames_total} "
            f"({self._app.frames_rejected} rejected)",
            f"# baseline (first frames after Start): {len(baseline)}",
            f"# recent (rolling buffer, latest first): {len(recent)}",
            "",
            "=== BASELINE (idle, first 12 frames after Start) ===",
        ]
        for i, fr in enumerate(baseline):
            lines.extend(_dump_frame(f"baseline[{i}]", fr))
        lines += ["", "=== RECENT (last frames captured — should include button presses) ==="]
        # show last 12 of the rolling buffer
        for i, fr in enumerate(recent[-12:]):
            lines.extend(_dump_frame(f"recent[-{12 - i}]", fr))
        # Diff: bytes that differ between any baseline and any recent frame
        if baseline and recent:
            lines += ["", "=== DIFF (bytes that change between baseline and recent) ==="]
            lines.extend(_diff_summary(baseline, recent[-12:]))
        out.write_text("\n".join(lines), encoding="utf-8")
        self.append_log(f"Wrote {len(baseline)} baseline + {min(12, len(recent))} recent frames to {out}")

    def _on_wake(self) -> None:
        from ..hid_device import wake_all_valve_interfaces
        try:
            stats = wake_all_valve_interfaces(self._devices)
            self.append_log(
                f"Wake sent: opened {stats['opened']} interface(s), "
                f"{stats['commands_sent']} commands, {stats['errors']} errors."
            )
        except Exception as e:
            self.append_log(f"Wake failed: {e}")

    def _on_scan(self) -> None:
        # Open each interface for a short window and count frames. UI freezes
        # briefly — fine for a diagnostic.
        import hid
        import time
        self.append_log("Scanning interfaces — press buttons on the controller now...")
        results: list[tuple[int, int, str]] = []  # (frames, idx, label)
        for i, d in enumerate(self._devices):
            try:
                dev = hid.device()
                dev.open_path(d.path)
                dev.set_nonblocking(True)
                # Wake while we're here.
                for cmd in ([0x81], [0x87, 0x03, 0x08, 0x07, 0x00]):
                    buf = bytes([0x00] + cmd + [0x00] * (64 - len(cmd)))
                    try: dev.send_feature_report(buf)
                    except Exception: pass
                end = time.monotonic() + 0.8
                n = 0
                while time.monotonic() < end:
                    chunk = dev.read(128, 50)
                    if chunk:
                        n += 1
                dev.close()
                results.append((n, i, d.label))
                self.append_log(f"  [{i}] frames={n:4d}  {d.label}")
            except Exception as e:
                self.append_log(f"  [{i}] error: {e}  {d.label}")
        if results:
            best = max(results, key=lambda r: r[0])
            if best[0] > 0:
                from .. import settings
                best_dev = self._devices[best[1]]
                settings.set_("last_good_device_path", _decode_path(best_dev.path))
                self.append_log(
                    f"Best: [{best[1]}] with {best[0]} frames — auto-selecting "
                    f"and saving as default for next launch."
                )
                self.device_combo.setCurrentIndex(best[1])
            else:
                self.append_log("No interface received frames. Controller may be off, asleep, "
                                "or stuck in lizard mode. Hit 'Wake / Disable Lizard' then try again.")

    def _on_load_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            return
        try:
            self._app.load_profile(name)
            self.profile_changed.emit(name)
        except FileNotFoundError:
            self.append_log(f"No such profile: {name}")

    def _on_save_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            return
        prof = self._app.profile
        prof.name = name
        self._app.save_current_profile()
        self.refresh_profiles()
        self.append_log(f"Saved profile: {name}")
