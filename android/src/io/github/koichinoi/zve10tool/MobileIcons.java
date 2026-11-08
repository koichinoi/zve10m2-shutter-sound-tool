package io.github.koichinoi.zve10tool;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.function.Consumer;
import org.json.*;

final class MobileIcons {
    static final String ROOT = "camera-icons/";
    static final String PENDING = "mobile-icons.pending";
    private static final String BANK_1 = "/usr/share/app/image_01_23_IPSX.uxc";
    private static final String BANK_2 = "/usr/share/app/image_02_23_IPSX.uxc";
    private static final String BANK_1_32 = "/usr/share/app/image_01_32_IPSX.uxc";
    private static final String BANK_2_32 = "/usr/share/app/image_02_32_IPSX.uxc";
    private static final String LOADER = "/tmp/jiritsu/libJit.so";
    private static final String APP = "/usr/lib/appFw.so";

    static boolean available(Context context) {
        try (InputStream input = context.getAssets().open(ROOT + "display32b2/manifest.json")) { return true; }
        catch (IOException missing) { return false; }
    }

    static boolean install(Context context, SonyService usb, Consumer<String> progress) throws Exception {
        if (android.os.Build.VERSION.SDK_INT < 28) throw new IOException("图标写入需要 Android 9 或以上");
        File root = context.getFilesDir();
        File pending = new File(root, PENDING);
        if (pending.exists() || new File(root, MobileLooks.PENDING).exists()
                || new File(root, "mobile-sound.pending").exists())
            throw new IOException("有未确认的相机写入，请保留应用数据");
        Plan initial = new Plan(context, ROOT, BANK_1, 9675260, "zvicon_", 18, 18, 18, 2);
        Plan extra1 = new Plan(context, ROOT + "extra1/", BANK_1, 9675260, "zviconx1_", 2);
        Plan extra2 = new Plan(context, ROOT + "extra2/", BANK_2, 6838252, "zviconx2_", 6);
        Plan display1 = new Plan(context, ROOT + "display32b1/", BANK_1_32, 9685748, "zvicon32b1_", 18, 18, 18, 4);
        Plan display2 = new Plan(context, ROOT + "display32b2/", BANK_2_32, 6929728, "zvicon32b2_", 6);
        List<Plan> finalPlans = Arrays.asList(extra1, extra2, display1, display2);
        progress.accept("正在核对 23_IPSX 和 32_IPSX 图标资源…");
        Map<String, String> beforeBanks = new LinkedHashMap<>();
        for (Plan plan : finalPlans) {
            beforeBanks.put(plan.path, MobileLooks.hashFile(usb, plan.path, plan.size));
        }
        List<Plan> plans = selectPlans(initial, finalPlans, beforeBanks);
        if (plans.isEmpty()) return false;
        MobileLooks.requireInstalled(context, usb, progress);

        JSONObject sound = MobileLooks.config(context, CustomSound.ROOT, 8192);
        Map<String, Integer> sizes = new LinkedHashMap<>();
        Map<String, String> hashes = new LinkedHashMap<>();
        progress.accept("正在核对快门音与成像文件…");
        String appHash = MobileLooks.hashFile(usb, APP, 93620512);
        JSONObject currentSound = CustomSound.findState(context, sound.getJSONArray("known"), appHash);
        sizes.put(APP, 93620512);
        hashes.put(APP, appHash);
        JSONObject pins = sound.getJSONObject("pins");
        for (Iterator<String> it = pins.keys(); it.hasNext();) {
            String path = it.next();
            JSONArray pin = pins.getJSONArray(path);
            sizes.put(path, pin.getInt(0));
            hashes.put(path, pin.getString(1));
            if (!pin.getString(1).equals(MobileLooks.hashFile(usb, path, pin.getInt(0))))
                throw new IOException("保护文件不匹配 " + path);
        }
        String audio = currentSound.getString("audio");
        byte[] oldAudio = usb.readSmall(audio, 16384, false);
        MobileSound.checkHash(oldAudio, currentSound.getString("hash"), "当前快门音");
        sizes.put(audio, oldAudio.length);
        hashes.put(audio, currentSound.getString("hash"));
        byte[] preload = usb.readSmall("/etc/ld.so.preload", 4096, true);
        if (preload != null && preload.length != 0) throw new IOException("检测到其他启动修改");
        requireAbsent(usb, LOADER);

        File folder = new File(root, "icons-" + UUID.randomUUID());
        if (!folder.mkdir()) throw new IOException("无法创建图标备份目录");
        List<Step> workers = new ArrayList<>();
        for (Plan plan : plans) {
            workers.addAll(plan.workers);
            MobileLooks.persist(new File(folder, plan.prefix + "manifest.json"),
                    plan.manifest.toString().getBytes(StandardCharsets.UTF_8));
            for (Step step : plan.workers) {
                requireAbsent(usb, step.stage);
                requireAbsent(usb, step.result);
                MobileLooks.persist(new File(folder, step.restoreName), step.restore);
            }
        }
        progress.accept("正在备份四组图标资源…");
        for (Plan plan : finalPlans) backup(usb, folder, plan.path, plan.size, beforeBanks.get(plan.path));
        if (!pending.createNewFile()) throw new IOException("无法锁定图标写入记录");

        for (int i = 0; i < workers.size(); i++) {
            Step step = workers.get(i);
            if (!step.before.equals(MobileLooks.hashFile(usb, step.path, step.size))) throw new IOException("图标资源在写入前发生变化");
            progress.accept("写入并回读图标 " + (i + 1) + "/" + workers.size());
            MobileLooks.persist(pending, (folder.getName() + "\n" + (i + 1)).getBytes(StandardCharsets.UTF_8));
            usb.putFile(step.stage, step.data, true);
            if (!Arrays.equals(step.data, usb.readSmall(step.stage, 65536, false))) throw new IOException("图标辅助程序回读失败");
            usb.putFile(LOADER, step.data, true);
            byte[] result = usb.readSmall(step.result, 136, false);
            MobileLooks.persist(new File(folder, "result-" + (i + 1) + ".bin"), result);
            MobileSound.verifyReport(result, step.windows);
            if (!step.after.equals(MobileLooks.hashFile(usb, step.path, step.size))) throw new IOException("图标资源回读失败");
            usb.removeHelper(step.stage, step.data);
            usb.removeHelper(LOADER, step.data);
        }
        progress.accept("正在核对图标、快门音与成像文件…");
        for (Plan plan : finalPlans) {
            sizes.put(plan.path, plan.size);
            hashes.put(plan.path, plan.after);
        }
        for (Map.Entry<String, Integer> pin : sizes.entrySet()) {
            String path = pin.getKey();
            if (!hashes.get(path).equals(MobileLooks.hashFile(usb, path, pin.getValue())))
                throw new IOException("保护文件回读不匹配 " + path);
        }
        if (!pending.delete()) throw new IOException("图标已核对，但未能清除本地记录");
        return true;
    }

    private static void requireAbsent(SonyService usb, String path) throws IOException {
        if (usb.readSmall(path, 65536, true) != null) throw new IOException("已有未清理的相机辅助文件 " + path);
    }

    static List<Plan> selectPlans(Plan initial, List<Plan> finalPlans, Map<String, String> beforeBanks)
            throws IOException {
        Plan extra1 = finalPlans.get(0);
        if (!initial.path.equals(extra1.path) || !initial.after.equals(extra1.before))
            throw new IOException("图标更新顺序不匹配");
        List<Plan> plans = new ArrayList<>();
        boolean stock = initial.before.equals(beforeBanks.get(initial.path));
        if (stock) plans.add(initial);
        for (Plan plan : finalPlans) {
            String hash = plan == extra1 && stock ? initial.after : beforeBanks.get(plan.path);
            if (plan.before.equals(hash)) plans.add(plan);
            else if (!plan.after.equals(hash))
                throw new IOException("图标资源不匹配：" + new File(plan.path).getName());
        }
        return plans;
    }

    private static void backup(SonyService usb, File folder, String path, int size, String hash) throws Exception {
        byte[] before = usb.readSmall(path, size, false);
        MobileSound.checkHash(before, hash, "原始图标资源");
        MobileLooks.persist(new File(folder, new File(path).getName()), before);
    }

    static final class Plan {
        final String before, after, prefix, path;
        final int size;
        final JSONObject manifest;
        final List<Step> workers = new ArrayList<>();

        Plan(Context context, String assets, String path, int size, String prefix, int... counts) throws Exception {
            this(MobileLooks.config(context, assets, 8192), size, prefix);
            if (!path.equals(manifest.getString("path")) || manifest.getInt("size") != size)
                throw new IOException("图标资源清单不匹配");
            JSONArray rows = manifest.getJSONArray("steps");
            if (rows.length() != counts.length || manifest.getInt("simulated_cases") != counts.length * 30)
                throw new IOException("图标写入批次未通过离线验证");
            String current = before;
            for (int i = 0; i < counts.length; i++) {
                Step step = new Step(context, rows.getJSONObject(i), assets, path, size, prefix, i + 1, counts[i]);
                if (!current.equals(step.before)) throw new IOException("图标写入批次顺序异常");
                current = step.after;
                workers.add(step);
            }
            if (!current.equals(after)) throw new IOException("图标目标校验不匹配");
        }

        Plan(JSONObject manifest, int size, String prefix) throws JSONException {
            this.manifest = manifest;
            this.size = size;
            this.prefix = prefix;
            path = manifest.getString("path");
            before = manifest.getString("before");
            after = manifest.getString("after");
        }
    }

    private static final class Step {
        final String before, after, stage, result, path, restoreName;
        final byte[] data, restore;
        final int windows, size;

        Step(Context context, JSONObject row, String assets, String path, int size, String prefix, int number,
             int count) throws Exception {
            this.path = path;
            this.size = size;
            before = row.getString("before");
            after = row.getString("after");
            windows = row.getInt("windows");
            JSONObject install = row.getJSONObject("install");
            result = "/tmp/jiritsu/" + prefix + number + "_install.result";
            stage = result.replace(".result", ".stage.so");
            String name = "install" + number + ".so";
            if (!result.equals(install.getString("result")) || !name.equals(install.getString("file"))
                    || windows != count) throw new IOException("图标写入配置不匹配");
            data = MobileSound.asset(context, assets, name, 65536);
            MobileSound.checkHash(data, install.getString("sha256"), "图标写入程序");
            JSONObject undo = row.getJSONObject("restore");
            String file = "restore" + number + ".so";
            if (!file.equals(undo.getString("file"))) throw new IOException("图标恢复文件名异常");
            restore = MobileSound.asset(context, assets, file, 65536);
            MobileSound.checkHash(restore, undo.getString("sha256"), "图标恢复程序");
            restoreName = prefix + file;
        }
    }
}
