import unittest
from dataclasses import replace

from filters import JobInfo, TextLine, activity_days, evaluate, extract_job


CONFIG = {"filters": {"allowed_cities": ["武汉"], "max_active_days": 7}}


def line(text, x, y, width=0.3, score=0.99):
    return TextLine(text, score, x, y, x + width, y + 0.02)


def header(location="武汉·洪山区", activity="今日活跃"):
    return [
        line("容器运维工程师（武汉）", 0.06, 0.12, 0.65),
        line("7-8K", 0.82, 0.12, 0.12),
        line(location, 0.08, 0.22),
        line("3-5年", 0.52, 0.22, 0.13),
        line("本科", 0.72, 0.22, 0.1),
        line("李女士", 0.26, 0.30),
        line("北京某某科技·人事专员", 0.26, 0.33, 0.65),
        line(activity, 0.26, 0.37, 0.65),
        line("职位详情", 0.06, 0.43),
        line("工作要求：武汉出差，今日回复所有工单", 0.06, 0.51, 0.88),
    ]


FOOTER = [line("立即沟通", 0.40, 0.94)]


class ActivityTests(unittest.TestCase):
    def test_recent_labels(self):
        for text, expected in {"今日活跃": 0, "今日回复10+次": 0, "刚刚活跃": 0,
                               "在线": 0, "昨日活跃": 1, "3日内活跃": 3,
                               "7日内活跃": 7, "７ 日 内 活跃": 7,
                               "一周内活跃": 7, "本周活跃": 7,
                               "30分钟前回复丨今日回复5次": 30 / 1440,
                               "2小时前活跃": 2 / 24}.items():
            with self.subTest(text=text):
                self.assertAlmostEqual(activity_days(text), expected)

    def test_long_labels_without_image_templates(self):
        for text in ["两个月内活跃", "2个月内活跃", "半年内活跃", "半年前活跃",
                     "一个月内活跃", "30天前活跃", "一年内活跃", "十五天内活跃"]:
            with self.subTest(text=text):
                self.assertGreater(activity_days(text), 7)

    def test_no_invented_time(self):
        for text in ["", "回复率高", "近期活跃", "该职位于昨日新发布", "今日回复率高"]:
            with self.subTest(text=text):
                self.assertIsNone(activity_days(text))

    def test_conflicting_labels_use_larger_range(self):
        self.assertGreater(activity_days("今日回复1次 | 两个月内活跃"), 7)


class FilterTests(unittest.TestCase):
    def test_sample_layout_with_wrapped_title(self):
        job = extract_job(header(), FOOTER)
        self.assertEqual(job.location, "武汉·洪山区")
        self.assertEqual(job.title, "容器运维工程师（武汉）")
        self.assertEqual(evaluate(job, CONFIG).action, "pass")

    def test_company_and_title_city_do_not_override_location(self):
        job = extract_job(header(location="深圳·南山区"), FOOTER)
        self.assertIn("武汉", job.title)
        self.assertEqual(evaluate(job, CONFIG).action, "skip")
        job = extract_job(header(), FOOTER)
        self.assertEqual(evaluate(job, CONFIG).action, "pass")  # 公司在北京也可投。

    def test_description_below_anchor_cannot_make_hr_active(self):
        job = extract_job(header(activity="回复率高"), FOOTER)
        self.assertIsNone(job.active_days)
        self.assertEqual(evaluate(job, CONFIG).action, "review")

    def test_old_status_and_boundary(self):
        for text, action in [("7日内活跃", "pass"), ("8日内活跃", "skip"),
                             ("两个月内活跃", "skip"), ("半年内活跃", "skip")]:
            with self.subTest(text=text):
                job = extract_job(header(activity=text), FOOTER)
                self.assertEqual(evaluate(job, CONFIG).action, action)

    def test_merged_metadata_box(self):
        lines = [item for item in header() if item.top != 0.22]
        lines.append(line("武汉·洪山区 3-5年 本科", 0.08, 0.22, 0.78))
        job = extract_job(lines, FOOTER)
        self.assertEqual(job.location, "武汉·洪山区")
        self.assertEqual(evaluate(job, CONFIG).action, "pass")

    def test_already_contacted(self):
        job = extract_job(header(), [line("继续沟通", 0.40, 0.94)])
        self.assertEqual(evaluate(job, CONFIG).action, "skip")

    def test_default_title_filter_skips_only_matching_titles(self):
        job = extract_job(header(), FOOTER)
        for title, word in [
            ("朝九晚五 不加班 双休\n经理 助理", "经理助理"),
            ("招聘专员", "招聘专员"),
            ("后台数据审核专员", "数据审核专员"),
            ("ＹｏｕＴｕｂｅ 运营", "YouTube运营"),
        ]:
            with self.subTest(title=title):
                decision = evaluate(replace(job, title=title), CONFIG)
                self.assertEqual(decision.action, "skip")
                self.assertIn(word, decision.reason)
        for title in ("运维助理", "售前工程师", "软件实施工程师", "招聘系统运维工程师", "技术客服工程师"):
            with self.subTest(title=title):
                self.assertEqual(evaluate(replace(job, title=title), CONFIG).action, "pass")

    def test_custom_title_exclusions_replace_defaults(self):
        job = replace(extract_job(header(), FOOTER), title="后台数据审核专员")
        config = {"filters": {**CONFIG["filters"], "exclude_title_keywords": []}}
        self.assertEqual(evaluate(job, config).action, "pass")
        config["filters"]["exclude_title_keywords"] = ["后台数据审核"]
        self.assertEqual(evaluate(job, config).action, "skip")
        config["filters"]["exclude_title_keywords"] = "后台数据审核"
        with self.assertRaisesRegex(ValueError, "字符串列表"):
            evaluate(job, config)

    def test_missing_or_low_confidence_data_does_not_pass(self):
        job = extract_job(header(), FOOTER)
        for changed in [replace(job, location=""), replace(job, active_days=None),
                        replace(job, button_text=""), replace(job, is_detail=False),
                        replace(job, location="武汉洪山区")]:
            self.assertEqual(evaluate(changed, CONFIG).action, "review")
        poor = [replace(item, score=0.3) if item.text.startswith("武汉·") else item for item in header()]
        self.assertEqual(evaluate(extract_job(poor, FOOTER), CONFIG).action, "review")

    def test_city_boundary(self):
        job = extract_job(header(), FOOTER)
        self.assertEqual(evaluate(replace(job, location="武汉市·洪山区"), CONFIG).action, "pass")
        self.assertNotEqual(evaluate(replace(job, location="武汉县·某区"), CONFIG).action, "pass")

    def test_key_ignores_changing_reply_time(self):
        before = extract_job(header(activity="9分钟前回复"), FOOTER)
        after = extract_job(header(activity="10分钟前回复"), [line("继续沟通", 0.4, 0.94)])
        self.assertEqual(before.key, after.key)


if __name__ == "__main__":
    unittest.main()
