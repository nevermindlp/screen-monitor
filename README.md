# Screen Monitor（区域视觉监控 + 模板匹配 + Gmail 截图告警）

基于“指定屏幕区域”的视觉监控：当识别到你提供的“固定数字”模板后，自动对区域截图并通过 Gmail 发送到邮箱；同时支持定期点击指定坐标，推动区域内容变化，变化后立即继续检测；邮件可合并多次命中结果。

## 环境要求

- Python 3.10+（建议 3.11/3.12）
- macOS / Windows（优先适配 macOS）

## 安装

建议使用虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\\Scripts\\activate  # Windows PowerShell

pip install -r requirements.txt
```

## macOS 权限（必须）

第一次运行时，macOS 可能会拦截：

- **屏幕录制**：用于抓屏（`mss`）
- **辅助功能**：用于自动点击（`pyautogui`）

在「系统设置 → 隐私与安全性」里给你的终端（或 Cursor）开启以上权限后重试。

## 高分辨率截图（改善 OCR / 模板匹配）

在 macOS Retina 上，默认抓图是“逻辑分辨率”（1x），同一区域像素较少，可能影响 OCR 和匹配效果。

- **capture.high_dpi**（仅 macOS）：设为 `true` 时，使用系统原生分辨率抓图（同一区域约 2x 像素），从源头提高截图清晰度。在 `config.yaml` 中增加：
  ```yaml
  capture:
    high_dpi: true
  ```
- **capture.capture_scale**：抓图后的放大倍数（默认 `1.0`）。设为 `2.0` 会在抓图后再放大 2 倍再用于匹配与保存，跨平台可用；若已开启 `high_dpi`，一般保持 `1.0` 即可。

注意：开启 `high_dpi` 后，截图与证据图分辨率会变高，模板图建议用当前程序抓到的截图裁剪制作，以保证比例一致。

## 1）交互式校准（框选监控区域 + 选择点击点）

```bash
python -m screen_monitor.main calibrate --config config.yaml
```

执行后会弹出一个窗口：先框选监控区域（ROI），确认后，再按提示选择点击点并写入 `config.yaml`。

## 2）准备模板图

把包含“固定数字”的模板小图放到项目目录（默认 `template.png`），或修改 `config.yaml` 的 `template.path`。

模板建议：
- 直接截取屏幕上那串 **完整数字**（比单个数字更稳）
- 用无损 PNG，边缘留少量空白 padding

## 2.1）图片尺寸调整工具

如果模板图尺寸与实际屏幕上的目标不一致，可以使用内置的图片缩放工具对子图进行缩放并另存：

```bash
python -m screen_monitor.main resize-image \
  --src 原始图片路径 \
  --dst 目标图片路径 \
  --width 目标宽度像素 \
  --height 目标高度像素
```

示例（将 `pic-2.png` 缩放到 `43x15` 并保存为 `pic-2-new.png`）：

```bash
python -m screen_monitor.main resize-image \
  --src pic-2.png \
  --dst pic-2-new.png \
  --width 43 \
  --height 15
```

然后在 `config.yaml` 中把 `template.path` 指向新的模板图即可。

## 3）运行监控

```bash
python -m screen_monitor.main run --config config.yaml
```

常用参数：
- `--dry-run`：只保存命中截图，不发邮件
- `--once`：仅一次：对 config 中的监控区域做高清截图并做模板识别，不包含点击，完成后退出（适合调试/单次检测）

命中截图会保存在 `evidence/`。

## 4）SMTP 发信（推荐用授权码/应用密码）

此项目支持通用 SMTP。通常邮箱服务商都会提供“授权码/应用密码”（推荐使用它，而不是网页登录密码）。\n
配置方式二选一（推荐用环境变量）：

- 环境变量（推荐）：

```bash
export EMAIL_SMTP_PASSWORD="你的邮箱授权码/应用密码"
```

- 或写入 `config.yaml` 的 `email.app_password`（不建议提交到仓库）

发送测试邮件：

```bash
python -m screen_monitor.main test-email --config config.yaml
```

## 5）OCR 工具（可选）

项目内置了一个简单的 OCR 工具，方便你对任意图片做一次文本识别（例如验证某个数字/标记的可识别性）：

```bash
python -m screen_monitor.main ocr-image \
  --path 某张图片.png \
  --whitelist "0123456789+"
```

- `--path`：要识别的图片路径
- `--whitelist`：可选，限定只识别哪些字符，默认为不限制
- `--psm`：可选，传给 Tesseract 的 PSM 模式（默认为 7，单行文本）

使用前需要先安装 Tesseract-OCR（以 macOS 为例）：

```bash
brew install tesseract
```

然后在虚拟环境中安装依赖（已包含在 `requirements.txt` 中）：

```bash
pip install -r requirements.txt
```

## 6）高清截图工具（capture-image）

不跑监控循环，仅截取一次指定区域或全屏为高清 PNG，便于制作模板、调试或存档。在 macOS 上可启用原生分辨率（Retina 2x）。

```bash
# 交互式选择区域（与 calibrate 相同：鼠标移到左上角、右下角各按回车后截取）
python -m screen_monitor.main capture-image -o evidence/capture.png -i

# 使用 config 中的 monitor_region，输出到指定文件（高清由 config 中 capture.high_dpi 决定）
python -m screen_monitor.main capture-image -o evidence/capture.png --config config.yaml

# 截取主显示器全屏
python -m screen_monitor.main capture-image -o desktop.png --full-screen

# 指定区域（x y w h，逻辑坐标）
python -m screen_monitor.main capture-image -o region.png --region "100 200 800 600"

# 强制启用/禁用高清（覆盖 config）
python -m screen_monitor.main capture-image -o hi.png --high-dpi
python -m screen_monitor.main capture-image -o lo.png --no-high-dpi

# 抓图后再放大 2 倍
python -m screen_monitor.main capture-image -o scaled.png --scale 2.0
```

参数说明：

- `-o / --output`：输出 PNG 路径（必填）
- `-i / --interactive`：交互式选择区域（按提示将鼠标移到左上角、右下角各按回车，与 calibrate 相同方式）
- `--config`：配置文件路径，用于读取 `monitor_region` 和 `capture` 设置（默认 `config.yaml`）
- `--region X Y W H`：覆盖区域，四个整数，如 `"100 200 800 600"`
- `--full-screen`：截取主显示器全屏（忽略 config 区域）
- `--high-dpi`：启用高清截屏（macOS 下为原生分辨率）
- `--no-high-dpi`：禁用高清（覆盖 config）
- `--scale`：抓图后缩放倍数，如 `2.0`（默认从 config 的 `capture.capture_scale` 读取）

未指定 `--region` 且未使用 `--full-screen`、`-i/--interactive` 时，区域来自 `config.yaml` 的 `monitor_region`（可先执行 `calibrate` 写入）。

## 故障排查

- **抓屏黑屏/失败**：检查 macOS 的“屏幕录制”权限
- **无法点击**：检查 macOS 的“辅助功能”权限
- **匹配不稳定**：调低/调高 `template.threshold`，或开启 `template.multiscale`

