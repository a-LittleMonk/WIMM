import os
import cv2
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QFileDialog, QProgressBar, QMessageBox, QCheckBox, QApplication,
)
from PyQt5.QtCore import Qt
from tracking.tracker import TrackerThread
from analysis.open_field import compute_metrics
from export.excel_export import export_results


VIDEO_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv")


class BatchDialog(QDialog):
    """Run current Open-Field settings on multiple videos sequentially."""

    def __init__(self, of_tab, parent=None):
        super().__init__(parent)
        self.of_tab = of_tab
        self.setWindowTitle("Batch Processing")
        self.resize(680, 520)

        v = QVBoxLayout(self)
        info = QLabel(
            "Apply CURRENT Open-Field settings (zones, calibration, model, sliders, "
            "tuning, threshold, trim, bins) to multiple videos. Each video gets its "
            "own xlsx + CSV files in the output folder. Zone shape is preserved as "
            "normalized coordinates so it adapts to each video's resolution."
        )
        info.setWordWrap(True)
        v.addWidget(info)

        self.list_videos = QListWidget()
        self.list_videos.setSelectionMode(QListWidget.ExtendedSelection)
        v.addWidget(self.list_videos, 1)

        list_btns = QHBoxLayout()
        b_add = QPushButton("Add videos…")
        b_add.clicked.connect(self._add_videos)
        b_remove = QPushButton("Remove selected")
        b_remove.clicked.connect(self._remove_selected)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self.list_videos.clear)
        list_btns.addWidget(b_add)
        list_btns.addWidget(b_remove)
        list_btns.addWidget(b_clear)
        list_btns.addStretch()
        v.addLayout(list_btns)

        self.chk_use_filename_id = QCheckBox(
            "Use video filename as Animal ID (overrides metadata field)"
        )
        self.chk_use_filename_id.setChecked(True)
        v.addWidget(self.chk_use_filename_id)

        self.progress_overall = QProgressBar()
        self.progress_overall.setVisible(False)
        v.addWidget(self.progress_overall)
        self.progress_video = QProgressBar()
        self.progress_video.setVisible(False)
        v.addWidget(self.progress_video)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#555; font-size:11px;")
        self.lbl_status.setWordWrap(True)
        v.addWidget(self.lbl_status)

        ctl = QHBoxLayout()
        self.btn_run = QPushButton("Run Batch")
        self.btn_run.setFixedHeight(30)
        self.btn_run.clicked.connect(self._run)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setFixedHeight(30)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedHeight(30)
        self.btn_close.clicked.connect(self.reject)
        ctl.addStretch()
        ctl.addWidget(self.btn_run)
        ctl.addWidget(self.btn_stop)
        ctl.addWidget(self.btn_close)
        v.addLayout(ctl)

        self._stop = False

    def _add_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select videos", "",
            "Videos (*.mp4 *.avi *.mov *.mkv *.wmv *.flv);;All files (*)"
        )
        for p in paths:
            if p.lower().endswith(VIDEO_EXTS):
                self.list_videos.addItem(p)

    def _remove_selected(self):
        for it in self.list_videos.selectedItems():
            self.list_videos.takeItem(self.list_videos.row(it))

    def _on_stop(self):
        self._stop = True

    def _run(self):
        n = self.list_videos.count()
        if n == 0:
            QMessageBox.warning(self, "Empty", "Add at least one video.")
            return
        out_folder = self.of_tab.config.get("output_folder")
        if not out_folder:
            out_folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if not out_folder:
                return

        of = self.of_tab
        if not of.zone_drawer.arena:
            if QMessageBox.question(
                self, "No arena",
                "No arena drawn in current settings. Continue anyway (no zone metrics)?",
                QMessageBox.Yes | QMessageBox.No,
            ) != QMessageBox.Yes:
                return

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_overall.setVisible(True)
        self.progress_overall.setRange(0, n)
        self.progress_video.setVisible(True)
        self.progress_video.setRange(0, 100)
        self._stop = False

        meta_template = of._metadata()
        for i in range(n):
            if self._stop:
                break
            path = self.list_videos.item(i).text()
            name = os.path.splitext(os.path.basename(path))[0]
            self.lbl_status.setText(f"[{i + 1}/{n}] {name} — tracking…")
            self.progress_overall.setValue(i)
            self.progress_video.setValue(0)
            QApplication.processEvents()
            try:
                self._process_one(path, name, out_folder, meta_template)
                self.lbl_status.setText(f"[{i + 1}/{n}] {name} — done.")
            except Exception as e:
                self.lbl_status.setText(f"[{i + 1}/{n}] {name} — FAILED: {e}")
            self.progress_overall.setValue(i + 1)
            QApplication.processEvents()

        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_video.setVisible(False)
        if self._stop:
            self.lbl_status.setText("Batch stopped by user.")
        else:
            self.lbl_status.setText("Batch complete.")

    def _arena_for_video(self, vw, vh):
        of = self.of_tab
        if of.zone_drawer.arena:
            return [(int(nx * vw), int(ny * vh)) for nx, ny in of.zone_drawer.arena]
        return None

    def _center_for_video(self, vw, vh):
        of = self.of_tab
        if of.zone_drawer.center_zone:
            return [(int(nx * vw), int(ny * vh)) for nx, ny in of.zone_drawer.center_zone]
        return None

    def _px_per_cm_for_video(self, vw, vh):
        of = self.of_tab
        zd = of.zone_drawer
        if not zd.calib_p1 or not zd.calib_p2 or of.spin_cm.value() <= 0:
            return None
        p1 = (zd.calib_p1[0] * vw, zd.calib_p1[1] * vh)
        p2 = (zd.calib_p2[0] * vw, zd.calib_p2[1] * vh)
        dist_px = ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5
        return dist_px / of.spin_cm.value() if dist_px > 0 else None

    def _process_one(self, path, name, out_folder, meta_template):
        of = self.of_tab
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise RuntimeError("Cannot open video")
        vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        auto_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.release()

        arena_px = self._arena_for_video(vw, vh)
        center_px = self._center_for_video(vw, vh)
        px_per_cm = self._px_per_cm_for_video(vw, vh)

        captured = []
        thread = TrackerThread(
            video_path=path,
            arena=arena_px,
            threshold=of.spin_threshold.value(),
            brightness=of.slider_brightness.value(),
            contrast=of.slider_contrast.value() / 100.0,
            blur=of.slider_blur.value(),
            gamma=of.slider_gamma.value() / 100.0,
            sharpen=of.slider_sharpen.value(),
            clahe_clip=of.spin_clahe.value(),
            model=of.combo_model.currentData(),
            exclusion_mask=of.zone_drawer.get_exclusion_mask(),
            body_style=of.combo_body_style.currentData(),
            max_blob_pct=of.spin_max_blob.value(),
            proc_scale=of.combo_proc_scale.currentData(),
            colors={
                "body": of._bgr("body"),
                "nose": of._bgr("nose"),
                "tail": of._bgr("tail"),
            },
            homography=None,
            warp_size=None,
            model_params=dict(of._model_params[of.combo_model.currentData()]),
            post_params=dict(of._post_params),
            fps_override=of._fps_override(),
            trim_start_s=of._trim_start_s(),
            trim_duration_s=of._trim_duration_s(),
            smooth_window=int(of.spin_smooth_window.value()) if hasattr(of, "spin_smooth_window") else 3,
        )
        thread.finished_tracking.connect(lambda r: captured.append(r))
        thread.progress.connect(lambda p: (self.progress_video.setValue(p),
                                           QApplication.processEvents()))
        # Synchronous run (current thread)
        thread.run()
        results = captured[0] if captured else []
        if not results:
            raise RuntimeError("No tracking results")

        fps = of._fps_override() or auto_fps
        metrics, raw_df, bin_df = compute_metrics(
            results=results, arena=arena_px, center_zone=center_px,
            px_per_cm=px_per_cm, fps=fps,
            movement_threshold=of._movement_threshold(),
            bin_size_s=of._bin_size_s(),
            zone_mode=of.zone_drawer.zone_mode if hasattr(of, "zone_drawer") else "center_zone",
            trim_start_s=of._trim_start_s(),
        )

        meta = dict(meta_template)
        if self.chk_use_filename_id.isChecked():
            meta["Animal ID"] = name

        out_path = os.path.join(out_folder, f"{name}_open_field.xlsx")
        export_results(
            metrics=metrics, raw_df=raw_df, output_path=out_path,
            video_name=name, arena=arena_px, video_size=(vw, vh),
            graph_images=None, bin_df=bin_df, metadata=meta, write_csv=True,
            video_config=of.snapshot_settings(),
        )
