# Bambu A1 CLI

[English](README.md)

独立、实验性的 A1 命令行工作流：切片文件检查、调用本机 Studio CLI 切片、局域网状态与相机、检查后单次签名开打。保持原有云端与 Handy 设置，不使用窗口控制或 WSL。

**仓库不包含应用私钥，也不提供从官方插件提取凭据的工具。** 签名开打需要使用者自行提供有权使用、且已被目标打印机信任的应用签名身份。仅安装项目不能完成凭据初始化。没有这类凭据时，仍可使用文件检查、切片、状态和相机功能。详见 [凭据说明](docs/credentials.md)。

## 当前范围

- Python 3.11+；完整签名发送流程目前仅支持 Windows。
- A1、0.4 mm、单盘单材料 PLA、按层打印、AMS 第一个单元的第 1–4 槽。
- 不包含多色、外置料架、云端发送、跨机器任务队列。
- Linux/macOS 可运行离线检查等可移植部分，凭据存储及发送尚未适配。
- 原始私有原型已在 A1 固件 01.08.01.00、Studio 02.08.02.61 上真实启动打印。此公开重构版通过离线测试，未另外发起一盘实机打印来验证重构。

## 安装与配置

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\bambu-a1.exe --help
```

激活虚拟环境后可直接用 `bambu-a1`，也可用该环境的 `python -m bambu_a1`。

```powershell
bambu-a1 init --host 192.0.2.10 --serial YOURPRINTERSERIAL --ca-file C:/private/printer-ca.pem --studio-config C:/path/to/BambuStudio.conf --studio-exe 'C:/Program Files/Bambu Studio/bambu-studio.exe' --profile C:/private/a1-full-profile.json
bambu-a1 status
bambu-a1 camera --out C:/private/bed.jpg
```

示例 IP 是文档占位地址，路径及序列号须自行替换。CA 应来自可信来源；TLS 始终检查证书链及设备序列号主机名。可以用 `--app-ca-file` 指定独立的应用证书根。`--studio-config` 可省略，改由秘密管理工具设置 `BAMBU_A1_ACCESS_CODE` 环境变量。命令行不接收明文访问码。

配置和运行记录默认在 `%LOCALAPPDATA%/BambuA1Cli`；可在启动前设置 `BAMBU_A1_HOME` 使用其他私有目录。不要放进 Git 仓库。`init` 不覆盖旧配置，程序也不会自动读取作者的私有原型目录。DPAPI 通常绑定 Windows 用户与机器，不能把加密文件同步后当作跨机可用凭据。

切片使用完整、已展开的 A1 配置，可从正确设置的 3MF 中提取 `Metadata/project_settings.config`。仓库不附带温度、个人耗材配置或模型。

## 检查和打印

```powershell
bambu-a1 inspect --file C:/prints/part.gcode.3mf
bambu-a1 slice --model C:/prints/part.stl --out C:/prints/part.gcode.3mf --profile C:/private/a1-full-profile.json
bambu-a1 preflight --file C:/prints/part.gcode.3mf --slot 2
```

完成 [凭据配置](docs/credentials.md) 后：

```powershell
bambu-a1 prepare-print --file C:/prints/part.gcode.3mf --slot 2 --label 'Reviewed part'
# 实际查看返回的床面图片，核对材料、打印板和本盘授权；在 5 分钟内发送。
bambu-a1 dispatch --job-id RETURNED_JOB_ID --reviewed-bed-sha256 REVIEWED_IMAGE_SHA256
bambu-a1 job-status --job-id RETURNED_JOB_ID
```

程序重新核对文件、状态和 AMS，上传唯一文件并逐字节回读，保存回执后只发一次。已有回执时拒绝重发；超时先查看状态，不能删回执或另建任务绕过检查。任务归属按唯一文件名核对，不用可重复的任务名称冒充启动证明。

当前文件检查核验归档、元数据和边界，不是运动仿真。床面图的 SHA256 只能记录查看的是哪张图，不能自动判断床面是否清空。程序不会自行清理热床。

每台打印机应由一个执行端调度；当前锁只能保护同一台电脑的同一运行目录。远程 API、SSH 网关和跨机队列未实现。

## 开发和许可证

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

测试使用临时合成数据，不连接打印机、不读取私人凭据、不启动打印。GitHub Actions 在 Windows 及 Ubuntu 上运行相应测试；Windows 专属测试在 Ubuntu 跳过。

项目采用 **AGPL-3.0-or-later**，详见 [LICENSE](LICENSE) 和 [来源说明](NOTICE.md)。这是非官方项目；固件、凭据和信任状态变化可能需要重新适配。
