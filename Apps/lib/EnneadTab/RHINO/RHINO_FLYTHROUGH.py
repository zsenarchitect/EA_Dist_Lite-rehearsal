# -*- coding: utf-8 -*-
"""Rhino fly-through content pipeline (senzhang-todo #452).

Locks a camera path from the live Rhino 3D viewport, exports keyframe stills
for human approval, then renders a dense image set + optional video. Job
progress and failures are written to a monitor log under Dump/FlyThrough/.

IRONPYTHON 2.7 -- no f-strings, no type hints, no pathlib.

How to run from Rhino
---------------------
1. Open a Perspective (or other) viewport and frame the start of the shot.
2. Render tab -> FlyThrough (or alias ``FlyThrough`` / ``EA_FlyThrough``).
3. Choose **Lock keyframe** repeatedly as you orbit/walk the camera.
   Optionally **Import named views** to pull existing Named Views into the path.
4. Choose **Export keyframe stills** and review the stills folder before paying
   for a full render.
5. Choose **Render final video + images** to sample the path, write frames,
   copy an image set, and attempt ffmpeg mp4 encode when available.
6. Watch Dump/FlyThrough/<job_id>/monitor.log and job_status.json for progress.

This lives in EnneadTab-OS (Rhino), not RenderPolisher. RenderPolisher is the
AI-from-stills / Veo path; this pipeline is precise operator-locked motion.
"""

from __future__ import print_function

import json
import os
import shutil
import time
import traceback

try:
    import subprocess
except Exception:
    subprocess = None

try:
    from EnneadTab import ENVIRONMENT
    from EnneadTab import FOLDER
    from EnneadTab import NOTIFICATION
    from EnneadTab import UI
except Exception:
    ENVIRONMENT = None
    FOLDER = None
    NOTIFICATION = None
    UI = None

# Rhino / .NET are optional: this module's pure path/monitor helpers must import
# under CPython CI. Viewport I/O goes through _require_rhino() only.
try:
    import rhinoscriptsyntax as rs  # pyright: ignore
    import scriptcontext as sc  # pyright: ignore
    import Rhino  # pyright: ignore
    import System  # pyright: ignore
    _RHINO_OK = True
except Exception:
    rs = None
    sc = None
    Rhino = None
    System = None
    _RHINO_OK = False

try:
    from System.Diagnostics import Process, ProcessStartInfo  # pyright: ignore
    _NET_PROCESS_OK = True
except Exception:
    Process = None
    ProcessStartInfo = None
    _NET_PROCESS_OK = False

PATH_VERSION = 1
SUBDIR = "FlyThrough"
NAMED_VIEW_PREFIX = "EA_FT_"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 24
DEFAULT_DURATION_SEC = 8.0
DEFAULT_IMAGE_SET_COUNT = 12


# ---------------------------------------------------------------------------
# Pure math / path model (CPython + IronPython safe)
# ---------------------------------------------------------------------------

def _as_list3(value):
    if value is None:
        return [0.0, 0.0, 0.0]
    return [float(value[0]), float(value[1]), float(value[2])]


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_vec(a, b, t):
    a = _as_list3(a)
    b = _as_list3(b)
    return [
        lerp(a[0], b[0], t),
        lerp(a[1], b[1], t),
        lerp(a[2], b[2], t),
    ]


def _vec_len(v):
    return (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5


def _normalize(v, fallback=None):
    length = _vec_len(v)
    if length < 1e-9:
        if fallback is None:
            return [0.0, 0.0, 1.0]
        return _as_list3(fallback)
    return [v[0] / length, v[1] / length, v[2] / length]


def lerp_unit_vec(a, b, t):
    """Lerp then renormalize. Good enough for camera-up between nearby keyframes."""
    mixed = lerp_vec(a, b, t)
    return _normalize(mixed, fallback=a)


def empty_path(settings=None):
    base = {
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
        "fps": DEFAULT_FPS,
        "duration_sec": DEFAULT_DURATION_SEC,
        "format": "jpg",
        "image_set_count": DEFAULT_IMAGE_SET_COUNT,
    }
    if settings:
        base.update(settings)
    return {
        "version": PATH_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keyframes": [],
        "settings": base,
    }


def make_keyframe(camera, target, lens=50.0, up=None, name=None, source="viewport"):
    index_hint = name or "kf"
    return {
        "name": index_hint,
        "camera": _as_list3(camera),
        "target": _as_list3(target),
        "lens": float(lens) if lens is not None else 50.0,
        "up": _as_list3(up) if up is not None else [0.0, 0.0, 1.0],
        "source": source,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def append_keyframe(path_data, keyframe):
    if path_data is None:
        path_data = empty_path()
    kfs = path_data.setdefault("keyframes", [])
    name = keyframe.get("name") or "kf"
    if not name.startswith(NAMED_VIEW_PREFIX):
        name = "{}{:03d}".format(NAMED_VIEW_PREFIX, len(kfs) + 1)
        keyframe = dict(keyframe)
        keyframe["name"] = name
    kfs.append(keyframe)
    path_data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return path_data, keyframe


def interpolate_pose(kf_a, kf_b, t):
    t = max(0.0, min(1.0, float(t)))
    return {
        "camera": lerp_vec(kf_a["camera"], kf_b["camera"], t),
        "target": lerp_vec(kf_a["target"], kf_b["target"], t),
        "lens": lerp(float(kf_a.get("lens", 50.0)), float(kf_b.get("lens", 50.0)), t),
        "up": lerp_unit_vec(kf_a.get("up"), kf_b.get("up"), t),
    }


def sample_path(path_data, frame_count=None):
    """Return evenly spaced poses along the locked keyframe path.

    With N keyframes and F frames, frame 0 is keyframe 0 and frame F-1 is
    keyframe N-1. Segments between consecutive keyframes get equal frame budget.
    """
    kfs = (path_data or {}).get("keyframes") or []
    if not kfs:
        return []
    if len(kfs) == 1:
        pose = {
            "camera": _as_list3(kfs[0]["camera"]),
            "target": _as_list3(kfs[0]["target"]),
            "lens": float(kfs[0].get("lens", 50.0)),
            "up": _as_list3(kfs[0].get("up")),
            "frame_index": 0,
            "keyframe_span": [0, 0],
            "t": 0.0,
        }
        return [pose]

    settings = path_data.get("settings") or {}
    if frame_count is None:
        fps = max(1, int(settings.get("fps", DEFAULT_FPS)))
        duration = float(settings.get("duration_sec", DEFAULT_DURATION_SEC))
        frame_count = max(len(kfs), int(round(fps * duration)))
    frame_count = max(2, int(frame_count))

    poses = []
    segment_count = len(kfs) - 1
    for i in range(frame_count):
        # Map frame index onto continuous keyframe parameter [0, segment_count]
        u = (float(i) / float(frame_count - 1)) * float(segment_count)
        seg = int(u)
        if seg >= segment_count:
            seg = segment_count - 1
            t = 1.0
        else:
            t = u - float(seg)
        pose = interpolate_pose(kfs[seg], kfs[seg + 1], t)
        pose["frame_index"] = i
        pose["keyframe_span"] = [seg, seg + 1]
        pose["t"] = t
        poses.append(pose)
    return poses


def pick_image_set_indices(total_frames, count):
    """Evenly spaced indices for the approval/image-set deliverable."""
    total_frames = int(total_frames)
    count = int(count)
    if total_frames <= 0:
        return []
    if count <= 1:
        return [0]
    if count >= total_frames:
        return list(range(total_frames))
    out = []
    for i in range(count):
        idx = int(round(float(i) * float(total_frames - 1) / float(count - 1)))
        if idx not in out:
            out.append(idx)
    return out


def path_to_json(path_data):
    return json.dumps(path_data, indent=2, sort_keys=True)


def path_from_json(text):
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("path json must be an object")
    data.setdefault("version", PATH_VERSION)
    data.setdefault("keyframes", [])
    data.setdefault("settings", empty_path()["settings"])
    return data


# ---------------------------------------------------------------------------
# Monitor log (Dump/FlyThrough/<job_id>/)
# ---------------------------------------------------------------------------

class MonitorLog(object):
    """Append-only monitor.log + job_status.json for long fly-through jobs.

    Mirrors the RevitSlave dual status/log idea and feeds UI.ProgressBarManager
    when a capable NotificationHost is present.
    """

    def __init__(self, job_dir, job_id):
        self.job_dir = job_dir
        self.job_id = job_id
        self.log_path = os.path.join(job_dir, "monitor.log")
        self.status_path = os.path.join(job_dir, "job_status.json")
        self._ensure_dir(job_dir)
        self._status = {
            "job_id": job_id,
            "status": "started",
            "stage": "init",
            "progress": 0.0,
            "message": "",
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "errors": [],
            "outputs": {},
        }
        self._write_status()
        self.log("JOB START {}".format(job_id))

    @staticmethod
    def _ensure_dir(path):
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except Exception:
                pass

    def log(self, message, level="INFO"):
        line = "[{}] [{}] {}\n".format(
            time.strftime("%Y-%m-%d %H:%M:%S"), level, message)
        try:
            handle = open(self.log_path, "a")
            try:
                handle.write(line)
            finally:
                handle.close()
        except Exception:
            pass
        try:
            print(line.rstrip())
        except Exception:
            pass

    def _write_status(self):
        self._status["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            handle = open(self.status_path, "w")
            try:
                json.dump(self._status, handle, indent=2, sort_keys=True)
            finally:
                handle.close()
        except Exception:
            pass

    def set_stage(self, stage, message="", progress=None):
        self._status["stage"] = stage
        self._status["status"] = "running"
        if message:
            self._status["message"] = message
        if progress is not None:
            self._status["progress"] = float(progress)
        self._write_status()
        self.log("{} | {}".format(stage, message or ""))

    def set_progress(self, progress, message=None):
        self._status["progress"] = float(progress)
        if message is not None:
            self._status["message"] = message
        self._write_status()

    def add_output(self, key, value):
        self._status.setdefault("outputs", {})[key] = value
        self._write_status()

    def fail(self, message):
        self._status["status"] = "failed"
        self._status["message"] = message
        errors = self._status.setdefault("errors", [])
        errors.append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "message": message,
        })
        self._write_status()
        self.log(message, level="ERROR")

    def complete(self, message="done"):
        self._status["status"] = "completed"
        self._status["progress"] = 100.0
        self._status["message"] = message
        self._write_status()
        self.log("JOB COMPLETE | {}".format(message))


def _flythrough_root():
    if FOLDER is not None:
        root = FOLDER.get_local_dump_folder_folder(SUBDIR)
    elif ENVIRONMENT is not None:
        root = os.path.join(ENVIRONMENT.DUMP_FOLDER, SUBDIR)
    else:
        root = os.path.join(os.getcwd(), SUBDIR)
    if not os.path.exists(root):
        try:
            os.makedirs(root)
        except Exception:
            pass
    return root


def active_path_file():
    return os.path.join(_flythrough_root(), "active_path.json")


def new_job_dir(prefix="job"):
    job_id = "{}_{}".format(prefix, time.strftime("%Y%m%d-%H%M%S"))
    job_dir = os.path.join(_flythrough_root(), job_id)
    if not os.path.exists(job_dir):
        os.makedirs(job_dir)
    return job_id, job_dir


def load_active_path():
    path = active_path_file()
    if not os.path.exists(path):
        return empty_path()
    handle = open(path, "r")
    try:
        text = handle.read()
    finally:
        handle.close()
    if not text.strip():
        return empty_path()
    return path_from_json(text)


def save_active_path(path_data):
    path_data = path_data or empty_path()
    path_data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = active_path_file()
    handle = open(path, "w")
    try:
        handle.write(path_to_json(path_data))
    finally:
        handle.close()
    return path


# ---------------------------------------------------------------------------
# Rhino viewport I/O (gated -- unit tests never enter these)
# ---------------------------------------------------------------------------

def _require_rhino():
    if not _RHINO_OK:
        raise RuntimeError("Rhino APIs are not available in this runtime.")
    return rs, sc, Rhino


def capture_current_camera():
    """Read camera/target/lens/up from the active Rhino viewport."""
    rs_mod, sc_mod, _rhino = _require_rhino()
    view = sc_mod.doc.Views.ActiveView
    if view is None:
        raise RuntimeError("No active Rhino view.")
    cam, target = rs_mod.ViewCameraTarget()
    if cam is None or target is None:
        raise RuntimeError("Could not read ViewCameraTarget from active view.")
    lens = rs_mod.ViewCameraLens()
    if lens is None:
        lens = 50.0
    up = rs_mod.ViewCameraUp()
    if up is None:
        up = [0.0, 0.0, 1.0]
    return make_keyframe(cam, target, lens=lens, up=up, source="viewport")


def apply_camera(pose, view=None):
    rs_mod, sc_mod, _rhino = _require_rhino()
    rs_mod.ViewCameraTarget(view, pose["camera"], pose["target"])
    if pose.get("lens") is not None:
        try:
            rs_mod.ViewCameraLens(view, float(pose["lens"]))
        except Exception:
            pass
    if pose.get("up") is not None:
        try:
            rs_mod.ViewCameraUp(view, pose["up"])
        except Exception:
            pass
    try:
        sc_mod.doc.Views.Redraw()
    except Exception:
        pass


def lock_named_view_for_keyframe(keyframe):
    """Also mirror the keyframe into a Named View so existing camera tools see it."""
    rs_mod, _sc_mod, _rhino = _require_rhino()
    name = keyframe.get("name")
    if not name:
        return
    try:
        apply_camera(keyframe)
        # AddNamedView(name, view) -- first arg is the named-view name.
        existing = rs_mod.NamedViews() or []
        if name in existing:
            try:
                rs_mod.DeleteNamedView(name)
            except Exception:
                pass
        rs_mod.AddNamedView(name, None)
    except Exception:
        pass


def capture_still_to_file(file_path, width, height):
    """Capture active view to an image file without resizing the viewport."""
    rs_mod, sc_mod, rhino_mod = _require_rhino()
    if System is None:
        raise RuntimeError("System.Drawing is not available for ViewCapture.")

    view = sc_mod.doc.Views.ActiveView
    if view is None:
        raise RuntimeError("No active Rhino view to capture.")

    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)

    ext = os.path.splitext(file_path)[1].lower()
    capture = rhino_mod.Display.ViewCapture()
    capture.Width = int(width)
    capture.Height = int(height)
    capture.ScaleScreenItems = False
    capture.DrawAxes = False
    capture.DrawGrid = False
    capture.DrawGridAxes = False
    capture.TransparentBackground = False

    bitmap = capture.CaptureToBitmap(view)
    if bitmap is None:
        # Fallback used by batch_export_rhino_view -- mutates less predictably
        # but works when ViewCapture is unavailable.
        cmd = '!_-ViewCaptureToFile _Width {} _Height {} "{}" -enter -enter'.format(
            int(width), int(height), file_path)
        ok = rs_mod.Command(cmd, echo=False)
        if not ok or not os.path.exists(file_path):
            raise RuntimeError("ViewCapture failed for {}".format(file_path))
        return file_path

    try:
        if ext in (".jpg", ".jpeg"):
            fmt = System.Drawing.Imaging.ImageFormat.Jpeg
        elif ext == ".bmp":
            fmt = System.Drawing.Imaging.ImageFormat.Bmp
        else:
            fmt = System.Drawing.Imaging.ImageFormat.Png
            if ext != ".png":
                file_path = os.path.splitext(file_path)[0] + ".png"
        bitmap.Save(file_path, fmt)
    finally:
        bitmap.Dispose()
    return file_path


def find_ffmpeg():
    """Return an ffmpeg executable path if one is on PATH or a common install."""
    candidates = []
    path_env = os.environ.get("PATH") or ""
    for folder in path_env.split(os.pathsep):
        if not folder:
            continue
        for name in ("ffmpeg.exe", "ffmpeg"):
            candidate = os.path.join(folder, name)
            if os.path.exists(candidate):
                candidates.append(candidate)
    extras = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for candidate in extras:
        if os.path.exists(candidate):
            candidates.append(candidate)
    return candidates[0] if candidates else None


def encode_video_from_frames(frames_dir, output_mp4, fps, pattern="frame_%04d.jpg"):
    """Best-effort ffmpeg encode. Returns (ok, message)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "ffmpeg not found on PATH; image sequence left in {}".format(frames_dir)

    input_pattern = os.path.join(frames_dir, pattern)
    # Prefer System.Diagnostics under IronPython; fall back to subprocess.
    args = [
        ffmpeg, "-y",
        "-framerate", str(int(fps)),
        "-i", input_pattern,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        output_mp4,
    ]
    if _NET_PROCESS_OK:
        try:
            info = ProcessStartInfo()
            info.FileName = args[0]
            quoted = []
            for a in args[1:]:
                if " " in a and not a.startswith('"'):
                    quoted.append('"{}"'.format(a))
                else:
                    quoted.append(str(a))
            info.Arguments = " ".join(quoted)
            info.UseShellExecute = False
            info.CreateNoWindow = True
            info.RedirectStandardOutput = True
            info.RedirectStandardError = True
            proc = Process.Start(info)
            proc.WaitForExit()
            code = proc.ExitCode
            err = ""
            try:
                err = proc.StandardError.ReadToEnd()
            except Exception:
                pass
            if code == 0 and os.path.exists(output_mp4):
                return True, output_mp4
            return False, "ffmpeg exit {}: {}".format(code, (err or "")[:300])
        except Exception:
            pass

    if subprocess is None:
        return False, "no process launcher available for ffmpeg"
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _out, err = proc.communicate()
        if proc.returncode == 0 and os.path.exists(output_mp4):
            return True, output_mp4
        err_text = err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err)
        return False, "ffmpeg exit {}: {}".format(proc.returncode, err_text[:300])
    except Exception as ex:
        return False, "ffmpeg launch failed: {}".format(ex)


def _notify(text):
    if NOTIFICATION is not None:
        try:
            NOTIFICATION.messenger(main_text=text)
            return
        except Exception:
            pass
    try:
        print(text)
    except Exception:
        pass


def _copy_file(src, dst):
    folder = os.path.dirname(dst)
    if folder and not os.path.exists(folder):
        os.makedirs(folder)
    shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def stage_lock_keyframe(also_named_view=True):
    """Capture the live viewport camera into the active path."""
    path_data = load_active_path()
    kf = capture_current_camera()
    path_data, kf = append_keyframe(path_data, kf)
    if also_named_view:
        lock_named_view_for_keyframe(kf)
    save_active_path(path_data)
    msg = "Locked keyframe {} ({} total).".format(
        kf["name"], len(path_data["keyframes"]))
    _notify(msg)
    return path_data, kf


def stage_import_named_views(view_names):
    """Build / extend the path from existing Named Views (ordered)."""
    rs_mod, _sc_mod, _rhino = _require_rhino()
    path_data = load_active_path()
    added = []
    for name in view_names or []:
        try:
            rs_mod.RestoreNamedView(name, view=None, restore_bitmap=False)
            kf = capture_current_camera()
            kf["source"] = "named_view"
            path_data, kf = append_keyframe(path_data, kf)
            # Keep operator-chosen Named View name for traceability.
            path_data["keyframes"][-1]["name"] = name
            added.append(name)
        except Exception as ex:
            _notify("Skip view {}: {}".format(name, ex))
    save_active_path(path_data)
    _notify("Imported {} named view(s) into path ({} total).".format(
        len(added), len(path_data["keyframes"])))
    return path_data, added


def stage_clear_path():
    path_data = empty_path()
    save_active_path(path_data)
    _notify("Fly-through path cleared.")
    return path_data


def stage_path_status():
    path_data = load_active_path()
    kfs = path_data.get("keyframes") or []
    settings = path_data.get("settings") or {}
    lines = [
        "Keyframes: {}".format(len(kfs)),
        "Settings: {}x{} @ {}fps, {}s".format(
            settings.get("width"), settings.get("height"),
            settings.get("fps"), settings.get("duration_sec")),
        "Path file: {}".format(active_path_file()),
    ]
    for i, kf in enumerate(kfs):
        lines.append("  [{:02d}] {}".format(i + 1, kf.get("name")))
    text = "\n".join(lines)
    _notify("Fly-through path\n{}".format(text))
    return path_data, text


def _settings_from_path(path_data):
    settings = (path_data or {}).get("settings") or {}
    width = int(settings.get("width", DEFAULT_WIDTH))
    height = int(settings.get("height", DEFAULT_HEIGHT))
    fps = int(settings.get("fps", DEFAULT_FPS))
    duration = float(settings.get("duration_sec", DEFAULT_DURATION_SEC))
    fmt = str(settings.get("format", "jpg")).lower().lstrip(".")
    if fmt == "jpeg":
        fmt = "jpg"
    image_set_count = int(settings.get("image_set_count", DEFAULT_IMAGE_SET_COUNT))
    return width, height, fps, duration, fmt, image_set_count


def stage_export_keyframe_stills(width=None, height=None):
    """Restore each keyframe and export a still for debug/approval."""
    path_data = load_active_path()
    kfs = path_data.get("keyframes") or []
    if not kfs:
        raise RuntimeError("No keyframes locked. Lock at least one camera pose first.")

    w, h, _fps, _dur, fmt, _isc = _settings_from_path(path_data)
    if width:
        w = int(width)
    if height:
        h = int(height)

    job_id, job_dir = new_job_dir(prefix="stills")
    monitor = MonitorLog(job_dir, job_id)
    stills_dir = os.path.join(job_dir, "stills")
    os.makedirs(stills_dir)
    save_active_path(path_data)
    # Snapshot path into the job folder for auditability
    handle = open(os.path.join(job_dir, "path.json"), "w")
    try:
        handle.write(path_to_json(path_data))
    finally:
        handle.close()

    monitor.set_stage("export_stills", "Exporting {} keyframe stills".format(len(kfs)))
    outputs = []

    def _work(item):
        i, kf = item
        apply_camera(kf)
        file_path = os.path.join(
            stills_dir, "{:03d}_{}.{}".format(i + 1, kf.get("name", "kf"), fmt))
        try:
            capture_still_to_file(file_path, w, h)
            outputs.append(file_path)
            monitor.log("Wrote {}".format(file_path))
        except Exception as ex:
            monitor.fail("Still failed for {}: {}".format(kf.get("name"), ex))
            raise

    items = list(enumerate(kfs))
    if UI is not None:
        UI.progress_bar(
            items, _work,
            label_func=lambda it: "Still {}".format(it[1].get("name")),
            title="FlyThrough keyframe stills")
    else:
        for item in items:
            _work(item)
            monitor.set_progress(100.0 * float(item[0] + 1) / float(len(items)))

    monitor.add_output("stills_dir", stills_dir)
    monitor.add_output("still_count", len(outputs))
    monitor.complete("Exported {} stills to {}".format(len(outputs), stills_dir))
    _notify("Keyframe stills ready:\n{}".format(stills_dir))
    try:
        os.startfile(stills_dir)
    except Exception:
        pass
    return job_dir, outputs


def stage_render_final(width=None, height=None, fps=None, duration_sec=None):
    """Sample the path, write frames + image set, optionally encode mp4."""
    path_data = load_active_path()
    kfs = path_data.get("keyframes") or []
    if len(kfs) < 1:
        raise RuntimeError("No keyframes locked. Lock a camera path first.")

    w, h, default_fps, default_dur, fmt, image_set_count = _settings_from_path(path_data)
    if width:
        w = int(width)
    if height:
        h = int(height)
    use_fps = int(fps) if fps else default_fps
    use_dur = float(duration_sec) if duration_sec else default_dur
    path_data.setdefault("settings", {})
    path_data["settings"]["width"] = w
    path_data["settings"]["height"] = h
    path_data["settings"]["fps"] = use_fps
    path_data["settings"]["duration_sec"] = use_dur
    save_active_path(path_data)

    poses = sample_path(path_data)
    if not poses:
        raise RuntimeError("Path sampling produced no poses.")

    job_id, job_dir = new_job_dir(prefix="final")
    monitor = MonitorLog(job_dir, job_id)
    frames_dir = os.path.join(job_dir, "frames")
    images_dir = os.path.join(job_dir, "images")
    os.makedirs(frames_dir)
    os.makedirs(images_dir)

    handle = open(os.path.join(job_dir, "path.json"), "w")
    try:
        handle.write(path_to_json(path_data))
    finally:
        handle.close()

    monitor.set_stage("render_frames", "Rendering {} frames".format(len(poses)))
    frame_paths = []
    pattern_ext = fmt
    frame_pattern = "frame_%04d.{}".format(pattern_ext)

    def _work(pose):
        apply_camera(pose)
        idx = int(pose["frame_index"]) + 1
        file_path = os.path.join(
            frames_dir, "frame_{:04d}.{}".format(idx, pattern_ext))
        capture_still_to_file(file_path, w, h)
        frame_paths.append(file_path)
        monitor.set_progress(
            100.0 * float(idx) / float(len(poses)),
            message="frame {}/{}".format(idx, len(poses)))
        monitor.log("Frame {} -> {}".format(idx, file_path))

    if UI is not None:
        UI.progress_bar(
            poses, _work,
            label_func=lambda p: "Frame {}".format(int(p["frame_index"]) + 1),
            title="FlyThrough final render")
    else:
        for pose in poses:
            _work(pose)

    # Image set -- evenly spaced copies for decks / reviews
    monitor.set_stage("image_set", "Building image set")
    indices = pick_image_set_indices(len(frame_paths), image_set_count)
    image_set = []
    for n, idx in enumerate(indices):
        src = frame_paths[idx]
        dst = os.path.join(
            images_dir, "image_{:02d}.{}".format(n + 1, pattern_ext))
        _copy_file(src, dst)
        image_set.append(dst)

    monitor.add_output("frames_dir", frames_dir)
    monitor.add_output("frame_count", len(frame_paths))
    monitor.add_output("images_dir", images_dir)
    monitor.add_output("image_set_count", len(image_set))

    # Optional video
    monitor.set_stage("encode_video", "Attempting ffmpeg encode")
    mp4_path = os.path.join(job_dir, "flythrough.mp4")
    # ffmpeg %d patterns are 1-based with frame_0001.jpg when using frame_%04d
    ok, detail = encode_video_from_frames(
        frames_dir, mp4_path, use_fps, pattern=frame_pattern)
    if ok:
        monitor.add_output("video", mp4_path)
        monitor.log("Video encoded: {}".format(mp4_path))
    else:
        monitor.log("Video skipped/failed: {}".format(detail), level="WARN")
        monitor.add_output("video", None)
        monitor.add_output("video_note", detail)

    summary = "frames={} images={} video={}".format(
        len(frame_paths), len(image_set), "yes" if ok else "no")
    monitor.complete(summary)
    _notify("Fly-through final ready:\n{}\n{}".format(job_dir, summary))
    try:
        os.startfile(job_dir)
    except Exception:
        pass
    return job_dir, {
        "frames": frame_paths,
        "images": image_set,
        "video": mp4_path if ok else None,
        "video_note": None if ok else detail,
    }


def stage_configure_settings(width, height, fps, duration_sec, image_set_count=None):
    path_data = load_active_path()
    settings = path_data.setdefault("settings", {})
    settings["width"] = int(width)
    settings["height"] = int(height)
    settings["fps"] = int(fps)
    settings["duration_sec"] = float(duration_sec)
    if image_set_count is not None:
        settings["image_set_count"] = int(image_set_count)
    save_active_path(path_data)
    _notify("Fly-through settings updated.")
    return path_data


def safe_stage(fn, *args, **kwargs):
    """Run a stage; failures are logged to a one-off monitor job when possible."""
    try:
        return fn(*args, **kwargs)
    except Exception as ex:
        try:
            job_id, job_dir = new_job_dir(prefix="error")
            monitor = MonitorLog(job_dir, job_id)
            monitor.fail("{}: {}".format(ex, traceback.format_exc()))
        except Exception:
            pass
        raise
