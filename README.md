# 头歌实践教学平台自动化工具（Educoder Automation Tools）

针对头歌（Educoder）实践教学平台的可视化自动化工具集，用 Python + Playwright 实现，凭账号 Cookie 鉴权，无需密码，无需手动操作浏览器即可批量完成课程作业。

## 包含三个工具

### 1. 答案搬运器 Answer Copier（`answer_copier_gui.py`）

把一个账号（**答案账号**）某课程的选择题答案，自动补全到另一个账号（**目标账号**）的同课程，使目标账号所有选择题全部通过。

**功能流程**
1. 填答案账号 Cookie → 自动反查身份 → 导出该课程全部选择题答案
2. 填目标账号 Cookie → 解析其当前关卡链
3. 按关卡标题匹配答案，提交所有**未通过**的选择题关（答错用平台回吐标准答案兜底）
4. 自动跳过已通过关 / 无答案关 / 已完成实验，不覆盖已完成作业

**输入**
| 输入 | 说明 |
|---|---|
| 答案账号 Cookie | 有完整答案账号的整段 Cookie（含 `_educoder_session`） |
| 目标账号 Cookie | 待补全账号的整段 Cookie |
| 课程链接 | `https://w.educoder.net/classrooms/{课堂code}/...` |

### 2. 自动点击评测 Auto Click Judge（`auto_click_judge_gui.py`）

对**画图 / 代码类关卡**（无法用 API 提交、必须走界面评测）自动遍历大关内所有小关，逐个点击"评测"按钮，间隔后进入下一关，免值守完成整关评测。

**功能流程**
1. 填账号 Cookie + 大关任务链接（可多行，逐大关）
2. 自动解析该大关完整关卡链（先沿 prev 回退到头，再沿 next 前进补全）
3. 逐个进入关卡 → 点"启动环境"（如需）→ 点击"评测"按钮
4. 等满平台限定的评测间隔（默认 30s）→ 强制进入下一关继续评测
5. 整个大关一个页面连续导航不关闭，单关异常不中断

**输入**
| 输入 | 说明 |
|---|---|
| 账号 Cookie | 待评测账号的整段 Cookie |
| 大关任务链接 | `https://www.educoder.net/tasks/{课程code}/{作业id}/{关卡id}`，每行一个 |
| 间隔（秒） | 平台小关评测间隔，默认 30 |

### 3. 图文作业一键提交 / 拉取（`图文作业一键提交/`）

把"答案账号"已提交的图文作业拉取到本地，本地修改后，用"目标账号"一键上传提交。

**功能流程**
1. 填答案账号 Cookie、目标账号 Cookie、课程图文作业链接、本地答案根文件夹
2. **列出作业**：读取课程下全部图文作业（名称 + id），勾选要处理的作业
3. **拉取答案**：用答案账号把所有已提交作业的文件下载到「根文件夹/作业名/」
4. **一键提交**：用目标账号对每个作业上传本地文件并点击提交

详见 [`图文作业一键提交/README.md`](图文作业一键提交/README.md)。

## 运行

- 双击对应 `.bat`：
  - `answer_copier.bat` → 答案搬运器
  - `auto_click_judge.bat` → 自动点击评测
  - `图文作业一键提交\start_gui.bat` → 图文作业工具
- 或命令行：`python answer_copier_gui.py` / `python auto_click_judge_gui.py`

## 依赖环境

- Windows 本地 + Python 3.9+（含 tkinter）+ `playwright` + `requests`
- 浏览器内核：`python -m playwright install msedge`（或 chromium）
- 网络可达 `educoder.net`；凭 Cookie 鉴权，无需密码

## 目录结构

```
answer-copier/
├── answer_copier_gui.py      # 答案搬运器
├── answer_copier.bat
├── auto_click_judge_gui.py   # 自动点击评测
├── auto_click_judge.bat
├── README.md
├── educoder_reminder/        # 共享依赖模块（签名、鉴权、导出、提交）
│   ├── auth.py
│   ├── client.py
│   ├── errors.py
│   ├── export.py
│   ├── login.py
│   ├── submit.py
│   ├── _oslock.py
│   └── __init__.py
└── 图文作业一键提交/           # 图文作业一键提交 / 拉取
    ├── common_homework.py
    ├── common_homework_gui.py
    ├── start_gui.bat
    ├── .env.example
    └── README.md
```

## Cookie 获取与安全

浏览器登录 educoder 后，F12 → 控制台执行 `document.cookie`，复制含 `autologin_trustie=...; _educoder_session=...` 的整段字符串填入界面。

- Cookie 即会话凭据，**勿外发、勿提交到公开仓库**。
- `auto_click_judge_gui.py` 顶部保留了一个调试用的 `DEFAULT_COOKIE` 默认值，分发或上传前请将其清空为 `''`。
- `.env.example` 仅为占位示例，不含真实 Cookie。

## 快速开始（新机器 / 全新 clone）

1. 安装 Python 3.9+（安装时勾选 **Add Python to PATH** 和 **py launcher**）。
2. 安装依赖：
   ```
   pip install -r requirements.txt
   ```
3. 安装浏览器内核（脚本默认调用系统 Edge，无需下载 chromium；若需无头自动登录兜底，再执行）：
   ```
   python -m playwright install chromium
   ```
4. 双击对应 `.bat` 启动图形界面：
   - `answer_copier.bat` → 答案搬运器
   - `auto_click_judge.bat` → 自动点击评测
   - `图文作业一键提交\start_gui.bat` → 图文作业工具

`.bat` 会自动通过 `py -3` 或 `python` 命令定位解释器，不再硬编码本机路径，换机器直接可用。

## 常见问题

- **双击 `.bat` 闪退 / 提示"未找到 Python"**：Python 未加入 PATH，重装时勾选 Add to PATH，或改用 `py -3 xxx_gui.py` 手动启动。
- **启动报 `ModuleNotFoundError: No module named 'playwright'`**：依赖装到了别的 Python 环境里，执行 `py -m pip install -r requirements.txt`。
- **浏览器窗口起不来 / 报 Executable doesn't exist**：执行 `python -m playwright install chromium`，或确认系统已装 Edge（`channel='msedge'` 依赖系统 Edge）。
- **拉到新机器后没有"图文作业一键提交"目录**：确认已 `git pull` 到最新，该目录已纳入版本管理。
