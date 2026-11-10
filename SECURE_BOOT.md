# ACT1250 的 Secure Boot 实测步骤与排错细节

本文记录已能正常启动 macOS 的本机如何增加 UEFI Secure Boot。它不是从零安装 macOS 的通用教程。ACPI、CPU 支持、USB 映射、显卡安装需先完成适合各自机器的配置。

## 1. 先确认 Dell 的固件限制

[Dell 公告 000250090](https://www.dell.com/support/kbdoc/en-us/000250090/alienware-area-51-aat2250-does-not-display-after-changing-bios-settings) 明确列出 ACT1250：Secure Boot、Custom Mode、Audit Mode 的特定组合会造成无显示；修改 Secure Boot 数据库还可能导致设备不能启动。公告建议更新 BIOS 到 1.19.0 或更高以预防相关问题。

本机 CPU 是 265F，不能假定有核显输出作为退路。公告对 ACT1250/AAT2250 的问题恢复指向 Dell 支持；不要把 EBT2250 的 Thunderbolt 显示恢复操作直接套到 ACT1250。

因此，本次没有清空、替换或向固件 PK/KEK/db/dbx 写入自有密钥，也没有用 Custom/Audit 作为签名登记入口。采用出厂 Microsoft 信任链进入 shim，再由机器所有者通过 MokManager 登记信任。

本机成功进入系统时实际读到 Deployed 模式开启、Audit 模式关闭；实际 BIOS 版本和 BIOS 中 Custom Mode 的现场画面没有保留。这个成功案例不替代对另一台机器的版本和模式核对，也不能保证排除固件黑屏问题。

## 2. 准备 USB 测试链路

先备份现有两个系统的 EFI 分区和固件设置，准备已能回到原系统的启动方式。最初只在 FAT 格式测试 U 盘中准备下面的组件，硬盘保持原有引导，确认可用后再迁移。

本次所用 shim 来自 Ubuntu `shim-signed 1.59+15.8-0ubuntu2` 解包出的 `shimx64.efi.signed.latest`。独立核查其签名后使用；没有把名字相近的 `.dualsigned` 文件当成完全相同的签名链。匹配的 `mmx64.efi` 来自同套发行版组件。

**这记录的是本次通过的具体构建，并不建议绕过后来发布的 dbx/SBAT 撤销。** 换版本、换固件数据库后必须重新核对签名、SBAT、信任和运行结果。

测试 U 盘的核心布局：

```text
EFI/BOOT/BOOTX64.EFI       Microsoft 签名的 shim
EFI/BOOT/grubx64.efi      自有 MOK 签名的 rEFInd（文件名是 shim 的默认第二阶段名）
EFI/BOOT/mmx64.efi        对应的 MokManager
EFI/BOOT/refind.conf      手动菜单
EFI/BOOT/drivers_mok/     签名的 OpenRuntime / HFS+ / APFS 驱动
EFI/OC/OpenCore.efi       自有 MOK 签名
EFI/OC/config.plist       针对本机已能工作的配置
EFI/OC/...                本机所需的 kext、ACPI、资源
OWNER-MOK.der             自己生成的公开证书，仅供现场登记
```

每个读者都应生成自己的所有者密钥。私钥保留在受保护的本地目录，不放 U 盘或公开仓库。本机采用 RSA-2048 自签名 X.509 证书并使用 SHA-256 签名；不要加入限定为“仅签内核模块”的 EKU OID。shim 的实际 EKU 校验要按所用版本的 [shim.c](https://github.com/rhboot/shim/blob/15.8/shim.c) 检查。

签名示例，变量对应自己已核实的文件：

```sh
osslsigncode sign -certs OWNER-MOK.pem -key OWNER-MOK.key -h sha256 \
  -in refind_x64.efi -out grubx64.efi
osslsigncode verify -CAfile OWNER-MOK.pem -in grubx64.efi
```

OpenCore、OpenRuntime、文件系统驱动同样需要核对其信任方式。shim 本身保留原发行版的 Microsoft 签名，MokManager 保留其供应商签名。不能认为“签了 OpenCore”就自动覆盖其余所有 EFI 映像。

## 3. 在 MokManager 登记证书

在适用的 Dell BIOS 版本和正确模式下保留出厂密钥，启用正常的 Secure Boot；F12 从测试 U 盘启动。进入匹配的 MokManager 后：

1. 选择 `Enroll key from disk`。
2. 在测试 U 盘中选自己的 DER 证书。
3. 检查证书身份，选择继续、确认登记并重启。
4. 再次从同一 U 盘启动，检查 rEFInd、OpenCore 和各 EFI 驱动分别是否通过。

这是 shim 管理的 Machine Owner Key，不是把证书写入 BIOS 的 db。MOK 登记持久保存在固件变量中，拔掉 U 盘不会撤销它。测试失败时应读日志判断是哪一级被拒绝，不要选择关闭验证来掩盖问题。

## 4. 第一个故障：常见工具验签通过，shim 仍拒绝文件系统驱动

本次两个失败样本：

| 文件 | 原始 raw 布局中的空隙 | 常见签名工具 | 独立 shim 15.8 摘要 |
|---|---:|---|---|
| HfsPlus EFI | 512 B | 验签通过 | 与签名内摘要不一致 |
| APFS EFI | 4096 B + 512 B | 验签通过 | 与签名内摘要不一致 |
| OpenRuntime / rEFInd / OpenCore 对照 | 无同类空隙 | 验签通过 | 与签名内摘要一致 |

诊断按照 [shim 15.8 pe.c 中 generate_hash()](https://github.com/rhboot/shim/blob/15.8/pe.c) 的顺序计算摘要：

- 跳过 PE checksum 及证书目录项；散列其余 header 区。
- 将节按 `PointerToRawData` 排序，散列各节的 `SizeOfRawData`。
- 按该版本实现计算末尾数据的散列范围；有签名与无签名的尾部处理并不相同。

具体文件布局会使“节后尾部”的范围与真实 raw 空隙产生不直观的关系。因此 `osslsigncode verify` 的成功只是其中一项证据，还需比对 shim 实际会算出的摘要。

本次修复步骤：

1. 仅在工作副本上移除旧的 Authenticode 签名。
2. 解析全部原有节，记录名称、VA、virtual size、raw offset、raw size、permissions 和内容 SHA-256。
3. 找出 `SizeOfHeaders` 与 raw 节之间以及 raw 节之间的空隙。
4. 确认它们满足文件对齐，现有 section table 后有足够且未占用的 header 空间，文件结尾没有未知 overlay。
5. 增加 `.sgap0` / `.sgap1` 节覆盖**原位置的现有空隙字节**；属性 `0x42000040`，即只读、已初始化、可丢弃的数据，**没有执行权限**。给新增节分配独立且按 `SectionAlignment` 对齐的虚拟地址。
6. 更新节数、`SizeOfImage`、初始化数据总量及 checksum。原有节的地址、尺寸、属性和字节不变。
7. 用同一个自有 MOK 重新签名；重新比对签名摘要和独立 shim 摘要，并验证原节完全未变。
8. 再用一个调用原始 shim `generate_hash()` 的本机 C 测试程序交叉核对，最后实际在 Secure Boot 开启的机器上启动。

修复后，两个失败样本和三个原本通过的对照样本摘要一致；实机日志显示这两个文件系统驱动成功加载。本次是两个特定二进制的 PE 布局兼容修复，不是通用 PE 重写器、漏洞或验签绕过。没有足够 header 空间、存在 overlay 或布局不同的文件需要另外分析，不能直接套用。

公开的 [ZFSBootMenu discussion #825](https://github.com/zbm-dev/zfsbootmenu/discussions/825) 已讨论过“常见工具验证成功但 shim 拒绝”及 PE 布局检查。这说明该类现象已有公开讨论；该讨论最终的主要原因又与本机不同，不能把所有 `0x1A` 都归结为 raw gap。

## 5. 第二个故障：Apple boot.efi 的磁盘字节与被验证的内存映像不同

OpenCore 文档的 [FixupAppleEfiImages](https://dortania.github.io/docs/latest/Configuration.html) 已说明 Apple EFI 映像的预处理问题。本机需要保留这个设置；仅登记磁盘原始 booter 的哈希不等于登记预处理后的映像。

本次在离线副本上按官方 1.0.8 的相关实现复现处理：

- 先验证原始 Apple EFI 的 RSA-2048 / SHA-256 签名，公钥模数必须已存在于官方 OpenCore 的 Apple key database。
- 按 `PeCoffSanitiseAppleImage` 规则清零 DOS stub、checksum 和 security directory，去掉 Apple 签名尾部。
- 按 W^X 修复规则去掉同时可写、可执行的数据节的执行属性；本机只涉及 `.data`。
- 比较所有原有代码/数据节的内容、VA、尺寸与 raw 位置，确认保持一致。
- 按 shim 15.8 的实际 PE 摘要规则计算 SHA-256；不能简单用整个文件的 SHA-256 代替。

本机这一构建的结果：

| 项目 | 结果 |
|---|---|
| 原文件大小 | 723512 B |
| 处理后大小 | 722952 B |
| 原始 Apple 签名 | 校验通过，模数在官方 OC 数据库中 |
| 修改原有代码/数据节的内容 | 无 |
| 处理后 shim SHA-256 | `2e868710c257f7486250b7260285a03208e665d7e5ed59483d7db346a6eebfa0` |
| 改动代码字节的反例 | 摘要改变，不再匹配准许值 |

这个摘要只是记录本机该 booter 的结果。读者必须从自己的文件计算并核对，不应照抄登记。原始 Apple booter、处理副本和系统证书都不在仓库中分发。

仓库提供 [prepare_boot_hash.py](prepare_boot_hash.py)，只接受上述已测试的 `25G332` 原始 booter。它先校验原文件 SHA-256 和 Apple RSA 签名，再创建新目录中的登记副本和 JSON 报告。不同构建会停止处理；源文件、EFI 分区和信任库均不修改。

```sh
python3 prepare_boot_hash.py ./boot-original.efi \
  --oc-source ./OpenCorePkg-1.0.8 \
  --output-directory ./enrollment-copy
```

这里的输入应为从自己系统取得的原始文件副本，源码应为官方 OpenCore 1.0.8。登记前核对 JSON 中的 `shim15_8SHA256`；输出目录必须尚不存在。这个脚本没有代替现场登记的步骤。

将处理副本以 `MOK-boot-26.7.2.efi` 放到测试 U 盘根目录，仅供登记：

1. 启动 MokManager，选择 `Enroll hash from disk`，不是 `Enroll key from disk`。
2. 选择自己的处理副本，核对显示的摘要。
3. 确认登记并重启。
4. 正常启动链仍由 OpenCore 加载原 APFS/Preboot 路径中的原始 `boot.efi`。不要把登记副本设成日常 macOS loader，也不要替换系统文件。

本机 OpenCore 是自定义 DBG-109，离线分析参考官方 1.0.8。日志中的大小和 W^X 修复符合预期，登记后硬件启动通过；本次没有证明该自定义版本与官方源码的所有内存处理逐字节等价。其他固件可能额外验证原磁盘路径，换平台仍需实际测试。

## 6. 通过后迁移到内部 SSD

先在 U 盘确认全部阶段通过，再备份现有硬盘 EFI，将同样的、已验证的链路部署到 macOS SSD：

```text
EFI/refind/refind_x64.efi  实际内容是 Microsoft 签名 shim
EFI/refind/grubx64.efi    实际内容是 MOK 签名 rEFInd
EFI/refind/mmx64.efi      MokManager
EFI/refind/refind.conf    图形菜单
EFI/refind/drivers_mok/   已验证的三个签名驱动
EFI/OC/OpenCore.efi       已验证的签名 OpenCore
EFI/BOOT/BOOTX64.EFI      shim 的备用启动位置
EFI/BOOT/grubx64.efi      匹配的 rEFInd 备用入口
EFI/BOOT/...             匹配的配置、MokManager、驱动和主题
```

`refind_x64.efi` 是为了沿用固件原有入口路径的文件名，内容仍是 shim；不能只凭文件名判断签名链。

首个成功硬盘配置由 rEFInd 预加载三个签名驱动，`scan_driver_dirs` 指向本目录的 `drivers_mok`。rEFInd 菜单的 Mac 项指向本机 macOS ESP 内的 `/EFI/OC/OpenCore.efi`，Windows 项明确指定另一个 Windows ESP 内的 `/EFI/Microsoft/Boot/bootmgfw.efi`。使用各自实际分区标识，不能照抄别人机器的 GUID。

本机与信任链相关的配置：

```text
UEFI.Quirks.ShimRetainProtocol = true
UEFI.Quirks.DisableSecurityPolicy = false
Booter.Quirks.ProtectSecureBoot = true
Booter.Quirks.ProtectUefiServices = true
Booter.Quirks.FixupAppleEfiImages = true
Misc.Security.SecureBootModel = Disabled
Misc.Boot.LauncherOption = Full
Misc.Boot.LauncherPath = \EFI\refind\refind_x64.efi
Misc.Boot.ShowPicker = false
```

`ShowPicker=false` 只隐藏 OpenCore 的第二个选择器，rEFInd 图形双系统菜单仍保留。macOS 看到的 BootOrder 可能受 `RequestBootVarRouting` 影响，不能仅靠这一项判断 Dell 实际使用哪个固件入口。本机日志确认已有实际 `Boot0008` 入口有效，内部 SSD 的启动路径也吻合。

随后拔掉全部测试 U 盘，重启，从内部 SSD 进入 macOS，再读取实际 Secure Boot 模式、启动设备路径和 shim MOK 状态。这一步已经完成，不能只凭在 U 盘上成功就宣称硬盘迁移成功。

## 7. 后续维护与排错

macOS 更新可能改变 booter；Recovery 和安装器也可能使用不同 booter。新的映像应按实际内容重新核对摘要和信任关系。哈希登记对应具体映像字节，不能把旧值当作所有系统版本的通行值。

遇到 `Verification failed / Security Violation`，逐级定位：固件是否接受 shim；shim 是否接受第二阶段；rEFInd 是否加载驱动；OpenCore 是否验证目标 booter。核对证书、MokListRT、SBAT/dbx 和 PE 摘要；文件整体 SHA-256 与 PE 验证摘要是不同概念。

在仍有 BIOS 画面的启动失败中，使用保留的已验证 U 盘或原引导恢复，并核对日志。ACT1250 若完全无显示，按 Dell 对该型号的恢复支持处理。

## 来源

- [OpenCore 官方源码 1.0.8](https://github.com/acidanthera/OpenCorePkg/tree/1.0.8)：Apple EFI 验签、映像处理、内存属性修复和配置语义。
- [OpenCore 配置文档](https://dortania.github.io/docs/latest/Configuration.html)：FixupAppleEfiImages、ShimRetainProtocol、LauncherOption 等。在线最新文档可能继续变化，需对应实际版本。
- [shim 15.8 源码](https://github.com/rhboot/shim/tree/15.8) 和 [MOK 变量说明](https://github.com/rhboot/shim/blob/main/MokVars.txt)。
- [rEFInd](https://www.rodsbooks.com/refind/)：本次使用 0.14.2；签名和 chainloader 支持归原项目作者。
- [Dell 官方公告](https://www.dell.com/support/kbdoc/en-us/000250090/alienware-area-51-aat2250-does-not-display-after-changing-bios-settings)。
- [NullMoth NVIDIA 驱动](https://github.com/nullmoth/nvidia-macos-driver) / [1401](https://github.com/nullmoth/1401)。
- [Ersiter/AirportItlwm-BE200](https://github.com/Ersiter/AirportItlwm-BE200)、[其上游 laobamac/itlwm](https://github.com/laobamac/itlwm) / [OpenIntelWireless](https://github.com/OpenIntelWireless/itlwm)。

感谢这些项目的作者和维护者。本记录中的硬件结果属于单机观察，原有方法和驱动的贡献应归各自项目。
