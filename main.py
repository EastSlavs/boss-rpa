"""手机投屏岗位筛选：默认预览，--live 才点击沟通。"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from filters import Decision, compact, evaluate

BASE_DIR = Path(__file__).resolve().parent
LOG = logging.getLogger("boss-rpa")


def read_config(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return config


def load_config(path: Path) -> dict:
    config = read_config(path)
    default_path = BASE_DIR / "config.json"
    if path.resolve() != default_path.resolve():
        defaults = read_config(default_path)
        for section, default in defaults.items():
            if isinstance(default, dict) and isinstance(config.get(section), dict):
                config[section] = {**default, **config[section]}
        config = {**defaults, **config}

    if config.get("mode") not in {"preview", "auto"}:
        raise ValueError("mode 只能为 preview 或 auto")
    if config.get("platform") not in {"boss", "51job", "zhilian"}:
        raise ValueError("platform 只能为 boss、51job 或 zhilian")
    required = {
        "filters": ("allowed_cities", "max_active_days", "unknown_activity", "exclude_title_keywords"),
        "activity": ("text_days", "unit_minutes", "suffixes"),
        "ocr": ("detail_markers",),
        "button_texts": ("clickable", "contacted"),
        "limits": ("contact_checks",),
    }
    for section, keys in required.items():
        if not isinstance(config.get(section), dict):
            raise ValueError(f"配置需要 {section} 对象，请使用新版 config.json")
        for key in keys:
            if key not in config[section]:
                raise ValueError(f"配置缺少 {section}.{key}，请使用新版 config.json 补齐")

    settings, activity, buttons = config["filters"], config["activity"], config["button_texts"]
    for name, values, allow_empty in [
        ("filters.allowed_cities", settings["allowed_cities"], False),
        ("filters.exclude_title_keywords", settings["exclude_title_keywords"], True),
        ("activity.suffixes", activity["suffixes"], False),
        ("ocr.detail_markers", config["ocr"]["detail_markers"], False),
        ("button_texts.clickable", buttons["clickable"], False),
        ("button_texts.contacted", buttons["contacted"], False),
    ]:
        if (not isinstance(values, list) or (not allow_empty and not values)
                or not all(isinstance(value, str) and compact(value) for value in values)):
            raise ValueError(f"{name} 必须是字符串列表，文字不能为空")
    if set(map(compact, buttons["clickable"])) & set(map(compact, buttons["contacted"])):
        raise ValueError("button_texts 的可点击和已沟通文字不能重复")
    if settings["unknown_activity"] not in ("review", "skip"):
        raise ValueError("filters.unknown_activity 只能为 review 或 skip")
    for name, table, allow_zero in [
        ("activity.text_days", activity["text_days"], True),
        ("activity.unit_minutes", activity["unit_minutes"], False),
    ]:
        if not isinstance(table, dict) or (not allow_zero and not table):
            raise ValueError(f"{name} 必须是文字到数字的映射")
        for label, value in table.items():
            if (not compact(label) or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not 0 <= value < float("inf") or (value == 0 and not allow_zero)):
                raise ValueError(f"{name} 的文字或数值无效：{label}")

    days = settings["max_active_days"]
    if isinstance(days, bool) or not isinstance(days, (int, float)) or not 0 <= days <= 3660:
        raise ValueError("max_active_days 必须为 0～3660 的数字")
    for name, region in [("window_region", config["window_region"]),
                         ("header_region", config["ocr"]["header_region"]),
                         ("footer_region", config["ocr"]["footer_region"])]:
        if (len(region) != 4 or not all(isinstance(value, (int, float)) for value in region)
                or not 0 <= region[0] < region[2] <= 1 or not 0 <= region[1] < region[3] <= 1):
            raise ValueError(f"{name} 必须为 [左, 上, 右, 下]，每项在 0～1 之间")
    for value in config["limits"].values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("limits 中的每项必须为正整数")
    for name in ("min_confidence",):
        if not 0 < config["ocr"][name] <= 1:
            raise ValueError(f"{name} 必须在 0～1 之间")
    if not 0 < config["button_confidence"] <= 1:
        raise ValueError("button_confidence 必须在 0～1 之间")
    if not config["button_scales"] or not all(0 < scale <= 5 for scale in config["button_scales"]):
        raise ValueError("button_scales 必须为 0～5 之间的正数列表")
    if not config["window_titles"] or not all(isinstance(title, str) and title for title in config["window_titles"]):
        raise ValueError("window_titles 不能为空")
    if not all(isinstance(value, (int, float)) and 0 <= value <= 30 for value in config["timing"].values()):
        raise ValueError("timing 中的每项必须为 0～30 秒")
    for filename in config["button_templates"].values():
        if not (BASE_DIR / filename).is_file():
            raise ValueError(f"按钮模板不存在：{filename}")
    return config


class Audit:
    def __init__(self):
        self.directory = BASE_DIR / "logs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.directory.mkdir(parents=True)
        self.path = self.directory / "results.jsonl"
        handler = logging.FileHandler(self.directory / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        self.index = 0

    def write(self, job, decision: Decision, image=None, **extra):
        self.index += 1
        record = {"time": datetime.now().isoformat(timespec="seconds"),
                  "action": decision.action, "reason": decision.reason,
                  "job": job.to_dict(), **extra}
        if image is not None:
            name = f"{self.index:04d}_{decision.action}.png"
            image.save(self.directory / name)
            record["screenshot"] = name
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        label = {"pass": "符合", "skip": "跳过", "review": "待确认", "contacted": "已沟通",
                 "unconfirmed": "沟通结果待确认", "error": "停止"}.get(decision.action, decision.action)
        LOG.info("[%s] %s | %s | %s", label, job.title or "未识别职位", job.location or "地点未知", decision.reason)


@dataclass
class Snapshot:
    image: object
    region: tuple[int, int, int, int]
    window_rect: tuple[int, int, int, int]


class Desktop:
    def __init__(self, config: dict):
        if sys.platform != "win32":
            raise RuntimeError("投屏控制目前支持 Windows；其他系统可以用 --image 测试截图")
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
        import pyautogui
        import pygetwindow

        self.mouse = pyautogui
        self.windows = pygetwindow
        self.config = config
        self.mouse.FAILSAFE = True
        self.mouse.PAUSE = 0.15
        self.win = self.find_window()

    def find_window(self):
        for title in self.config["window_titles"]:
            matches = [win for win in self.windows.getWindowsWithTitle(title) if win.width > 150 and win.height > 250]
            if len(matches) > 1:
                raise RuntimeError(f"找到多个包含 {title} 的窗口，请关闭多余窗口或把 window_titles 改得更准确")
            if matches:
                return matches[0]
        raise RuntimeError("未找到投屏窗口，请先打开投屏，并在 config.json 设置 window_titles")

    def rect(self):
        return (self.win.left, self.win.top, self.win.width, self.win.height)

    def capture(self) -> Snapshot:
        if self.win.isMinimized:
            self.win.restore()
        if not self.win.isActive:
            self.win.activate()
            time.sleep(0.35)
        if not self.win.isActive:
            raise RuntimeError("投屏窗口未获得焦点，已停止")
        rect = self.rect()
        left, top, width, height = rect
        sw, sh = self.mouse.size()
        if left < 0 or top < 0 or left + width > sw or top + height > sh:
            raise RuntimeError("请把投屏窗口完整放在主显示器内，避免截图与点击坐标偏移")
        x0, y0, x1, y1 = self.config["window_region"]
        region = (left + round(width * x0), top + round(height * y0),
                  round(width * x1) - round(width * x0), round(height * y1) - round(height * y0))
        return Snapshot(self.mouse.screenshot(region=region), region, rect)

    def ensure_unchanged(self, snapshot: Snapshot):
        if self.rect() != snapshot.window_rect or not self.win.isActive:
            raise RuntimeError("窗口位置或焦点发生变化，已停止，请重新启动")

    def click(self, snapshot: Snapshot, point):
        self.ensure_unchanged(snapshot)
        self.mouse.click(snapshot.region[0] + point[0], snapshot.region[1] + point[1])

    def back(self, snapshot: Snapshot):
        self.ensure_unchanged(snapshot)
        left, top, width, height = snapshot.region
        self.mouse.click(left + width // 2, top + height // 2, button="right")

    def swipe_left(self, snapshot: Snapshot):
        self.ensure_unchanged(snapshot)
        left, top, width, height = snapshot.region
        self.mouse.moveTo(left + round(width * 0.88), top + height // 2)
        # 全程留在投屏区域，避免拖到其他窗口。
        self.mouse.dragTo(left + round(width * 0.12), top + height // 2, duration=0.8, button="left")


def move_to_next(desktop, reader, config, previous_key):
    for attempt in range(config["limits"]["swipe_retries"]):
        desktop.swipe_left(desktop.capture())
        time.sleep(config["timing"]["page_wait_seconds"])
        snapshot = desktop.capture()
        job = reader.analyze(snapshot.image)
        # 不在页面尚未加载、滑到聊天页等情况下继续盲点。
        if job.is_detail and job.key and job.key != previous_key:
            return snapshot, job
        LOG.warning("左滑后未确认新岗位，第 %s 次", attempt + 1)
    raise RuntimeError("左滑后没有识别到新岗位，可能到达末尾或页面卡住，已停止")


def contact(desktop, reader, config, job):
    from vision import find_button

    # 点击前重新读取当前页面，防止判断后页面发生切换。
    current = desktop.capture()
    fresh = reader.analyze(current.image)
    if not fresh.is_detail:
        raise RuntimeError("点击前无法确认仍在岗位详情页，已停止")
    if fresh.key != job.key:
        return current, fresh, Decision("skip", "点击前两次识别的岗位信息不一致")
    eligibility = evaluate(fresh, config)
    if eligibility.action != "pass":
        return current, fresh, Decision("skip", f"点击前复核未通过：{eligibility.reason}")
    point = find_button(current.image, config, BASE_DIR)
    if point is None:
        return current, fresh, Decision("review", "OCR 通过，但按钮图片未匹配；本岗位未点击")
    LOG.info("按钮模板匹配置信度 %.3f", point[2])
    desktop.click(current, point)
    time.sleep(config["timing"]["after_click_seconds"])
    backed = False
    contacted_texts = config["button_texts"]["contacted"]
    for checks_left in range(config["limits"]["contact_checks"] - 1, -1, -1):
        after = desktop.capture()
        after_job = reader.analyze(after.image)
        if after_job.is_detail and after_job.key == job.key and after_job.button_text in contacted_texts:
            return after, after_job, Decision("contacted", f"按钮已变为{after_job.button_text}")
        if checks_left == 0:
            break
        if not after_job.is_detail and not backed:
            # 聊天页可能延迟出现，等待期间最多返回一次。
            desktop.back(after)
            backed = True
        time.sleep(config["timing"]["page_wait_seconds"])
    if not after_job.is_detail:
        after.image.save(BASE_DIR / "logs" / "last_unconfirmed.png")
        raise RuntimeError("点击后未能回到岗位详情页，已停止；请检查手机和 logs/last_unconfirmed.png")
    reason = "岗位识别不一致" if after_job.key != job.key else "未读到已沟通状态"
    button = after_job.button_text or "未识别"
    return after, after_job, Decision("unconfirmed", f"已点击，{reason}（按钮：{button}），继续下一条")


def run_desktop(config, reader, audit, live):
    desktop = Desktop(config)
    LOG.info("模式：%s；城市：%s；活跃状态：%s 天以内", "自动沟通" if live else "预览（会翻页，不点击沟通）",
             "/".join(config["filters"]["allowed_cities"]), config["filters"]["max_active_days"])
    LOG.info("请停在岗位首屏；Ctrl+C 或把鼠标移到主屏幕左上角可停止。%s 秒后开始。", config["timing"]["startup_seconds"])
    time.sleep(config["timing"]["startup_seconds"])
    snapshot = desktop.capture()
    job = reader.analyze(snapshot.image)
    clicks, confirmed, unknown = 0, 0, 0
    for count in range(config["limits"]["max_jobs"]):
        decision = evaluate(job, config)
        saved = snapshot.image if decision.action == "review" or config["save_preview_screenshots"] else None
        audit.write(job, decision, saved, mode="auto" if live else "preview")
        if not job.is_detail or not job.key:
            raise RuntimeError("当前页面无法确认是岗位首屏，已保存截图并停止")
        previous_key = job.key
        needs_review = decision.action == "review"
        if live and decision.action == "pass":
            target_job = job
            snapshot, job, result = contact(desktop, reader, config, job)
            needs_review = result.action == "review"
            unconfirmed = result.action == "unconfirmed"
            recorded_job = target_job if unconfirmed else job
            audit.write(recorded_job, result, snapshot.image if needs_review or unconfirmed else None, mode="auto")
            previous_key = job.key or previous_key
            if result.action in {"contacted", "unconfirmed"}:
                clicks += 1
            if result.action == "contacted":
                confirmed += 1
            if clicks >= config["limits"]["max_clicks"]:
                LOG.info("达到本次点击上限：%s", clicks)
                break
        unknown = unknown + 1 if needs_review else 0
        if unknown >= config["limits"]["max_consecutive_unknown"]:
            raise RuntimeError("连续多个岗位识别或按钮匹配不清，已停止；请检查 logs 中的截图和识别结果")
        if count + 1 < config["limits"]["max_jobs"]:
            snapshot, job = move_to_next(desktop, reader, config, previous_key)
    LOG.info("本次结束，点击 %s 次，确认发起沟通 %s 次。记录：%s", clicks, confirmed, audit.directory)


def main() -> int:
    parser = argparse.ArgumentParser(description="投屏岗位筛选，默认预览，不点击沟通")
    parser.add_argument("--config", type=Path, default=BASE_DIR / "config.json")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="自动点击符合规则的沟通按钮")
    mode.add_argument("--preview", action="store_true", help="只筛选和翻页，不点击沟通")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--image", type=Path, help="仅分析一张截图，不操作鼠标")
    source.add_argument("--folder", type=Path, help="仅分析目录中的 PNG/JPG 截图，不操作鼠标")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if not (3, 10) <= sys.version_info[:2] <= (3, 12):
            raise RuntimeError("请使用 64 位 Python 3.10～3.12，推荐 3.12")
        config = load_config(args.config)
        live = args.live or (config["mode"] == "auto" and not args.preview)
        if live and (args.image or args.folder):
            raise ValueError("截图测试不能使用自动沟通模式；请加 --preview")
        from vision import ScreenReader
        LOG.info("正在加载本地 OCR…")
        reader = ScreenReader(config)
        audit = Audit()
        if args.image or args.folder:
            from PIL import Image
            files = [args.image] if args.image else sorted(
                path for path in args.folder.iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"})
            if not files:
                raise ValueError("没有找到截图")
            for path in files:
                with Image.open(path) as image:
                    job = reader.analyze(image.convert("RGB"))
                audit.write(job, evaluate(job, config), source=str(path))
            LOG.info("截图测试结束，结果：%s", audit.path)
        else:
            run_desktop(config, reader, audit, live)
        return 0
    except KeyboardInterrupt:
        LOG.info("已手动停止")
        return 0
    except Exception as exc:
        if exc.__class__.__name__ == "FailSafeException":
            LOG.info("鼠标已移到屏幕角落，已停止")
            return 0
        LOG.error("%s: %s", exc.__class__.__name__, exc)
        if isinstance(exc, ImportError):
            LOG.error("当前 Python：%s。请运行 install.bat 安装依赖，再用 start_preview.bat 或 start_auto.bat 启动。", sys.executable)
        return 1


if __name__ == "__main__":
    sys.exit(main())
