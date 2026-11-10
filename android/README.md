# ZV-E10 II 安卓工具

公开 APK 为 0.2.5，本地测试源码为 0.2.8。最低要求 Android 8.0，快门音和图标写入需 Android 9 或更高版本。

[下载公开测试 APK](downloads/ZVE10-II-Android-0.2.5-public.apk)。公开包支持离线音频处理、外观文件生成和 USB 检测。服务模式、相机备份、快门音写入、外观导入和图标更新需要带本地资源的构建。

- 快门音。选取音频、调节音量、生成 24 kHz 单声道 WAV、试听并导出。限制为 0.620 秒，超长文件需要先剪短。生成的 WAV 可在电脑版选取后写入相机。
- FL2／FL3。分别选择三份匹配的原始备份，选择 FL2、FL3 或两套，校验原始文件和生成结果的 SHA-256 后导出 ZIP。备份文件名和适用基线见 [外观数据说明](../filters/README.md)。
- USB 检测。使用支持 OTG 的数据线接入相机，选择 USB 海量存储器，点「检测 USB 相机」并同意安卓的授权提示。应用检测 Sony USB 存储设备和授权状态，并发送只读 SCSI INQUIRY。若安卓系统仍占用 ZV-E10M2 的 USB 存储接口，先在系统通知中安全弹出 Sony U 盘，保持连接，再点击「弹出后接管检测」。确认后应用会尝试临时接管接口，仅发送只读识别请求。

## 服务模式检测

安装带本地服务认证资源的测试包。相机选择 USB 海量存储器，安全弹出 Sony U 盘并保持数据线连接，点「相机服务模式检测」并确认。切换后再次点击并授权，应用会尝试读取固件版本并结束服务会话。此入口用于验证手机直连。

## 相机文件备份

同样的连接流程中，点「备份相机文件」读取并校验四个相机文件，完成后导出 ZIP。这是只读诊断备份，尚不包含全部写入所需的状态。

## 临时写入测试

测试在相机临时目录写入 15,360 字节，逐字节回读后删除并确认文件已不存在。这个入口用于验证传输，尚不安装快门音或外观。

## 写入预制快门音

此入口需要带预制数据的本地测试 APK、Android 9 及以上和匹配的相机起始状态。应用会在备份与哈希校验通过后写入，最后再次读回核对。发生中断时保留应用数据。机主已在一台 ZV-E10M2 固件 1.02 上确认，使用本地测试 APK 从安卓手机直连写入的预制快门音可用。原厂声音恢复使用电脑版。

本地构建时，用配置好的电脑版 Python 运行 prepare_sound.py，依次提供电脑版目录、已准备的目标 state.json 和新的输出目录。将输出目录作为 build.ps1 的 -PreparedSound 参数。

## 自定义快门音直写

本地测试 APK 自 0.1.8 起支持直接写入手机生成的快门音。选择不超过 0.620 秒的音频，生成并试听后，点「写入自定义快门音」。进入 USB 服务模式后再次点击，确认相机电量超过 50%。写入前工具会备份并校验相机状态，完成后回读。请关机断电后重新开机拍照试听。机主已在 ZV-E10M2 固件 1.02 上确认，从手机选择并直连写入的自定义快门音可用。

构建此入口时，用配置好的电脑版 Python 运行 `prepare_custom_templates.py`，依次提供电脑版目录和新的输出目录，并将输出目录传给 `build.ps1 -CustomSound`。模板以两份已知的自定义快门音状态为起点，手机成功写入后会记录新的状态。

实时状态固定在顶部。0.2.1 将功能分为「快门音」「创意外观」「相机」三个页签。右上角「日志」可实时查看带时间和类别的记录，也可复制日志。

## 导入 FL2／FL3 到相机

0.2.2 本地测试包在「创意外观」页提供「导入 FL2／FL3 到相机」。接入相机、选择 USB 海量存储器并在手机上安全弹出 Sony U 盘。保持连接，按提示切到服务模式并再次授权。确认电量超过 50% 后，应用会检查、备份并写入匹配的相机状态。原 IN 对应 FL2，原 SH 对应 FL3。检测到已安装的两套数据时会跳过写入。安卓正式导入尚待真机验证。

本地构建需用配置好的电脑版 Python 运行 `prepare_looks.py`，提供电脑版目录和新的输出目录，再将输出目录传给 `build.ps1 -CameraLooks`。同时提供 `-CustomSound` 和 `-ServiceAuth`，供相机及快门音状态校验。

## 导入预制 LUT 外观

0.2.6 本地包可把电脑预制的两套 LUT 外观导入原 IN／SH。电脑端沿用 Windows 0.3.6 的色调和色彩拟合流程，并为目标相机编译和离线验证写入程序。手机上按「创意外观」页显示的两套预制名称确认后，通过同一 USB 服务模式入口导入。应用只接受构建时核对过的相机状态，完成后会回读核对。重启后选 IN 和 SH 分别拍 JPEG，检查实际效果。

重新预制时，先保留一次完成写入与回读的 Windows LUT 操作目录，再运行：

```powershell
python android/prepare_looks.py . android/build/my-lut --from-operation operations/<已完成操作目录> --in-cube <IN.cube> --sh-cube <SH.cube>
```

将新目录传给 `build.ps1 -CameraLut`，同时提供本地 `-ServiceAuth`。选择的文件在电脑端转换并随本地 APK 打包。Windows 和 Android 已通过离线数据对照，安卓实际写入及重启后的 JPEG 效果待真机验证。

0.2.7 支持在手机上来回切换两套预制组合。构建时用 `prepare_looks.py --from-prepared` 以第一套的目标文件为起点，准备切回原组合的数据，并将该目录传给 `build.ps1 -AlternateCameraLut`。两套的起点和目标须互相匹配。连接相机后，在「创意外观」选目标套装，再点「导入外观到相机」。

0.2.8 本地测试包可直接在手机上选文件。打开「创意外观」，为 IN 和 SH 各选一个纯 3D `.cube`，再点「导入外观到相机」。支持每轴 2–65 点和最大 24 MB 的文件。工具在手机端拟合相机色调曲线与色彩矩阵，回读通过后记录当前外观，可继续更换或切回预设。真机 JPEG 效果需试拍确认。

本地打包时运行 `prepare_lut_templates.py`，依次传入电脑版目录、准备好的 `-CameraLut` 目录和新的模板输出目录。构建 APK 时用 `-LutTemplates` 指定该输出。模板只允许填入已验证的 12 个相机曲线窗口对应的数据。

## 下载本机构建模板

[下载安卓 0.2.8 模板 ZIP](downloads/ZVE10-II-Android-0.2.8-templates.zip)。模板带有 ZV-E10M2 固件 1.02 的兼容状态校验，实际写入前还会核对相机文件。若起始状态不同，需要用相机的对应备份重新生成模板。

在仓库根目录解压至 `android/build/templates`，再按下面的参数构建。服务认证文件须从自己的本地环境提供。预制音频需单独用 `prepare_sound.py` 生成，并通过 `-PreparedSound` 传入。

```powershell
$templates = 'android/build/templates'
./android/build.ps1 -JavaHome 'C:/path/to/jdk-17' `
  -AndroidJar 'C:/path/to/android-35/android.jar' -BuildTools 'C:/path/to/build-tools/35.0.0' `
  -ServiceAuth 'C:/local/sony-service-auth.bin' -CustomSound "$templates/custom-sound" `
  -CameraLooks "$templates/camera-looks" -CameraLut "$templates/camera-lut" `
  -AlternateCameraLut "$templates/camera-lut-alt" -LutTemplates "$templates/lut-templates" `
  -CameraIcons "$templates/camera-icons" -ExtraCameraIcons "$templates/extra" `
  -Display32CameraIcons "$templates/display32"
```

## 更新相机左侧图标

0.2.5 本地测试包在「创意外观」页提供「更新相机 FL2／FL3 图标」。适用于已装好两套成像数据的 ZV-E10M2 1.02。按同样的 USB 服务模式连接流程操作，确认电量超过 50%。应用先备份原图标文件，再分批写入并回读。重启相机后检查左侧列表。图标资源解码和写入辅助程序已通过离线验证，0.2.3 已在真机完成回读，但左侧显示仍未更新。0.2.4 补上 64×27 和 64×40 两组图标，并识别此前已写入的资源。Windows 0.3.4 补齐 32_IPSX 图标后，机主确认左侧 FL2／FL3 显示正常。安卓 0.2.5 使用同一套资源，安卓入口仍待真机验证。

本地构建需要额外提供经校验的图标辅助程序和清单，使用 `build.ps1 -CameraIcons` 指向原图标辅助程序目录，并分别用 `-ExtraCameraIcons` 和 `-Display32CameraIcons` 提供其余 23_IPSX 资源和 32_IPSX 资源。

## 构建

使用 JDK 17、Android SDK Platform 35 和 Build Tools 35.0.0。在 PowerShell 中运行：

```powershell
./android/build.ps1 -JavaHome 'C:/path/to/jdk-17' -AndroidJar 'C:/path/to/android-35/android.jar' -BuildTools 'C:/path/to/build-tools/35.0.0'
```

脚本生成并校验测试签名 APK，默认保存在本目录的 `build` 文件夹。调试签名仅供测试安装。

本地测试包可通过 -ServiceAuth 提供与电脑版相同的认证资源。资源文件不随源码分发。
