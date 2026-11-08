"""只处理 OCR 文字和坐标，不导入鼠标、窗口或 OCR 运行库。"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field


def compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class TextLine:
    text: str
    score: float
    left: float
    top: float
    right: float
    bottom: float


@dataclass
class JobInfo:
    title: str = ""
    location: str = ""
    activity: str = ""
    active_days: float | None = None
    button_text: str = ""
    is_detail: bool = False
    key: str = ""
    header_text: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    action: str  # pass / skip / review
    reason: str


DETAIL = re.compile(r"职位详情|岗位详情|职位描述")
META = re.compile(
    r"(?:\d+[-—~至]?\d*年|经验不限|不限经验|无需经验|应届|在校|"
    r"大专|本科|硕士|博士|中专|高中|初中|学历不限)"
)
STATUS = re.compile(r"活跃|回复|在线")
SALARY = re.compile(r"^[\d.]+[-~—][\d.]+[Kk万千元].*$|^面议$")
SEPARATOR = r"[·•・.。|｜]"

DEFAULT_EXCLUDED_TITLES = (
    "经理助理", "行政助理", "行政专员", "行政文员", "办公室文员", "前台接待",
    "人事助理", "人事专员", "招聘助理", "招聘专员",
    "销售代表", "销售专员", "电话销售", "客服专员",
    "数据审核专员", "数据审核员", "内容审核专员", "内容审核员",
    "YouTube运营", "短视频运营", "新媒体运营",
)


def group_rows(lines: list[TextLine]) -> list[list[TextLine]]:
    """合并同一行内被 OCR 分开的地点、经验、学历。坐标均为全图的 0～1。"""
    rows: list[list[TextLine]] = []
    for line in sorted(lines, key=lambda item: (item.top, item.left)):
        center = (line.top + line.bottom) / 2
        for row in reversed(rows):
            ref = row[0]
            ref_center = (ref.top + ref.bottom) / 2
            tolerance = min(line.bottom - line.top, ref.bottom - ref.top) * 0.55
            if abs(center - ref_center) <= tolerance:
                row.append(line)
                break
        else:
            rows.append([line])
    return [sorted(row, key=lambda item: item.left) for row in rows]


def chinese_number(text: str) -> float | None:
    if text == "半":
        return 0.5
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text in digits:
        return float(digits[text])
    total, current = 0, 0
    for char in text:
        if char in digits:
            current = digits[char]
        elif char in {"十", "百"}:
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        else:
            return None
    return float(total + current) if text else None


def activity_days(text: str) -> float | None:
    """以标签的时间范围上界判断；不把发布时间、回复率当成活跃时间。"""
    text = compact(text)
    values: list[float] = []
    for pattern, days in [
        (r"(?:刚刚|刚才|今日|今天)(?:活跃|回复(?!率))", 0),
        (r"(?:当前|正在)?在线", 0),
        (r"(?:昨日|昨天)(?:活跃|回复(?!率))", 1),
        (r"前天(?:活跃|回复(?!率))", 2),
        (r"本周(?:活跃|回复(?!率))", 7),
        (r"本月(?:活跃|回复(?!率))", 31),
    ]:
        if re.search(pattern, text):
            values.append(float(days))
    pattern = (
        r"(?P<number>\d+(?:\.\d+)?|[零一二两三四五六七八九十百半]+)"
        r"(?P<unit>分钟|小时|个月|日|天|周|月|年)"
        r"(?:以内|以前|之内|内|前|以来)?(?:活跃|回复(?!率))"
    )
    units = {"分钟": 1 / 1440, "小时": 1 / 24, "日": 1, "天": 1,
             "周": 7, "个月": 31, "月": 31, "年": 366}
    for match in re.finditer(pattern, text):
        number = chinese_number(match["number"])
        if number is not None:
            values.append(number * units[match["unit"]])
    # 同时出现多个标签时采用较大的时间范围，避免矛盾信息被当成近期。
    return max(values) if values else None


def extract_job(header: list[TextLine], footer: list[TextLine], min_score: float = 0.65) -> JobInfo:
    header = [line for line in header if line.score >= min_score]
    footer = [line for line in footer if line.score >= min_score]
    anchor_lines = [line for line in header if DETAIL.fullmatch(compact(line.text))]
    cutoff = min((line.top for line in anchor_lines), default=0.60)
    rows = group_rows([line for line in header if line.bottom < cutoff])
    job = JobInfo(is_detail=bool(anchor_lines))
    job.header_text = [" ".join(line.text for line in row) for row in rows]

    metadata_index = None
    for index, row in enumerate(rows):
        # 元信息须在页面上半部；招聘者公司名称和职位正文不参与城市判断。
        if row[0].top > 0.36:
            continue
        meta_parts = [line for line in row if META.search(compact(line.text))]
        location_parts = [line for line in row if line.left < 0.52 and not META.search(compact(line.text))]
        if meta_parts and location_parts:
            metadata_index = index
            # 地点可能被识别为多个片段；只取经验、学历之前的文字。
            first_meta_x = min(line.left for line in meta_parts)
            parts = [line.text for line in row if line.left < first_meta_x]
            job.location = compact("".join(parts))
            job.location = re.sub(r"^[^\u4e00-\u9fff]+", "", job.location)
            break
        # 部分 OCR 会把整行合并成一个框。
        merged = compact("".join(line.text for line in row))
        match = re.match(r"^[^\u4e00-\u9fff]*([\u4e00-\u9fff]{2,12}" + SEPARATOR + r".*?)", merged)
        meta_match = META.search(merged)
        if match and meta_match:
            metadata_index = index
            job.location = re.sub(r"^[^\u4e00-\u9fff]+", "", merged[:meta_match.start()]).rstrip("·•・.。|｜")
            break

    if metadata_index is not None:
        title_lines = [line for row in rows[:metadata_index] for line in row
                       if line.top > 0.075 and not SALARY.match(compact(line.text))
                       and len(compact(line.text)) >= 2
                       and re.search(r"[\u4e00-\u9fffA-Za-z]", line.text)]
        job.title = "".join(line.text for line in title_lines)
        recruiter_rows = rows[metadata_index + 1:]
        activity_rows = [" ".join(line.text for line in row) for row in recruiter_rows
                         if any(STATUS.search(line.text) for line in row)]
        job.activity = " | ".join(activity_rows)
        job.active_days = activity_days(job.activity)
        stable = [job.title, job.location]
        stable.extend("".join(line.text for line in row) for row in recruiter_rows
                      if not any(STATUS.search(line.text) or "发布" in line.text for line in row))
        job.key = hashlib.sha256(compact("|".join(stable)).encode("utf-8")).hexdigest()[:20]

    footer_text = "|".join(compact(line.text) for line in footer)
    # 已沟通状态优先，避免“继续沟通”被按钮图片的相似部分误匹配。
    for text in ("继续沟通", "已沟通", "已投递", "立即沟通", "去聊聊", "立即投递"):
        if text in footer_text:
            job.button_text = text
            break
    return job


def evaluate(job: JobInfo, config: dict) -> Decision:
    if not job.is_detail:
        return Decision("review", "未找到职位详情标记，请确认停留在岗位首屏")
    if job.button_text in {"继续沟通", "已沟通", "已投递"}:
        return Decision("skip", "已经沟通或投递")
    settings = config["filters"]
    excluded = settings.get("exclude_title_keywords", DEFAULT_EXCLUDED_TITLES)
    if not isinstance(excluded, (list, tuple)) or not all(isinstance(word, str) and word.strip() for word in excluded):
        raise ValueError("filters.exclude_title_keywords 必须是字符串列表，每个词不能为空")
    title = compact(job.title).casefold()
    for word in excluded:
        if compact(word).casefold() in title:
            return Decision("skip", f"岗位标题命中排除词：{word}")
    if not job.location:
        return Decision("review", "工作地点未识别清楚")
    location = compact(job.location)
    allowed = settings["allowed_cities"]
    city_ok = any(re.match(re.escape(city.removesuffix("市")) + r"(?:市)?(?:[·•・.。|｜]|$)", location)
                  for city in allowed)
    if not city_ok:
        # 缺少分隔符的 OCR 结果不作猜测。
        if not re.search(SEPARATOR, location) and not location.endswith("市"):
            return Decision("review", f"地点格式不明确：{job.location}")
        return Decision("skip", f"工作地点不在允许城市：{job.location}")
    if job.active_days is None:
        return Decision("review", f"活跃时间未知：{job.activity or '未读到状态'}")
    maximum = settings["max_active_days"]
    if job.active_days > maximum:
        return Decision("skip", f"招聘者状态超过 {maximum} 天：{job.activity}")
    if job.button_text not in {"立即沟通", "去聊聊", "立即投递"}:
        return Decision("review", "未识别到可投递按钮")
    return Decision("pass", f"城市符合，招聘者状态在 {maximum} 天以内")
