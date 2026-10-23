# 头歌实践教学平台自动化工具（Educoder Automation Tools）

针对头歌（Educoder）实践教学平台的可视化自动化工具集，用 Python + Playwright 实现，无需手动操作浏览器即可批量完成课程作业。凭账号 Cookie 鉴权，不需要密码。

## 包含两个工具

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

## 运行

- 双击对应 `.bat`（用系统 Python，含 tkinter）
- 或命令行：`python answer_copier_gui.py` / `python auto_click_judge_gui.py`

## 首次使用：迁移依赖模块

两个工具都依赖 `educoder_reminder` 模块（签名、鉴权、导出、提交）。首次使用双击 **`migrate_deps.bat`**，自动把依赖模块拷贝到本目录。

## 依赖环境

- Windows 本地 + Python（含 tkinter）+ `playwright` + `python-dotenv`
- 网络可达 `educoder.net`；凭 Cookie 鉴权，无需密码

## 目录结构

```
头歌选择快答/
├── answer_copier_gui.py      # 答案搬运器
├── answer_copier.bat
├── auto_click_judge_gui.py   # 自动点击评测
├── auto_click_judge.bat
├── migrate_deps.bat          # 依赖迁移
├── README.md
└── educoder_reminder/        # 依赖模块
```

## 迁移到其他机器

拷走整个目录（含 `educoder_reminder\`），目标机器装好 Python / playwright 后双击 `.bat` 即可。
"# answer-copier" 
