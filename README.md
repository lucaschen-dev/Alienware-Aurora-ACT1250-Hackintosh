# Alienware Aurora ACT1250 — macOS, RTX 5070 and UEFI Secure Boot

这是一份单机实测记录：Dell Alienware Aurora ACT1250 在 **UEFI Secure Boot 开启、两只测试 U 盘均拔掉**的状态下，从内部 SSD 进入 macOS Tahoe。记录包括签名启动链、两个实际遇到的 PE/COFF 验证问题，以及重新执行的 Wi-Fi、Metal 计算和离屏渲染测试。

**English:** A hardware-tested case study of macOS Tahoe on an Alienware Aurora ACT1250 with firmware Secure Boot enabled, internal-SSD boot, an RTX 5070 and an Intel wireless adapter. This documents owner-authorized shim/MOK trust, PE/COFF interoperability debugging and the functional tests performed on this machine.

记录日期：2026-11-09，美国西海岸时间。固件日志采用不同的时区，部分原始日志日期为次日。

## 实测配置

| 项目 | 本机情况 |
|---|---|
| 机器 | Dell Alienware Aurora ACT1250 |
| CPU | Intel Core Ultra 7 265F，无可用核显 |
| 显卡 | NVIDIA GeForce RTX 5070，12 GB，PCI device `2f04` |
| 内存 | 32 GB |
| macOS SSD | Samsung 990 PRO 1 TB |
| Windows SSD | SanDisk PC SN7100S，独立系统盘 |
| 系统 | macOS Tahoe 26.7.2，build `25G332` |
| SMBIOS 类型 | MacPro7,1；序列号等身份信息不公开 |
| 实际 OpenCore 二进制 | 自定义 `DBG-109-2026-10-31`；不是声称使用原版 1.0.8 |
| 配置校验及离线源码参考 | 官方 OpenCore 1.0.8；与上述自定义二进制存在版本边界 |
| 菜单 | rEFInd 0.14.2，macOS / Windows 两个手动入口 |
| shim | Ubuntu `shim-signed 1.59+15.8-0ubuntu2`，Microsoft 签名 |
| 显卡驱动 | NullMoth 2.7.2 |
| Wi-Fi | Intel `8086:272b`，subsystem `8086:40f0`，属于 BE200/BE202/Killer GL 系列 PCI ID |
| Wi-Fi 驱动运行时标识 | `AirportItlwm 2.4.0`；firmware 字符串 `2.4.0_FIX29_20261101` / `92.67ce4588.0` |

Wi-Fi 的 PCI ID 不是零售型号的唯一依据。公开的 [Ersiter/AirportItlwm-BE200](https://github.com/Ersiter/AirportItlwm-BE200) 包含该系列及 FIX29 相关开发记录，但本记录没有完成已装二进制与该仓库某个发布资产的逐字节来源核验。

## 哪些结果已经验证

| 项目 | 结果和证据边界 |
|---|---|
| 真正的 UEFI Secure Boot | 进入桌面后读取到 `SecureBoot=1`、`SetupMode=0`、`AuditMode=0`、`DeployedMode=1` |
| 脱离 U 盘启动 | 两只测试 U 盘均未连接；启动路径指向内部 Samsung SSD 的 OpenCore；用户确认进入桌面 |
| shim 的信任校验 | 使用自有 MOK 签名及特定 booter 哈希；未设置禁用 shim 验证的 `MokSBStateRT` |
| Wi-Fi 真正联网 | HTTPS 请求强制绑定 Wi-Fi 接口，禁用代理，3/3 返回 HTTP 200，TLS 校验通过，连接源地址与 Wi-Fi 一致 |
| GPU 计算 | Metal 全数组计算 4096 个结果，0 个错误 |
| GPU 渲染 | Metal 离屏绘制 64×64 全屏三角形，CPU 回读全部 4096 个像素，容差 1/255，0 个错误 |
| GPU 小型算术测试 | float4 FMA 约 11.698 TFLOP/s，三个抽样结果校验通过；只是这一段测试的运算量估计 |

可读的结构化结果放在 [VALIDATION.json](VALIDATION.json)。[metal_functional_test.py](metal_functional_test.py) 可在 macOS 上用 Python 3 重新执行，不需要第三方 Python 包：

```sh
python3 metal_functional_test.py
```

该脚本只检查小规模计算和离屏渲染，不测窗口交换链、游戏帧率、专业软件兼容性或长时间稳定性。

## 启动方法

本机验证通过的链路：

```text
Dell UEFI，Secure Boot ON，保留出厂平台密钥
  → Microsoft 签名的 Ubuntu shim
  → 自有 MOK 签名的 rEFInd
  → 自有 MOK 签名的 OpenCore
  → 原 APFS/Preboot 路径中的 Apple boot.efi
     （OpenCore 预处理后的映像，按精确 MOK 哈希信任）
  → macOS
```

完整步骤、文件布局、证书登记、哈希登记和失败排查见 [SECURE_BOOT.md](SECURE_BOOT.md)。其中有两个容易漏掉的细节：

1. 部分 HFS+/APFS EFI 驱动在常见签名工具中验证成功，但与 shim 15.8 的摘要不一致。本次为原始文件中的空隙补上不执行的 PE 节，再重新签名，实际启动通过。
2. OpenCore 会预处理 Apple EFI 映像。因此，直接把磁盘上原始 `boot.efi` 的哈希登记进 MOK，可能无法匹配随后被验证的内存映像。本次登记的是经过验证、按相同规则生成的副本哈希；正常启动仍读取原始 APFS 文件。

## 显卡和 Wi-Fi

显卡依赖现有的 [NullMoth NVIDIA macOS driver](https://github.com/nullmoth/nvidia-macos-driver) 和其驱动安装工具 [1401](https://github.com/nullmoth/1401)。本机加载了 `NVRM`、`NVRMFB`、`NVAccel`、`NVRMAGDC` 2.7.2；NVMTL 报告的设备是 RTX 5070 / NVK GB205-A。本记录新增的是这台机器上的验证结果，显卡驱动来自上述项目。

本机保留驱动要求的 `SecureBootModel=Disabled`、AMFI/SIP 相关配置。这里的 **Apple SecureBootModel 与主板 UEFI Secure Boot 是两回事**。主板显示 Secure Boot 开启，并不代表该 macOS 获得了原生 Mac 的完整安全策略。

光标使用 `nvcursor=0` 作为当前机器的实际配置。是否需要这个选项应按具体故障判断，不把它当作所有显卡的通用要求。

Wi-Fi 当前系统报告支持 `802.11 a/b/g/n/ac`，基本连接和实际传输已通过。本机的 PHY 报告与实际配置未开启 `itlwm_he=1` 一致。

## USB 接口说明

**USB 映射仍有部分接口不可用。** 后方一组非 USB 2.0 的 USB-A 接口，当前连键盘、鼠标也无法使用，仍需重新完成逐口映射。其他接口的工作情况应以实际逐口测试为准。

## 本次记录与已有方法的关系

shim/MOK、自签名 rEFInd、OpenCore 的 Apple EFI 预处理以及这些第三方驱动都有公开实现。本次检索没有找到这台 ACT1250、这组组件版本和这两处失败原因的完整同配置实测记录；这不构成“全球首发”或“GitHub 从未有人做过”的证明。

值得保留的是：实际从 U 盘到硬盘的验证过程、两种独立摘要实现与实际固件结果的交叉核对、以及有明确边界的 Wi-Fi / Metal 功能测试。相关来源及排错细节集中在 [SECURE_BOOT.md](SECURE_BOOT.md)。

本仓库仅发布技术说明、经裁剪的测试结果和小型测试脚本。EFI 二进制、Apple 系统文件、完整机器配置、MOK 私钥/证书、设备身份和原始网络日志均留在本地。
