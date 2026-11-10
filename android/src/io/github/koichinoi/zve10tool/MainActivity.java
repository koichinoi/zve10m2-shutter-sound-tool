package io.github.koichinoi.zve10tool;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.hardware.usb.*;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.widget.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final int PAPER = 0xfffff7f6, INK = 0xff302028, MUTED = 0xff715663;
    private static final int BERRY = 0xff9a2146, DARK = 0xff45192b, BLUSH = 0xffffe8ee;
    private final ScrollView[] screens = new ScrollView[3];
    private final Button[] tabs = new Button[3];
    private int activeTab;
    private static final String USB_PERMISSION = "io.github.koichinoi.zve10tool.USB_PERMISSION";
    private static final int PICK_AUDIO = 1, EXPORT_AUDIO = 2, EXPORT_LOOKS = 3, EXPORT_CAMERA = 4, PICK_BACKUP = 10;
    private final Uri[] originals = new Uri[Looks.FILES.length];
    private Spinner lutSelector;
    private String primaryLut;
    private String alternateLut;
    private static final int PICK_CUBE = 20;
    private final MobileCube[] selectedCubes = new MobileCube[2];
    private final Button[] cubeButtons = new Button[2];
    private final String[] cubeNames = new String[2];
    private int customLutIndex = -1;

    private boolean customLutSelected() {
        return customLutIndex >= 0 && lutSelector.getSelectedItemPosition() == customLutIndex;
    }

    private String selectedLooksRoot() {
        if (primaryLut == null) return MobileLooks.ROOT;
        return alternateLut != null && lutSelector != null && lutSelector.getSelectedItemPosition() == 1
                ? MobileLooks.ALTERNATE_LUT_ROOT : MobileLooks.LUT_ROOT;
    }
    private final Button[] backupButtons = new Button[Looks.FILES.length];
    private TextView liveStatus;
    private final java.util.ArrayDeque<LogEntry> statusLog = new java.util.ArrayDeque<>();
    private static final java.time.format.DateTimeFormatter LOG_TIME =
            java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss", Locale.ROOT);
    private AlertDialog logDialog;
    private LinearLayout logRows;
    private ScrollView logScroll;
    private TextView logCount;

    private static final class LogEntry {
        final String time, message;
        final Area area;
        LogEntry(Area area, String message) {
            this.time = java.time.LocalTime.now().format(LOG_TIME);
            this.area = area;
            this.message = message;
        }
    }
    private enum Area {
        AUDIO("快门音"), LOOKS("创意外观"), USB("USB"), SERVICE("相机");
        final String label;
        Area(String label) { this.label = label; }
    }
    private Button chooseAudio, preview, saveAudio, writeCustom, generate, saveLooks;
    private SeekBar volume;
    private Spinner looks;
    private Uri audio;
    private File audioOutput, looksOutput;
    private MediaPlayer player;
    private boolean working;
    private boolean checkingUsb;
    private UsbManager usb;
    private Button retryUsb;
    private Button exportBackup;
    private File cameraBackup;
    private static final String SERVICE_PERMISSION = USB_PERMISSION + ".SERVICE";
    private static final String BACKUP_PERMISSION = USB_PERMISSION + ".BACKUP";
    private static final String WRITE_TEST_PERMISSION = USB_PERMISSION + ".WRITE_TEST";
    private static final String SOUND_PERMISSION = USB_PERMISSION + ".SOUND";
    private static final String CUSTOM_PERMISSION = USB_PERMISSION + ".CUSTOM";
    private static final String LOOKS_PERMISSION = USB_PERMISSION + ".LOOKS";
    private static final String ICONS_PERMISSION = USB_PERMISSION + ".ICONS";
    private enum ServiceAction {
        DETECT("相机服务模式检测", SERVICE_PERMISSION), BACKUP("备份相机文件", BACKUP_PERMISSION),
        WRITE_TEST("测试临时写入", WRITE_TEST_PERMISSION), SOUND("写入预制快门音", SOUND_PERMISSION), CUSTOM("写入自定义快门音", CUSTOM_PERMISSION), LOOKS("导入外观到相机", LOOKS_PERMISSION), ICONS("更新相机 FL2／FL3 图标", ICONS_PERMISSION);
        final String label, permission;
        ServiceAction(String label, String permission) {
            this.label = label;
            this.permission = permission;
        }
    }

    private final BroadcastReceiver usbPermission = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (USB_PERMISSION.equals(intent.getAction())) checkUsb(false);
            if (SERVICE_PERMISSION.equals(intent.getAction())) checkService(false, ServiceAction.DETECT);
            if (BACKUP_PERMISSION.equals(intent.getAction())) checkService(false, ServiceAction.BACKUP);
            if (WRITE_TEST_PERMISSION.equals(intent.getAction())) checkService(false, ServiceAction.WRITE_TEST);
            if (SOUND_PERMISSION.equals(intent.getAction())) checkService(false, ServiceAction.SOUND);
            if (CUSTOM_PERMISSION.equals(intent.getAction())) checkService(false, ServiceAction.CUSTOM);
            if (LOOKS_PERMISSION.equals(intent.getAction())) checkService(false, ServiceAction.LOOKS);
            if (ICONS_PERMISSION.equals(intent.getAction())) checkService(false, ServiceAction.ICONS);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        usb = getSystemService(UsbManager.class);
        IntentFilter filter = new IntentFilter(USB_PERMISSION);
        filter.addAction(SERVICE_PERMISSION);
        filter.addAction(BACKUP_PERMISSION);
        filter.addAction(WRITE_TEST_PERMISSION);
        filter.addAction(SOUND_PERMISSION);
        filter.addAction(CUSTOM_PERMISSION);
        filter.addAction(LOOKS_PERMISSION);
        filter.addAction(ICONS_PERMISSION);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(usbPermission, filter, RECEIVER_NOT_EXPORTED);
        else registerReceiver(usbPermission, filter);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(PAPER);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            root.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(dp(16), dp(14), dp(16), dp(12));
        header.setBackground(rounded(DARK, 22));
        LinearLayout.LayoutParams headerParams = new LinearLayout.LayoutParams(-1, -2);
        headerParams.setMargins(dp(14), dp(8), dp(14), dp(8));
        root.addView(header, headerParams);
        LinearLayout identity = new LinearLayout(this);
        identity.setGravity(android.view.Gravity.CENTER_VERTICAL);
        header.addView(identity);
        ImageView mascot = new ImageView(this);
        mascot.setImageResource(getApplicationInfo().icon);
        mascot.setBackground(rounded(BLUSH, 12));
        mascot.setClipToOutline(true);
        identity.addView(mascot, new LinearLayout.LayoutParams(dp(44), dp(44)));
        LinearLayout nameplate = new LinearLayout(this);
        nameplate.setOrientation(LinearLayout.VERTICAL);
        nameplate.setPadding(dp(12), 0, 0, 0);
        identity.addView(nameplate, new LinearLayout.LayoutParams(0, -2, 1));
        TextView title = label(nameplate, "ZV-E10 II 相机工具", 19, true);
        title.setTextColor(Color.WHITE);
        label(nameplate, "固件 1.02  ·  安卓 0.2.9", 12, false).setTextColor(0xffffcddd);
        Button history = new Button(this, null, android.R.attr.borderlessButtonStyle);
        history.setText("日志");
        history.setMinWidth(0);
        history.setTextColor(Color.WHITE);
        history.setOnClickListener(view -> showLog());
        identity.addView(history, new LinearLayout.LayoutParams(-2, dp(48)));

        LinearLayout statusRow = new LinearLayout(this);
        statusRow.setGravity(android.view.Gravity.CENTER_VERTICAL);
        statusRow.setPadding(dp(12), dp(8), dp(12), dp(8));
        statusRow.setBackground(rounded(0xff603047, 12));
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(-1, -2);
        statusParams.topMargin = dp(8);
        header.addView(statusRow, statusParams);
        label(statusRow, "●", 12, false).setTextColor(0xffffaabd);
        liveStatus = new TextView(this);
        liveStatus.setTextColor(0xffffedf3);
        liveStatus.setPadding(dp(8), 0, 0, 0);
        liveStatus.setTextSize(14);
        liveStatus.setMinLines(2);
        liveStatus.setMaxLines(3);
        liveStatus.setEllipsize(android.text.TextUtils.TruncateAt.END);
        statusRow.addView(liveStatus, new LinearLayout.LayoutParams(0, -2, 1));
        setStatus(Area.SERVICE, "等待操作 · 固件 1.02");

        LinearLayout navigation = new LinearLayout(this);
        navigation.setPadding(dp(4), dp(3), dp(4), dp(3));
        navigation.setBackground(rounded(0xfff6e4e9, 16));
        LinearLayout.LayoutParams navParams = new LinearLayout.LayoutParams(-1, -2);
        navParams.setMargins(dp(14), 0, dp(14), dp(8));
        root.addView(navigation, navParams);
        String[] tabLabels = {"快门音", "创意外观", "相机"};
        for (int i = 0; i < tabs.length; i++) {
            int tab = i;
            Button item = new Button(this, null, android.R.attr.borderlessButtonStyle);
            item.setText(tabLabels[i]);
            item.setMinWidth(0);
            item.setPadding(0, 0, 0, 0);
            item.setOnClickListener(view -> selectTab(tab));
            tabs[i] = item;
            navigation.addView(item, new LinearLayout.LayoutParams(0, dp(48), 1));
        }
        FrameLayout content = new FrameLayout(this);
        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);

        LinearLayout page = card(screen(content, 0));
        section(page, "自定义快门音");
        label(page, "选取最长 0.620 秒的音频，调整音量、试听并导出 WAV。", 14, false);
        chooseAudio = button(page, "选择音频", view -> pick("audio/*", PICK_AUDIO));
        TextView gain = label(page, "音量 100%", 14, false);
        volume = new SeekBar(this);
        volume.setMax(90);
        volume.setProgress(90);
        volume.setProgressTintList(ColorStateList.valueOf(BERRY));
        volume.setThumbTintList(ColorStateList.valueOf(BERRY));
        volume.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onStartTrackingTouch(SeekBar bar) {}
            public void onStopTrackingTouch(SeekBar bar) {}
            public void onProgressChanged(SeekBar bar, int progress, boolean user) {
                gain.setText("音量 " + (progress + 10) + "%");
                if (user) {
                    audioOutput = null;
                    if (audio != null) setStatus(Area.AUDIO, "音量已调整，请重新生成。");
                    refresh();
                }
            }
        });
        page.addView(volume);
        button(page, "生成快门音", view -> prepareAudio());
        LinearLayout audioActions = actionRow(page);
        preview = action(audioActions, "试听", false, true, view -> play());
        saveAudio = action(audioActions, "导出 WAV", false, true,
                view -> export("audio/wav", "shutter.wav", EXPORT_AUDIO));
        writeCustom = button(page, "写入自定义快门音", view -> checkService(true, ServiceAction.CUSTOM));

        page = card(screen(content, 1));
        section(page, "FL2／FL3 创意外观");
        label(page, "选择三份匹配的原始备份，校验后生成外观 ZIP。", 14, false);
        for (int i = 0; i < originals.length; i++) {
            int slot = i;
            backupButtons[i] = action(page, Looks.FILES[i], false, false, view -> pick("*/*", PICK_BACKUP + slot));
        }
        looks = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item,
                new String[] {"FL2 + FL3", "FL2", "FL3"});
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        looks.setAdapter(adapter);
        looks.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> parent) {}
            public void onItemSelected(AdapterView<?> parent, View view, int index, long id) {
                if (looksOutput != null) setStatus(Area.LOOKS, "外观选项已调整，请重新生成。");
                looksOutput = null;
                refresh();
            }
        });
        page.addView(looks);
        generate = button(page, "生成外观文件", view -> prepareLooks());
        saveLooks = action(page, "导出外观 ZIP", false, false, view ->
                export("application/zip", "ZVE10M2-" + lookLabel() + ".zip", EXPORT_LOOKS));

        if (MobileLooks.available(this)) {
            primaryLut = MobileLooks.lutLabels(this, MobileLooks.LUT_ROOT);
            alternateLut = MobileLooks.lutLabels(this, MobileLooks.ALTERNATE_LUT_ROOT);
            boolean customLut = primaryLut != null && DynamicLooks.available(this);
            if (primaryLut != null && (alternateLut != null || customLut)) {
                label(page, "选择要切换的 LUT 套装", 14, true);
                lutSelector = new Spinner(this);
                java.util.ArrayList<String> choices = new java.util.ArrayList<>();
                choices.add("套装 A");
                if (alternateLut != null) choices.add("套装 B");
                if (customLut) {
                    customLutIndex = choices.size();
                    choices.add("自选 .cube");
                }
                ArrayAdapter<String> lutOptions = new ArrayAdapter<>(this,
                        android.R.layout.simple_spinner_item, choices);
                lutOptions.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
                lutSelector.setAdapter(lutOptions);
                page.addView(lutSelector);
                label(page, "套装 A\n" + primaryLut
                        + (alternateLut == null ? "" : "\n\n套装 B\n" + alternateLut), 13, false);
            } else if (primaryLut != null) {
                label(page, "本地预制 LUT 外观\n" + primaryLut, 13, false);
            }
            if (customLut) {
                for (int i = 0; i < cubeButtons.length; i++) {
                    int slot = i;
                    cubeButtons[i] = button(page, i == 0 ? "为 IN 选择 .cube" : "为 SH 选择 .cube",
                            view -> chooseCube(slot));
                }
                label(page, "支持每轴 2–65 点的纯 3D .cube。两槽都选好后可直接导入。", 13, false);
            }
            button(page, ServiceAction.LOOKS.label, view -> checkService(true, ServiceAction.LOOKS));
            label(page, "导入前会备份并核对当前相机状态。", 13, false);
        }

        if (MobileIcons.available(this)) {
            button(page, "更新相机 FL2／FL3 图标", view -> checkService(true, ServiceAction.ICONS));
            label(page, "适用于已装好 FL2／FL3 的相机。更新列表左侧原 IN／SH 图标。", 13, false);
        }

        LinearLayout cameraPage = screen(content, 2);
        page = card(cameraPage);
        section(page, "USB 相机连接");
        label(page, "用 OTG 数据线连接相机，选择 USB 海量存储器。", 14, false);
        button(page, "检测 USB 相机", view -> checkUsb(true));
        retryUsb = button(page, "弹出后接管检测", null);
        retryUsb.setVisibility(View.GONE);
        button(page, "相机服务模式检测", view -> checkService(true, ServiceAction.DETECT));
        page = card(cameraPage);
        section(page, "备份与测试");
        button(page, "备份相机文件", view -> checkService(true, ServiceAction.BACKUP));
        exportBackup = action(page, "导出相机备份 ZIP", false, false, view ->
                export("application/zip", "ZVE10M2-camera-backup.zip", EXPORT_CAMERA));
        action(page, "测试临时写入", false, false, view -> checkService(true, ServiceAction.WRITE_TEST));
        action(page, "写入预制快门音", false, false, view -> {
            if (MobileSound.available(this)) checkService(true, ServiceAction.SOUND);
            else setStatus(Area.SERVICE, "当前安装包缺少预制快门音。");
        });
        selectTab(state == null ? 0 : state.getInt("activeTab"));
        refresh();
    }

    private void checkService(boolean ask, ServiceAction action) {
        if (usb == null || checkingUsb || working) return;
        if (action == ServiceAction.LOOKS && customLutSelected()
                && (selectedCubes[0] == null || selectedCubes[1] == null)) {
            setStatus(Area.LOOKS, "请为 IN 和 SH 各选一个有效的 .cube 文件。");
            return;
        }
        if (action == ServiceAction.CUSTOM) {
            if (audioOutput == null) {
                setStatus(Area.SERVICE, "请先选择并生成快门音。");
                return;
            }
            try (InputStream input = getAssets().open(CustomSound.ROOT + "manifest.json")) {
                // This feature requires a camera-specific local build.
            } catch (IOException missing) {
                setStatus(Area.SERVICE, "当前安装包缺少自定义快门音写入模板。");
                return;
            }
        }

        UsbDevice camera = null;
        for (UsbDevice device : usb.getDeviceList().values()) {
            if (!SonyService.isService(device) && !UsbInquiry.supportsRetry(device)) continue;
            if (camera != null) {
                setStatus(Area.SERVICE, "检测到多个匹配设备，请只连接一台相机。");
                return;
            }
            camera = device;
        }
        if (camera == null) {
            setStatus(Area.SERVICE, "请连接相机并选择 USB 海量存储器。");
            return;
        }
        if (!usb.hasPermission(camera)) {
            setStatus(Area.SERVICE, "需要为当前 USB 模式授权。");
            if (ask) {
                Intent result = new Intent(action.permission).setPackage(getPackageName());
                usb.requestPermission(camera, PendingIntent.getBroadcast(this, 0, result, PendingIntent.FLAG_IMMUTABLE));
            }
            return;
        }
        UsbDevice selected = camera;
        if (SonyService.isService(selected)) {
            if (action == ServiceAction.LOOKS || action == ServiceAction.ICONS) {
                if (ask) {
                    new AlertDialog.Builder(this).setTitle(action.label)
                            .setMessage(action == ServiceAction.ICONS
                                    ? "将备份相机的图标资源，再更新左侧 IN／SH 图标。请保持数据线连接。"
                                    : "将先核对相机状态并备份，再替换原 IN／SH 的成像数据。请保持数据线连接。"
                                    + (primaryLut == null ? "" : "\n\n" + (customLutSelected()
                                            ? "IN · " + cubeNames[0] + "\nSH · " + cubeNames[1]
                                            : selectedLooksRoot().equals(MobileLooks.LUT_ROOT) ? primaryLut : alternateLut)))
                            .setNegativeButton("取消", null)
                            .setPositiveButton("电量超过 50%，继续", (dialog, button) -> runService(selected, false, action))
                            .show();
                } else {
                    setStatus(Area.LOOKS, "已授权。再次点击「" + action.label + "」并确认。");
                }
            } else if (action == ServiceAction.SOUND || action == ServiceAction.CUSTOM) {
                if (ask) confirmSound(selected, action);
                else setStatus(Area.SERVICE, "已授权。再次点击「" + action.label + "」并确认。");
            } else if (action != ServiceAction.WRITE_TEST) {
                runService(selected, false, action);
            } else if (ask) {
                new AlertDialog.Builder(this)
                        .setTitle("测试相机临时文件写入")
                        .setMessage("测试会写入一个临时文件，逐字节核对后删除。请保持相机连接。")
                        .setNegativeButton("取消", null)
                        .setPositiveButton("开始测试", (dialog, button) -> runService(selected, false, action))
                        .show();
            } else {
                setStatus(Area.SERVICE, "已授权，再点一次「测试临时写入」并确认。");
            }
        } else if (ask) {
            new AlertDialog.Builder(this)
                    .setTitle("确认已安全弹出 Sony U 盘")
                    .setMessage("请先在系统通知中弹出 Sony U 盘并保持数据线连接。检测将切换 USB 服务模式并读取固件版本。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("已弹出，继续", (dialog, button) -> runService(selected, true, action))
                    .show();
        } else {
            setStatus(Area.SERVICE, "已授权。弹出 Sony U 盘后再点一次「" + action.label + "」。");
        }
    }

    private void confirmSound(UsbDevice camera, ServiceAction action) {
        try {
            new AlertDialog.Builder(this)
                    .setTitle(action == ServiceAction.CUSTOM ? "写入刚生成的快门音" : "写入 " + MobileSound.name(this))
                    .setMessage("将先备份并核对相机状态。请确认相机电量超过 50%，写入时保持应用在前台，保持数据线连接。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("电量超过 50%，写入", (dialog, button) -> runService(camera, false, action))
                    .show();
        } catch (Exception error) {
            setStatus(Area.SERVICE, "无法读取预制快门音：" + error.getLocalizedMessage());
        }
    }

    private void runService(UsbDevice camera, boolean switching, ServiceAction action) {
        boolean backup = action == ServiceAction.BACKUP;
        boolean sound = action == ServiceAction.SOUND || action == ServiceAction.CUSTOM;
        File customWav = action == ServiceAction.CUSTOM ? audioOutput : null;
        if (checkingUsb || working) return;
        UsbDevice current = usb.getDeviceList().get(camera.getDeviceName());
        if (current == null || current.getProductId() != camera.getProductId()
                || current.getVendorId() != camera.getVendorId() || !usb.hasPermission(current)) {
            setStatus(Area.SERVICE, "USB 设备已变化，请重新检测。");
            return;
        }
        checkingUsb = true;
        String looksRoot = selectedLooksRoot();
        MobileCube[] cubes = action == ServiceAction.LOOKS && customLutSelected() ? selectedCubes.clone() : null;
        refresh();
        if ((backup || sound || action == ServiceAction.LOOKS || action == ServiceAction.ICONS) && !switching) {
            getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }
        retryUsb.setVisibility(View.GONE);
        setStatus(Area.SERVICE, switching ? "正在请求切换相机服务模式…" : "正在认证并读取固件版本…");
        new Thread(() -> {
            String message;
            File completedBackup = null;
            java.util.function.Consumer<String> progress = update -> runOnUiThread(() -> {
                if (!isDestroyed()) setStatus(Area.SERVICE, update);
            });
            try {
                byte[] keys = new byte[3072];
                try (DataInputStream input = new DataInputStream(getAssets().open("sony-service-auth.bin"))) {
                    input.readFully(keys);
                    if (input.read() != -1) throw new IOException("服务认证资源无效");
                } catch (FileNotFoundException error) {
                    throw new IOException("此 APK 缺少本地服务认证资源", error);
                }
                try (SonyService service = new SonyService(usb, current, switching)) {
                    service.start();
                    boolean switched = false;
                    try {
                        service.authenticate(keys);
                        switched = switching;
                        if (switching) {
                            message = "已请求切换。等待几秒，再点「"
                                    + action.label + "」并授权。";
                        } else {
                            String version = service.readFirmware();
                            if (!"33002_03.2025101101".equals(version)) throw new IOException("固件版本与目标版本不匹配");
                            message = "服务模式读取成功 · ZV-E10M2 固件 1.02";
                            if (backup) {
                                File archive = File.createTempFile("zve-camera-", ".zip", getCacheDir());
                                try {
                                    CameraBackup.create(service, archive, progress);
                                    completedBackup = archive;
                                } finally {
                                    if (completedBackup == null) archive.delete();
                                }
                                message = "4 个相机文件已备份并校验，可以导出 ZIP。";
                            } else if (action == ServiceAction.WRITE_TEST) {
                                service.testTemporaryWrite();
                                message = "临时写入、逐字节回读和删除均成功。";
                            } else if (action == ServiceAction.ICONS) {
                                boolean installed = MobileIcons.install(this, service, progress);
                                message = installed ? "图标更新和回读通过，请重启相机查看左侧列表。"
                                        : "相机图标已是 FL2／FL3，已跳过写入。";
                            } else if (action == ServiceAction.LOOKS) {
                                boolean installed = MobileLooks.install(this, service, looksRoot, cubes, progress);
                                message = installed ? "外观导入和回读通过，请重启相机并在 IN／SH 试拍 JPEG。"
                                        : "相机已安装所选外观，已核对并跳过写入。";
                            } else if (sound) {
                                completedBackup = MobileSound.install(this, service, customWav, progress);
                                message = "快门音写入和回读通过。拔线，关机等读写灯熄灭，取出电池一分钟，再开机试听。";
                            }
                        }
                    } finally {
                        if (!switched) service.stop();
                    }
                }
            } catch (Exception error) {
                message = (sound || action == ServiceAction.LOOKS || action == ServiceAction.ICONS) && !switching
                        ? "相机操作未确认完成：" + error.getLocalizedMessage() + "。请保留应用数据和提示。"
                        : "服务检测未完成：" + error.getLocalizedMessage() + "。若相机已切换，可重新检测。";
            }
            String status = message;
            File result = completedBackup;
            runOnUiThread(() -> {
                checkingUsb = false;
                if (isDestroyed()) {
                    if (result != null && result.getParentFile().equals(getCacheDir())) result.delete();
                    return;
                }
                getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                if (result != null) {
                    if (cameraBackup != null && cameraBackup.getParentFile().equals(getCacheDir())) cameraBackup.delete();
                    cameraBackup = result;
                }
                setStatus(Area.SERVICE, status);
                refresh();
            });
        }, "zve-service-check").start();
    }

    private void checkUsb(boolean ask) {
        if (checkingUsb) return;
        retryUsb.setVisibility(View.GONE);
        if (usb == null || !getPackageManager().hasSystemFeature("android.hardware.usb.host")) {
            setStatus(Area.USB, "手机未报告 USB Host 支持。");
            return;
        }
        UsbDevice sony = null;
        for (UsbDevice device : usb.getDeviceList().values()) {
            if (device.getVendorId() != 0x054c) continue;
            for (int i = 0; i < device.getInterfaceCount(); i++) {
                if (device.getInterface(i).getInterfaceClass() != UsbConstants.USB_CLASS_MASS_STORAGE) continue;
                if (sony != null) {
                    setStatus(Area.USB, "检测到多个 Sony 存储接口，请仅连接一台相机。");
                    return;
                }
                sony = device;
                break;
            }
        }
        if (sony == null) {
            setStatus(Area.USB, "未检测到 Sony 海量存储设备。");
            return;
        }
        String name = sony.getProductName();
        if (name == null || name.isEmpty()) name = "Sony USB 设备";
        String id = String.format(Locale.ROOT, " · %04X:%04X", sony.getVendorId(), sony.getProductId());
        boolean granted = usb.hasPermission(sony);
        setStatus(Area.USB, name + id + (granted ? " · 已取得 USB 权限" : " · 尚未取得 USB 权限"));
        if (granted) {
            probeUsb(sony, name + id, false);
        } else if (ask) {
            Intent result = new Intent(USB_PERMISSION).setPackage(getPackageName());
            PendingIntent callback = PendingIntent.getBroadcast(this, 0, result, PendingIntent.FLAG_IMMUTABLE);
            usb.requestPermission(sony, callback);
        }
    }

    private void probeUsb(UsbDevice device, String prefix, boolean force) {
        if (checkingUsb) return;
        checkingUsb = true;
        retryUsb.setVisibility(View.GONE);
        setStatus(Area.USB, prefix + " · 正在发送只读识别请求…");
        new Thread(() -> {
            String message;
            boolean offerRetry = false;
            try {
                message = " · 只读通信成功 · " + UsbInquiry.read(usb, device, force);
            } catch (UsbInquiry.InterfaceBusy error) {
                offerRetry = !force && UsbInquiry.supportsRetry(device);
                message = force ? " · 接管失败，手机仍未释放 USB 接口"
                        : " · USB 接口仍被占用。安全弹出 Sony U 盘后，可手动重试。";
            } catch (Exception error) {
                message = " · 无法完成只读通信：" + error.getLocalizedMessage();
            }
            String status = prefix + message;
            boolean canRetry = offerRetry;
            runOnUiThread(() -> {
                checkingUsb = false;
                if (isDestroyed()) return;
                setStatus(Area.USB, status);
                if (canRetry) {
                    retryUsb.setVisibility(View.VISIBLE);
                    retryUsb.setOnClickListener(view -> confirmUsbRetry(device, prefix));
                }
            });
        }, "zve-usb-inquiry").start();
    }

    private void confirmUsbRetry(UsbDevice device, String prefix) {
        new AlertDialog.Builder(this)
                .setTitle("确认已安全弹出 Sony U 盘")
                .setMessage("请先在系统通知中弹出 Sony U 盘，关闭正在使用它的应用，并保持数据线连接。检测会临时接管 USB 接口，只读取设备识别信息。")
                .setNegativeButton("取消", null)
                .setPositiveButton("已弹出，开始检测", (dialog, button) -> {
                    UsbDevice current = usb.getDeviceList().get(device.getDeviceName());
                    if (current == null || !UsbInquiry.supportsRetry(current) || !usb.hasPermission(current)) {
                        setStatus(Area.USB, "USB 设备已变化，请重新检测。");
                        retryUsb.setVisibility(View.GONE);
                        return;
                    }
                    probeUsb(current, prefix, true);
                })
                .show();
    }

    private void prepareAudio() {
        if (checkingUsb || working || audio == null) {
            if (!working && !checkingUsb) setStatus(Area.AUDIO, "请先选择音频。");
            return;
        }
        Uri source = audio;
        int gain = volume.getProgress() + 10;
        audioOutput = null;
        runTask(Area.AUDIO, () -> {
            File file = new File(getCacheDir(), "prepared-shutter.wav");
            double seconds = ShutterAudio.prepare(this, source, gain, file);
            return () -> {
                audioOutput = file;
                setStatus(Area.AUDIO, String.format(Locale.ROOT, "%.3f 秒 · 音量 %d%% · 可以试听或导出", seconds, gain));
            };
        });
    }

    private String lookLabel() {
        return new String[]{"FL2-FL3", "FL2", "FL3"}[looks.getSelectedItemPosition()];
    }

    private void prepareLooks() {
        Uri[] files = originals.clone();
        String selection = lookLabel();
        String[] names = selection.equals("FL2-FL3") ? new String[]{"FL2", "FL3"} : new String[]{selection};
        looksOutput = null;
        runTask(Area.LOOKS, () -> {
            File file = new File(getCacheDir(), "prepared-looks.zip");
            Looks.generate(getContentResolver(), getAssets(), files, names, file);
            return () -> {
                looksOutput = file;
                setStatus(Area.LOOKS, selection + " 已通过校验，可以导出。");
            };
        });
    }

    private void play() {
        try {
            stopPreview();
            player = new MediaPlayer();
            player.setDataSource(audioOutput.getAbsolutePath());
            player.prepare();
            player.start();
        } catch (Exception error) {
            stopPreview();
            setStatus(Area.AUDIO, "试听失败：" + error.getMessage());
        }
    }

    private void stopPreview() {
        if (player != null) {
            player.release();
            player = null;
        }
    }

    private void pick(String type, int request) {
        if (working || checkingUsb) return;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(type);
        startActivityForResult(intent, request);
    }

    private void export(String type, String name, int request) {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType(type).putExtra(Intent.EXTRA_TITLE, name);
        startActivityForResult(intent, request);
    }

    private void chooseCube(int slot) {
        JSONArray catalog;
        try {
            byte[] bytes = MobileSound.asset(this, "builtin-luts/", "catalog.json", 65536);
            catalog = new JSONArray(new String(bytes, StandardCharsets.UTF_8));
        } catch (FileNotFoundException absent) {
            pick("*/*", PICK_CUBE + slot);
            return;
        } catch (Exception invalid) {
            setStatus(Area.LOOKS, "内置 LUT 列表无法读取，已打开手机文件选择。");
            pick("*/*", PICK_CUBE + slot);
            return;
        }
        String[] names = new String[catalog.length() + 1];
        names[0] = "从手机选择 .cube 文件";
        for (int i = 0; i < catalog.length(); i++) names[i + 1] = catalog.optJSONObject(i).optString("name");
        new AlertDialog.Builder(this).setTitle(slot == 0 ? "为 IN 选择 LUT" : "为 SH 选择 LUT")
                .setItems(names, (dialog, index) -> {
                    if (index == 0) {
                        pick("*/*", PICK_CUBE + slot);
                        return;
                    }
                    JSONObject entry = catalog.optJSONObject(index - 1);
                    String file = entry.optString("file");
                    if (file.matches("[0-9]+\\.cube")) loadCube(slot, null, file, names[index]);
                }).setNegativeButton("取消", null).show();
    }

    private void loadCube(int slot, Uri uri, String assetFile, String name) {
        String label = slot == 0 ? "IN" : "SH";
        selectedCubes[slot] = null;
        cubeNames[slot] = null;
        cubeButtons[slot].setText("为 " + label + " 选择 .cube");
        runTask(Area.LOOKS, () -> {
            String filename = name;
            if (uri != null) {
                try (android.database.Cursor cursor = getContentResolver().query(uri,
                        new String[]{android.provider.OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst() && cursor.getString(0) != null)
                        filename = cursor.getString(0);
                }
            }
            MobileCube cube;
            try (InputStream input = uri == null ? getAssets().open("builtin-luts/" + assetFile)
                    : getContentResolver().openInputStream(uri)) {
                if (input == null) throw new IOException("无法打开 LUT 文件");
                cube = MobileCube.read(input);
            }
            String displayName = filename;
            return () -> {
                selectedCubes[slot] = cube;
                cubeNames[slot] = displayName;
                cubeButtons[slot].setText(label + " · " + displayName);
                lutSelector.setSelection(customLutIndex);
                setStatus(Area.LOOKS, label + " 的 LUT 已校验。");
            };
        });
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        if (request == PICK_AUDIO) {
            audio = uri;
            audioOutput = null;
            stopPreview();
            setStatus(Area.AUDIO, "已选择音频，可以生成。");
        } else if (request >= PICK_CUBE && request < PICK_CUBE + selectedCubes.length
                && cubeButtons[request - PICK_CUBE] != null) {
            loadCube(request - PICK_CUBE, uri, null, request == PICK_CUBE ? "IN.cube" : "SH.cube");
        } else if (request >= PICK_BACKUP && request < PICK_BACKUP + originals.length) {
            int index = request - PICK_BACKUP;
            originals[index] = uri;
            backupButtons[index].setText("已选择 · " + Looks.FILES[index]);
            looksOutput = null;
            setStatus(Area.LOOKS, "生成时会核对所选文件。");
        } else if (request == EXPORT_AUDIO || request == EXPORT_LOOKS || request == EXPORT_CAMERA) {
            File file = request == EXPORT_AUDIO ? audioOutput : request == EXPORT_LOOKS ? looksOutput : cameraBackup;
            Area status = request == EXPORT_AUDIO ? Area.AUDIO : request == EXPORT_LOOKS ? Area.LOOKS : Area.SERVICE;
            if (file == null) {
                setStatus(status, "请重新生成后再导出。");
                return;
            }
            runTask(status, () -> {
                try (InputStream input = new FileInputStream(file);
                     OutputStream output = getContentResolver().openOutputStream(uri, "wt")) {
                    if (output == null) throw new IOException("无法打开导出文件");
                    byte[] bytes = new byte[16384];
                    int size;
                    while ((size = input.read(bytes)) != -1) output.write(bytes, 0, size);
                }
                return () -> setStatus(status, "导出完成。");
            });
        }
        refresh();
    }

    private interface Task { Runnable run() throws Exception; }

    private void runTask(Area status, Task task) {
        working = true;
        setStatus(status, "处理中…");
        refresh();
        new Thread(() -> {
            Runnable completion;
            try {
                completion = task.run();
            } catch (Exception error) {
                completion = () -> setStatus(status, "操作失败：" + error.getLocalizedMessage());
            }
            Runnable result = completion;
            runOnUiThread(() -> {
                if (isDestroyed()) return;
                working = false;
                result.run();
                refresh();
            });
        }, "zve-tool-worker").start();
    }

    private void refresh() {
        if (saveLooks == null) return;
        chooseAudio.setEnabled(!working && !checkingUsb);
        volume.setEnabled(!working && !checkingUsb);
        writeCustom.setEnabled(!working && !checkingUsb && audioOutput != null);
        looks.setEnabled(!working);
        if (lutSelector != null) lutSelector.setEnabled(!working && !checkingUsb);
        for (Button button : cubeButtons) if (button != null) button.setEnabled(!working && !checkingUsb);
        for (Button button : backupButtons) button.setEnabled(!working);
        preview.setEnabled(!working && audioOutput != null);
        saveAudio.setEnabled(!working && audioOutput != null);
        saveLooks.setEnabled(!working && looksOutput != null);
        exportBackup.setEnabled(!working && !checkingUsb && cameraBackup != null);
        boolean ready = !working;
        for (Uri file : originals) ready &= file != null;
        generate.setEnabled(ready);
    }

    @Override protected void onDestroy() {
        if (logDialog != null) logDialog.dismiss();
        unregisterReceiver(usbPermission);
        stopPreview();
        super.onDestroy();
    }

    private void setStatus(Area area, String message) {
        String text = area.label + " · " + message;
        liveStatus.setText(text);
        LogEntry previous = statusLog.peekLast();
        if (previous != null && previous.area == area && previous.message.equals(message)) return;
        LogEntry entry = new LogEntry(area, message);
        boolean full = statusLog.size() == 60;
        if (full) statusLog.removeFirst();
        statusLog.addLast(entry);
        if (logRows == null) return;
        int position = logScroll.getScrollY();
        if (full) logRows.removeViewAt(logRows.getChildCount() - 1);
        View row = addLogRow(entry, 0);
        updateLogCount();
        if (position > 0) {
            ScrollView opened = logScroll;
            row.post(() -> {
                if (logScroll == opened) opened.scrollTo(0, position + row.getHeight() + dp(8));
            });
        }
    }

    private void showLog() {
        if (logDialog != null) return;
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(16), dp(16), dp(16), dp(14));
        panel.setBackground(rounded(PAPER, 24));
        label(panel, "操作日志", 22, true);
        logCount = label(panel, "", 13, false);
        updateLogCount();
        logScroll = new ScrollView(this);
        logScroll.setVerticalScrollBarEnabled(true);
        logRows = new LinearLayout(this);
        logRows.setOrientation(LinearLayout.VERTICAL);
        logScroll.addView(logRows);
        int height = Math.min(dp(420), getResources().getDisplayMetrics().heightPixels / 2);
        LinearLayout.LayoutParams listParams = new LinearLayout.LayoutParams(-1, height);
        listParams.topMargin = dp(12);
        panel.addView(logScroll, listParams);

        java.util.Iterator<LogEntry> recent = statusLog.descendingIterator();
        while (recent.hasNext()) addLogRow(recent.next(), logRows.getChildCount());
        LinearLayout controls = actionRow(panel);
        action(controls, "复制日志", false, true, view -> copyLog());
        action(controls, "关闭", true, true, view -> logDialog.dismiss());
        logDialog = new AlertDialog.Builder(this).setView(panel).create();
        logDialog.setOnDismissListener(dialog -> {
            logDialog = null;
            logRows = null;
            logScroll = null;
            logCount = null;
        });
        logDialog.show();
        if (logDialog.getWindow() != null) {
            logDialog.getWindow().setBackgroundDrawableResource(android.R.color.transparent);
            logDialog.getWindow().setLayout(Math.min(dp(480), getResources().getDisplayMetrics().widthPixels - dp(28)), -2);
        }
    }

    private View addLogRow(LogEntry entry, int index) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(dp(12), dp(9), dp(12), dp(10));
        row.setBackground(rounded(Color.WHITE, 14));
        LinearLayout meta = new LinearLayout(this);
        meta.setGravity(android.view.Gravity.CENTER_VERTICAL);
        row.addView(meta);
        TextView badge = label(meta, entry.area.label, 12, true);
        badge.setTextColor(BERRY);
        badge.setPadding(dp(8), dp(3), dp(8), dp(3));
        badge.setBackground(rounded(BLUSH, 8));
        TextView time = label(meta, entry.time, 12, false);
        time.setPadding(dp(9), 0, 0, 0);
        TextView message = label(row, entry.message, 14, false);
        message.setTextColor(INK);
        message.setPadding(0, dp(6), 0, 0);
        message.setTextIsSelectable(true);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(8);
        logRows.addView(row, index, params);
        return row;
    }

    private void updateLogCount() {
        logCount.setText(statusLog.size() + " 条记录  ·  最新在上");
    }

    private void copyLog() {
        StringBuilder text = new StringBuilder();
        java.util.Iterator<LogEntry> recent = statusLog.descendingIterator();
        while (recent.hasNext()) {
            LogEntry entry = recent.next();
            text.append(entry.time).append("  ").append(entry.area.label).append("  ")
                    .append(entry.message).append('\n');
        }
        android.content.ClipboardManager clipboard = getSystemService(android.content.ClipboardManager.class);
        if (clipboard != null) clipboard.setPrimaryClip(android.content.ClipData.newPlainText("相机操作日志", text));
    }

    private void section(LinearLayout page, String title) {
        TextView view = label(page, title, 22, true);
        view.setPadding(0, 0, 0, dp(8));
    }

    private TextView label(LinearLayout page, String text, int size, boolean heading) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setTextColor(heading ? INK : MUTED);
        if (heading) view.setTypeface(null, Typeface.BOLD);
        page.addView(view);
        return view;
    }

    private Button button(LinearLayout page, String text, View.OnClickListener click) {
        return action(page, text, true, false, click);
    }

    private Button action(LinearLayout page, String text, boolean primary, boolean half,
                          View.OnClickListener click) {
        Button button = new Button(this, null, android.R.attr.borderlessButtonStyle);
        button.setText(text);
        button.setAllCaps(false);
        button.setMinWidth(0);
        button.setMinimumHeight(dp(48));
        button.setPadding(dp(12), dp(7), dp(12), dp(7));
        int[][] states = {{-android.R.attr.state_enabled}, {}};
        button.setTextColor(new ColorStateList(states, new int[]{0xff75636b, primary ? Color.WHITE : DARK}));
        android.graphics.drawable.StateListDrawable fill = new android.graphics.drawable.StateListDrawable();
        fill.addState(states[0], rounded(0xffeee5e8, 12));
        fill.addState(states[1], rounded(primary ? BERRY : BLUSH, 12));
        button.setBackground(new android.graphics.drawable.RippleDrawable(
                ColorStateList.valueOf(primary ? 0x40ffffff : 0x229a2146), fill, null));
        button.setOnClickListener(click);
        LinearLayout.LayoutParams params = half
                ? new LinearLayout.LayoutParams(0, -1, 1) : new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = dp(8);
        if (half && page.getChildCount() > 0) params.setMarginStart(dp(8));
        page.addView(button, params);
        return button;
    }

    private LinearLayout actionRow(LinearLayout parent) {
        LinearLayout row = new LinearLayout(this);
        parent.addView(row, new LinearLayout.LayoutParams(-1, -2));
        return row;
    }

    private android.graphics.drawable.GradientDrawable rounded(int color, int radius) {
        android.graphics.drawable.GradientDrawable shape = new android.graphics.drawable.GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radius));
        return shape;
    }

    private LinearLayout screen(FrameLayout parent, int index) {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        screens[index] = scroll;
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(14), 0, dp(14), dp(16));
        scroll.addView(body);
        parent.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
        return body;
    }

    private LinearLayout card(LinearLayout parent) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(16), dp(16), dp(16), dp(16));
        android.graphics.drawable.GradientDrawable surface = rounded(Color.WHITE, 18);
        surface.setStroke(dp(1), 0xffeedce2);
        card.setBackground(surface);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.bottomMargin = dp(10);
        parent.addView(card, params);
        return card;
    }

    private void selectTab(int index) {
        activeTab = index >= 0 && index < tabs.length ? index : 0;
        for (int i = 0; i < tabs.length; i++) {
            boolean selected = i == activeTab;
            tabs[i].setSelected(selected);
            tabs[i].setTextColor(selected ? BERRY : MUTED);
            tabs[i].setTypeface(null, selected ? Typeface.BOLD : Typeface.NORMAL);
            tabs[i].setBackground(new android.graphics.drawable.RippleDrawable(
                    ColorStateList.valueOf(0x229a2146),
                    rounded(selected ? Color.WHITE : Color.TRANSPARENT, 12), rounded(Color.WHITE, 12)));
            screens[i].setVisibility(selected ? View.VISIBLE : View.GONE);
        }
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        state.putInt("activeTab", activeTab);
        super.onSaveInstanceState(state);
    }

    private int dp(int size) {
        return Math.round(getResources().getDisplayMetrics().density * size);
    }
}
