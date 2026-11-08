"""离线 OCR 和按钮模板匹配；不会点击或上传截图。"""
from __future__ import annotations

from pathlib import Path

from filters import TextLine, extract_job


class ScreenReader:
    def __init__(self, config: dict):
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        self.np = np
        self.config = config
        # 限制线程数，避免桌面端和小型虚拟机初始化时占满 CPU。
        self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)

    def read_region(self, image, region: list[float]) -> list[TextLine]:
        width, height = image.size
        x0, y0, x1, y1 = region
        bounds = (int(width * x0), int(height * y0), int(width * x1), int(height * y1))
        crop = image.crop(bounds).convert("RGB")
        target_width = max(900, min(1200, crop.width))
        scale = target_width / crop.width
        if scale != 1:
            from PIL import Image
            crop = crop.resize((target_width, round(crop.height * scale)), Image.Resampling.LANCZOS)
        # RapidOCR 的 ndarray 接口接受 BGR。
        result, _ = self.engine(self.np.asarray(crop)[:, :, ::-1].copy())
        lines = []
        for box, text, score in result or []:
            xs, ys = [point[0] for point in box], [point[1] for point in box]
            lines.append(TextLine(
                text=str(text), score=float(score),
                left=(min(xs) / scale + bounds[0]) / width,
                top=(min(ys) / scale + bounds[1]) / height,
                right=(max(xs) / scale + bounds[0]) / width,
                bottom=(max(ys) / scale + bounds[1]) / height,
            ))
        return lines

    def analyze(self, image):
        header = self.read_region(image, self.config["ocr"]["header_region"])
        footer = self.read_region(image, self.config["ocr"]["footer_region"])
        return extract_job(header, footer, self.config["ocr"]["min_confidence"])


def find_button(image, config: dict, base_dir: Path) -> tuple[int, int, float] | None:
    import cv2
    import numpy as np

    width, height = image.size
    y0 = int(height * config["ocr"]["footer_region"][1])
    screen = cv2.cvtColor(np.asarray(image.convert("RGB"))[y0:], cv2.COLOR_RGB2GRAY)
    filename = config["button_templates"][config["platform"]]
    path = base_dir / filename
    # imdecode 支持 Windows 中文路径，避免 imread 无法读取。
    template = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise RuntimeError(f"按钮模板读取失败：{path}")
    best = None
    for scale in config["button_scales"]:
        tw, th = round(template.shape[1] * scale), round(template.shape[0] * scale)
        if tw < 8 or th < 8 or tw > width or th > screen.shape[0]:
            continue
        resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(screen, resized, cv2.TM_CCOEFF_NORMED))
        if best is None or score > best[2]:
            best = (point[0] + tw // 2, point[1] + th // 2 + y0, float(score))
    return best if best and best[2] >= config["button_confidence"] else None
