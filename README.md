# 运动想象实验设计器

这是一个跨 Windows / macOS / Linux 的 Python 原型。它支持：

- 在 GUI 中设置总实验时间、单元实验库和各单元权重；
- 自定义主标题和副标题，并显示在顶部标题栏；
- 每个单元由多个按顺序执行的阶段组成，例如准备、运动想象、休息；
- 按权重配额抽取，或每次按权重随机抽取；
- 阶段显示文本、空白屏、图片或视频；
- 实验呈现时中央指令使用大字号，左上角显示下一步动作提示；
- 可选启用离线语音播报，在每个阶段开始时朗读指令；
- 通过 LSL 发送 JSON string marker；
- 每次实验输出 CSV 时序日志。

## 运行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

也可以直接打开 `sample_config.json`。在“单元实验库”中添加或编辑单元，在阶段编辑器里选择 `text`、`blank`、`image` 或 `video`。图片需要 Pillow；视频原型使用 OpenCV 按帧播放，暂不处理音频。

在“语音播报”页勾选自动语音并设置语速。语音使用 `pyttsx3` 调用本机 TTS，默认优先选择中文语音；Windows/macOS/Linux 的实际可用声音取决于系统已安装的语音。Linux 如无声音，按系统安装 `espeak-ng` 和 `libespeak1`。

## LSL marker

程序创建一个 `Markers` 类型、单通道、string 格式的 LSL stream。每个样本是一条 JSON，例如：

```json
{"event":"phase/start","experiment":"运动想象实验","trial_index":0,"unit":"左手","phase_index":1,"phase":"运动想象","marker":"left_hand","scheduled_elapsed_s":3.0,"actual_elapsed_s":3.012}
```

会发送的主要事件是：`experiment/start`、`unit/start`、`phase/start`、`phase/end`、`unit/end`、`experiment/end`；按 Esc 停止时发送 `experiment/aborted`。同步时建议使用 LSL timestamp，不要使用 CSV 的本地时间。

## 时序边界

核心计划器使用 `time.perf_counter()`，LSL timestamp 在画面更新后立即写入。Tkinter 的事件循环适合原型和常规秒级阶段，但不是硬实时呈现；如果后续需要严格的帧锁定、刺激物刷新率校准或视频音频同步，可以保留 `experiment_core.py` 和 marker schema，把 `PresentationWindow` 替换为 PsychoPy presenter。

语音请求在阶段开始后异步发出，不阻塞主计时；`phase/start` 的 LSL timestamp 代表画面阶段切换，不代表声波真正到达耳机的时刻。若要对声音 onset 做毫秒级 EEG 对齐，应改用预先生成的音频文件、固定音频输出设备并做声卡/耳机延迟校准。

## 自检

```bash
python experiment_core.py
```

它只检查配置校验、30 秒单元计划、按比例抽取、随机抽取和 JSON 往返，不需要 GUI 或 LSL。
