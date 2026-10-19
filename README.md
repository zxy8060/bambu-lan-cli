# Bambu LAN CLI

[English](README.en.md)

面向拓竹打印机的实验性 Python 命令行工具，提供切片文件检查、Bambu Studio 命令行切片、局域网状态查询和打印任务发送。支持 AMS 与外置料架，发送前进行设备预检，并由使用者确认床面状态。

**仓库不包含应用私钥，也不提供从官方插件提取凭据的工具。** 签名开打需要使用者自行提供有权使用、且已被目标打印机信任的应用签名身份。仅安装项目不能完成凭据初始化。没有这类凭据时，仍可使用文件检查、切片、状态和相机功能。详见 [凭据说明](docs/credentials.md)。

## 当前范围

- Python 3.11+；完整签名发送流程目前仅支持 Windows。
- 单喷嘴、单盘单材料、按层打印；矩形打印范围与高度、喷嘴直径、型号均从配置读取。
- 耗材类型与温度由切片配置指定；发送前核对 AMS 或外置料架中记录的材料与切片一致。
- 支持指定 AMS 单元和槽位、AMS HT 单槽、外置料架。双喷嘴、多色、混合 AMS 路由尚未实现。
- 内置相机为 A1/P1 使用的 TLS JPEG 路径；其他相机可提供新拍的 JPEG，尚未实现内置 RTSPS 抓图。
- 不包含云端发送、跨机器任务队列。
- 局域网连接保留设备现有的云端与 Handy 设置。
- Linux/macOS 可运行离线检查等可移植部分，凭据存储及发送尚未适配。

公开版本通过离线测试，尚未完成各机型、固件及材料组合的实机验证。已记录的实机测试来自 A1 研究原型，具体配置与结果见 [协议与验证记录](docs/protocol.md)。缺少所需设备状态或签名协议不兼容时，程序停止发送。

## 安装与配置

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\bambu-lan.exe --help
```

主命令为 `bambu-lan`，也可使用别名 `bambu-a1` 或 `python -m bambu_a1`。

```powershell
bambu-lan init --host 192.0.2.10 --serial YOURPRINTERSERIAL --ca-file C:/private/printer-ca.pem --studio-config C:/path/to/BambuStudio.conf --studio-exe 'C:/Program Files/Bambu Studio/bambu-studio.exe' --profile C:/private/machine-full-profile.json
bambu-lan status
bambu-lan camera --out C:/private/bed.jpg
```

示例 IP 是文档占位地址，路径及序列号须自行替换。CA 应来自可信来源；TLS 始终检查证书链及设备序列号主机名。可以用 `--app-ca-file` 指定独立的应用证书根。`--studio-config` 可省略，改由秘密管理工具设置 `BAMBU_A1_ACCESS_CODE` 环境变量。命令行不接收明文访问码。

配置和运行记录默认保存在 `%LOCALAPPDATA%/BambuA1Cli`；可设置 `BAMBU_LAN_HOME` 指定其他私有目录，也支持别名 `BAMBU_A1_HOME`。运行目录应放在 Git 仓库之外。`init` 创建新配置，遇到已有配置时停止。DPAPI 通常绑定 Windows 用户与机器，跨机使用时需在目标机器重新导入凭据。

切片需要目标机器和耗材的完整、已展开的 Studio 配置，可从正确设置的 3MF 中提取 `Metadata/project_settings.config`。温度等打印参数取自该配置，更换材料时应选择相应的完整配置。

`init --profile` 同时设置默认切片配置和目标机器。使用 `bambu-lan configure-machine --profile C:/private/machine-full-profile.json` 可更新本地目标机器配置。预检会核对切片与目标的型号、喷嘴、打印范围及高度，并读取设备喷嘴直径。目标型号由使用者配置，设备身份通过 TLS 证书中的序列号验证。默认切片材料需另行选择。

## 检查和打印

```powershell
bambu-lan inspect --file C:/prints/part.gcode.3mf
bambu-lan slice --model C:/prints/part.stl --out C:/prints/part.gcode.3mf --profile C:/private/machine-full-profile.json
bambu-lan preflight --file C:/prints/part.gcode.3mf --slot 2
```

完成 [凭据配置](docs/credentials.md) 后：

```powershell
bambu-lan prepare-print --file C:/prints/part.gcode.3mf --slot 2 --label 'Reviewed part'
# 实际查看返回的床面图片，核对材料、打印板和本盘授权；在 5 分钟内发送。
bambu-lan dispatch --job-id RETURNED_JOB_ID --reviewed-bed-sha256 REVIEWED_IMAGE_SHA256
bambu-lan job-status --job-id RETURNED_JOB_ID
```

`--ams-id` 使用 `status` 返回的单元 ID，默认 0；`--slot` 从 1 开始。支持四槽单元协议 ID 0–25、HT 单槽 ID 128–135，且必须能读到实际槽位；该范围不是每台机器可连接的单元数量。外置料架用 `--external` 代替槽位参数，并先在打印机设置其材料。例如：

```powershell
bambu-lan preflight --file C:/prints/petg.gcode.3mf --ams-id 1 --slot 2
bambu-lan prepare-print --file C:/prints/tpu.gcode.3mf --external --bed-image C:/private/fresh-bed.jpg
```

选择适合机器、喷嘴、打印板及送料方式的耗材与配置。程序检查记录的材料名称是否一致，耗材与硬件的适用性需由使用者确认。流量和振动校准默认关闭，可在准备时通过 `--flow-calibration`、`--vibration-calibration` 开启；调平默认开启。

对于 X1 等未实现内置抓图的相机接口，可用 `--bed-image` 提供这台机器的新拍 JPEG。仍需实际查看照片，文件修改时间只作为拍摄时间的近似，不能证明照片来自当前设备或确实是新拍的。程序保留原照片时间，照片与准备操作在发送时都必须未超过 5 分钟，不能通过刷新时间复用旧图。

程序重新核对文件、目标机器、状态和选定耗材，上传唯一文件并逐字节回读，保存回执后只发一次。型号或路由变化需要重新准备。已有回执时拒绝重发；超时先查看状态，不能删回执或另建任务绕过检查。任务归属按唯一文件名核对，不用可重复的任务名称冒充启动证明。

当前文件检查核验归档、元数据和边界，不是运动仿真。床面图的 SHA256 只能记录查看的是哪张图，不能自动判断床面是否清空。程序不会自行清理热床。

每台打印机应由一个执行端调度；当前锁只能保护同一台电脑的同一运行目录。远程 API、SSH 网关和跨机队列未实现。

## 从 0.1 升级

从 0.1 升级时建议新建虚拟环境安装 `bambu-lan-cli`，或先卸载旧发行包 `bambu-a1-cli`，避免两个发行包共用 Python 包目录。运行目录、凭据和历史回执保留。未配置目标机器的旧安装需补充配置；0.1 已准备的任务不能直接用 0.2 发送，应先核对原任务状态与回执，再按需重新准备，不能清除回执强行重发。

## 开发和许可证

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

测试使用临时合成数据，不连接打印机、不读取私人凭据、不启动打印。GitHub Actions 在 Windows 及 Ubuntu 上运行相应测试；Windows 专属测试在 Ubuntu 跳过。

项目采用 **AGPL-3.0-or-later**，详见 [LICENSE](LICENSE) 和 [来源说明](NOTICE.md)。这是非官方项目；固件、凭据和信任状态变化可能需要重新适配。
