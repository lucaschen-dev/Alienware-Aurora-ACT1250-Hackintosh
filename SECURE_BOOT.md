# ACT1250 Secure Boot: reproducible procedure and verification details

This is the detailed procedure behind the successful internal-SSD boot described in the [README](README.md). It starts with a machine that already boots macOS through a working, hardware-specific OpenCore configuration. CPU support, ACPI, storage, USB and graphics setup remain prerequisites.

The important integration work was establishing exactly **which component verifies which bytes**, then fixing two failures without disabling the verifier: a PE-layout digest disagreement in two filesystem drivers, and a mismatch between an on-disk Apple booter and its preprocessed image.

## 1. Understand the four different kinds of trust

| Mechanism | What it does in this setup |
|---|---|
| Firmware Secure Boot | The Dell firmware authenticates the first EFI program using its existing platform trust databases. |
| shim's owner trust | The Microsoft-signed shim accepts eligible EFI images signed by the enrolled Machine Owner Key, or an image whose exact digest has been enrolled. |
| OpenCore's Apple SecureBootModel | A separate Apple-oriented policy. It is `Disabled` in this installation because of the GPU-driver configuration. |
| macOS SIP/AMFI | Operating-system policies, separately configured for the third-party driver. Firmware Secure Boot being on does not establish their native-Mac state. |

The owner certificate is enrolled in shim's MOK mechanism. It is not added to Dell's firmware `db`, and no owner replacement for `PK` or `KEK` is required by this procedure.

The first trusted program is still Microsoft's signed shim. The owner then authorizes the subsequent programs and the specific processed Apple image. The chain is intentionally owner-controlled; it does not mean Microsoft has signed rEFInd, OpenCore or the GPU driver.

## 2. Resolve the Dell-specific firmware constraint first

[Dell advisory 000250090](https://www.dell.com/support/kbdoc/en-us/000250090/alienware-area-51-aat2250-does-not-display-after-changing-bios-settings) explicitly includes the Alienware Aurora ACT1250. It describes a no-display condition with Secure Boot enabled, Custom Mode on and Audit Mode selected, and recommends BIOS 1.19.0 or later for prevention.

That is why this procedure retains the factory `PK/KEK/db/dbx` and uses normal deployed Secure Boot with shim/MOK. It does not require enabling Custom Mode, switching to Audit Mode or clearing platform keys. The CPU here is a 265F, so integrated-graphics fallback cannot be assumed.

For an ACT1250/AAT2250 already affected by the no-display condition, Dell directs users to support. Its EBT2250-specific Thunderbolt recovery instructions should not be assumed to apply to the ACT1250.

The successful runtime state on this machine was `DeployedMode=1` and `AuditMode=0`. The actual installed BIOS version was not recorded. Confirm the real machine's BIOS version and settings before reproducing the procedure; the case study does not establish them for another computer.

## 3. Record the known-good baseline

Before changing the active hard-disk boot path:

1. Preserve a complete copy of the currently bootable EFI partition and its configuration.
2. Identify the macOS and Windows ESPs by their actual disk model and partition identity. Disk numbers can change across boots.
3. Keep a verified route back to the original boot setup.
4. Build the first experiment on a separate FAT-formatted USB drive. The initial tests here used a 64 GB drive; the original hard-disk boot configuration was left in place during that phase.
5. Record the exact versions and hashes of each EFI program. Treat filenames as labels, not proof of what a file contains.

This experiment used:

- Ubuntu package `shim-signed 1.59+15.8-0ubuntu2`, specifically its `shimx64.efi.signed.latest` payload.
- A matching distribution MokManager, `mmx64.efi`.
- rEFInd 0.14.2.
- The machine's existing custom OpenCore binary, reporting `DBG-109-2026-10-31`.
- Official OpenCore 1.0.8 source for offline analysis and configuration tooling.
- osslsigncode 2.15 for Authenticode signing and verification.

The similarly named `.dualsigned` shim payload was not treated as an interchangeable file: the actual signer chain was inspected. This is a record of a specific build that worked, not an instruction to evade later dbx or SBAT revocations. A different shim or firmware database requires its own compatibility check.

## 4. Generate and protect an owner key

Generate your own key. The private key used on this machine is not distributed, and readers should not enroll somebody else's owner certificate just to reproduce the directory layout.

The following is an example for a new local RSA-2048 owner key. Use a new working directory. OpenSSL 3 supports the shown `-addext` options.

```sh
mkdir owner-signing
cd owner-signing
umask 077
mkdir private
chmod 700 private

openssl req -new -x509 -newkey rsa:2048 -sha256 -nodes -days 3650 \
  -subj "/CN=Local EFI Owner/" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature" \
  -keyout private/OWNER-MOK.key -out OWNER-MOK.pem

chmod 600 private/OWNER-MOK.key
openssl x509 -in OWNER-MOK.pem -outform DER -out OWNER-MOK.der
openssl x509 -in OWNER-MOK.pem -noout -subject -issuer -dates -fingerprint -sha256
```

This example creates an unencrypted private key protected by local file permissions. Keep its directory protected and maintain a secure offline backup. Copy only the public DER certificate to the enrollment USB. The private key stays off the USB and out of Git.

The certificate intentionally omits an Extended Key Usage extension. In particular, do not add the Linux module-signing-only OID `1.3.6.1.4.1.2312.16.1.2` to a key intended to authorize EFI loaders; the selected shim's [EKU checks](https://github.com/rhboot/shim/blob/15.8/shim.c) matter.

Certificate identity, certificate fingerprint, an image's whole-file SHA-256 and its PE verification digest are four different values. Compare like with like when inspecting enrollment screens and tool output.

## 5. Lay out the USB chain

The tested removable-media layout was:

```text
USB FAT filesystem
├── OWNER-MOK.der
└── EFI
    ├── BOOT
    │   ├── BOOTX64.EFI            Microsoft-signed shim
    │   ├── grubx64.efi            owner-signed rEFInd
    │   ├── mmx64.efi              matching vendor MokManager
    │   ├── refind.conf
    │   ├── drivers_mok
    │   │   ├── 01_OpenRuntime.efi
    │   │   ├── 02_HfsPlus.efi
    │   │   └── 03_apfs_aligned.efi
    │   └── themes/...
    └── OC
        ├── OpenCore.efi           owner-signed, existing working binary
        ├── config.plist
        ├── ACPI/...
        ├── Kexts/...
        └── Resources/...
```

Why those names matter:

- `BOOTX64.EFI` is the removable-media firmware entry point.
- This Ubuntu shim expects its normal next stage at `grubx64.efi`. In this layout that file contains rEFInd, not GRUB.
- MokManager is the matching vendor component. Keep its vendor signature rather than treating it as an arbitrary owner-signed replacement.
- rEFInd is the graphical selector. Its macOS entry loads OpenCore; OpenCore then locates the original macOS booter.

The first successful route used rEFInd to preload the three signed EFI drivers. It intentionally avoided loading the same drivers again through OpenCore. Do not combine preload and native-driver configurations without checking for duplicate loads and runtime-driver compatibility.

A minimal illustrative rEFInd configuration is below. `MAC-ESP` and `WINDOWS-ESP` are placeholders for your own volume labels or partition identities; they are not this machine's identifiers.

```text
timeout 0
scanfor manual
default_selection macOS
use_nvram false
resolution max
scan_driver_dirs \EFI\BOOT\drivers_mok

menuentry "macOS" {
    volume "MAC-ESP"
    loader /EFI/OC/OpenCore.efi
    ostype MacOS
    graphics on
}

menuentry "Windows" {
    volume "WINDOWS-ESP"
    loader /EFI/Microsoft/Boot/bootmgfw.efi
    ostype Windows
    graphics on
}
```

Use the existing OpenCore configuration that already supports the machine. The trust-chain settings retained here included:

```text
UEFI.Quirks.ShimRetainProtocol = true
UEFI.Quirks.DisableSecurityPolicy = false
Booter.Quirks.ProtectSecureBoot = true
Booter.Quirks.ProtectUefiServices = true
Booter.Quirks.FixupAppleEfiImages = true
Misc.Security.SecureBootModel = Disabled
```

`SecureBootModel=Disabled` is the separate Apple setting discussed earlier. It is not a substitute for checking the Dell firmware flags.

## 6. Sign the owner-controlled EFI programs

Work on copies. Keep the Microsoft-signed shim and matching vendor MokManager intact. Sign the rEFInd and OpenCore copies with the owner key:

```sh
osslsigncode sign -certs OWNER-MOK.pem -key private/OWNER-MOK.key -h sha256 \
  -n "Local EFI loader" -in refind_x64.efi -out grubx64.efi

osslsigncode sign -certs OWNER-MOK.pem -key private/OWNER-MOK.key -h sha256 \
  -n "Local OpenCore" -in OpenCore-original.efi -out OpenCore.efi

osslsigncode verify -CAfile OWNER-MOK.pem -in grubx64.efi
osslsigncode verify -CAfile OWNER-MOK.pem -in OpenCore.efi
```

EFI drivers also require an appropriate trust path. A signed OpenCore does not make every subsequently loaded EFI image automatically trusted. Sign and inspect OpenRuntime and the filesystem-driver working copies, then compare their actual shim digests as described below.

## 7. Enroll the certificate in MokManager

With an appropriate Dell firmware version and normal Secure Boot mode, enable firmware Secure Boot while retaining the factory keys. Use F12 to boot the prepared USB.

If shim rejects the unrecognized owner-signed second stage, its verification path can offer MokManager. Alternatively use a prepared MokManager menu entry. At its enrollment interface:

1. Choose **Enroll key from disk**.
2. Select the USB filesystem and `OWNER-MOK.der`.
3. Inspect the certificate identity and fingerprint against the local certificate.
4. Choose the available continue/enrollment confirmation and confirm **Yes**.
5. Reboot, use F12 again, and boot the same USB chain.

Wording and filesystem labels vary with the distribution build. This is an X.509 certificate enrollment, not a booter hash enrollment. Do not choose an option that disables validation to make an error disappear.

MOK trust persists in firmware variables. Removing the USB does not remove the enrolled owner key. Later replacing the owner key also requires signing the relevant payloads with the intended key and deliberately maintaining that trust relationship.

## 8. Failure one: valid Authenticode, different shim digest

The initial owner certificate was not the entire solution. Two signed filesystem drivers were accepted by osslsigncode, but failed along the real Secure Boot chain.

### Observed evidence

| Artifact | Raw gaps | Conventional verification | Signature digest vs shim 15.8 |
|---|---:|---|---|
| HFS+ driver | 512 bytes | Passed | Different |
| APFS driver | 4096 + 512 bytes | Passed | Different |
| OpenRuntime control | No equivalent gap | Passed | Equal |
| rEFInd control | No equivalent gap | Passed | Equal |
| OpenCore control | No equivalent gap | Passed | Equal |

The full sanitized before/after values are in [PE_VALIDATION.json](PE_VALIDATION.json).

### Why the distinction matters

The relevant implementation is [shim 15.8 `generate_hash()` in pe.c](https://github.com/rhboot/shim/blob/15.8/pe.c). Its processing skips the checksum and security-directory entry, hashes the remaining headers, sorts sections by raw-file position and hashes their raw bytes. The signed-image tail starts from a byte-count accumulator, not simply from the highest raw-section end.

Raw gaps therefore matter to the sequence of bytes the verifier actually hashes. A successful result from one signing tool is not sufficient evidence that another implementation constructs the same digest. The independent calculation was compared against the digest inside a cryptographically verified signature, not merely a whole-file checksum.

The new [pe_tools.py](pe_tools.py) exposes read-only inspection:

```sh
python3 pe_tools.py digest HfsPlus-signed.efi

python3 pe_tools.py verify HfsPlus-signed.efi \
  --cert OWNER-MOK.pem --osslsigncode osslsigncode
```

`verify` requires conventional signature/certificate verification to succeed first. It then reports whether the signed digest matches shim's digest. Exit status `2` means those digests differ; it does not mean the signature's mathematics failed.

### The repair: describe existing gap bytes as non-executable sections

The repair preserved every original code and data section. It added metadata describing bytes that already existed at their original file offsets:

| Driver | Gap offset, decimal | Gap size | Added section |
|---|---:|---:|---|
| HFS+ | 37888 | 512 | `.sgap0` |
| APFS | 712704 | 4096 | `.sgap0` |
| APFS | 718336 | 512 | `.sgap1` |

Each added section uses characteristics `0x42000040`: initialized data, readable and discardable, without execute permission. New virtual addresses are placed after the original virtual sections with the appropriate section alignment. The original raw offsets, raw sizes, virtual addresses, virtual sizes, permissions and content hashes remain unchanged.

The section count, initialized-data size, `SizeOfImage` and checksum field are updated. There must be sufficient unused section-header space; the helper refuses occupied headers, overlapping raw sections, unsupported alignment, unknown overlays and already signed inputs.

Example using an existing signed **working copy**, not an installed driver:

```sh
osslsigncode remove-signature \
  -in HfsPlus-signed.efi -out HfsPlus-unsigned.efi

python3 pe_tools.py normalize HfsPlus-unsigned.efi HfsPlus-normalized.efi

osslsigncode sign -certs OWNER-MOK.pem -key private/OWNER-MOK.key -h sha256 \
  -n "Local HFS+ driver" -in HfsPlus-normalized.efi -out HfsPlus-fixed-signed.efi

python3 pe_tools.py verify HfsPlus-fixed-signed.efi --cert OWNER-MOK.pem
```

Repeat the same sequence for the affected APFS working copy. The helper generates the required `.sgap` entries from that input's layout rather than hard-coding the offsets above. It is deliberately restricted to eligible x86_64 PE32+ files and writes a new output file with exclusive creation; an existing output is not overwritten.

### What was checked before using the repaired copies

1. Reproduced both original mismatches using the same digest calculation.
2. Confirmed every original section's attributes and content remained identical after normalization.
3. Confirmed the added sections had no execute bit and the raw gaps were covered.
4. Re-signed with the same owner key and passed conventional certificate/signature verification.
5. Confirmed the signature digest and shim digest now matched.
6. Cross-checked the Python calculation against a native harness running the original upstream shim `generate_hash()` function, with host-side crypto and PE-context adapters.
7. Booted the repaired drivers on the actual Secure Boot-enabled machine and checked the resulting load status.

For the published normalizer, its output was also compared byte-for-byte with both normalized working copies used in the successful hardware experiment. The Python digest matched the native reference on eight artifacts, including the two original failures, two repairs, three controls and the processed Apple booter.

This is a compatibility repair for these layouts. It does not make arbitrary malformed PE files valid and does not bypass signature checking. A [public ZFSBootMenu discussion](https://github.com/zbm-dev/zfsbootmenu/discussions/825) also describes conventional verification succeeding while shim rejects an image; its final diagnosis differs from this case. Similar error text alone does not identify a common cause.

## 9. Failure two: the Apple booter changes before verification

Once the second stage, OpenCore and filesystem drivers worked, the Apple booter still needed a valid trust path. The relevant distinction is between:

```text
A. Original boot.efi bytes stored in APFS/Preboot
B. Image after OpenCore's Apple EFI preprocessing
C. Digest produced from B by shim's PE verification algorithm
```

Enrolling a whole-file SHA-256 of A does not establish C. Nor should the original system booter be replaced with an enrollment artifact.

OpenCore's [configuration documentation](https://dortania.github.io/docs/latest/Configuration.html) already discusses this `FixupAppleEfiImages` interaction. The offline source references used here were [ImageLoader.c](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Library/OcBootManagementLib/ImageLoader.c), [OcPeCoffExtLib.c](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Library/OcPeCoffExtLib/OcPeCoffExtLib.c), and the [Apple public-key database](https://github.com/acidanthera/OpenCorePkg/blob/1.0.8/Library/OcAppleKeysLib/OcAppleKeysLib.c).

### Verify the source before preparing a copy

The included [prepare_boot_hash.py](prepare_boot_hash.py) is intentionally limited to the exact tested `25G332` input. It checks the original size and whole-file SHA-256 before processing:

```text
Original bytes: 723512
Original file SHA-256:
016ccd2dde70411ed45b2603d14a5917cc1ce9bda866f086421e8d8e4f22a6cc
```

It then parses the Apple certificate format, requires the embedded RSA public modulus to be present in the official OpenCore Apple-key database, and validates the original PKCS#1 v1.5 RSA-2048/SHA-256 signature. A different build or changed input is rejected. The script must be run with normal Python assertions enabled, without `-O`.

### Reproduce the preprocessing in an enrollment-only copy

For this input the preparation:

1. Clears the DOS-stub range between the DOS header and PE header.
2. Clears the checksum and security-directory entry.
3. Removes the Apple certificate tail from the enrollment representation.
4. Clears the execute bit of the writable/executable `.data` section to reproduce the W^X fixup.
5. Verifies that original code/data bytes, addresses and sizes are preserved.
6. Calculates the resulting shim 15.8 PE digest.
7. Checks that changing an executable byte changes that digest.

The resulting values were:

```text
Prepared bytes: 722952
Prepared whole-file SHA-256:
1c67d9be812fe2566c4c7ca4df1069608d7689c2d39e826461f595d81cf712b4

Prepared shim 15.8 PE SHA-256:
2e868710c257f7486250b7260285a03208e665d7e5ed59483d7db346a6eebfa0
```

Those last two hashes are intentionally different. The second is the value relevant to the selected shim/MokManager image-hash path.

Obtain the original booter from your own system as a read-only working copy, and obtain the official OpenCore 1.0.8 source tree. Then run:

```sh
python3 prepare_boot_hash.py ./boot-original.efi \
  --oc-source ./OpenCorePkg-1.0.8 \
  --output-directory ./enrollment-copy

python3 pe_tools.py digest ./enrollment-copy/MOK-boot-26.7.2.efi
```

The output directory must not already exist. It contains the enrollment-only EFI copy and `boot-hash-preparation.json`. The original input, installed EFI, APFS booter and firmware trust variables are not modified by either tool.

The published helper was rerun locally: its enrollment copy was byte-identical to the earlier hardware-tested copy. A deliberately changed source input was rejected without creating an output directory. The native shim-hash harness independently produced the same PE digest.

The running OpenCore is a custom DBG-109 binary, whereas this offline reproduction uses official 1.0.8 source. The runtime logs, sizes and W^X processing matched the investigation, and the actual enrolled hash enabled the boot. Full byte-for-byte equivalence of all custom-loader processing was not established; another loader or a firmware path that additionally validates disk bytes needs separate testing.

## 10. Enroll the processed-image hash

Copy only the prepared `MOK-boot-26.7.2.efi` to the USB root as an enrollment artifact. This is separate from the earlier certificate enrollment.

In MokManager:

1. Choose **Enroll hash from disk**.
2. Select the USB filesystem.
3. Select `MOK-boot-26.7.2.efi`.
4. Inspect the digest shown by the manager and compare it to the locally calculated shim PE digest.
5. Continue, confirm **Yes**, and reboot.
6. Boot the normal USB rEFInd macOS entry, then the normal macOS entry through OpenCore.

The enrollment copy is never selected as the everyday macOS loader. OpenCore still reads the original Apple file from its original APFS/Preboot path and performs its usual preprocessing. The owner has authorized the exact resulting image by hash.

A hash record grants trust to that particular representation, not to every future Apple booter. Updating macOS, booting an installer or using Recovery can introduce a different image and require a new analysis/enrollment. Calculate values from the actual intended source rather than copying the example hash because the version label looks similar.

## 11. Migrate the verified chain to the internal SSD

After the full USB chain worked with firmware Secure Boot enabled, a fresh hard-disk EFI backup was made and the verified payloads were installed on the macOS SSD. Windows' original EFI files were preserved.

```text
macOS ESP
└── EFI
    ├── refind
    │   ├── refind_x64.efi         actually Microsoft-signed shim
    │   ├── grubx64.efi            actually owner-signed rEFInd
    │   ├── mmx64.efi
    │   ├── refind.conf
    │   ├── drivers_mok/...
    │   └── themes/...
    ├── OC
    │   ├── OpenCore.efi
    │   ├── config.plist
    │   └── ...
    └── BOOT
        ├── BOOTX64.EFI           shim at the fallback path
        ├── grubx64.efi
        ├── mmx64.efi
        ├── refind.conf
        └── matching drivers and resources
```

The existing firmware launcher path used `\EFI\refind\refind_x64.efi`. Keeping that path while changing its payload to shim preserved the usable entry point. Despite its filename, it is shim that the firmware authenticates first. The sibling `grubx64.efi` then provides rEFInd.

For the installed primary rEFInd configuration, `scan_driver_dirs` changes to `\EFI\refind\drivers_mok`. Its macOS menu targets the macOS ESP's OpenCore. Its Windows menu explicitly targets the separate Windows ESP's original `bootmgfw.efi`.

The working launcher configuration included:

```text
Misc.Boot.LauncherOption = Full
Misc.Boot.LauncherPath = \EFI\refind\refind_x64.efi
Misc.Boot.ShowPicker = false
Misc.Boot.Timeout = 0
```

The rEFInd graphical menu remains. `ShowPicker=false` removes the second OpenCore picker from that route. The actual firmware launcher log confirmed an existing valid `Boot0008` entry on this machine; the number itself is machine-specific.

Keep primary and fallback shim/rEFInd/MokManager directories internally consistent. A copied rEFInd configuration that still searches the USB's driver path can leave the hard-disk chain incomplete.

## 12. Prove the internal-SSD result

The decisive test was performed with **both test USB drives disconnected**. The machine restarted, used the internal Samsung SSD chain, and reached the macOS desktop.

Read the firmware flags individually; these read-only commands were checked on this machine:

```sh
nvram 8be4df61-93ca-11d2-aa0d-00e098032b8c:SecureBoot
nvram 8be4df61-93ca-11d2-aa0d-00e098032b8c:SetupMode
nvram 8be4df61-93ca-11d2-aa0d-00e098032b8c:AuditMode
nvram 8be4df61-93ca-11d2-aa0d-00e098032b8c:DeployedMode
```

The GUID above is the standard EFI global-variable namespace, not this machine's UUID. Observed values:

```text
SecureBoot    %01
SetupMode     %00
AuditMode     %00
DeployedMode  %01
```

The check also confirmed the absence of `MokSBStateRT` under shim's standard variable namespace, verified the enrolled booter digest, and decoded the OpenCore boot path locally to confirm the Samsung ESP. Raw boot paths contain disk identities, so only the conclusion is published.

These signals were checked together. A BIOS screenshot alone does not prove which device booted; reaching a desktop alone does not prove firmware verification was enabled. Likewise, macOS' visible BootOrder can be affected by `RequestBootVarRouting`, so it was not used as the sole evidence of Dell's real boot entry.

## 13. Troubleshoot by verification stage

| Last successful stage | Inspect next |
|---|---|
| Firmware can open its menu but rejects the first EFI | Actual shim signer, firmware trust/revocation state, and whether the expected shim payload is at the selected path |
| shim starts but second stage is rejected | Owner certificate enrollment, actual signing key, second-stage filename, certificate eligibility and PE digest |
| rEFInd starts but a filesystem driver fails | That driver's signature, raw layout, independent shim digest, loading path and duplicate loads |
| OpenCore starts but Apple booter is rejected | Actual source booter, preprocessing, exact PE hash enrollment and whether the intended APFS path is selected |
| USB works but SSD boot fails | Real firmware entry, primary/fallback directory consistency, driver paths and correct target ESP |
| Complete no-display condition on affected Dell platform | Dell's model-specific recovery/support procedure |

Keep diagnostics in local files while testing. Do not publish full NVRAM dumps, raw network reports, signing certificates or device paths. Change one verification stage at a time so a successful or failed result has a clear interpretation.

## 14. Upstream work and acknowledgment

- [OpenCorePkg 1.0.8](https://github.com/acidanthera/OpenCorePkg/tree/1.0.8) and [configuration documentation](https://dortania.github.io/docs/latest/Configuration.html).
- [shim 15.8](https://github.com/rhboot/shim/tree/15.8), its [PE implementation](https://github.com/rhboot/shim/blob/15.8/pe.c), [MokManager](https://github.com/rhboot/shim/blob/15.8/MokManager.c) and [MOK variable documentation](https://github.com/rhboot/shim/blob/main/MokVars.txt).
- [rEFInd](https://www.rodsbooks.com/refind/).
- [osslsigncode](https://github.com/mtrojnar/osslsigncode).
- [Dell's advisory](https://www.dell.com/support/kbdoc/en-us/000250090/alienware-area-51-aat2250-does-not-display-after-changing-bios-settings).
- [NullMoth NVIDIA driver](https://github.com/nullmoth/nvidia-macos-driver) and [1401](https://github.com/nullmoth/1401).
- [AirportItlwm-BE200](https://github.com/Ersiter/AirportItlwm-BE200), [laobamac/itlwm](https://github.com/laobamac/itlwm) and [OpenIntelWireless](https://github.com/OpenIntelWireless/itlwm).

With appreciation to **ChatGPT** for helping with the research, debugging, testing and preparation of this reproducible record. The underlying bootloaders, drivers and upstream mechanisms are credited to their authors above.
