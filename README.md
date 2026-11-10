# Alienware Aurora ACT1250: macOS, RTX 5070 and UEFI Secure Boot

A hardware-tested record of macOS Tahoe running on an Alienware Aurora ACT1250 with **firmware Secure Boot enabled and both test USB drives disconnected**. The machine booted from its internal SSD. This repository explains the complete trust chain, the two verification failures encountered along the way, and the Wi-Fi and Metal tests performed afterward.

Recorded November 9, 2026, Pacific time. Firmware logs used a different time zone, so some original log filenames carry the following day's date.

## Hardware and software

| Component | Tested configuration |
|---|---|
| Computer | Dell Alienware Aurora ACT1250 |
| CPU | Intel Core Ultra 7 265F; no usable integrated graphics |
| GPU | NVIDIA GeForce RTX 5070, 12 GB, PCI device `2f04` |
| Memory | 32 GB |
| macOS storage | Samsung 990 PRO 1 TB |
| Windows storage | Separate SanDisk PC SN7100S SSD |
| macOS | Tahoe 26.7.2, build `25G332` |
| SMBIOS model | MacPro7,1; machine identity values are excluded |
| Running OpenCore binary | Custom `DBG-109-2026-10-31` |
| Offline source reference | Official OpenCore 1.0.8; the custom running binary has a separate version boundary |
| Graphical menu | rEFInd 0.14.2, manual macOS and Windows entries |
| First-stage loader | Microsoft-signed Ubuntu shim, package `shim-signed 1.59+15.8-0ubuntu2` |
| GPU driver | NullMoth 2.7.2 |
| Wireless PCI IDs | `8086:272b`, subsystem `8086:40f0` |
| Loaded wireless driver | AirportItlwm 2.4.0 |
| Wireless firmware report | `itlwm: 2.4.0_FIX29_20261101 fw: 92.67ce4588.0` |

The wireless PCI ID belongs to the Intel BE200/BE202/Killer GL family supported by [Ersiter/AirportItlwm-BE200](https://github.com/Ersiter/AirportItlwm-BE200). A shared PCI ID alone does not establish an exact retail card model. The installed binary's runtime version is recorded here; its byte-for-byte provenance against a particular upstream release asset has not been established.

## Verified results

| Check | Observed result |
|---|---|
| Firmware state after reaching macOS | `SecureBoot=1`, `SetupMode=0`, `AuditMode=0`, `DeployedMode=1` |
| Internal-storage boot | Both test USB drives disconnected; boot path on the internal Samsung SSD; desktop confirmed |
| Owner-authorized trust | MOK signatures and an exact processed-booter hash; no `MokSBStateRT` disabling shim validation |
| Actual Wi-Fi traffic | Three HTTPS requests bound to the Wi-Fi interface, proxy bypassed, HTTP 200, valid TLS, source address matched Wi-Fi |
| Metal compute correctness | All 4,096 output elements checked; zero mismatches |
| Metal rendering correctness | A 64×64 fullscreen triangle rendered offscreen; all 4,096 pixels read back and checked; zero mismatches at 1/255 tolerance |
| Arithmetic microbenchmark | Approximately 11.698 TFLOP/s for the specific float4 FMA workload; three numerical samples passed |

The microbenchmark is a workload-specific arithmetic estimate, not a gaming benchmark or a Windows performance comparison. The rendering check covers offscreen drawing and readback.

See [VALIDATION.json](VALIDATION.json) for the sanitized results. To repeat the small functional checks on macOS with Python 3:

```sh
python3 metal_functional_test.py
```

## Secure Boot: the complete walkthrough

```text
Dell UEFI with Secure Boot ON and factory platform keys retained
  -> Microsoft-signed Ubuntu shim
  -> rEFInd signed by the machine owner's MOK
  -> OpenCore signed by the same owner
  -> original Apple boot.efi from its APFS/Preboot path
     (the processed image is trusted by an exact enrolled MOK hash)
  -> macOS
```

Read [SECURE_BOOT.md](SECURE_BOOT.md) for:

1. Dell's ACT1250 firmware restriction and why this setup uses MOK instead of replacing platform keys.
2. A stage-by-stage trust explanation and a precise USB directory layout.
3. Owner-key creation, signing commands, certificate inspection and MokManager enrollment.
4. Reproduction of the HFS+/APFS PE-layout digest mismatch, with before/after evidence.
5. A non-executable metadata-section repair, invariants and offline verification tools.
6. Verification of the original Apple signature and reproduction of the booter preprocessing.
7. The exact difference between enrolling a certificate and enrolling a processed-image hash.
8. Internal-SSD migration, boot-path verification and targeted troubleshooting.

Two details made the difference on this machine:

- A conventional Authenticode verifier accepted two filesystem drivers, but shim 15.8 calculated a different digest because of their raw-file gaps. Adding non-executable metadata sections for those existing bytes and signing the resulting copies resolved the mismatch.
- OpenCore preprocesses Apple EFI images. The exact image seen by the verifier can therefore differ from the file stored on disk. Enrolling a hash of a verified, deterministically processed copy allowed the original APFS booter to load through the normal path.

Tools included in this repository:

| File | Purpose |
|---|---|
| [pe_tools.py](pe_tools.py) | Inspect restricted x86_64 PE32+ layouts, calculate the shim 15.8 digest, normalize eligible raw gaps, and compare with a verified Authenticode digest |
| [prepare_boot_hash.py](prepare_boot_hash.py) | Verify and prepare an enrollment-only copy of the exact tested `25G332` Apple booter |
| [metal_functional_test.py](metal_functional_test.py) | Small Metal compute and offscreen-rendering correctness checks |
| [PE_VALIDATION.json](PE_VALIDATION.json) | Sanitized before/after driver evidence and tool cross-check results |

The offline tools write new working files. Firmware trust enrollment remains a separate, deliberate operation in MokManager.

## GPU and Wi-Fi

GPU support comes from the existing [NullMoth NVIDIA macOS driver](https://github.com/nullmoth/nvidia-macos-driver), installed using its associated [1401 project](https://github.com/nullmoth/1401). This machine loaded `NVRM`, `NVRMFB`, `NVAccel` and `NVRMAGDC` 2.7.2. NVMTL identified the RTX 5070 through NVK GB205-A. The new contribution here is the machine-specific integration and validation record.

The macOS configuration retains the driver's required Apple `SecureBootModel=Disabled` and AMFI/SIP-related settings. **Apple SecureBootModel and motherboard UEFI Secure Boot are different mechanisms.** The firmware flags above describe the latter; they do not assert that this macOS installation has the security policy of a native Mac.

The working local configuration also uses `nvcursor=0`. Current Wi-Fi reporting lists `802.11 a/b/g/n/ac`; the actual bound HTTPS tests confirmed connectivity. This record reports those observed modes rather than inferring higher wireless modes from the adapter's product family.

## USB mapping note

**Some rear USB-A ports remain unusable under the current USB map, including with a keyboard or mouse.** The affected group still needs a complete physical-port and USB2/USB3 companion mapping pass.

## Attribution and contribution

shim/MOK, signed rEFInd, OpenCore's Apple-image processing, and both driver projects are existing public work. The searches performed for this record did not locate a complete report of this exact ACT1250/component combination and both failure diagnoses. That is not evidence of global priority.

This record contributes a tested USB-to-internal-SSD procedure, a reproducible investigation of the two verification failures, and fresh Wi-Fi and Metal correctness results. Upstream references are linked in the walkthrough.

### With help from ChatGPT

Created with help from **ChatGPT**. With appreciation for the assistance with research, debugging, test design, verification and documentation throughout this project. Credit for the bootloaders, drivers and underlying implementations belongs to their respective authors and maintainers.

## Publication privacy

The public files contain hardware models, component versions, technical methods and sanitized test results. Private signing material, personal certificates, hardware serials, machine UUIDs, MAC/IP addresses, network names, personal email addresses, local home-directory paths and raw system/network logs are excluded. GitHub still identifies this repository through its owner's existing public account.
