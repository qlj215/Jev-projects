# Jev 文本判断工具

Python 3 标准库实现，无需安装依赖。使用 `jev-latest`。深色网页版支持 Noul（是非判断）、Choice（选项判断）和 Score（分级评分）；命令行版保留原有是非判断用法。

## 网页版（推荐）

需要 Python 3.9 或更新版本。首次下载并启动：

```bash
git clone https://github.com/qlj215/Jev-projects.git
cd Jev-projects
python3 -B web.py
```

已有项目时，直接在项目目录运行 `python3 -B web.py`。

浏览器打开 **http://127.0.0.1:8765**。点击“API Key 设置”，输入并保存一次，以后重新启动也不必重复输入。当前环境已设置 `TYPESAFE_API_KEY` 时，无需先输入即可使用。

Windows PowerShell 中也可在项目目录执行 `py -3 -B web.py`。使用 `--port 8766` 可更换端口；按 Ctrl+C 停止服务。

网页版保存的 Key 优先于环境变量，保存在运行 Python 的用户目录 `~/.config/jev-local/api-key`，为明文文件；WSL 下目录权限 700、文件权限 600，Windows 下使用用户目录的系统权限。文件在项目之外，不会随项目提交 Git。浏览器不使用 localStorage 或 Cookie 保存 Key，服务也不会将已保存 Key 返回前端。“删除已保存 Key”会删除该文件，若仍有环境变量则继续使用环境变量。WSL 与 Windows 各自的用户目录和环境变量独立。

网页仅监听本机 `127.0.0.1`，支持多行文本。运行期间保持终端打开。本工具不修改现有 Agent 模型配置。命令行版仍仅从环境变量读取 Key。

## 三种网页判断方式

选择判断类型，输入文本和问题，点击“开始判断”。“填入示例”会填入当前类型的示例；三种类型共用文本框，切换时分别保留各自的问题和选项/等级草稿（仅保留在当前页面内存中）。

| 类型 | 额外输入 | 结果 |
| --- | --- | --- |
| Noul | 无 | 是、否的概率；不另报置信度 |
| Choice | 每行一个候选选项，2–255 个；可写 `选项名称 | 说明` | 选中选项、所有选项的概率、置信度 |
| Score | 每行一个等级说明，从低到高排列，2–10 级 | 加权分数、实际量程、各等级概率、置信度 |

Choice 示例选项：

```text
账务 | 付款、退款、发票问题
物流 | 配送进度、包裹丢失
技术 | 网站或软件故障
其他 | 不属于上述团队的问题
```

Score 示例等级：

```text
仅外观问题，不影响任何功能
部分功能受损，但存在可用的替代方法
核心功能完全不可用，且没有替代方法
```

Score 等级自动从 0 编号：上例的量程为 0–2。分数为各等级编号的概率加权平均，不是百分比，也不是固定的十分制。置信度反映概率分布的集中程度，与选项概率不同。详情见官方 [Choice](https://docs.typesafe.ai/primitives/choice)、[Score](https://docs.typesafe.ai/primitives/score) 文档。

修改代码后需重启 `web.py` 并刷新浏览器。运行离线测试（临时目录和假 Key，不调用计费 API）：

```bash
python3 -B -m unittest -v test_jev.py test_web.py
```

## 命令行：WSL / Bash

```bash
cd Jev-projects
python3 jev.py
```

按提示分别输入文本和问题；也可直接传参：

```bash
python3 jev.py --text '我想取消订单，请把钱退给我。' --question '这段文本是否要求退款？'
```

API Key 必须已存在于当前终端的 `TYPESAFE_API_KEY` 环境变量中。如果新终端未设置，可用隐藏输入临时设置（不会把密钥字面值写入命令历史）：

```bash
read -rsp 'TypeSafe API Key: ' TYPESAFE_API_KEY
echo
export TYPESAFE_API_KEY
```

## Windows PowerShell

安装 Python 3，且当前 PowerShell 已设置 `TYPESAFE_API_KEY` 后：

```powershell
cd Jev-projects
py -3 jev.py
py -3 jev.py --text '我想取消订单，请把钱退给我。' --question '这段文本是否要求退款？'
```

WSL 和 Windows 的环境变量可能不同。PowerShell 可通过隐藏输入设置当前会话变量：

```powershell
$jevSecret = Read-Host 'TypeSafe API Key' -AsSecureString
$env:TYPESAFE_API_KEY = [System.Net.NetworkCredential]::new('', $jevSecret).Password
Remove-Variable jevSecret
```

## 行为

- 命令行 Key 仅从环境变量读取；网页版可额外保存本机 Key。Key 只用于官方 HTTPS 接口认证，不打印；工具不读取 `.env`。
- 工具不保存输入或响应，不修改 Agent 配置。`.gitignore` 排除常见密钥文件。
- 空输入、缺少 Key、网络失败或异常响应会给出简短错误并返回非零退出码。
- 每次执行发送一次请求，超时 60 秒；限流或服务繁忙时可稍后手动重试。
- 无参数模式每项输入一行；多行文本可通过 `--text` 传入。

依据官方 [HTTP API](https://docs.typesafe.ai/api) 和 [Noul 文档](https://docs.typesafe.ai/primitives/noul)：Noul 返回的是回答为“是”的概率，没有单独的 confidence 字段。接近 0.5 表示“是”和“否”的概率接近。
