package io.github.koichinoi.zve10tool;

import android.content.Context;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.UUID;
import java.util.zip.CRC32;
import java.util.zip.ZipFile;
import org.json.*;

final class CustomSound {
    static final String ROOT = "custom-sound/";
    private static final String APP = "/usr/lib/appFw.so";
    private static final int[] POSITIONS = {0x4637500, 0x60, 0x2d5039c};
    private static final int[] SIZES = {0xb00, 16, 4};

    static final class Plan {
        final JSONObject manifest;
        final byte[] audio, worker;
        Plan(JSONObject manifest, byte[] audio, byte[] worker) {
            this.manifest = manifest;
            this.audio = audio;
            this.worker = worker;
        }
    }

    static File stateFile(Context context) {
        return new File(context.getFilesDir(), "custom-sound-state.json");
    }

    static Plan prepare(Context context, ZipFile backup, File wav) throws Exception {
        JSONObject template = new JSONObject(new String(
                MobileSound.asset(context, ROOT, "manifest.json", 8192), StandardCharsets.UTF_8));
        byte[] guard = MobileSound.asset(context, ROOT, "guard.bin", SIZES[0]);
        byte[] worker = MobileSound.asset(context, ROOT, "worker.so", 65536);
        MobileSound.checkHash(guard, template.getString("guard_hash"), "加载程序模板");
        MobileSound.checkHash(worker, template.getString("worker_hash"), "写入程序模板");
        if (template.getInt("guard_base") != POSITIONS[0]) throw new IOException("加载程序偏移不匹配");
        byte[] audio = encode(wav);
        String audioHash = sha(audio);
        String audioPath = "/cp/zvs_" + audioHash.substring(0, 16) + ".bin";
        String result = "/tmp/jiritsu/zvs_mobile_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16) + ".result";

        JSONObject guardOffsets = template.getJSONObject("guard_offsets");
        patch(guard, guardOffsets, "mobile_path", cString(audioPath));
        CRC32 crc = new CRC32();
        crc.update(audio);
        patch(guard, guardOffsets, "mobile_crc", ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN)
                .putInt((int) crc.getValue()).array());

        byte[][] old = {new byte[SIZES[0]], new byte[SIZES[1]], new byte[SIZES[2]]};
        long end = POSITIONS[0] + guard.length;
        byte[][] target = {java.util.Arrays.copyOf(guard, SIZES[0]),
                ByteBuffer.allocate(16).order(ByteOrder.LITTLE_ENDIAN).putLong(end).putLong(end).array(), old[2]};
        MessageDigest currentHash = MessageDigest.getInstance("SHA-256");
        MessageDigest targetHash = MessageDigest.getInstance("SHA-256");
        try (DataInputStream input = new DataInputStream(backup.getInputStream(backup.getEntry(APP.substring(1))))) {
            byte[] buffer = new byte[32768];
            int cursor = 0;
            for (int index : new int[]{1, 2, 0}) {
                copyHash(input, buffer, POSITIONS[index] - cursor, currentHash, targetHash);
                input.readFully(old[index]);
                currentHash.update(old[index]);
                targetHash.update(target[index]);
                cursor = POSITIONS[index] + SIZES[index];
            }
            copyHash(input, buffer, 93620512 - cursor, currentHash, targetHash);
            if (input.read() != -1) throw new IOException("相机程序长度不匹配");
        }
        String current = MobileSound.hex(currentHash.digest());
        String after = MobileSound.hex(targetHash.digest());
        JSONObject state = findState(context, template.getJSONArray("known"), current);
        if (after.equals(current) || audioHash.equals(state.getString("hash"))) throw new IOException("相机已使用这段快门音");
        JSONObject pins = template.getJSONObject("pins");
        pins.put(APP, new JSONArray().put(93620512).put(current));
        JSONObject workerOffsets = template.getJSONObject("worker_offsets");
        patch(worker, workerOffsets, "mobile_audio_path", cString(audioPath));
        patch(worker, workerOffsets, "mobile_result", cString(result));
        patch(worker, workerOffsets, "audio_payload", audio);
        for (int i = 0; i < old.length; i++) {
            patch(worker, workerOffsets, "old_" + i, old[i]);
            patch(worker, workerOffsets, "new_" + i, target[i]);
        }
        JSONObject manifest = new JSONObject().put("name", "手机自定义快门音").put("pins", pins)
                .put("target_app", after).put("result", result)
                .put("old_audio", state.getString("audio")).put("old_audio_hash", state.getString("hash"))
                .put("audio", audioPath).put("audio_hash", audioHash).put("worker_hash", sha(worker));
        return new Plan(manifest, audio, worker);
    }

    private static JSONObject findState(Context context, JSONArray known, String app) throws Exception {
        for (int i = 0; i < known.length(); i++) {
            JSONObject entry = known.getJSONObject(i);
            if (app.equals(entry.getString("app"))) return entry;
        }
        android.util.AtomicFile file = new android.util.AtomicFile(stateFile(context));
        try (DataInputStream input = new DataInputStream(file.openRead())) {
            int length = input.readUnsignedShort();
            byte[] bytes = new byte[length];
            input.readFully(bytes);
            JSONObject entry = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
            if (app.equals(entry.getString("app"))) return entry;
        } catch (FileNotFoundException ignored) {}
        throw new IOException("相机快门程序与已知版本不匹配");
    }

    static void recordState(Context context, JSONObject manifest) throws Exception {
        JSONObject state = new JSONObject().put("app", manifest.getString("target_app"))
                .put("audio", manifest.getString("audio")).put("hash", manifest.getString("audio_hash"));
        byte[] bytes = state.toString().getBytes(StandardCharsets.UTF_8);
        File file = stateFile(context);
        android.util.AtomicFile atomic = new android.util.AtomicFile(file);
        FileOutputStream output = atomic.startWrite();
        try {
            DataOutputStream data = new DataOutputStream(output);
            data.writeShort(bytes.length);
            data.write(bytes);
            data.flush();
            atomic.finishWrite(output);
        } catch (IOException error) {
            atomic.failWrite(output);
            throw error;
        }
    }

    private static void copyHash(DataInputStream input, byte[] buffer, int count,
                                 MessageDigest current, MessageDigest target) throws IOException {
        while (count > 0) {
            int length = Math.min(buffer.length, count);
            input.readFully(buffer, 0, length);
            current.update(buffer, 0, length);
            target.update(buffer, 0, length);
            count -= length;
        }
    }

    private static byte[] cString(String value) {
        byte[] bytes = value.getBytes(StandardCharsets.US_ASCII);
        return java.util.Arrays.copyOf(bytes, bytes.length + 1);
    }

    private static void patch(byte[] blob, JSONObject offsets, String field, byte[] value) throws Exception {
        int offset = offsets.getInt(field);
        if (offset < 0 || offset > blob.length - value.length) throw new IOException("模板位置无效");
        System.arraycopy(value, 0, blob, offset, value.length);
    }

    static byte[] encode(File wav) throws IOException {
        if (wav.length() < 46 || wav.length() > 29804) throw new IOException("音频超过已验证的容量");
        byte[] bytes = new byte[(int) wav.length()];
        try (DataInputStream input = new DataInputStream(new FileInputStream(wav))) {
            input.readFully(bytes);
        }
        ByteBuffer pcm = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        int frames = (bytes.length - 44) / 2;
        if ((bytes.length & 1) != 0 || pcm.getInt(0) != 0x46464952 || pcm.getInt(8) != 0x45564157
                || pcm.getInt(12) != 0x20746d66 || pcm.getInt(16) != 16 || pcm.getShort(20) != 1
                || pcm.getShort(22) != 1 || pcm.getInt(24) != 24000 || pcm.getShort(34) != 16
                || pcm.getInt(36) != 0x61746164 || pcm.getInt(40) != frames * 2) {
            throw new IOException("请重新生成手机快门音");
        }
        byte[] output = new byte[15360];
        for (int block = 0; block * 31 < frames; block++) {
            int shift = 0, start = block * 31;
            for (; shift < 8; shift++) {
                boolean fits = true;
                for (int index = start; index < Math.min(start + 31, frames); index++) {
                    double value = Math.rint(pcm.getShort(44 + index * 2) / (double) (1 << shift));
                    if (value < -128 || value > 127) { fits = false; break; }
                }
                if (fits) break;
            }
            output[block * 32] = (byte) shift;
            for (int index = start; index < Math.min(start + 31, frames); index++) {
                int value = (int) Math.rint(pcm.getShort(44 + index * 2) / (double) (1 << shift));
                output[block * 32 + 1 + index - start] = (byte) Math.max(-128, Math.min(127, value));
            }
        }
        return output;
    }

    private static String sha(byte[] bytes) throws Exception {
        return MobileSound.hex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
}
