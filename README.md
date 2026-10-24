# 手作包包记账本 · 本地版

按指定参考站复刻界面与交互，保留「订单台账、收支明细、月度汇总」三个页签。FastAPI + Vue 3 + SQLite，账目与照片保存在电脑，手机通过同一局域网访问。安装依赖时需要联网，安装后页面、API、图片和导出均在本地运行。

## Mac 一键启动（包括 2017 款 Intel MacBook Pro）

在 Finder 中打开项目文件夹，双击 **`启动针线小账.command`**。会打开终端，自动准备环境、启动服务并打开电脑上的网页。手机连同一个 Wi-Fi，输入终端打印的手机访问地址即可。保留启动窗口，按 `Ctrl+C` 停止服务。

- 自动检测系统版本和 Intel / Apple Silicon 芯片，不需要手动选择安装包。
- macOS 13 自动使用项目内的 uv 准备 Python 3.12；macOS 12 提供项目内的 `realpath` 兼容辅助程序。无需先安装 Homebrew，也不需要管理员密码。uv 官方支持 macOS 13，并说明 macOS 12 可在安装 `realpath` 后使用，见 [uv 平台说明](https://docs.astral.sh/uv/reference/policies/platforms/)。
- macOS 11 及更早版本尝试使用已经安装的 Python 3.10+；缺少时会明确显示当前版本和安装指引。低于 macOS 11 时，请携带已构建的 `frontend/dist`，无需在旧系统上构建新版前端。
- 首次准备需要联网，下载运行环境及依赖；之后没有源码或依赖变动时可直接使用本机缓存启动。Python 由 [uv 管理](https://docs.astral.sh/uv/concepts/python-versions/)，不更改系统 Python。
- 有可用的 `frontend/dist` 时直接使用静态页面；需要构建时，检测符合版本及芯片的 Node.js，没有则从官方下载安装到项目内并校验 SHA-256。使用的 Node.js 22 Intel 安装包要求 macOS 11 以上，见 [官方平台说明](https://github.com/nodejs/node/blob/v22.23.0/BUILDING.md#platform-list)。
- 运行环境和下载缓存位于 `.runtime`，按芯片分开保存，不纳入 Git。旧电脑的 `.venv` 不会被直接复用；需要重建前端依赖时会重新安装正确架构的 `node_modules`。
- 已有同一账本服务时复用；8000 端口被其他服务占用或无响应时尝试 8001 等端口，不会结束其他进程。以每次打印的地址为准。
- 数据仍保存在 `data` 和 `images`，启动过程不会清空账目或照片。运行日志位于 `.runtime/server-端口.log`，错误时保留终端提示方便检查。

复制项目到另一台 Mac 时，可省略 `.runtime`、`.venv` 和 `node_modules`，在目标电脑双击启动即可。从 Git 获取的项目不包含个人账目；先在原电脑导出完整 JSON 备份，在目标电脑「工作室 → 恢复备份」导入。

可选终端用法：

```bash
./启动针线小账.command --port 8080   # 指定起始端口
./启动针线小账.command --rebuild     # 重新构建前端
./启动针线小账.command --no-browser  # 启动后不打开系统浏览器
```

Git 会保留脚本的可执行权限。若其他复制方式丢失权限，可运行 `chmod +x 启动针线小账.command`。修改后端源码后，请先在原启动窗口按 `Ctrl+C`，再双击重新启动。

## 启动

要求 Python 3.10+。从 Git 获取项目后首次构建前端需要 Node.js 20.19+ 或 22.12+。

在项目目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

本机已有 `frontend/dist` 时可以直接启动。构建产物不纳入 Git；从 Git 获取项目后，首次运行 `python run.py` 会自动执行 `npm ci` 和前端构建。前端源码修改后运行 `python run.py --build` 重新构建。

- 电脑打开 `http://127.0.0.1:8000`。
- 手机连接和电脑相同的 Wi-Fi，打开启动时打印的 `http://电脑局域网IP:8000`。
- 服务监听 `0.0.0.0:8000`。电脑需要保持开机；手机地址中不能写 `localhost` 或 `127.0.0.1`。
- 若手机无法连接，检查两台设备是否在同一网络、电脑防火墙是否允许 Python 的传入连接、Wi-Fi 是否开启客户端隔离。无需配置路由器端口转发。
- 改端口：`python run.py --port 8080`。结束服务：终端 `Ctrl+C`。

Windows 可使用 `.venv\Scripts\activate` 激活环境；其余 Python 启动步骤相同。

## 界面与功能

参考站：[手作包包记账本](https://a016fde1063bbc64b.app.workbuddy.host/)。

- 订单台账：总数、待收尾款、已收金额、优惠合计；按姓名、编号、电话、款式等搜索；点击订单编辑。
- 订单表单：下单日期、编号、客户、收货信息、快递单号、款式、报价、定金、尾款、优惠、三种状态和备注。常用款式支持多选、数量与报价相加，定金和抹零提供快捷按钮；已移除成品照片和订单截图入口。
- 收支明细：采购布料、耗材辅料、工具、每周合并运费、定金和尾款；日期、关联订单编号、事项、支出或收入、备注；编辑和删除。
- 月度汇总：全程总账、累计净利润、收入、支出及逐月统计，计算口径与参考站一致。
- 底部操作：按当前页新增、导出 Excel、更多。更多菜单包含款式管理、JSON 备份恢复和清空确认。

填写订单的已收定金、尾款并保存后，自动生成关联收入流水，月度收入和净利润按收款日期更新，无需重复登记。首次登记某类收款时生成流水，可在「本次收款日期」补录实际日期。之后修改金额直接更新对应原流水，保留原记录编号与日期，不追加差额记录；重复保存不会重复记账。已有多次收款记录时，金额增加修正最近一笔，金额减少从最近一笔开始冲减。客户、款式和订单编号同步到关联收入；自动流水的订单备注也会同步。修改或删除关联收入流水也会回写订单已收金额。删除订单保留历史收支及单号。

恢复备份按文件原样还原，不重新生成收入。移除照片入口后，已有图片数据仍保留在本地与完整备份中，编辑订单不会删除历史图片。

## 数据和目录

```text
backend/              FastAPI 接口、记账规则、图片与 Excel 处理
frontend/src/         原站样式、交互与 Vue 页面入口
frontend/dist/        可直接使用的前端构建
images/               上传照片（压缩后的 JPG）
data/bookkeeping.sqlite3   SQLite 数据库，启动时自动建立
启动针线小账.command  Mac 双击启动入口
scripts/              环境准备、兼容辅助与启动管理
run.py                手动局域网启动入口
requirements*.txt     Python 依赖与当前环境锁定版本
frontend/package-lock.json  前端依赖锁定版本
tests/                后端集成测试
sites/stitch-ledger/   早期静态设计原型，正式服务不使用此目录
```

数据库以整数分保存金额。页面与导出按参考站口径计算：待收尾款＝报价−定金−尾款−优惠，合计时逐单取非负值；净利润＝实际收入−实际支出；月度订单数量、完成数量和待收按订单下单月份汇总。

SQLite 事务保证一次保存完整落盘。电脑和手机同时编辑时，版本校验会提示刷新，避免覆盖另一台设备的新数据。既有接口和旧版备份格式保留兼容，网页使用 `/api/book` 读取和保存原站格式。

JSON 备份包含照片，可在另一台电脑的「更多 → 恢复备份」中导入。清除手机浏览器缓存不会清空电脑账本。移除照片关联后，实际图片文件会保留以支持备份恢复。

直接复制项目数据到另一台电脑时，先停止服务，再一起复制 `data` 与 `images`。

可以通过 `BOOKKEEPING_DATA_DIR` 和 `BOOKKEEPING_IMAGES_DIR` 环境变量设置存储位置，默认是项目根目录下的 `data` 与 `images`。

## 接口

启动后访问 `http://127.0.0.1:8000/docs`，可查看和试用 API。

| 路径 | 用途 |
| --- | --- |
| `GET/PUT /api/book` | 原站格式账本、版本校验及独立台账保存 |
| `GET /api/book/backup` | 原站格式含照片 JSON 备份 |
| `GET /api/ledger` | 兼容接口：完整账本、版本和统计 |
| `GET/POST /api/orders` | 查询/新建订单 |
| `PUT/DELETE /api/orders/{id}` | 修改/删除订单 |
| `PATCH /api/orders/{id}/status` | 修改进度 |
| `GET/POST /api/transactions` | 查询/新建收支 |
| `PUT/DELETE /api/transactions/{id}` | 修改/删除收支 |
| `GET/POST /api/styles` | 常用款式 |
| `PUT/DELETE /api/styles/{id}` | 修改/删除款式 |
| `POST /api/images` | 图片上传；multipart 字段名 `file`，单张最多 12 MB |
| `GET /api/reports` | 累计及月度统计 |
| `GET /api/export.xlsx` | 下载 Excel |
| `GET /api/backup` | 下载含照片完整备份 |
| `POST /api/restore` | 导入 JSON 备份 |
| `POST /api/clear` | 清空；提交 `{"confirmation":"清空"}` |
| `POST /api/undo` | 恢复最近一次操作前的账本 |

图片上传示例：

```bash
curl -F "file=@包包照片.jpg" http://127.0.0.1:8000/api/images
```

返回 `{"url":"/images/随机编号.jpg","filename":"随机编号.jpg"}`，可直接用返回的 URL 显示图片或写入订单的 `photos`。

## 开发和验证

```bash
pip install -r requirements-dev.txt
python -m pytest -q
cd frontend
npm ci
npm run dev
```

开发时另开终端运行 `python run.py --reload`。Vite 会把 `/api` 和 `/images` 代理给 8000 端口；正式使用只运行 FastAPI 即可。

参考功能清单见 `FEATURE_PARITY.md`。框架说明参考 [FastAPI 文件上传](https://fastapi.tiangolo.com/tutorial/request-files/)、[Vue 3](https://vuejs.org/guide/introduction)、[Vite 构建](https://vite.dev/guide/build)。

## Git 管理

项目根目录使用 `main` 分支管理后端、Vue 源码、静态素材、依赖锁定文件、测试和文档。数据库、上传照片、备份、虚拟环境、`node_modules`、构建产物和本机截图由 `.gitignore` 排除。账目与照片请继续使用网页的完整 JSON 备份保存。

常用命令：

```bash
git status
git log --oneline -5
git add .
git commit -m "描述这次修改"
```

`sites/stitch-ledger` 为早期原型的独立仓库，保留在本机，未作为嵌套仓库加入根目录 Git。
