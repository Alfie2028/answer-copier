# 头歌图文作业 一键提交 / 拉取 工具（可迁移板块）

把"答案账号"已提交的图文作业拉取到本地，本地修改后，用"目标账号"一键上传提交。

## 依赖
- Python 3.9+（已在 PATH）
- 安装库：`pip install playwright requests`
- 初始化浏览器：`python -m playwright install msedge`（如用 Edge 内核，可跳过或用默认 chromium）

## 使用方法
1. 双击 `start_gui.bat` 打开图形界面。
2. 填入：
   - **答案账号 cookie**（格式 `autologin_trustie=...; _educoder_session=...`，用于拉取）
   - **目标账号 cookie**（用于一键提交）
   - **课程图文作业链接**，形如 `https://w.educoder.net/classrooms/xxxx/common_homework`
   - **本地答案根文件夹**（每个图文作业一个同名子文件夹，如 `9、软件工程导论-软件项目管理/`）
3. 点击按钮：
   - **列出作业**：读取课程下全部图文作业（名称 + id），用于核对匹配。
   - **拉取答案**：用答案账号把所有已提交作业的文件下载到「根文件夹/作业名/」。
   - **一键提交**：用目标账号对每个作业上传「根文件夹/作业名/」下的本地文件并点击提交。
4. 完成后到平台核对各作业提交状态。

## cookie 获取方式
浏览器登录 educoder 后，打开开发者工具(F12) → 控制台执行：
```
document.cookie
```
复制返回的字符串（含 `autologin_trustie=...; _educoder_session=...`）填入界面。
（不要外泄 cookie，仅本机使用。`.env.example` 为占位示例，可自行配置。）

## 原理说明
- 目标账号点"提交作品"→ 新标签页打开 `/post` 提交页；已提交账号点"修改作品"→ `/edit` 编辑页。
- 提交页/编辑页为 antd 多文件上传组件，脚本通过注入本地文件完成上传，再点击"提交"。
- 已提交文件可从编辑页经 OSS 签名链接下载（即"拉取"）。
- 作业列表通过 `homework_commons` 接口获取（带平台签名头），稳定可靠。

## 目录结构
```
图文作业一键提交/
├─ common_homework.py       核心逻辑（提交/拉取/列作业）
├─ common_homework_gui.py   图形界面
├─ start_gui.bat            启动脚本
├─ .env.example             cookie 占位示例（不含真实值）
└─ README.md                本说明
```

## 注意
- 脚本会自动打开 Edge 完成浏览器操作（有头、窗口移出屏幕规避风控）。
- 提交会真实提交目标账号作业，请确认本地文件无误后再执行。
- cookie 含会话凭据，请妥善保管，勿随板块一起外发。
