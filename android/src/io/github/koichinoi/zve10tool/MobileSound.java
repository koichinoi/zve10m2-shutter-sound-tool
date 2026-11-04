package io.github.koichinoi.zve10tool;

import android.content.Context;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Iterator;
import java.util.zip.ZipFile;
import org.json.JSONArray;
import org.json.JSONObject;

final class MobileSound {
    private static final String APP = "/usr/lib/appFw.so";
    private static final String HELPER = "/tmp/jiritsu/libJit.so";
    private static final String ASSET = "prepared-sound/";

    static boolean available(Context context) {
        try (InputStream input = context.getAssets().open(ASSET + "manifest.json")) {
            return true;
        } catch (IOException missing) {
            return false;
        }
    }

    static String name(Context context) throws Exception {
        return manifest(context).getString("name");
    }

    static File install(Context context, SonyService service, File customWav,
                        java.util.function.Consumer<String> progress) throws Exception {
        if (android.os.Build.VERSION.SDK_INT < 28) throw new IOException("快门音写入需要 Android 9 或更高版本");
        File pending = new File(context.getFilesDir(), "mobile-sound.pending");
        if (pending.exists()) throw new IOException("有未确认的写入，请保留应用数据");
        File folder = new File(context.getFilesDir(), "sound-" + java.util.UUID.randomUUID());
        if (!folder.mkdir()) throw new IOException("无法创建本地备份目录");
        File backup = new File(folder, "camera-backup.zip");
        CameraBackup.create(service, backup, progress);
        progress.accept("正在核对相机状态并准备写入…");
        JSONObject manifest;
        byte[] audio, worker;
        if (customWav == null) {
            manifest = manifest(context);
            audio = asset(context, ASSET, "audio.bin", 15360);
            worker = asset(context, ASSET, "worker.so", 65536);
        } else {
            try (ZipFile zip = new ZipFile(backup)) {
                CustomSound.Plan plan = CustomSound.prepare(context, zip, customWav);
                manifest = plan.manifest;
                audio = plan.audio;
                worker = plan.worker;
            }
        }

        JSONObject pins = manifest.getJSONObject("pins");
        String targetApp = manifest.getString("target_app");
        String oldAudio = audioPath(manifest.getString("old_audio"));
        String audioPath = audioPath(manifest.getString("audio"));
        String result = manifest.getString("result");
        if (!result.matches("/tmp/jiritsu/zvs_mobile_[0-9a-f]{16}\\.result")) throw new IOException("结果路径无效");
        String stage = result.replace(".result", ".stage.so");


        checkHash(audio, manifest.getString("audio_hash"), "目标音频");
        checkHash(worker, manifest.getString("worker_hash"), "写入程序");
        byte[] old = service.readSmall(oldAudio, 16384, false);
        checkHash(old, manifest.getString("old_audio_hash"), "当前声音");
        byte[] preload = service.readSmall("/etc/ld.so.preload", 4096, true);
        if (preload != null && preload.length != 0) throw new IOException("检测到其他启动修改");
        for (String path : new String[]{HELPER, stage, result}) {
            if (service.readSmall(path, 65536, true) != null) throw new IOException("相机已有辅助文件：" + path);
        }
        byte[] existing = service.readSmall(audioPath, 16384, true);
        if (existing != null && !Arrays.equals(audio, existing)) throw new IOException("目标音频路径已有不同内容");

        try (ZipFile zip = new ZipFile(backup)) {
            for (Iterator<String> it = pins.keys(); it.hasNext();) {
                String path = it.next();
                JSONArray pin = pins.getJSONArray(path);
                try (InputStream input = zip.getInputStream(zip.getEntry(path.substring(1)))) {
                    if (!pin.getString(1).equals(hash(input))) throw new IOException("相机基线不匹配：" + path);
                }
            }
        }
        try (RandomAccessFile file = new RandomAccessFile(backup, "rw")) {
            file.getFD().sync();
        }
        save(new File(folder, "previous-audio.bin"), old);
        save(new File(folder, "manifest.json"), manifest.toString().getBytes(StandardCharsets.UTF_8));
        if (!pending.createNewFile()) throw new IOException("无法锁定写入记录");
        save(pending, folder.getName().getBytes(StandardCharsets.UTF_8));

        progress.accept("正在写入音频并回读…");
        if (existing == null) service.putFile(audioPath, audio, false);
        if (!Arrays.equals(audio, service.readSmall(audioPath, 16384, false))) throw new IOException("音频回读失败");
        service.putFile(stage, worker, true);
        if (!Arrays.equals(worker, service.readSmall(stage, 65536, false))) throw new IOException("辅助文件回读失败");
        progress.accept("正在更新快门加载程序，请保持连接…");
        service.putFile(HELPER, worker, true);
        byte[] report = service.readSmall(result, 136, false);
        save(new File(folder, "camera-result.bin"), report);
        verifyReport(report);
        for (Iterator<String> it = pins.keys(); it.hasNext();) {
            String path = it.next();
            progress.accept("写后回读 · " + new File(path).getName());
            JSONArray pin = pins.getJSONArray(path);
            String expected = APP.equals(path) ? targetApp : pin.getString(1);
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            service.readFile(path, pin.getInt(0), new DigestOutputStream(new OutputStream() {
                @Override public void write(int value) {}
                @Override public void write(byte[] bytes, int offset, int length) {}
            }, digest));
            if (!expected.equals(hex(digest.digest()))) throw new IOException("写后核对失败：" + path);
        }
        if (!Arrays.equals(audio, service.readSmall(audioPath, 16384, false))
                || !Arrays.equals(old, service.readSmall(oldAudio, 16384, false))) throw new IOException("声音文件核对失败");
        progress.accept("回读通过，正在清理辅助文件…");
        service.removeHelper(stage, worker);
        service.removeHelper(HELPER, worker);
        if (customWav != null) CustomSound.recordState(context, manifest);
        if (!pending.delete()) throw new IOException("写入已校验，但未能清除本地记录");
        return backup;
    }

    static void verifyReport(byte[] report) throws IOException {
        if (report.length != 136) throw new IOException("相机结果长度不匹配");
        ByteBuffer data = ByteBuffer.wrap(report).order(ByteOrder.LITTLE_ENDIAN);
        String magic = new String(report, 0, 8, StandardCharsets.US_ASCII);
        String before = mode(report, 104);
        String after = mode(report, 120);
        if (!magic.equals("ZVBINS01") || data.getInt(8) != 1 || data.getInt(12) != 30
                || data.getLong(16) != 0 || data.getLong(24) != 0 || data.getLong(32) != 0
                || data.getLong(40) != 0 || data.getLong(64) != 512 || data.getLong(72) == 0
                || data.getLong(80) == 0 || data.getInt(88) != 3 || data.getInt(92) != 3
                || data.getInt(96) != 0 || data.getInt(100) != 0
                || !(before.equals("0\n") || before.equals("2\n")) || !after.equals("0\n")) {
            throw new IOException("相机未确认写入完成");
        }
    }

    private static String mode(byte[] report, int start) {
        int end = start + 16;
        while (end > start && report[end - 1] == 0) end--;
        return new String(report, start, end - start, StandardCharsets.US_ASCII);
    }

    private static String audioPath(String path) throws IOException {
        if (!path.matches("/cp/(zvs_[0-9a-f]{16}|zve10m2_project11_full)\\.bin")) {
            throw new IOException("音频路径不匹配");
        }
        return path;
    }

    private static JSONObject manifest(Context context) throws Exception {
        return new JSONObject(new String(asset(context, ASSET, "manifest.json", 8192), StandardCharsets.UTF_8));
    }

    static byte[] asset(Context context, String root, String name, int limit) throws IOException {
        try (InputStream input = context.getAssets().open(root + name)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] block = new byte[4096];
            int count;
            while ((count = input.read(block)) != -1) {
                if (bytes.size() + count > limit) throw new IOException("安装数据超限");
                bytes.write(block, 0, count);
            }
            return bytes.toByteArray();
        }
    }

    private static void save(File file, byte[] bytes) throws IOException {
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(bytes);
            output.getFD().sync();
        }
    }

    static void checkHash(byte[] bytes, String expected, String label) throws Exception {
        if (!expected.equals(hex(MessageDigest.getInstance("SHA-256").digest(bytes)))) {
            throw new IOException(label + "校验失败");
        }
    }

    private static String hash(InputStream input) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] bytes = new byte[32768];
        int count;
        while ((count = input.read(bytes)) != -1) digest.update(bytes, 0, count);
        return hex(digest.digest());
    }

    static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte value : bytes) {
            result.append(Character.forDigit((value >>> 4) & 15, 16));
            result.append(Character.forDigit(value & 15, 16));
        }
        return result.toString();
    }
}
