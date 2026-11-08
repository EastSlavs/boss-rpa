import copy
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import main
from filters import JobInfo


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.config = main.load_config(main.BASE_DIR / "config.json")
        self.config["limits"]["max_jobs"] = 1
        self.config["timing"] = dict.fromkeys(self.config["timing"], 0)
        self.image = Mock()
        self.snapshot = main.Snapshot(self.image, (0, 0, 400, 900), (0, 0, 400, 900))
        self.desktop = Mock()
        self.desktop.capture.return_value = self.snapshot
        self.job = JobInfo(title="运维工程师", location="武汉·洪山区", activity="今日活跃",
                           active_days=0, button_text="立即沟通", is_detail=True, key="job-1")
        self.reader = Mock()
        self.reader.analyze.return_value = self.job
        self.audit = Mock()

    def test_preview_never_calls_contact(self):
        with patch("main.Desktop", return_value=self.desktop), patch("main.contact") as contact:
            main.run_desktop(self.config, self.reader, self.audit, live=False)
            contact.assert_not_called()
            self.desktop.click.assert_not_called()

    def test_foreign_and_old_jobs_never_click(self):
        for location, days in [("深圳·南山区", 0), ("武汉·洪山区", 180)]:
            self.job.location, self.job.active_days = location, days
            with patch("main.Desktop", return_value=self.desktop), patch("main.contact") as contact:
                main.run_desktop(self.config, self.reader, self.audit, live=True)
                contact.assert_not_called()

    def test_unknown_page_stops_without_swiping(self):
        self.job.is_detail = False
        with patch("main.Desktop", return_value=self.desktop):
            with self.assertRaisesRegex(RuntimeError, "岗位首屏"):
                main.run_desktop(self.config, self.reader, self.audit, live=True)
        self.desktop.swipe_left.assert_not_called()

    def test_failed_navigation_stops(self):
        with self.assertRaisesRegex(RuntimeError, "没有识别到新岗位"):
            main.move_to_next(self.desktop, self.reader, self.config, self.job.key)
        self.assertEqual(self.desktop.swipe_left.call_count, 2)
        self.desktop.click.assert_not_called()

    def test_failed_preclick_recheck_skips_to_next_job(self):
        self.config["limits"]["max_jobs"] = 2
        for field, value in [("key", "job-2"), ("active_days", 30)]:
            with self.subTest(field=field):
                fresh = copy.copy(self.job)
                setattr(fresh, field, value)
                next_job = copy.copy(self.job)
                next_job.key = "job-3"
                next_job.location = "鄂州·华容区"
                self.reader.analyze.side_effect = [self.job, fresh, next_job]
                self.desktop.reset_mock()
                self.audit.reset_mock()
                with patch("main.Desktop", return_value=self.desktop):
                    main.run_desktop(self.config, self.reader, self.audit, live=True)
                self.desktop.swipe_left.assert_called_once()
                self.desktop.click.assert_not_called()
                actions = [call.args[1].action for call in self.audit.write.call_args_list]
                self.assertEqual(actions, ["pass", "skip", "skip"])

    def test_lost_detail_before_click_stops(self):
        fresh = copy.copy(self.job)
        fresh.is_detail = False
        self.reader.analyze.side_effect = [self.job, fresh]
        with patch("main.Desktop", return_value=self.desktop):
            with self.assertRaisesRegex(RuntimeError, "点击前无法确认"):
                main.run_desktop(self.config, self.reader, self.audit, live=True)
        self.desktop.swipe_left.assert_not_called()
        self.desktop.click.assert_not_called()

    def test_failed_template_does_not_click(self):
        with patch("vision.find_button", return_value=None):
            result = main.contact(self.desktop, self.reader, self.config, self.job)
        self.assertEqual(result[2].action, "review")
        self.desktop.click.assert_not_called()

    def test_unconfirmed_click_continues_to_next_job_without_retry(self):
        self.config["limits"].update(max_jobs=2, max_consecutive_unknown=1)
        next_job = replace(self.job, title="系统运维工程师", key="job-3")
        next_contacted = replace(next_job, button_text="继续沟通")
        for result in [replace(self.job, key="job-2", button_text="继续沟通"),
                       replace(self.job, button_text="")]:
            with self.subTest(key=result.key, button=result.button_text):
                self.reader.analyze.side_effect = [
                    self.job, self.job, result, result, result, next_job, next_job, next_contacted,
                ]
                self.desktop.reset_mock()
                self.audit.reset_mock()
                with patch("main.Desktop", return_value=self.desktop), \
                        patch("vision.find_button", return_value=(200, 850, 0.99)):
                    main.run_desktop(self.config, self.reader, self.audit, live=True)
                self.desktop.swipe_left.assert_called_once()
                self.desktop.back.assert_not_called()
                self.assertEqual(self.desktop.click.call_count, 2)
                records = self.audit.write.call_args_list
                self.assertEqual([call.args[1].action for call in records],
                                 ["pass", "unconfirmed", "pass", "contacted"])
                self.assertEqual(records[1].args[0].key, self.job.key)
                self.assertIs(records[1].args[2], self.image)

    def test_late_chat_is_recovered_before_continuing(self):
        self.config["button_texts"]["contacted"] = ["已联系"]
        self.reader.analyze.side_effect = [
            self.job, self.job, JobInfo(), replace(self.job, button_text="已联系"),
        ]
        with patch("vision.find_button", return_value=(200, 850, 0.99)):
            _, _, decision = main.contact(self.desktop, self.reader, self.config, self.job)
        self.assertEqual(decision.action, "contacted")
        self.desktop.click.assert_called_once()
        self.desktop.back.assert_called_once()

    def test_unrecovered_postclick_page_stops_without_swiping(self):
        self.config["limits"]["max_jobs"] = 2
        chat = JobInfo()
        self.reader.analyze.side_effect = [self.job, self.job, chat, chat, chat]
        with patch("main.Desktop", return_value=self.desktop), \
                patch("vision.find_button", return_value=(200, 850, 0.99)):
            with self.assertRaisesRegex(RuntimeError, "未能回到岗位详情页"):
                main.run_desktop(self.config, self.reader, self.audit, live=True)
        self.desktop.click.assert_called_once()
        self.desktop.back.assert_called_once()
        self.desktop.swipe_left.assert_not_called()

    def test_unconfirmed_click_counts_towards_limit(self):
        self.config["limits"].update(max_jobs=2, max_clicks=1, contact_checks=1)
        with patch("main.Desktop", return_value=self.desktop), \
                patch("vision.find_button", return_value=(200, 850, 0.99)):
            main.run_desktop(self.config, self.reader, self.audit, live=True)
        self.desktop.click.assert_called_once()
        self.desktop.swipe_left.assert_not_called()
        self.assertEqual(self.reader.analyze.call_count, 3)

    def test_consecutive_template_failures_stop(self):
        self.config["limits"]["max_jobs"] = 10
        with patch("main.Desktop", return_value=self.desktop), \
                patch("main.move_to_next", return_value=(self.snapshot, self.job)), \
                patch("main.contact", return_value=(self.snapshot, self.job, main.Decision("review", "按钮未匹配"))) as contact:
            with self.assertRaisesRegex(RuntimeError, "连续多个岗位"):
                main.run_desktop(self.config, self.reader, self.audit, live=True)
        self.assertEqual(contact.call_count, 3)

    def test_invalid_config_stops(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = main.Path(folder) / "config.json"
            for filters, expected in [
                ({"allowed_cities": []}, "allowed_cities"),
                ({"exclude_title_keywords": "经理助理"}, "exclude_title_keywords"),
                ({"unknown_activity": "pass"}, "unknown_activity"),
            ]:
                with self.subTest(filters=filters):
                    path.write_text(json.dumps({"filters": filters}), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, expected):
                        main.load_config(path)

    def test_old_custom_config_keeps_values_and_loads_new_defaults(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = main.Path(folder) / "old-config.json"
            old = {"filters": {"allowed_cities": ["长沙"], "max_active_days": 14}}
            path.write_text(json.dumps(old), encoding="utf-8")
            config = main.load_config(path)
        self.assertEqual(config["filters"]["allowed_cities"], ["长沙"])
        self.assertEqual(config["filters"]["max_active_days"], 14)
        self.assertIn("经理助理", config["filters"]["exclude_title_keywords"])
        self.assertIn("继续沟通", config["button_texts"]["contacted"])


if __name__ == "__main__":
    unittest.main()
