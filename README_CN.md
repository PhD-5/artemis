<p align="center">
  <img src="./docs/assets/artemis-banner-cn.png?v=7" alt="ARTEMIS Banner" width="100%" />
</p>

<p align="center">
  <strong>让 AI 助手与测试套件像人一样直接操作真机。</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> •
  <a href="./README_CN.md"><b>中文文档</b></a> •
  <a href="#workflow-showcase">全流程演示</a> •
  <a href="#quick-start">快速上手</a> •
  <a href="#mcp-setup">MCP 接入 IDE</a> •
  <a href="#benchmarks">基准评测</a> •
  <a href="https://discord.gg/wF2FN4WHGY">Discord 社区</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache-2.0"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-Native%20Server-8A2BE2.svg" alt="MCP Native"></a>
  <a href="https://ai.google.dev/"><img src="https://img.shields.io/badge/Multimodal-Gemini%20%7C%20Claude%20%7C%20GPT--4o%20%7C%20Qwen--VL-4285F4.svg" alt="Multi-Model"></a>
  <a href="https://github.com/google-research/android_world"><img src="https://img.shields.io/badge/AndroidWorld-99%25%2B%20SOTA-success.svg" alt="AndroidWorld SOTA"></a>
</p>

<!-- 演示效果图 -->
<p align="center">
  <img src="./docs/assets/demo.gif" alt="Artemis 演示效果" width="100%" />
  <br>
  <em>实机演示：在 Google Maps 中设置驾车路线并计算总耗时，随后打开 YouTube 播放 Coldplay 的歌曲。</em>
</p>

## 核心亮点

* **跨 App 自动化**：根据自然语言指令，在 Android 上执行测试流程和日常任务。
* **多模态定位**：优先使用元素索引，对自绘界面提供坐标和视觉定位兜底。
* **IDE 内诊断**：通过 **MCP 协议**，让 **Antigravity、Claude Code、Windsurf** 操作测试设备，收集 **Logcat** 输出和截图。
* **Flash 执行**：使用观察、执行循环和异步历史摘要，单步通常约 **3–5 秒**。
* **Pro 探索**：单个动作执行前校验目标，被拦截的动作交回 Operator 处理。支持长时间探索和稳定性测试。
* **AndroidWorld 结果**：在 Google Research **AndroidWorld** 基准评测（100+ 多步任务）中取得 **99%+ 任务完成率**。

<a id="workflow-showcase"></a>
<a id="全流程演示"></a>
## Antigravity × ARTEMIS：全流程自主测试演示

**Antigravity** 通过 MCP 调用 **ARTEMIS**，将测试需求转为计划、真机操作和诊断报告：

<table width="100%">
  <tr>
    <td width="50%" align="center">
      <b>1. 输入测试提示词 (Task Dispatch)</b><br>
      <sub>在 Antigravity 中用自然语言描述测试需求与目标指标</sub><br><br>
      <img src="./docs/assets/workflow-1-prompt.png" width="100%" alt="步骤一：输入测试提示词" />
    </td>
    <td width="50%" align="center">
      <b>2. 生成测试方案 (Test Plan Generation)</b><br>
      <sub>自动拆解任务，生成详细测试步骤与架构图供确认</sub><br><br>
      <img src="./docs/assets/workflow-2-plan.png" width="100%" alt="步骤二：生成测试方案" />
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <b>3. 自主执行测试 (Autonomous Test Execution)</b><br>
      <sub>驱动真机操作、界面导航并实时分析性能指标</sub><br><br>
      <img src="./docs/assets/workflow-3-exec.png" width="100%" alt="步骤三：自主执行测试" />
    </td>
    <td width="50%" align="center">
      <b>4. 交付最终报告 (Comprehensive Final Report)</b><br>
      <sub>生成结构化测试报告，交付性能图表、结论与原始数据</sub><br><br>
      <img src="./docs/assets/workflow-4-report.png" width="100%" alt="步骤四：交付最终报告" />
    </td>
  </tr>
</table>

<a id="quick-start"></a>
<a id="快速上手"></a>
## 快速上手

确保电脑已连接 Android 实体机（已开启 **USB 调试**）或 Android 模拟器。一键启动脚本将会自动完成以下配置：
- **安装系统环境依赖**：自动检测并安装 ADB、scrcpy、FFmpeg 与 Python（`uv`）运行时及项目依赖。
- **全局挂载 MCP 服务与测试准则 (Rules)**：主动引导并自动将全局 MCP 服务与 **Artemis 移动端测试思维准则 (`rules.md`)** 挂载至你使用的 AI IDE（支持 **Antigravity**、**Cursor**、**Claude Code**、**Codex**、**Windsurf**、**VS Code**、**Cline/Roo**、**OpenClaw**）。

### macOS 与 Linux

```bash
# 1. 克隆代码仓库并进入目录
git clone https://github.com/google/artemis.git && cd artemis

# 2. 一键启动
./start.sh
```

### Windows PowerShell

```powershell
# 1. 克隆代码仓库并进入目录
git clone https://github.com/google/artemis.git
cd artemis

# 2. 一键启动
.\start.bat
```

> PowerShell 默认不会从当前目录查找可执行脚本，因此必须使用 `.\start.bat`，且命令末尾不要添加 `\`。如果使用传统命令提示符（CMD），则运行 `start.bat`。

> **提示**：启动后将自动在默认浏览器中打开 Web 控制台（`http://localhost:8000`），提供设备连接向导、实时投屏、任务演练与状态回放面板。你也可以通过命令行直接运行：`uv run artemis run "打开系统设置，找到电池选项并告诉我当前电量" --profile flash`。

### Web 模型配置、推荐任务与目标设备

- **AI Model Setup** 优先推荐 DeepSeek，支持 DeepSeek、Zhipu、Gemini、OpenAI 兼容接口、Anthropic、OpenRouter 和 xAI。Base URL 可读、可修改；已存 API Key 只能覆盖写入，接口、就绪状态和配置预览仅返回固定 `********`，不返回前后缀或原始值。密码框不回填，保存时留空保留旧 Key，填写新 Key 则验证后覆盖。
- Provider 配置持久化到当前安装环境的 `.env`（源码运行时为仓库根目录，实际路径见界面的 `env_path`）。密钥在磁盘上是**明文存储，不是加密存储**。URL 环境变量为 `GOOGLE_BASE_URL`、`DEEPSEEK_BASE_URL`、`ZHIPU_BASE_URL`、`OPENAI_BASE_URL`、`ANTHROPIC_BASE_URL`、`OPEN_ROUTER_BASE_URL`、`XAI_BASE_URL`。DeepSeek 使用 `DEEPSEEK_API_KEY`，默认 URL 为 `https://api.deepseek.com`；Zhipu 使用 `ZAI_API_KEY`，默认 URL 为 `https://open.bigmodel.cn/api/paas/v4`。**Test configuration** 可用服务端已有 Key 测试修改后的 URL，不返回 Key，也不保存草稿。
- 保存 Provider 配置**不会自动切换运行模型**。在 `config/artemis.jsonc` 中设置 `provider: "deepseek"` 或 `provider: "zhipu"`、账户支持的模型名称及所需 fallback/节点覆盖。模型显式配置的 `base_url` 优先于 Provider URL。覆盖密钥后，新获取的客户端使用新 Key，正在运行的任务保留原客户端。API 兼容不代表图像、视频或专用空间定位能力兼容；视觉节点需选择相应能力的模型。
- **Recommended Tasks → Manage recommended tasks** 支持新建、查看完整列表及详情、编辑和确认删除。变更通过 SQLite 持久化；内置模板只初始化一次，删除后不会因重启恢复，删除全部模板后仍保持为空。**Use task** 只填入任务，不自动执行。
- Pro 模板可选保存 **Expected Output** 格式或 schema（模板 API 字段为 `expected_output`）。**Use task** 会同时回填该字段；应用未设置输出预设的模板时会清空上一模板的值。留空即不设置预设，Flash 模板不显示此字段。
- 模板应用图标使用 Material Symbols。编辑器提供带应用名称的下拉选项和实时图标预览，复用现有应用注册表，并保留已保存模板使用的图标。
- Setup 只列出检测到的 Android 设备及连接/锁屏状态，不再选择 active 设备。请在首页或 Workspace 下发区域选择 **Target Android device**。已授权且连接正常的锁屏设备也能下发任务：任务取得设备执行锁后，先唤醒并尝试解除非安全锁屏，再初始化 UI 自动化。如果需要 PIN、密码或图案，或无法确认已解锁，则任务失败，不尝试输入凭据。断连后需重新选择，不会静默切换到其他设备；切换只影响新任务，不改变已排队或运行中的任务。
- **Active Queue → Cancel queued task** 会取消该任务及其设备预约，不影响其他排队或运行中的任务。**Stop this task** 用于停止执行。通过 API 删除排队会话也会先取消设备预约，再删除历史；正在启动或运行的任务必须先停止并结束，才能删除历史和产物（仍在执行时返回 HTTP 409）。取消或删除后的任务会从实时界面缓存中清除，不会重新显示为运行中任务。
- **Past Runs & History → Retry this task**：悬浮在失败或已取消记录上时，Delete 左侧会显示 Retry；桌面列表和窄屏 Task Queue 均支持。重试以原任务目标、设备、Flash/Pro 模式、已保存的 Pro 参数、Expected Output 和 Outputter 开关创建新 run，不覆盖原记录，也不从中断步骤续跑；显式关闭的 Outputter 保持关闭。新 run 将输出配置保存在 `device_info.output_config`；旧记录若未保存该配置，请从首页重新选择模板或填写 Expected Output 后下发，重试不会从当前模板猜测原配置。未保存的其他启动选项使用当前默认值。提交期间禁用重复重试；设备不可用或服务拒绝提交时，在列表中显示错误。


<a id="mcp-setup"></a>
<a id="mcp"></a>
<details>
<summary><b>Codex / Antigravity / Claude Code / Windsurf MCP 配置（点击展开）</b></summary>

<br>

ARTEMIS 内置原生 **Model Context Protocol (MCP)** 服务。只需将以下配置加入你的 IDE 配置文件中，即可在编写代码时直接驱动真机：

### 1. 一键自动安装到 IDE（推荐）

运行 `./start.sh`（macOS/Linux）或 `.\start.bat`（Windows PowerShell）启动脚本时，会主动询问是否自动挂载全局 MCP 与测试行为准则（支持跳过并在之后随时手动执行以下命令挂载）：

```bash
# 一键安装全局 MCP 服务与 Rules 到 Antigravity / Jetski：
uv run artemis mcp --install antigravity

# 或一键安装到所有支持的 AI IDE（包括 Codex）：
uv run artemis mcp --install all
```

> **提示**：你也可以在首次运行 `uv run artemis init` 配置向导时，交互式完成 IDE 的 MCP 自动挂载。
> **进阶提示**：如果希望在任意目录下都不需要加 `uv run` 就能全局直接使用 `artemis` 命令，可在项目根目录下执行一次 `uv tool install -e .`。

### 2. 手动配置（可选）

如果你习惯手动复制配置，可运行 `uv run artemis mcp --generate-config <client>`（例如 `codex` 或 `antigravity`）获取对应的 TOML 或 JSON 配置。请将 `command` 填写为项目下 `.venv` 虚拟环境中的 Python 绝对路径，并将 `/path/to/artemis` 替换为项目实际路径：

* **Codex** (`~/.codex/config.toml`)：
```toml
[mcp_servers.artemis]
command = "/path/to/artemis/.venv/bin/python"
args = ["-m", "mcp_server"]
cwd = "/path/to/artemis"

[mcp_servers.artemis.env]
PYTHONUNBUFFERED = "1"
PYTHONPATH = "/path/to/artemis"
```

* **Antigravity** (`~/.gemini/jetski/mcp_config.json`)：
```json
{
  "mcpServers": {
    "artemis": {
      "command": "/path/to/artemis/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/artemis",
      "env": {
        "PYTHONUNBUFFERED": "1"
      },
      "tools": {
        "mobile_run_task": { "eager": true },
        "mobile_manage_task": { "eager": true },
        "mobile_get_device_state": { "eager": true },
        "mobile_inspect_trace": { "eager": true },
        "mobile_diagnose": { "eager": true }
      }
    }
  }
}
```

* **Claude Desktop** (`claude_desktop_config.json`)：
```json
{
  "mcpServers": {
    "artemis": {
      "command": "/path/to/artemis/.venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/path/to/artemis"
    }
  }
}
```

### 3. 挂载智能体行为规范 Rules（强烈推荐）

为使 AI 编程助手具备资深移动端测试工程师的严谨思维，避免凭空臆测 UI 交互，我们提供了专属的测试思维行为规范文件 [`mcp_server/rules.md`](./mcp_server/rules.md)（涵盖**可运行代码原则与真机探索**、**Flash 与 Pro 任务路由策略**、**延迟与时间补偿机制**以及**“动态优先、坐标兜底”定位模式**）。

你可以将 [`mcp_server/rules.md`](./mcp_server/rules.md) 挂载或复制到你的 AI IDE 规则配置中：
* **Antigravity**：将 `rules.md` 内容添加至工作区规则（Workspace Rules）或全局规则设置中。
* **Claude Code**：运行 `artemis mcp --install claude` 自动安装规则至 `~/.claude/rules/artemis.md`（只安装到单一位置——Claude Code 会同时加载 `~/.claude/CLAUDE.md` 与 `~/.claude/rules/*.md`，重复安装会浪费上下文）。
* **Cursor**：将内容复制到 `.cursorrules` 文件或在 `.cursor/rules/artemis.mdc` 中创建新规则。
* **Codex**：将内容添加至 `~/.codex/AGENTS.md`（或当前生效的 `AGENTS.override.md`）。
* **Windsurf / OpenClaw**：将内容添加到工作区规则或全局 System Prompt 中。

> 更多规范设计细节与 MCP 架构说明，请参阅 [MCP Server 文档](./mcp_server/README.md)。

### 4. 在 IDE 中体验真机协同
在 Codex / Antigravity / Claude Code 对话框中直接输入：
> *"请帮我把刚刚修改的代码编译成 APK 并安装到手机上，打开登录页面输入测试账号，验证登录后是否有异常弹窗，并把最终页面截图回传。"*

</details>

<a id="python-sdk"></a>
<details>
<summary><b>Python SDK 集成（点击展开）</b></summary>

<br>

开发电脑只需安装零运行时依赖的薄客户端；ADB、Agent、模型与图像处理全部留在设备主机：

```powershell
uv add "artemis-client @ git+https://github.com/google/artemis.git#subdirectory=packages/artemis-client"
```

```python
import asyncio
from artemis_client import ArtemisClient


async def main():
    client = ArtemisClient(
        "http://artemis-host:8000",
        device_serial="emulator-5554",  # 可选：指定目标设备序列号（不传则自动选择空闲设备）
        default_profile="flash",  # "flash" 极速校验 或 "pro" 深度推理自愈
    )

    result = await client.run(
        "打开系统设置，进入『电池』页面，验证是否正常显示电量百分比，确认页面无异常报错弹窗。",
    )

    assert result.succeeded, f"测试执行失败: {result.error or result.status}"
    print(f"✅ 测试通过！设备: {result.device_serial} | Trace ID: {result.trace_id}")


if __name__ == "__main__":
    asyncio.run(main())
```

已保存的模板可用字符串参数运行，无需传入原始 goal：

```python
result = await client.run(template_id="battery-check", args={"APP": "Settings"})
# 或：handle = await client.submit(template_id="battery-check", args={"APP": "Settings"})
# result = await client.wait_for_task(handle.task_id)
```

`goal` 与 `template_id` 互斥；`args` 只用于模板。必须提供所有声明的参数，
参数值可以是空字符串。服务端只展开一次 `${APP}`，`$${APP}` 保留字面 `${APP}`，
SDK 不在本地展开参数。显式传入的 `profile` 或 `expected_output` 覆盖模板配置
（`expected_output=None` 或 `""` 会清除模板中的预期输出），不传则继承模板；
直接传 goal 时仍采用客户端的 `default_profile`（默认 flash）。
`Task(goal="...")` 默认 pro；通过 `client.run_task(task)` 提交
`Task(template_id="...", args={...})` 时，除非显式设置 `profile`，否则沿用模板模式。

</details>

## 使用方式

<p align="center">
  <img src="./docs/assets/artemis-ui-showcase.png" alt="Artemis 可视化控制台" width="100%" />
  <br />
  <sub><b>控制台功能概览</b>：<b>① 视图切换</b>（主页与工作区） · <b>② 运行模式与回放</b>（Flash/Pro 状态与视频回放） · <b>③ 实时感知推理流</b>（动作感知、目标坐标与结构化总结） · <b>④ 提示词输入坞 (Prompt Dock)</b>（自然语言下发） · <b>⑤ 任务队列看板</b>（生命周期与历史回溯）</sub>
</p>

* **Web 可视化测试控制台 (`uv run artemis ui`)**：集成设备实时投屏与交互面板，支持通过自然语言下发测试用例，实时观测推理步骤、操作轨迹、截图留存与异常状态回放；支持在任意终端使用 `uv run artemis restart`、`uv run artemis stop`、`uv run artemis status` 一键重启、关停或查看服务状态；
* **原生 MCP 协议 (IDE 协同)**：作为标准 MCP 服务器接入 **Antigravity、Claude Code、Windsurf** 等开发环境，在 IDE 中直接驱动真机完成自动化测试与 Bug 复现验证；
* **开发者命令行 CLI (`uv run artemis run`)**：支持通过终端直接执行自动化测试用例、探索性稳定性巡检或 AndroidWorld 基准评测，提供高保真结构化终端输出；
* **Python SDK**：作为标准 Python 库集成至现有自动化测试框架（如 pytest）或 CI/CD 流水线，提供基于 Pydantic 的强类型结构化结果与断言支持。

### 可选 Yuri 设备插件（Flash / Pro）

Yuri 插件补充 OCR、设备配置、应用数据管理、代理及 root RPC，保留原有 Android UI 操作链路。**普通任务不加载插件、不探测 Yuri、不增加 Yuri 工具**；设备安装了 YuriClient 也不会自动启用。

启用须同时满足：配置允许、原始用户任务明确要求使用 Yuri、当前目标设备的只读 RPC `ping` 成功且版本兼容。否定指令、引用、代码示例、页面及工具输出不能启用插件；启用状态不跨任务继承。

在 `config/artemis.jsonc` 的 `agent` 中设置：

```json
"yuri": {
  "enabled": true,
  "allowed_tools": ["yuri_ping", "yuri_app_is_installed", "yuri_find_text", "yuri_click_text", "yuri_job_poll"],
  "identity": "shell",
  "compatible_versions": ["1.8.6", "1.8.7"]
}
```

任务示例：`使用 Yuri 检查 com.example.app 是否已安装`，或 `通过 Yuri 的 OCR 找到登录按钮`。仅开启配置而未明确请求 Yuri 时，仍走原有流程。SDK 可通过 `AgentConfigBuilder.with_yuri(YuriConfig(...))` 配置；`YuriConfig` 位于 `artemis.config.yuri`。UI、CLI、MCP 和 SDK 共用任务启动门控。

* **设备准备**：自行安装并启动兼容的 YuriClient，保证 `yuri.rpc` 服务就绪及 ROM/SELinux 权限允许连接。ARTEMIS 不自动安装、启动、重启或提权来修复 probe；请求 Yuri 但服务不可用时明确失败，不静默替换能力。分发包的 `yuri` 是宿主机 wrapper，插件直接调用已安装 APK 的 Java CLI，不向手机推送脚本。
* **能力权限**：`allowed_tools: null` 使用查询与 OCR 点击集合；`[]` 不允许任何工具。改机、reset、安装/卸载、清数据、备份/恢复、settings 写入、代理、root shell 及重复的原生 UI RPC 需显式列入白名单。定义与参数见 `artemis/tools/yuri.py`；角色 `denylisted_tools` 同时约束声明和直接执行。改机/reset 还要求有效的 `ro.yuri.rom.version`。
* **改机参数**：`yuri_device_modify` 支持先改机、后安装目标应用，无需目标包已安装。`brand` 是大小写匹配的模板名，例如 `Google_Pixel6`、`Samsung_GalaxyA90`，不是厂商品牌 `google`、`samsung`。
* **客户端 IP（Yuri 1.8.7）**：白名单加入 `yuri_network_client_ip`，调用参数为 `{}`。同步调用 `network.clientIP`，返回 YuriClient 进程的公网出口 IP 字符串；两个查询服务均失败时为 `null`。不是局域网地址，也不能据此证明其他应用 UID 的代理出口。无需 Job 轮询。
* **Clash**：`yuri_network_start_clash` 参数为 `{"clash":"<代理 URL 或节点 YAML 的 UTF-8 Base64 编码>"}`，`yuri_network_stop_clash` 参数为 `{}`。实际流量路由取决于设备端 Clash 模板；这两个工具启停 Clash 进程，不等同于 `yuri_network_start_proxy` / `yuri_network_stop_proxy` 的 UID 流量重定向。
* **执行语义**：查询 `false`、OCR 未命中 `null` 是正常答案；动作 `false`、shell 非零状态、Job `failed` 或 `done/false` 是失败。Yuri 变更单次派发、独占一个动作回合，不进入快速 burst，也不自动重试；系统操作使用参数和设备能力前置条件，不套用 UI 像素检查。
* **长任务**：拿到提交回执后有界轮询至完成。轮询超时保留任务专属 `job_id` 和结果未知状态，可用 `yuri_job_poll` 继续查询，启用 Job 能力时也应允许此工具。提交阶段若未收到回执，则无法取得 handle，端上是否执行仍未知，不能自动重提。Yuri 重启、换设备或换任务后旧 handle 无效；取消 ARTEMIS 不代表端上 Job 已取消。
  Job 绑定 PID、启动 tick 和可执行映像地址范围，不使用改机会虚拟化的 `boot_id`。若 ROM 隐藏这些进程元数据，必须显式配置 `identity: "su_brt"` 或 `"su"`；元数据不可验证时在提交前失败，不自动提权。
  `PROCESS_UNAVAILABLE` / `Cannot identify Yuri process for jobs` 也可能表示 shell 看到的代码地址被屏蔽为 `1`，并不表示 Yuri 未运行。修改 `agent.yuri.identity` 后重新发起 Web 任务即可读取新配置；运行中的任务不会热更新身份，无需重新部署 Web/API 服务。
* **参数与制品**：OCR 点/词框输出统一为设备像素坐标；截图取回宿主机制品路径，app-private 文件可能要求显式 root 身份。安装支持安全的设备路径或无 query/fragment 的 HTTP(S) APK/XAPK URL。Yuri 内部存在 shell 字符串拼接，因此相关参数拒绝不安全字符，不能以 JSON 转义代替端上安全性。备份返回成功仅表示 Yuri 调用返回，仍需独立验证归档完整性。
* **真机端到端验收**：`scripts/yuri_real_device_acceptance.py` 使用实际配置的模型，通过生产 `Agent.run_task(profile="flash"/"pro")` 执行代理、改机和普通任务六个场景，不 mock 模型或 RPC。除了任务完成状态，还检查执行记录中确实出现 Yuri 动作、实际出口 IP、目标应用 UID 可见的属性，以及普通任务没有 Yuri probe/RPC。root UID 的真实属性和缓存 profile 都不能单独证明改机生效。
  在已启动 Yuri 1.8.6、已有 `sec.prop`、支持 `su_brt` 且可联网的设备上运行：
  ```bash
  uv run --no-sync python scripts/yuri_real_device_acceptance.py \
    --device-id SERIAL --modes flash pro --output-dir traces/yuri-acceptance \
    --proxy-url-file /private/path/to/ss-uri.txt
  ```
  输入文件包含 SS URI；支持此次验证的 simple-obfs HTTP/TLS 节点。脚本临时使用无 TUN 的回环 SOCKS 模板和 Yuri UID 代理，并将 profile、代理文件、时区和时间设置恢复至测试前状态，不调用全局 NAT flush。`restore.json` 保存恢复数据；异常中断后可用同一输出目录及 `--restore-only` 恢复。报告含真实 session、执行记录、截图及 Checker 结论；Checker inconclusive 会单独标明，设备侧验收不冒充 Checker 通过。输入、恢复数据及正常 agent traces 可能包含凭据，应使用私有目录保存。


<a id="on-device-helper"></a>
## ARTEMIS 会在手机上安装什么

首次在某台设备上执行任务时，ARTEMIS 会安装 **Artemis Accessibility Helper**：一个用于读取屏幕布局的小型无障碍服务，
不占用 UiAutomation 连接。使用 UiAutomation 的工具需要启用 `FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES`，否则可能使该服务暂停运行。
手机上会出现一条折叠的"Artemis test helper is running"通知，以及"设置 > 无障碍"里的一个新条目，都是它。
它只监听手机本机回环地址，不向外发送任何数据。

* 预先安装（避免首个任务多等约 3 秒）：`uv run artemis helper install`
* 查看状态：`uv run artemis helper status` / `uv run artemis doctor`
* 随时移除：`uv run artemis helper uninstall`
* 改用 UIAutomator2：在 `.env` 中设置 `ARTEMIS_HIERARCHY_BACKEND=uiautomator`
* 禁止自动安装：在 `.env` 中设置 `ARTEMIS_HELPER_AUTO_INSTALL=false`

任务中途 helper 失效时，ARTEMIS 会回退到 UIAutomator2，并在任务时间线、`mobile_manage_task` 状态和最终报告里明确说明。

<a id="benchmarks"></a>
<a id="基准评测"></a>
## 基准评测：AndroidWorld (SOTA 99%+)

Artemis 在 Google Research 发布的 [AndroidWorld](https://github.com/google-research/android_world) 基准评测中取得 **99%+ 任务完成率**。该评测涵盖 20+ 款应用与 100+ 项多步任务。

<p align="center">
  <img src="./docs/assets/androidworld_leaderboard.png?v=2" alt="AndroidWorld 评测基准对比" width="100%" />
</p>

## ARTEMIS 是如何建构的

* **执行前校验与动作序列**：Pro 在下发单个动作前，通过实时 UI 树和像素校验目标。快速动作序列用于处理瞬态控件，无需等待下一轮模型响应。
* **元素定位**：结合无障碍树、OCR 和视觉模型，支持 Canvas、Compose、Flutter 等自绘界面。
* **共享历史压缩**：Flash 和 Pro 将较早的截图替换为视觉摘要，并把已完成步骤压缩为可检索的历史分块。上下文阈值决定何时替换原始记录。

<p align="center">
  <img src="./docs/assets/artemis_architecture_diagram.png" alt="ARTEMIS 架构系统示意图" width="100%" />
</p>

## 运行模式：Flash vs. Pro

ARTEMIS 提供两种运行模式以适应不同的自动化需求：

* **Flash 模式 (`--profile flash`)**：使用历史压缩的响应式循环（单步约 3–5 秒）：单个模型观察实时屏幕、思考、执行，不经过图编排，适合常规确定性 UI 操作。默认不限步数（`agent.flash.max_turns`，0 表示不限），因为历史是被压缩而不是被截断：Flash 与 Pro 共用同一套会话记录账本（相对测试时间 `T+mm:ss`、截图折叠为视觉摘要、更早的步骤分块归档并可通过 `search_history` / `replay_steps` 按需召回），并可调用 `video_analyzer` 分析整段会话录屏；对自动消失的控制栏、toast 等瞬态控件，用 `click_sequence` 把多次点击串成一个原子序列。*局限性*：没有任务计划与笔记、没有执行前安全网、没有检查点校验与最终报告、不能执行 ADB 命令。
* **Pro 模式 (`--profile pro`)**：包含计划和校验的执行流程（单步约 15–40 秒），由多智能体图编排：**Planner** 维护一份带里程碑和 `verify` / `assert` 检查项的 Markdown 任务计划；**Operator** 按计划执行，拥有全套工具（Explorer 元素定位，其 `flash` / `pro` / `ultra` 三档感知深度是按运行模式设置的用户配置——`config/artemis.jsonc` 里的 `pro.explorer.mode` / `flash.explorer_mode` 或 `--explorer-pro-mode`——智能体自身不会选择档位；笔记、历史召回、视频分析、ADB 诊断）。单个动作执行前都经过 **Safety Net** 校验（XML 优先、像素兜底），而一轮里的多个动作则作为**快速动作序列 (fast-action burst)** 连发，赶在瞬态控件消失前完成操作。动作被拦截或失败时会打开一条**执行事故 (execution incident)**，持续留在 Operator 的上下文里直到后续动作执行成功，恢复由 Operator 自己完成，不再有独立的修复智能体。只读的 **Checker** 校验计划中的检查点，并在退出前对照原始目标做终审（`--verification-level`：`off` / `final`（默认）/ `checkpoints` / `strict`），计划里程碑的改动会得到建议式复核。支持 100+ 步的长程复杂业务流、`[Loop:continuous]` 持续监控以及可选的书面报告。

## 路线图

- [ ] **Android Studio 深度集成**：推出官方 IDE 插件与协同工作流，支持在 Android Studio 内直接进行自动化测试、设备交互与断点调试。
- [ ] **iOS 跨平台支持**：将视觉感知与自动化执行引擎拓展至 iOS 真机与模拟器。
- [ ] **端侧轻量化模型**：支持离线运行的轻量级 Edge VLM，实现低延迟与隐私安全的本地自动化。
- [ ] **实时语音双工交互**：支持自然语音下发任务与实时打断（Barge-in）控制。

## 社区与贡献

欢迎通过以下方式参与项目建设：
* **Star 本项目**以关注最新进展与更新
* 加入 [Discord 社区](https://discord.gg/wF2FN4WHGY) 参与技术探讨与功能建议
* 提交 [Issue](https://github.com/google/artemis/issues) 反馈 Bug，欢迎发起 [Pull Request](https://github.com/google/artemis/pulls) 贡献代码

## 开源许可证

本项目基于 [Apache License 2.0](LICENSE) 协议开源。

### 第三方代码

非 Google 所有的代码位于 [`third_party/`](third_party/) 目录下，每个上游项目一个子目录，并各自附带 `LICENSE` 与 `METADATA`。

- [`third_party/mobile_use`](third_party/mobile_use/) – 来自 Minitap, Inc. 的 [mobile-use](https://github.com/minitap-ai/mobile-use) 的部分代码，Apache License 2.0。
