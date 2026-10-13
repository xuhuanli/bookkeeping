# 针线小账 · 本地手作记账

FastAPI + Vue 3 + SQLite。电脑保存数据，手机通过同一局域网访问；不需要外网部署、账号或云数据库。安装依赖时需要联网，安装后使用页面、API、图片和导出都不依赖外部服务。

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

## 已实现功能

- 订单：自动/自定义编号、下单日期、顾客、自由填写款式、常用款式多选合价、报价、定金、尾款、抹零/优惠及快捷按钮。
- 交付：五个制作/发货阶段、交付日期、收货信息复制、快递单号、渠道、成本和备注。
- 照片：每单最多六张，JPG/PNG/WebP 上传，自动调整方向、压缩并保存至 `images`；缩略图、放大、移除关联。
- 分享：生成订单 PNG，下载/系统分享/长按保存、复制文字版。局域网 HTTP 上，部分手机浏览器不提供系统分享或现代剪贴板 API，页面提供下载、长按保存和文字复制回退。
- 收支：采购布料、耗材辅料、工具、按周合并发货运费、定金、尾款和其他收支；关联订单；增删改、日期/分类/搜索筛选。
- 汇总：累计收入、支出、采购、运费、净收益；逐月收支、新增/完成订单、月末待收与收款图表。
- 数据：四张工作表的 `.xlsx` 导出；包含照片的 JSON 备份；恢复前预览；清空确认；恢复最近一次删除/清空/导入前的账本。
- 手机：底部导航、卡片、底部表单弹层。桌面保留侧栏和表格。常用款式和顾客小本从工作室进入。

初次启动是空账本，不含测试订单。订单收款自动生成流水，不必像参考网页那样重复记同一笔钱。

## 数据和目录

```text
backend/              FastAPI 接口、记账规则、图片与 Excel 处理
frontend/src/         Vue 组件及手机样式
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

金额以整数分保存。优惠不算收入。修改订单累计收款只调整差额：新增差额使用指定收款日期；减少时从最近一笔开始扣减，其他流水日期保留。若日期记错，可编辑单笔流水。删除关联收入会自动减少订单已收；删除订单会删除其收入流水，保留采购支出并取消关联。

月末待收按订单日期、实际收款日期与优惠日期计算；修改报价会重新计算该单历史待收。完成订单按标记完成的日期计入月份。净收益＝真实收入−真实支出；预估订单成本另用于毛利展示，不重复扣除。

服务端校验金额、日期和照片。SQLite 事务使订单及流水一起保存。网页提交数据版本，手机/电脑同时编辑发生冲突时返回提示，刷新后继续，避免覆盖另一台设备的记录。

照片移除或清空账本时保留实际文件，以支持恢复；完整备份包含当前订单引用的照片。搬到另一台电脑时，在新服务的「工作室 → 恢复备份」导入 JSON 即可。若直接拷贝目录，请先停止服务，再一起复制 `data` 与 `images`。

可以通过 `BOOKKEEPING_DATA_DIR` 和 `BOOKKEEPING_IMAGES_DIR` 环境变量设置存储位置，默认是项目根目录下的 `data` 与 `images`。

## 接口

启动后访问 `http://127.0.0.1:8000/docs`，可查看和试用 API。

| 路径 | 用途 |
| --- | --- |
| `GET /api/ledger` | 完整账本、版本和统计 |
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
