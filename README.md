# Boss RPA

配合 Windows 手机投屏使用的岗位筛选工具。按工作地点、招聘者活跃时间和岗位标题筛选，可以预览结果，也可以自动发起沟通。

## 使用

使用 64 位 Python 3.10～3.12，推荐 3.12。下载 ZIP 的话，解压后在 `boss-rpa` 目录执行 `install.bat`。

```powershell
git clone https://github.com/EastSlavs/boss-rpa.git
cd .\boss-rpa
.\install.bat
```

把手机投屏窗口放在主屏幕，打开一个岗位详情页。先运行预览，确认识别结果后，再运行自动沟通。

```powershell
.\start_preview.bat
```

```powershell
.\start_auto.bat
```

按 `Ctrl+C` 或把鼠标移到主屏幕左上角停止。每轮日志保存在 `logs/运行时间/`，`run.log` 是运行过程，`results.jsonl` 是逐条结果。

## 配置

编辑 `config.json`，重新启动后生效。优先按需要改 `filters` 里的几项。

| 配置 | 用途 |
| --- | --- |
| `filters.allowed_cities` | 工作城市，例如 `["武汉", "长沙"]`。 |
| `filters.max_active_days` | 招聘者活跃时间上限，默认 7 天。 |
| `filters.exclude_title_keywords` | 岗位标题含其中任一词就跳过。填 `[]` 可关闭这项筛选。 |
| `filters.unknown_activity` | 活跃时间读不出时，`review` 记为待确认，`skip` 直接跳过。 |
| `activity` | `text_days` 把「今日活跃」等标签对应到天数。`unit_minutes` 定义时间单位，例如一周是 10080 分钟。`suffixes` 是数字后识别的状态词。 |
| `button_texts` | `clickable` 是可点击按钮文字，`contacted` 是用于跳过和确认沟通结果的文字。 |
| `mode` | 直接运行 `main.py` 时的模式，`preview` 预览，`auto` 自动沟通。两个启动脚本各自指定模式。 |
| `window_titles`、`window_region` | 查找投屏窗口的标题和截图范围。范围按 `[左, 上, 右, 下]` 填 0～1 的比例。 |
| `ocr` | 头部和底部识别区域、最低识别分数、岗位详情标记。区域使用同样的比例格式。 |
| `platform`、`button_templates` | 平台和对应按钮图片。默认按 BOSS 直聘页面配置。 |
| `button_confidence`、`button_scales` | 图片匹配分数下限和尝试的缩放倍数。 |
| `timing` | 启动、翻页、点击后的等待秒数。 |
| `limits` | 每轮岗位数和点击数上限、连续待确认上限、点击后复查次数和左滑重试次数。 |
| `save_preview_screenshots` | 设为 `true` 保存每条筛选截图。默认按需保存待确认和异常截图。 |

可用 `--config 路径` 读取另一份配置，缺少的项从项目的 `config.json` 读取。也可以用截图测试 OCR。

```powershell
.\.venv\Scripts\python.exe -X utf8 main.py --image "D:\截图\岗位.jpg" --preview
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```
