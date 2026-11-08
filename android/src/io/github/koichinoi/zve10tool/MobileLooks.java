package io.github.koichinoi.zve10tool;

import android.content.Context;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.function.Consumer;
import java.util.zip.ZipFile;
import org.json.*;

final class MobileLooks {
    static final String ROOT = "camera-looks/";
    private static final String APP = "/usr/lib/appFw.so", CP = "/cp/cpapp-b.bin";
    private static final String LOADER = "/tmp/jiritsu/libJit.so";
    static final String PENDING = "mobile-looks.pending";

    static boolean available(Context context) {
        try (InputStream input = context.getAssets().open(ROOT + "manifest.json")) { return true; }
        catch (IOException missing) { return false; }
    }

    static boolean install(Context context, SonyService usb, Consumer<String> progress) throws Exception {
        File pending = new File(context.getFilesDir(), PENDING);
        if (pending.exists() || new File(context.getFilesDir(), "mobile-sound.pending").exists()
                || new File(context.getFilesDir(), MobileIcons.PENDING).exists())
            throw new IOException("有未确认的相机写入，请保留应用数据");
        JSONObject config = config(context, ROOT, 65536);
        JSONArray components = config.getJSONArray("components");
        JSONObject cpPlan = components.getJSONObject(0);
        Observation first = observe(usb, progress);
        String currentCp = hashFile(usb, CP, cpPlan.getInt("bytes"));
        if (currentCp.equals(cpPlan.getString("candidate_sha256")) && first.isTarget(components)) return false;
        if (!currentCp.equals(cpPlan.getString("source_sha256")))
            throw new IOException("相机外观程序不是匹配的原始状态");
        first.ram.verifySaveScope(first.stored);
        List<Fragment> edits = new ArrayList<>();
        byte[][] targets = buildTargets(components, first.units, edits);

        JSONObject sound = config(context, CustomSound.ROOT, 8192);
        File folder = new File(context.getFilesDir(), "looks-" + UUID.randomUUID());
        if (!folder.mkdir()) throw new IOException("无法创建备份目录");
        File backup = new File(folder, "camera-backup.zip");
        CameraBackup.create(usb, backup, progress);
        Map<String, String> protectedHashes = new LinkedHashMap<>();
        Map<String, Integer> protectedSizes = new LinkedHashMap<>();
        JSONObject pins = sound.getJSONObject("pins");
        try (ZipFile zip = new ZipFile(backup)) {
            if (!currentCp.equals(hashEntry(zip, CP))) throw new IOException("相机外观程序发生变化");
            String app = hashEntry(zip, APP);
            JSONObject currentSound = CustomSound.findState(context, sound.getJSONArray("known"), app);
            protectedHashes.put(APP, app);
            protectedSizes.put(APP, 93620512);
            for (Iterator<String> it = pins.keys(); it.hasNext();) {
                String path = it.next();
                if (path.equals(CP)) continue;
                JSONArray pin = pins.getJSONArray(path);
                if (!pin.getString(1).equals(hashEntry(zip, path))) throw new IOException("保护文件不匹配 " + path);
                protectedHashes.put(path, pin.getString(1));
                protectedSizes.put(path, pin.getInt(0));
            }
            String audio = currentSound.getString("audio");
            byte[] oldAudio = usb.readSmall(audio, 16384, false);
            MobileSound.checkHash(oldAudio, currentSound.getString("hash"), "当前快门音");
            protectedHashes.put(audio, currentSound.getString("hash"));
            protectedSizes.put(audio, oldAudio.length);
            persist(new File(folder, "current-audio.bin"), oldAudio);
        }
        JSONArray transport = config.getJSONArray("transport");
        for (int i = 0; i < transport.length(); i++) {
            JSONArray pin = transport.getJSONArray(i);
            String path = pin.getString(0);
            byte[] data = usb.readSmall(path, pin.getInt(1), false);
            MobileSound.checkHash(data, pin.getString(2), path);
            protectedHashes.put(path, pin.getString(2));
            protectedSizes.put(path, pin.getInt(1));
            persist(new File(folder, new File(path).getName()), data);
        }
        JSONObject workers = config.getJSONObject("workers");
        Worker wbi = new Worker(context, workers, "wbi");
        Worker cp = new Worker(context, workers, "cp");
        byte[] inverse = MobileSound.asset(context, ROOT, "restore.so", 65536);
        MobileSound.checkHash(inverse, config.getString("restore_hash"), "外观恢复程序");
        byte[] preload = usb.readSmall("/etc/ld.so.preload", 4096, true);
        if (preload != null && preload.length != 0) throw new IOException("检测到其他启动修改");
        for (String path : new String[]{LOADER, wbi.stage, wbi.result, cp.stage, cp.result}) {
            if (usb.readSmall(path, 65536, true) != null) throw new IOException("已有未清理的相机辅助文件 " + path);
        }
        Observation before = observe(usb, progress);
        first.compare(before, null, false);
        before.ram.verifySaveScope(before.stored);
        persist(new File(folder, "ram.bin"), before.ramBytes);
        persist(new File(folder, "stored.bin"), before.storedBytes);
        persist(new File(folder, "restore.so"), inverse);
        persist(new File(folder, "manifest.json"), config.toString().getBytes(StandardCharsets.UTF_8));
        try (RandomAccessFile file = new RandomAccessFile(backup, "rw")) { file.getFD().sync(); }
        if (!pending.createNewFile()) throw new IOException("无法锁定外观导入记录");
        journal(pending, folder, "准备启动映像");
        progress.accept("正在准备相机启动映像…");
        invoke(usb, wbi, folder);
        before.compare(observe(usb, progress), null, false);
        journal(pending, folder, "写入色彩程序");
        progress.accept("正在导入外观程序…");
        invoke(usb, cp, folder);
        if (!cpPlan.getString("candidate_sha256").equals(hashFile(usb, CP, cpPlan.getInt("bytes"))))
            throw new IOException("外观程序回读不匹配");
        before.compare(observe(usb, progress), null, false);

        for (Fragment edit : edits) {
            byte[] expected = Arrays.copyOfRange(before.units[edit.unit], edit.offset, edit.offset + edit.data.length);
            if (!Arrays.equals(expected, usb.adjust(edit.command(false), edit.data.length)))
                throw new IOException("色彩分段读取不匹配");
        }
        byte[][] current = {before.units[0].clone(), before.units[1].clone()};
        for (int i = 0; i < edits.size(); i++) {
            Fragment edit = edits.get(i);
            if (!Arrays.equals(current[edit.unit], readUnit(usb, edit.unit)))
                throw new IOException("色彩设置在写入前发生变化");
            journal(pending, folder, "写入色彩片段 " + (i + 1));
            progress.accept("导入色彩设置 " + (i + 1) + "/" + edits.size());
            usb.adjust(edit.command(true), 0);
            System.arraycopy(edit.data, 0, current[edit.unit], edit.offset, edit.data.length);
            if (!Arrays.equals(current[edit.unit], readUnit(usb, edit.unit))) throw new IOException("色彩片段回读失败");
        }
        before.compare(observe(usb, progress), targets, false);
        journal(pending, folder, "保存色彩设置");
        progress.accept("保存并核对相机色彩设置…");
        usb.adjust(packet(3, 2).putShort((short) CameraSettings.GROUP).array(), 0);
        before.compare(observe(usb, progress), targets, true);
        if (!cpPlan.getString("candidate_sha256").equals(hashFile(usb, CP, cpPlan.getInt("bytes"))))
            throw new IOException("保存后外观程序回读失败");
        for (Map.Entry<String, String> item : protectedHashes.entrySet()) {
            if (!item.getValue().equals(hashFile(usb, item.getKey(), protectedSizes.get(item.getKey()))))
                throw new IOException("保护文件回读失败 " + item.getKey());
        }
        if (!pending.delete()) throw new IOException("导入已核对，但未能清除本地记录");
        return true;
    }

    private static final class Observation {
        final byte[][] units;
        final byte[] ramBytes, storedBytes;
        final CameraSettings ram, stored;
        Observation(byte[][] units, byte[] ramBytes, byte[] storedBytes) throws IOException {
            this.units = units; this.ramBytes = ramBytes; this.storedBytes = storedBytes;
            ram = CameraSettings.parse(ramBytes);
            stored = CameraSettings.parse(storedBytes);
            if (!ram.properties.keySet().equals(stored.properties.keySet())) throw new IOException("设置清单不一致");
            for (int i = 0; i < units.length; i++) {
                if (!Arrays.equals(units[i], ram.unit(i))) throw new IOException("实时色彩单元回读不一致");
            }
        }
        boolean isTarget(JSONArray components) throws Exception {
            for (int i = 0; i < units.length; i++) {
                if (!digest(units[i]).equals(components.getJSONObject(i + 1).getString("candidate_sha256"))
                        || !Arrays.equals(units[i], stored.unit(i))) return false;
            }
            return true;
        }
        void compare(Observation after, byte[][] target, boolean saved) throws IOException {
            ram.verify(after.ram, target, true);
            stored.verify(after.stored, saved ? target : null, false);
        }
    }

    static void requireInstalled(Context context, SonyService usb, Consumer<String> progress) throws Exception {
        JSONArray components = config(context, ROOT, 65536).getJSONArray("components");
        JSONObject cp = components.getJSONObject(0);
        if (!cp.getString("candidate_sha256").equals(hashFile(usb, CP, cp.getInt("bytes")))
                || !observe(usb, progress).isTarget(components))
            throw new IOException("请先安装 FL2／FL3 成像数据，再更新图标");
    }

    private static Observation observe(SonyService usb, Consumer<String> progress) throws IOException {
        progress.accept("正在核对相机实时与已保存设置…");
        long start = android.os.SystemClock.elapsedRealtime();
        byte[][] units = {readUnit(usb, 0), readUnit(usb, 1)};
        byte[] ram = usb.adjust(packet(5, 1).put((byte) 1).array(), 8 * 1024 * 1024);
        byte[] stored = usb.adjust(packet(5, 1).put((byte) 0).array(), 8 * 1024 * 1024);
        Observation observation = new Observation(units, ram, stored);
        if (android.os.SystemClock.elapsedRealtime() - start > 60000) throw new IOException("设置读取超时");
        return observation;
    }

    private static byte[] readUnit(SonyService usb, int i) throws IOException {
        byte[] unit = usb.adjust(packet(0x40, 8).putInt(CameraSettings.KEYS[i]).putInt(1).array(), CameraSettings.SIZES[i]);
        if (unit.length != CameraSettings.SIZES[i]) throw new IOException("色彩单元长度不匹配");
        return unit;
    }

    private static final class Fragment {
        final int unit, offset;
        final byte[] data;
        Fragment(int unit, int offset, byte[] data) { this.unit = unit; this.offset = offset; this.data = data; }
        byte[] command(boolean write) {
            ByteBuffer buffer = packet(0x42, 20 + (write ? data.length : 0));
            buffer.putInt(write ? 1 : 0).putInt(CameraSettings.KEYS[unit]).putInt(offset).putInt(data.length).putInt(1);
            if (write) buffer.put(data);
            return buffer.array();
        }
    }

    static byte[][] buildTargets(JSONArray components, byte[][] units, List<Fragment> fragments) throws Exception {
        byte[][] targets = new byte[2][];
        for (int i = 0; i < units.length; i++) {
            JSONObject component = components.getJSONObject(i + 1);
            MobileSound.checkHash(units[i], component.getString("source_sha256"), "原始色彩单元");
            byte[] target = units[i].clone();
            JSONArray edits = component.getJSONArray("edits");
            if (edits.length() != 6) throw new IOException("色彩修改清单异常");
            TreeMap<Integer, byte[]> ordered = new TreeMap<>();
            for (int n = 0; n < edits.length(); n++) {
                JSONObject edit = edits.getJSONObject(n);
                int at = edit.getInt("offset"), length = edit.getInt("length");
                byte[] before = decode(edit.getString("before_hex")), after = decode(edit.getString("after_hex"));
                if (!allowed(i, at, length) || before.length != length || after.length != length
                        || !Arrays.equals(before, Arrays.copyOfRange(units[i], at, at + length))
                        || ordered.put(at, after) != null) throw new IOException("色彩修改范围不匹配");
            }
            for (Map.Entry<Integer, byte[]> row : ordered.entrySet()) {
                int at = row.getKey();
                byte[] bytes = row.getValue();
                System.arraycopy(bytes, 0, target, at, bytes.length);
                for (int n = 0; n < bytes.length; n += 128) {
                    fragments.add(new Fragment(i, at + n, Arrays.copyOfRange(bytes, n, Math.min(n + 128, bytes.length))));
                }
            }
            MobileSound.checkHash(target, component.getString("candidate_sha256"), "目标色彩单元");
            targets[i] = target;
        }
        if (fragments.size() != 20) throw new IOException("色彩片段数量不匹配");
        return targets;
    }

    private static boolean allowed(int unit, int offset, int size) {
        int header = unit == 0 ? 0x1200 : 0x196;
        for (int at : new int[]{43, 44, 47, 48}) if (size == 1 && offset == header + at) return true;
        int base = unit == 0 ? 0x1250 : 0x1e0, stride = unit == 0 ? 64 : 768;
        return size == (unit == 0 ? 64 : 576) && (offset == base + 23 * stride || offset == base + 25 * stride);
    }

    private static ByteBuffer packet(int code, int size) {
        return ByteBuffer.allocate(4 + size).order(ByteOrder.LITTLE_ENDIAN).putShort((short) 0x603).putShort((short) code);
    }

    private static final class Worker {
        final String name, stage, result;
        final byte[] data;
        Worker(Context context, JSONObject workers, String name) throws Exception {
            this.name = name;
            JSONObject info = workers.getJSONObject(name);
            stage = info.getString("stage"); result = info.getString("result");
            if (!stage.matches("/tmp/jiritsu/zve10m2\\.[a-z0-9]+\\.(stage|staged)\\.so")
                    || !result.matches("/tmp/jiritsu/zve10m2\\.[a-z0-9]+\\.result"))
                throw new IOException("相机辅助路径不匹配");
            data = MobileSound.asset(context, ROOT, name + ".so", 65536);
            MobileSound.checkHash(data, info.getString("sha256"), "外观辅助程序");
        }
    }

    private static void invoke(SonyService usb, Worker worker, File folder) throws Exception {
        usb.putFile(worker.stage, worker.data, true);
        if (!Arrays.equals(worker.data, usb.readSmall(worker.stage, 65536, false))) throw new IOException("辅助程序回读失败");
        usb.putFile(LOADER, worker.data, true);
        byte[] report = usb.readSmall(worker.result, 65536, false);
        persist(new File(folder, worker.name + "-result.bin"), report);
        verifyWorker(worker.name, report);
        usb.removeHelper(worker.stage, worker.data);
        usb.removeHelper(LOADER, worker.data);
    }

    static void verifyWorker(String name, byte[] report) throws IOException {
        ByteBuffer b = ByteBuffer.wrap(report).order(ByteOrder.LITTLE_ENDIAN);
        boolean ok;
        if (name.equals("wbi")) {
            ok = report.length == 1152 && text(report, 0, 8).equals("ZVIWBI01")
                    && b.getInt(8) == 1 && b.getInt(12) == 30 && b.getInt(20) == 0;
            if (ok) {
                int needed = b.getInt(16);
                String mode = text(report, 96, 8);
                ok = (needed == 0 || needed == 1) && zeroLongs(b, 24, 32, 48, 64, 88)
                        && b.getLong(40) == needed && b.getLong(56) == (mode.equals("2\n") ? 1 : 0)
                        && b.getLong(72) == 512 && b.getLong(80) == 512
                        && (mode.equals("0\n") || mode.equals("2\n")) && text(report, 104, 8).equals("0\n")
                        && text(report, 112, 8).equals("*wbi4\n") && text(report, 120, 8).equals("*wbi4\n")
                        && (needed == 0 ? allZero(report, 128, 512) : text(report, 128, 4).equals("WBI2"))
                        && allZero(report, 640, 512);
            }
        } else {
            ok = report.length == 136 && text(report, 0, 8).equals("ZVINSH01")
                    && b.getInt(8) == 1 && b.getInt(12) == 0 && b.getInt(16) == 40 && b.getInt(20) == 0
                    && zeroLongs(b, 24, 32, 48, 64, 72, 80) && b.getLong(56) == 512
                    && b.getLong(88) != 0 && b.getLong(96) != 0
                    && b.getInt(104) == 12 && b.getInt(108) == 12 && b.getInt(112) == 0 && b.getInt(116) == 0
                    && (text(report, 120, 8).equals("0\n") || text(report, 120, 8).equals("2\n"))
                    && text(report, 128, 8).equals("0\n");
        }
        if (!ok) throw new IOException("相机未确认外观写入完成 " + name);
    }

    private static String text(byte[] bytes, int start, int length) {
        while (length > 0 && bytes[start + length - 1] == 0) length--;
        return new String(bytes, start, length, StandardCharsets.US_ASCII);
    }

    private static boolean zeroLongs(ByteBuffer buffer, int... positions) {
        for (int at : positions) if (buffer.getLong(at) != 0) return false;
        return true;
    }

    private static boolean allZero(byte[] data, int at, int length) {
        for (int i = at; i < at + length; i++) if (data[i] != 0) return false;
        return true;
    }

    private static byte[] decode(String hex) throws IOException {
        if ((hex.length() & 1) != 0) throw new IOException("外观数据编码无效");
        byte[] data = new byte[hex.length() / 2];
        for (int i = 0; i < data.length; i++) data[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        return data;
    }

    private static String digest(byte[] bytes) throws Exception {
        return MobileSound.hex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }

    private static String hashEntry(ZipFile zip, String path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = zip.getInputStream(zip.getEntry(path.substring(1)))) {
            byte[] buffer = new byte[32768];
            int n;
            while ((n = input.read(buffer)) != -1) digest.update(buffer, 0, n);
        }
        return MobileSound.hex(digest.digest());
    }

    static String hashFile(SonyService usb, String path, int size) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        usb.readFile(path, size, new DigestOutputStream(new OutputStream() {
            @Override public void write(int value) {}
            @Override public void write(byte[] bytes, int offset, int length) {}
        }, digest));
        return MobileSound.hex(digest.digest());
    }

    static JSONObject config(Context context, String root, int limit) throws Exception {
        return new JSONObject(new String(MobileSound.asset(context, root, "manifest.json", limit), StandardCharsets.UTF_8));
    }

    private static void journal(File pending, File folder, String phase) throws IOException {
        persist(pending, (folder.getName() + "\n" + phase).getBytes(StandardCharsets.UTF_8));
    }

    static void persist(File file, byte[] bytes) throws IOException {
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(bytes);
            output.getFD().sync();
        }
        try (DataInputStream input = new DataInputStream(new FileInputStream(file))) {
            byte[] check = new byte[bytes.length];
            input.readFully(check);
            if (!Arrays.equals(bytes, check) || input.read() != -1) throw new IOException("本地备份回读失败");
        }
    }
}
