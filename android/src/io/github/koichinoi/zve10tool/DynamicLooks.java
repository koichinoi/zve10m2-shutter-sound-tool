package io.github.koichinoi.zve10tool;

import android.content.Context;
import android.util.AtomicFile;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.json.*;

final class DynamicLooks {
    static final String ROOT = "lut-templates/";
    private static final int[][] CURVE_OFFSETS = {
        {0xc78c90, 0xc78ed4, 0xc79a28}, {0xc79118, 0xc7935c, 0xc79c6c}
    };
    private static final int[] BANK = {23, 25};

    static boolean available(Context context) {
        try (InputStream stream = context.getAssets().open(ROOT + "manifest.json")) {
            return true;
        } catch (IOException unavailable) {
            return false;
        }
    }

    static byte[][] prepare(Context context, JSONObject plan, byte[] cp, byte[][] units,
                            MobileCube[] cubes) throws Exception {
        JSONArray hashes = new JSONArray().put(hash(cp)).put(hash(units[0])).put(hash(units[1]));
        JSONObject primary = MobileLooks.config(context, MobileLooks.LUT_ROOT, 65536);
        if (!matches(hashes, primary.getJSONArray("components"), "source_sha256")
                && !matches(hashes, primary.getJSONArray("components"), "candidate_sha256")
                && !isRecorded(context, hashes))
            throw new IOException("相机外观与本机记录不匹配，无法安全切换");
        JSONObject template = MobileLooks.config(context, ROOT, 65536);
        JSONArray components = plan.getJSONArray("components");
        if (cubes != null) {
            byte[] baseline = MobileSound.asset(context, ROOT, "baseline.bin", 1156);
            MobileSound.checkHash(baseline, template.getString("baseline_hash"), "标准外观数据");
            applyCubes(components, baseline, cubes);
        }
        byte[][] source = {cp, units[0], units[1]};
        for (int i = 0; i < source.length; i++) {
            JSONObject component = components.getJSONObject(i);
            byte[] input = source[i];
            if (input.length != component.getInt("bytes")) throw new IOException("外观数据长度不匹配");
            byte[] target = input.clone();
            JSONArray edits = component.getJSONArray("edits");
            for (int n = 0; n < edits.length(); n++) {
                JSONObject edit = edits.getJSONObject(n);
                int offset = edit.getInt("offset"), length = edit.getInt("length");
                byte[] replacement = MobileLooks.decode(edit.getString("after_hex"));
                if (offset < 0 || length != replacement.length || length > input.length - offset)
                    throw new IOException("LUT 写入范围不匹配");
                edit.put("before_hex", MobileSound.hex(Arrays.copyOfRange(input, offset, offset + length)));
                System.arraycopy(replacement, 0, target, offset, length);
            }
            component.put("source_sha256", hashes.getString(i));
            component.put("candidate_sha256", hash(target));
        }
        JSONArray windows = components.getJSONObject(0).getJSONArray("edits");
        byte[] apply = worker(context, template, "cp", windows);
        byte[] restore = worker(context, template, "restore", windows);
        plan.getJSONObject("workers").getJSONObject("cp").put("sha256", hash(apply));
        plan.put("restore_hash", hash(restore));
        return new byte[][]{apply, restore};
    }

    static void applyCubes(JSONArray components, byte[] baseline, MobileCube[] cubes) throws Exception {
        if (baseline.length != 1156) throw new IOException("标准外观数据长度不匹配");
        int[] reference = new int[129];
        ByteBuffer data = ByteBuffer.wrap(baseline).order(ByteOrder.LITTLE_ENDIAN);
        for (int i = 0; i < reference.length; i++) reference[i] = data.getInt();
        byte[] matrix = new byte[576], chroma = new byte[64];
        data.get(matrix).get(chroma);
        for (int slot = 0; slot < cubes.length; slot++) {
            MobileCube cube = cubes[slot];
            int[] offsets = CURVE_OFFSETS[slot];
            int[] maxima = new int[offsets.length];
            for (int i = 0; i < offsets.length; i++) {
                byte[] raw = MobileLooks.decode(edit(components, 0, offsets[i] + 0x220).getString("after_hex"));
                maxima[i] = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).getInt();
            }
            byte[][] curves = cube.curves(reference, maxima);
            for (int i = 0; i < offsets.length; i++)
                edit(components, 0, offsets[i]).put("after_hex", MobileSound.hex(curves[i]));
            byte[][] colors = cube.color(matrix, chroma);
            edit(components, 1, 0x1250 + BANK[slot] * 64).put("after_hex", MobileSound.hex(colors[0]));
            edit(components, 2, 0x1e0 + BANK[slot] * 768).put("after_hex", MobileSound.hex(colors[1]));
        }
    }

    private static JSONObject edit(JSONArray components, int component, int offset) throws Exception {
        JSONArray edits = components.getJSONObject(component).getJSONArray("edits");
        for (int i = 0; i < edits.length(); i++) {
            JSONObject edit = edits.getJSONObject(i);
            if (edit.getInt("offset") == offset) return edit;
        }
        throw new IOException("缺少已核对的 LUT 数据范围");
    }

    static byte[] fillWorker(byte[] blob, JSONArray rows, JSONArray windows) throws Exception {
        if (rows.length() != 12 || windows.length() != 12) throw new IOException("LUT 模板范围不匹配");
        BitSet occupied = new BitSet(blob.length);
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i), window = windows.getJSONObject(i);
            int length = row.getInt("length");
            if (row.getInt("offset") != window.getInt("offset") || length != window.getInt("length"))
                throw new IOException("LUT 模板位置不匹配");
            JSONArray positions = row.getJSONArray("positions");
            for (int side = 0; side < 2; side++) {
                int pos = positions.getInt(side);
                byte[] bytes = MobileLooks.decode(window.getString(side == 0 ? "before_hex" : "after_hex"));
                int overlap = pos < 0 ? -1 : occupied.nextSetBit(pos);
                if (pos < 0 || length != bytes.length || pos > blob.length - length
                        || (overlap >= 0 && overlap < pos + length))
                    throw new IOException("LUT 模板数据区不匹配");
                occupied.set(pos, pos + length);
                System.arraycopy(bytes, 0, blob, pos, length);
            }
        }
        return blob;
    }

    private static byte[] worker(Context context, JSONObject template, String name, JSONArray windows) throws Exception {
        JSONObject info = template.getJSONObject(name);
        byte[] blob = MobileSound.asset(context, ROOT, name + ".so", 65536);
        MobileSound.checkHash(blob, info.getString("sha256"), "LUT 写入模板");
        return fillWorker(blob, info.getJSONArray("rows"), windows);
    }

    private static AtomicFile state(Context context) {
        return new AtomicFile(new File(context.getFilesDir(), "mobile-lut-state.json"));
    }

    private static boolean isRecorded(Context context, JSONArray hashes) throws Exception {
        try {
            JSONArray saved = new JSONArray(new String(state(context).readFully(), StandardCharsets.UTF_8));
            return saved.toString().equals(hashes.toString());
        } catch (FileNotFoundException missing) {
            return false;
        }
    }

    private static boolean matches(JSONArray hashes, JSONArray parts, String field) throws JSONException {
        for (int i = 0; i < hashes.length(); i++)
            if (!hashes.getString(i).equals(parts.getJSONObject(i).getString(field))) return false;
        return true;
    }

    static void record(Context context, JSONArray parts) throws Exception {
        JSONArray hashes = new JSONArray();
        for (int i = 0; i < parts.length(); i++) hashes.put(parts.getJSONObject(i).getString("candidate_sha256"));
        AtomicFile file = state(context);
        FileOutputStream stream = file.startWrite();
        try {
            stream.write(hashes.toString().getBytes(StandardCharsets.UTF_8));
            file.finishWrite(stream);
        } catch (IOException error) {
            file.failWrite(stream);
            throw error;
        }
    }

    private static String hash(byte[] bytes) throws Exception {
        return MobileSound.hex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
}
