<p align="center">
  <img src="src/puripuly_heart/data/icons/icon.png" alt="PuriPuly Heart for Linux" width="128" />
</p>

<h1 align="center">PuriPuly Heart — Linux Port</h1>
<p align="center"><strong>Native Linux voice translation and subtitles for VRChat</strong><br>
PipeWire audio · CPU / Vulkan inference · Desktop / OpenXR captions</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black" alt="Platform: Linux" />
  <img src="https://img.shields.io/badge/status-beta-orange" alt="Status: beta" />
  <img src="https://img.shields.io/badge/tested_on-Arch_%2B_Hyprland-1793D1" alt="Tested on Arch Linux and Hyprland" />
  <img src="https://img.shields.io/badge/license-AGPL--3.0--or--later-blue" alt="License: AGPL-3.0-or-later" />
</p>

<p align="center"><a href="docs/Linux.md"><strong>Install on Linux</strong></a> · <a href="docs/Linux.md#stability-pass--october-3-2026">Testing and limitations</a> · <a href="https://github.com/kapitalismho/PuriPuly-heart">Original Windows project</a></p>

> **Linux beta fork:** Native Arch/Hyprland, PipeWire, Vulkan speech recognition, local translation and OpenXR subtitles. Based on [kapitalismho’s PuriPuly Heart](https://github.com/kapitalismho/PuriPuly-heart); original attribution and AGPL-3.0-or-later licensing are preserved. This is an independent fork, not an official upstream Linux release.

## Linux: start here

Follow the [Linux installation and verification guide](docs/Linux.md) for system prerequisites, installation, model setup and known limitations. The `linux-port` branch contains the port; installation currently builds from source, with no packaged Linux release yet. After installing the system prerequisites:

```sh
git clone --branch linux-port https://github.com/danrtz/PuriPuly-heart.git
cd PuriPuly-heart
scripts/linux/install-user.sh
```

Desktop audio capture, local English/Japanese recognition and translation, captions, and failure recovery have been tested on Arch/Hyprland. The Python suite passed 6,751 tests with 53 skipped. **Physical-headset/live VRChat validation is pending**; OpenXR overlays have passed simulated-headset tests. Account-backed cloud providers have not been verified in this port.

Report Linux-port problems in [this fork’s issues](https://github.com/danrtz/PuriPuly-heart/issues). The feature descriptions, demonstrations and benchmarks below come from upstream; they are not additional Linux validation results.

---

<h2 align="center">
  🇺🇸 English ·
  <a href="docs/readme/README.ko.md">🇰🇷 한국어</a> ·
  <a href="docs/readme/README.ja.md">🇯🇵 日本語</a> ·
  <a href="docs/readme/README.zh-CN.md">🇨🇳 简体中文</a> ·
  <a href="docs/readme/README.ru.md">🇷🇺 Русский</a>
</h2>

---

## Demo

![Comparison of translation results between PuriPuly (Deepgram + Gemini 3 Flash) and VRCT (Google Web Speech + Google Translate). PuriPuly STT: "아역시혼자기대하면안된다니깐", Translation: "(See, I knew I shouldn't have gotten my hopes up.)" | VRCT STT: "아 역시 혼자 기대하면 안 된다니까", Translation: "Oh, I guess you shouldn't expect it alone."](docs/images/demo/ko-en_screenshot.png)

---

<video src="https://github.com/user-attachments/assets/c667f44d-b91d-42a9-b24a-e6a993b392d3" controls width="100%"></video>

If you want to see more of actual communication with other foreign friends through PuriPuly:
- [Demo 1](https://www.youtube.com/watch?v=3p0CamYui0o)
- [Demo 2](https://youtu.be/DoX36Y7J_lc?si=YjbeVTS8v3jGQB1w)
- [Demo 3](https://www.youtube.com/watch?v=D0npvp68xNY)

---

## Finally, talk like real friends.

You've been there.  
Wanting to comfort a friend,  
but only managing: "Are you okay?"

You already know a 'translator'  
can't carry what's truly in your heart.

So I built one that can.

## What is PuriPuly?

PuriPuly is a two-way voice translator that translates your voice and the other person's voice in real time. This fork adds native Linux support to the upstream Windows application.
We aim for natural translation through LLMs.
Beyond stiff literal translation, so real person-to-person conversation can happen.
It works in many environments, including VRChat and Discord.

- **LLM-Powered Localization** — Slang, colloquialisms, and casual/formal speech, all rendered naturally.
- **Context Memory** — Keeps the conversation flowing naturally with awareness of prior context.
- **Two-way Voice Translation** — Translates the other person's voice too, with VR subtitle overlay support.
- **Start via Discord** — Get going right away without a complex setup process.
- **The most powerful local full stack** — From Parakeet to Gemma 4 E4B, built with the most efficient models available today.

## Q&A

- **How good is the translation quality?**
→ You can comfortably have even the deepest conversations people can share. It also outperforms traditional commercial translation services by a wide margin. See the 'Translation Comparison' section below for details.

- **How long does it take from speaking to getting a translation?**
→ Under optimal conditions, latency is around 1 second, measured from when the speaker finishes talking.

- **Does it cost money to use?**
→ Yes, but only later. New users get a free usage allowance, and even after that the pricing is very cheap; you can translate thousands of times for $1. You can also use it for free by running local models.

- **Do I need to get an API key?**
→ Yes, but again, only later. At first, just install and authenticate via Discord to start using it.

- **Voice recognition is slow.**
→ When using local ASR, processing times can be slow if compute resources are limited. In this case, we recommend switching to a cloud STT service.

- **How is personal data handled?**
→ Voice and conversation contents are never sent to Puripuly servers. In addition, all source code is publicly available in this repository, so you can verify its network behavior directly.

### [Linux installation](docs/Linux.md) · [Upstream Windows download](https://github.com/kapitalismho/PuriPuly-heart/releases/latest)

---

## Translation Comparison
![Mean error penalty per sentence for Korean to EN / JA / ZH-Hans across 216 multi-turn samples (Gemba MQM evaluation, lower is better). Blue bars are models available in PuriPuly: 1st Gemma 4 31B (0.353), 2nd Gemma 4 26B A4B (0.387), 3rd DeepSeek-V4 Flash 0731 (0.571), 4th Gemma 4 12B QAT Q4 (0.855), 5th Gemma 4 E4B QAT Q4 (1.577). Orange bars are external baselines: Hy-MT-7B (1.863), Papago (2.699), Gemini 3.5 Live Translate (2.991), MiLMMT 46-4B (3.087), DeepL (3.914), Google Cloud Translation Basic (5.731).](docs/images/performance/2.png)

- The blue bars are the models available in PuriPuly.
- We ran the experiment using Microsoft's Gemba MQM framework.
- It was set up as a multi-turn environment to better resemble real conversation.
- For the full results, see [here](https://github.com/kapitalismho/korean-llm-context-translation-benchmark).

## Cost

### Uses per Dollar

#### Recommended Models

| LLM \ ASR | Local ASR | Cloud Free Tier ASR | Soniox | Qwen Audio |
|---|---|---|---|---|
| **Gemma 4 E4B (Local)** | Unlimited | Unlimited | 5,000 | 7,260 |
| **Gemma 4 26B A4B + 31B** | 13,940 | 13,940 | 3,680 | 4,770 |
| **DeepSeek V4 Flash (OpenRouter)** | 17,020 | 17,020 | 3,860 | 5,090 |
| **DeepSeek V4.1 Flash** | 16,800 | 16,800 | 3,860 | 5,070 |

#### Other Models

| LLM \ ASR | Local ASR | Cloud Free Tier ASR | Soniox | Qwen Audio |
|---|---|---|---|---|
| **Gemini 3.8 Flash** | 1,160 | 1,160 | 940 | 1,000 |
| **Qwen 3.8 Flash** | 7,460 | 7,460 | 2,990 | 3,680 |

### Cost per Utterance

#### Recommended Models

| LLM \ ASR | Local ASR | Cloud Free Tier ASR | Soniox | Qwen Audio |
|---|---|---|---|---|
| **Gemma 4 E4B (Local)** | $0 | $0 | ~$0.0002 | ~$0.00014 |
| **Gemma 4 26B A4B + 31B** | ~$0.00007 | ~$0.00007 | ~$0.0003 | ~$0.00021 |
| **DeepSeek V4 Flash (OpenRouter)** | ~$0.00006 | ~$0.00006 | ~$0.0003 | ~$0.00020 |
| **DeepSeek V4.1 Flash** | ~$0.00006 | ~$0.00006 | ~$0.0003 | ~$0.00020 |

#### Other Models

| LLM \ ASR | Local ASR | Cloud Free Tier ASR | Soniox | Qwen Audio |
|---|---|---|---|---|
| **Gemini 3.8 Flash** | ~$0.0009 | ~$0.0009 | ~$0.0011 | ~$0.0010 |
| **Qwen 3.8 Flash** | ~$0.0001 | ~$0.0001 | ~$0.0003 | ~$0.00027 |

*   *Based on (Input 900 tokens + Output 12 tokens) × 1.2 avg LLM calls per utterance.*
*   *Uses per Dollar is derived from the un-rounded values in the Cost per Utterance table.*
*   *All costs and usage counts are approximate.*
*   *DeepSeek V4.1 Flash assumes a 70% cache hit rate; V4 Flash (OpenRouter) assumes 60%.*
*   *Qwen API costs are based on the Beijing region.*
*   *Pricing as of September 25, 2026.*

### Free Credits

| Service | Free Credit | Duration | Note |
|--------|------------|------|------|
| **Deepgram** | $200 | None | No card required |
| **ElevenLabs** | 10,000 credits | Monthly reset | No card required |
| **Gemini 3.5 Transcribe** | Free tier | None | Practically unlimited on the free tier |
| **Alibaba Cloud** | 1M tokens per model | 90 days | Singapore region |
| **Alibaba Cloud** | ¥300 | 1 year | Students in China |

---

## Local Models

PuriPuly comes with the following local models built in. You can also connect OpenAI-compatible APIs.
GPU inference runs on Vulkan. It works regardless of the vendor — Radeon or Arc alike.

**ASR**

| Model | Runtime | Quantization |
|---|---|---|
| Parakeet TDT 0.6B v3 | CPU | INT8 |
| Parakeet TDT-CTC 0.6B (ja) | CPU | INT8 |
| Qwen3-ASR 0.6B | CPU | INT8 |
| Qwen3-ASR 1.7B | GPU | Q6_K |
| OpenAI-compatible API | — | — |

**LLM**

| Model | Runtime | Quantization |
|---|---|---|
| Gemma 4 E4B IT QAT | CPU / GPU | UD Q4_K_XL |
| OpenAI-compatible API | — | — |

---

For Linux-port problems, use [this fork’s issue tracker](https://github.com/danrtz/PuriPuly-heart/issues). The upstream author's contact is [Twitter/X](https://x.com/kapitalismho).

## Usage

**Linux:** use the [Linux first-use instructions](docs/Linux.md#first-use). The Windows installer and Discord onboarding below describe the upstream distribution; local Linux models do not require a cloud account.

1. Download the latest version from the [Download page](https://github.com/kapitalismho/PuriPuly-heart/releases/latest).
2. Install PuriPuly.
3. Click the **TALK** button.
4. Click the **TRANS** button, then authenticate via Discord.
5. Click the **CAPTIONS** button to turn on VR subtitles.
6. (Optional) Click the **LISTEN** button to enable translation of the other person's voice.

   > Peer voice translation needs a low-noise space to work properly. When using it in VRChat, use Earmuff to control the environment.

7. Enable OSC in VRChat: Action menu → Settings → OSC → Enable.

For bidirectional control setup and the stable parameter ABI, see [VRChat OSC controls](docs/vrchat-osc.md).

### If audio capture does not work
On Linux, check the PipeWire/PulseAudio device selection and capture guidance in [the Linux guide](docs/Linux.md). The MME instructions below apply to Windows.

If audio capture does not work, open **Settings > General** and follow these steps.

1. Change **Audio Host API** to **Auto** or **MME**.
2. Select the correct microphone.
3. Restart the app.

---

### Note for Users in China

If Soniox/Gemini/Deepgram are blocked in your region, please use the following combination:

- STT: **Qwen Audio**
- LLM: **DeepSeek V4.1 Flash**

   > You can authenticate through QQ instead of Discord.

---

### Using Your Own API Keys

Follow the guide that matches the service you want to use.

For the translation LLM, we recommend selecting **Gemma 4 26B A4B + 31B** with the **OpenRouter** connection.

By the way, while you're setting things up, why not configure ASR too?
PuriPuly delivers the best experience when paired with a cloud STT.
For instance, even with the same Qwen ASR, local and cloud voice-recognition performance differ noticeably.

We recommend starting with Deepgram.
Just signing up gets you $200 in free credits.

<details>
<summary><h3>OpenRouter</h3></summary>

1. Set the options inside the red circle as shown in the screenshot.
   ![step0](docs/images/openrouter/0.png)

2. In the app, click the button inside the red circle.
   ![step1](docs/images/openrouter/1.png)

3. Login at OpenRouter.
   ![step2](docs/images/openrouter/2.png)

4. Click the button inside the red circle to exit the payment screen.
   ![step3](docs/images/openrouter/3.png)

5. Click the **Authorize** button.
   ![step4](docs/images/openrouter/4.png)

6. Prepay as much as you plan to use.
   ![step5](docs/images/openrouter/5.png)

<details>
<summary><h3>If clicking Authorize didn't authenticate you</h3></summary>

If you clicked Authorize but you're still not authenticated, retry, or directly issue an API key as below and paste it in.

6. Click your account in the top right, go to the API Keys tab on the left, then click the Create button in the center.
   ![step6](docs/images/openrouter/6.png)

7. Click the Create button.
   ![step7](docs/images/openrouter/7.png)

8. Click the button to copy the API key, then paste it into the API tab of the translator.
   ![step8](docs/images/openrouter/8.png)

</details>

</details>

<details>
<summary><h3>DeepSeek</h3></summary>

1. Set the options inside the red circle as shown in the screenshot.
   ![step0](docs/images/deepseek/0.png)

2. Go to the [DeepSeek official homepage](https://www.deepseek.com/en/) and click the **Access API** button.
   ![step1](docs/images/deepseek/1.png)

3. Login on the homepage.
   ![step2](docs/images/deepseek/2.png)

4. Go to the API Keys tab and click **Create new API Keys**.
   ![step3](docs/images/deepseek/3.png)

5. Click the button to copy the API key, then paste it into the API tab of the translator.
   ![step4](docs/images/deepseek/4.png)

6. Go to the Top Up tab and prepay as much as you plan to use.
   ![step5](docs/images/deepseek/5.png)

</details>

<details>
<summary><h3>Deepgram</h3></summary>

1. Login to the [Deepgram Console](https://console.deepgram.com/).
   ![step1](docs/images/deepgram/1.png)

2. If you see a welcome message/survey, click **Skip**.
   ![step2](docs/images/deepgram/2.png)

3. Select **STT (Speech-to-Text)** on the service selection screen.
   ![step3](docs/images/deepgram/3.png)

4. In the API Keys menu, click **Create a New API Key**.
   ![step4](docs/images/deepgram/4.png)

5. Enter a key name (e.g., `puripuly`) and create.
   ![step5](docs/images/deepgram/5.png)

6. Copy the generated key and paste it into PuriPuly settings.
   ![step6](docs/images/deepgram/6.png)

</details>

<details>
<summary><h3>Gemini</h3></summary>

1. Go to [Google AI Studio](https://aistudio.google.com/apikey) and click the **Get API key** button.
   ![step1](docs/images/gemini/1.png)

2. Create a new project.
   ![step2](docs/images/gemini/2.png)

3. Choose any name for the project.
   ![step3](docs/images/gemini/3.png)

4. Select the project you created and click **Create key**.
   ![step4](docs/images/gemini/4.png)

5. Click the circled area.
   ![step5](docs/images/gemini/5.png)

6. Click the circled area to copy the key.
   ![step6](docs/images/gemini/6.png)

7. (Recommended) Click the yellow **Set Up Billing** button to upgrade to the paid tier.
The tier transition may take a moment.
   ![step7](docs/images/gemini/7.png)

<details>
<summary><h3>For Gemini paid subscribers</h3></summary>

8. Go to [Google Developer Program](https://developers.google.com/program/my-benefits) and join the program.
   ![step8](docs/images/gemini/8.png)

9. Select the paid tier project you set up in step 7.
   ![step9](docs/images/gemini/9.png)

</details>

</details>

<details>
<summary><h3>Qwen</h3></summary>

1. Access Alibaba Cloud Model Studio via the appropriate path for your region:
   - [Mainland China](https://bailian.console.aliyun.com/cn-beijing)
   - [Outside Mainland China](https://bailian.console.alibabacloud.com)

2. Login at the URL above. Make sure to select the correct Region for your API key (e.g., Beijing).
   ![step2](docs/images/qwen/1.png)

3. Click the **gear icon** in the top right.
   ![step3](docs/images/qwen/2.png)

4. Create a workspace and go to the **API-KEY** page.
   ![step4](docs/images/qwen/3.png)

5. Click **Create API Key**.
   ![step5](docs/images/qwen/4.png)

6. Assign an account and workspace, then click OK.
   ![step6](docs/images/qwen/5.png)

7. Click the circled area to copy the key.
   ![step7](docs/images/qwen/6.png)

</details>

<details>
<summary><h3>Soniox</h3></summary>

1. Login to [Soniox Console](https://console.soniox.com/).
   ![step1](docs/images/soniox/1.png)

2. Enter an organization name of your choice.
   ![step2](docs/images/soniox/2.png)

3. Click **Add Funds** to link a payment method.
   ![step3](docs/images/soniox/3.png)

4. Soniox requires prepaid credits. Once added, go to the **API Keys** menu.
   ![step4](docs/images/soniox/4.png)

5. Create a new API Key.
   ![step5](docs/images/soniox/5.png)

6. Copy the generated key and paste it into PuriPuly settings.
   ![step6](docs/images/soniox/6.png)

</details>


---

## Architecture

![PuriPuly Heart hexagonal architecture: core runtimes surrounded by eight port adapters](docs/architecture-light.png)

See [`docs/architecture.md`](docs/architecture.md).

## Roadmap

Upcoming work is tracked publicly on the [PuriPuly project board](https://github.com/users/kapitalismho/projects/2).

---

## Development

### Environments

| Surface                    | Recommended environment | Documentation                                          |
| -------------------------- | ----------------------- | ------------------------------------------------------ |
| Python desktop application | Linux / Windows         | [Linux guide](docs/Linux.md); Windows below             |
| Broker service             | Linux                   | [`broker/README.md`](broker/README.md)                 |
| Native VR overlay          | Linux / Windows         | [Linux OpenXR](docs/Linux.md); [upstream Windows](native/overlay/README.md) |

### Python Environment

The Python application requires ordinary GIL-enabled CPython 3.14. For native x86-64 Linux builds, follow [the Linux guide](docs/Linux.md), which uses `.venv` and builds the platform runtimes. The following environment instructions are for upstream Windows development.

Create and activate the Windows environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install the application and development dependencies:

```powershell
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

`uv` may be used instead:

```powershell
uv sync --dev
```

For separate WSL development work, `.venv-wsl` may be used when available. This is separate from the native Linux installer above.

```bash
UV_PROJECT_ENVIRONMENT=.venv-wsl uv sync --dev
```

Repositories configured with `direnv` may run commands through:

```bash
direnv exec . <command>
```

### Running the Application

Run the Flet desktop application:

```powershell
python -m puripuly_heart.main run-gui
```

The equivalent `uv` command is:

```powershell
uv run python -m puripuly_heart.main run-gui
```

Developer preview controls for hidden UI states are enabled with:

```powershell
python -m puripuly_heart.main run-gui --debug-ui-preview
```

### Python Verification

Format the Python sources and tests:

```powershell
black src tests
```

Check formatting without modifying files:

```powershell
black --check src tests
```

Run lint checks:

```powershell
ruff check src tests
```

Run the complete Python test suite:

```powershell
python -m pytest
```

Run a focused test file or directory during development:

```powershell
python -m pytest tests/path/to/test_file.py
```

### Other Surfaces

Broker documentation is maintained in [`broker/README.md`](broker/README.md).

Native VR overlay documentation is maintained in [`native/overlay/README.md`](native/overlay/README.md).

Custom HTTP API extension documentation is maintained in [`docs/http-extensions.md`](docs/http-extensions.md). For the JSON Schema required for connection, see [`docs/http-extension.schema.json`](docs/http-extension.schema.json).

VRChat OSC controls are documented in [`docs/vrchat-osc.md`](docs/vrchat-osc.md).

---

## Developer

[salee](https://github.com/kapitalismho)

---

## Contributors

[RICHARDwuxiaofei](https://github.com/RICHARDwuxiaofei)
[fzcfweasdferttgg-png](https://github.com/fzcfweasdferttgg-png)

---

## Special Thanks

SUI\_32C, Nagikokoro, motoka96, \_Ykol魚, kascr\_, Just Monika V, FLUVIA, Han โชเล่ย์, EA\_PE, Ephedrine, ~ eri ~, fzcfweasdferttgg-png, Welcius, nunu299, 梅雨Shiro

---

## Policies

- [Code signing policy](CODE_SIGNING.md)
- [Privacy Policy](PRIVACY.md)

---

## License

[AGPL-3.0-or-later](LICENSE)

Third-party licenses and notices: `src/puripuly_heart/data/THIRD_PARTY_NOTICES.txt`
