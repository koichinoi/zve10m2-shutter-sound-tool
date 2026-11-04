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
import java.util.Locale;

public final class MainActivity extends Activity {
    private static final String USB_PERMISSION = "io.github.koichinoi.zve10tool.USB_PERMISSION";
    private static final int PICK_AUDIO = 1, EXPORT_AUDIO = 2, EXPORT_LOOKS = 3, EXPORT_CAMERA = 4, PICK_BACKUP = 10;
    private final Uri[] originals = new Uri[Looks.FILES.length];
    private final Button[] backupButtons = new Button[Looks.FILES.length];
    private TextView audioStatus, looksStatus, usbStatus;
    private Button chooseAudio, preview, saveAudio, generate, saveLooks;
    private SeekBar volume;
    private Spinner looks;
    private Uri audio;
    private File audioOutput, looksOutput;
    private MediaPlayer player;
    private boolean working;
    private boolean checkingUsb;
    private UsbManager usb;
    private Button retryUsb;
    private TextView serviceStatus;
    private Button exportBackup;
    private File cameraBackup;
    private static final String SERVICE_PERMISSION = USB_PERMISSION + ".SERVICE";
    private static final String BACKUP_PERMISSION = USB_PERMISSION + ".BACKUP";
    private static final String WRITE_TEST_PERMISSION = USB_PERMISSION + ".WRITE_TEST";
    private static final String SOUND_PERMISSION = USB_PERMISSION + ".SOUND";
    private enum ServiceAction {
        DETECT("相机服务模式检测", SERVICE_PERMISSION), BACKUP("备份相机文件", BACKUP_PERMISSION),
        WRITE_TEST("测试临时写入", WRITE_TEST_PERMISSION), SOUND("写入预制快门音", SOUND_PERMISSION);
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
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(usbPermission, filter, RECEIVER_NOT_EXPORTED);
        else registerReceiver(usbPermission, filter);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(24), dp(52), dp(24), dp(40));
        page.setBackgroundColor(0xfff4f7fb);
        scroll.addView(page);
        setContentView(scroll);

        label(page, "ZV-E10 II 相机工具", 27, true);
        label(page, "固件 1.02  ·  安卓测试版 0.1.7", 15, false);
        section(page, "自定义快门音");
        label(page, "选取最长 0.620 秒的音频，调整音量、试听并导出 WAV。", 14, false);
        chooseAudio = button(page, "选择音频", view -> pick("audio/*", PICK_AUDIO));
        TextView gain = label(page, "音量 100%", 14, false);
        volume = new SeekBar(this);
        volume.setMax(90);
        volume.setProgress(90);
        volume.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onStartTrackingTouch(SeekBar bar) {}
            public void onStopTrackingTouch(SeekBar bar) {}
            public void onProgressChanged(SeekBar bar, int progress, boolean user) {
                gain.setText("音量 " + (progress + 10) + "%");
                if (user) {
                    audioOutput = null;
                    if (audio != null) audioStatus.setText("音量已调整，请重新生成。");
                    refresh();
                }
            }
        });
        page.addView(volume);
        button(page, "生成快门音", view -> prepareAudio());
        preview = button(page, "试听", view -> play());
        saveAudio = button(page, "导出 WAV", view -> export("audio/wav", "shutter.wav", EXPORT_AUDIO));
        audioStatus = label(page, "请选择音频。", 14, false);

        section(page, "FL2／FL3 创意外观");
        label(page, "选择三份匹配的原始备份，校验后生成外观 ZIP。", 14, false);
        for (int i = 0; i < originals.length; i++) {
            int slot = i;
            backupButtons[i] = button(page, Looks.FILES[i], view -> pick("*/*", PICK_BACKUP + slot));
        }
        looks = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item,
                new String[] {"FL2 + FL3", "FL2", "FL3"});
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        looks.setAdapter(adapter);
        looks.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> parent) {}
            public void onItemSelected(AdapterView<?> parent, View view, int index, long id) {
                if (looksOutput != null) looksStatus.setText("外观选项已调整，请重新生成。");
                looksOutput = null;
                refresh();
            }
        });
        page.addView(looks);
        generate = button(page, "生成外观文件", view -> prepareLooks());
        saveLooks = button(page, "导出外观 ZIP", view ->
                export("application/zip", "ZVE10M2-" + lookLabel() + ".zip", EXPORT_LOOKS));
        looksStatus = label(page, "请选择备份文件。", 14, false);

        section(page, "USB 相机连接");
        label(page, "用支持 OTG 的数据线连接相机，选择 USB 海量存储器。此版本可写入随 APK 准备的快门音。导入外观和原厂恢复请使用电脑版。", 14, false);
        button(page, "检测 USB 相机", view -> checkUsb(true));
        usbStatus = label(page, "等待检测。", 14, false);
        retryUsb = button(page, "弹出后接管检测", null);
        retryUsb.setVisibility(View.GONE);
        button(page, "相机服务模式检测", view -> checkService(true, ServiceAction.DETECT));
        button(page, "备份相机文件", view -> checkService(true, ServiceAction.BACKUP));
        exportBackup = button(page, "导出相机备份 ZIP", view ->
                export("application/zip", "ZVE10M2-camera-backup.zip", EXPORT_CAMERA));
        button(page, "测试临时写入", view -> checkService(true, ServiceAction.WRITE_TEST));
        button(page, "写入预制快门音", view -> {
            if (MobileSound.available(this)) checkService(true, ServiceAction.SOUND);
            else serviceStatus.setText("当前安装包缺少预制快门音。");
        });
        serviceStatus = label(page, "读取相机固件版本，供直连写入前验证。", 14, false);
        refresh();
    }

    private void checkService(boolean ask, ServiceAction action) {
        if (usb == null || checkingUsb || working) return;

        UsbDevice camera = null;
        for (UsbDevice device : usb.getDeviceList().values()) {
            if (!SonyService.isService(device) && !UsbInquiry.supportsRetry(device)) continue;
            if (camera != null) {
                serviceStatus.setText("检测到多个匹配设备，请只连接一台相机。");
                return;
            }
            camera = device;
        }
        if (camera == null) {
            serviceStatus.setText("请连接相机并选择 USB 海量存储器。");
            return;
        }
        if (!usb.hasPermission(camera)) {
            serviceStatus.setText("需要为当前 USB 模式授权。");
            if (ask) {
                Intent result = new Intent(action.permission).setPackage(getPackageName());
                usb.requestPermission(camera, PendingIntent.getBroadcast(this, 0, result, PendingIntent.FLAG_IMMUTABLE));
            }
            return;
        }
        UsbDevice selected = camera;
        if (SonyService.isService(selected)) {
            if (action == ServiceAction.SOUND) {
                if (ask) confirmSound(selected);
                else serviceStatus.setText("已授权。再次点击「写入预制快门音」可查看待写入声音。");
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
                serviceStatus.setText("已授权，再点一次「测试临时写入」并确认。");
            }
        } else if (ask) {
            new AlertDialog.Builder(this)
                    .setTitle("确认已安全弹出 Sony U 盘")
                    .setMessage("请先在系统通知中弹出 Sony U 盘并保持数据线连接。检测将切换 USB 服务模式并读取固件版本。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("已弹出，继续", (dialog, button) -> runService(selected, true, action))
                    .show();
        } else {
            serviceStatus.setText("已授权。弹出 Sony U 盘后再点一次「" + action.label + "」。");
        }
    }

    private void confirmSound(UsbDevice camera) {
        try {
            new AlertDialog.Builder(this)
                    .setTitle("写入 " + MobileSound.name(this))
                    .setMessage("将先备份并核对相机状态。请确认相机电量超过 50%，写入时保持应用在前台，保持数据线连接。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("电量超过 50%，写入", (dialog, button) -> runService(camera, false, ServiceAction.SOUND))
                    .show();
        } catch (Exception error) {
            serviceStatus.setText("无法读取预制快门音：" + error.getLocalizedMessage());
        }
    }

    private void runService(UsbDevice camera, boolean switching, ServiceAction action) {
        boolean backup = action == ServiceAction.BACKUP;
        if (checkingUsb || working) return;
        UsbDevice current = usb.getDeviceList().get(camera.getDeviceName());
        if (current == null || current.getProductId() != camera.getProductId()
                || current.getVendorId() != camera.getVendorId() || !usb.hasPermission(current)) {
            serviceStatus.setText("USB 设备已变化，请重新检测。");
            return;
        }
        checkingUsb = true;
        refresh();
        if ((backup || action == ServiceAction.SOUND) && !switching) {
            getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }
        retryUsb.setVisibility(View.GONE);
        serviceStatus.setText(switching ? "正在请求切换相机服务模式…" : "正在认证并读取固件版本…");
        new Thread(() -> {
            String message;
            File completedBackup = null;
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
                                runOnUiThread(() -> serviceStatus.setText("正在读取并校验 4 个相机文件，约 111 MB，请保持连接…"));
                                File archive = File.createTempFile("zve-camera-", ".zip", getCacheDir());
                                try {
                                    CameraBackup.create(service, archive);
                                    completedBackup = archive;
                                } finally {
                                    if (completedBackup == null) archive.delete();
                                }
                                message = "4 个相机文件已备份并校验，可以导出 ZIP。";
                            } else if (action == ServiceAction.WRITE_TEST) {
                                service.testTemporaryWrite();
                                message = "临时写入、逐字节回读和删除均成功。";
                            } else if (action == ServiceAction.SOUND) {
                                runOnUiThread(() -> serviceStatus.setText("正在备份、写入并回读校验，请保持连接…"));
                                completedBackup = MobileSound.install(this, service);
                                message = "快门音写入和回读通过。拔线，关机等读写灯熄灭，取出电池一分钟，再开机试听。";
                            }
                        }
                    } finally {
                        if (!switched) service.stop();
                    }
                }
            } catch (Exception error) {
                message = action == ServiceAction.SOUND && !switching
                        ? "快门音未确认完成：" + error.getLocalizedMessage() + "。请保留应用数据和提示。"
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
                serviceStatus.setText(status);
                refresh();
            });
        }, "zve-service-check").start();
    }

    private void checkUsb(boolean ask) {
        if (checkingUsb) return;
        retryUsb.setVisibility(View.GONE);
        if (usb == null || !getPackageManager().hasSystemFeature("android.hardware.usb.host")) {
            usbStatus.setText("手机未报告 USB Host 支持。");
            return;
        }
        UsbDevice sony = null;
        for (UsbDevice device : usb.getDeviceList().values()) {
            if (device.getVendorId() != 0x054c) continue;
            for (int i = 0; i < device.getInterfaceCount(); i++) {
                if (device.getInterface(i).getInterfaceClass() != UsbConstants.USB_CLASS_MASS_STORAGE) continue;
                if (sony != null) {
                    usbStatus.setText("检测到多个 Sony 存储接口，请仅连接一台相机。");
                    return;
                }
                sony = device;
                break;
            }
        }
        if (sony == null) {
            usbStatus.setText("未检测到 Sony 海量存储设备。");
            return;
        }
        String name = sony.getProductName();
        if (name == null || name.isEmpty()) name = "Sony USB 设备";
        String id = String.format(Locale.ROOT, " · %04X:%04X", sony.getVendorId(), sony.getProductId());
        boolean granted = usb.hasPermission(sony);
        usbStatus.setText(name + id + (granted ? " · 已取得 USB 权限" : " · 尚未取得 USB 权限"));
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
        usbStatus.setText(prefix + " · 正在发送只读识别请求…");
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
                usbStatus.setText(status);
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
                        usbStatus.setText("USB 设备已变化，请重新检测。");
                        retryUsb.setVisibility(View.GONE);
                        return;
                    }
                    probeUsb(current, prefix, true);
                })
                .show();
    }

    private void prepareAudio() {
        if (working || audio == null) {
            if (!working) audioStatus.setText("请先选择音频。");
            return;
        }
        Uri source = audio;
        int gain = volume.getProgress() + 10;
        audioOutput = null;
        runTask(audioStatus, () -> {
            File file = new File(getCacheDir(), "prepared-shutter.wav");
            double seconds = ShutterAudio.prepare(this, source, gain, file);
            return () -> {
                audioOutput = file;
                audioStatus.setText(String.format(Locale.ROOT, "%.3f 秒 · 音量 %d%% · 可以试听或导出", seconds, gain));
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
        runTask(looksStatus, () -> {
            File file = new File(getCacheDir(), "prepared-looks.zip");
            Looks.generate(getContentResolver(), getAssets(), files, names, file);
            return () -> {
                looksOutput = file;
                looksStatus.setText(selection + " 已通过校验，可以导出。");
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
            audioStatus.setText("试听失败：" + error.getMessage());
        }
    }

    private void stopPreview() {
        if (player != null) {
            player.release();
            player = null;
        }
    }

    private void pick(String type, int request) {
        if (working) return;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(type);
        startActivityForResult(intent, request);
    }

    private void export(String type, String name, int request) {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType(type).putExtra(Intent.EXTRA_TITLE, name);
        startActivityForResult(intent, request);
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        if (request == PICK_AUDIO) {
            audio = uri;
            audioOutput = null;
            stopPreview();
            audioStatus.setText("已选择音频，可以生成。");
        } else if (request >= PICK_BACKUP && request < PICK_BACKUP + originals.length) {
            int index = request - PICK_BACKUP;
            originals[index] = uri;
            backupButtons[index].setText("已选择 · " + Looks.FILES[index]);
            looksOutput = null;
            looksStatus.setText("生成时会核对所选文件。");
        } else if (request == EXPORT_AUDIO || request == EXPORT_LOOKS || request == EXPORT_CAMERA) {
            File file = request == EXPORT_AUDIO ? audioOutput : request == EXPORT_LOOKS ? looksOutput : cameraBackup;
            TextView status = request == EXPORT_AUDIO ? audioStatus : request == EXPORT_LOOKS ? looksStatus : serviceStatus;
            if (file == null) {
                status.setText("请重新生成后再导出。");
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
                return () -> status.setText("导出完成。");
            });
        }
        refresh();
    }

    private interface Task { Runnable run() throws Exception; }

    private void runTask(TextView status, Task task) {
        working = true;
        status.setText("处理中…");
        refresh();
        new Thread(() -> {
            Runnable completion;
            try {
                completion = task.run();
            } catch (Exception error) {
                completion = () -> status.setText("操作失败：" + error.getLocalizedMessage());
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
        chooseAudio.setEnabled(!working);
        volume.setEnabled(!working);
        looks.setEnabled(!working);
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
        unregisterReceiver(usbPermission);
        stopPreview();
        super.onDestroy();
    }

    private void section(LinearLayout page, String title) {
        TextView view = label(page, title, 20, true);
        view.setPadding(0, dp(25), 0, dp(6));
    }

    private TextView label(LinearLayout page, String text, int size, boolean heading) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setTextColor(heading ? 0xff112846 : 0xff304866);
        if (heading) view.setTypeface(null, Typeface.BOLD);
        page.addView(view);
        return view;
    }

    private Button button(LinearLayout page, String text, View.OnClickListener click) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextColor(Color.WHITE);
        button.setBackgroundTintList(new ColorStateList(new int[][]{{-android.R.attr.state_enabled}, {}},
                new int[]{0xff68768a, 0xff1858a0}));
        button.setOnClickListener(click);
        page.addView(button, new LinearLayout.LayoutParams(-1, -2));
        return button;
    }

    private int dp(int size) {
        return Math.round(getResources().getDisplayMetrics().density * size);
    }
}
