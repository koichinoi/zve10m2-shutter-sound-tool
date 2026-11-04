package io.github.koichinoi.zve10tool;

import android.content.ContentResolver;
import android.content.res.AssetManager;
import android.net.Uri;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.security.MessageDigest;
import java.util.BitSet;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

final class Looks {
    static final String[] FILES = {"cpapp-b.bin", "unit-02a40001.bin", "unit-02a4000d.bin"};

    static void generate(ContentResolver resolver, AssetManager assets, Uri[] originals,
                         String[] names, File destination) throws Exception {
        JSONObject bundle;
        try (InputStream input = assets.open("FL2-FL3.json")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) bytes.write(buffer, 0, count);
            bundle = new JSONObject(bytes.toString("UTF-8"));
        }
        try (FileOutputStream output = new FileOutputStream(destination)) {
            generate(bundle, index -> resolver.openInputStream(originals[index]), names, output);
        }
    }

    interface OriginalSource {
        InputStream open(int index) throws IOException;
    }

    static void generate(JSONObject bundle, OriginalSource source, String[] names,
                         OutputStream output) throws Exception {
        try (ZipOutputStream zip = new ZipOutputStream(output)) {
            for (int index = 0; index < FILES.length; index++) {
                JSONObject first = bundle.getJSONObject(names[0]).getJSONArray("components").getJSONObject(index);
                int size = first.getInt("bytes");
                byte[] data = new byte[size];
                try (DataInputStream input = new DataInputStream(source.open(index))) {
                    input.readFully(data);
                    if (input.read() != -1) throw new IOException(FILES[index] + " 大小不匹配");
                }
                String sourceHash = first.getString("source_sha256");
                if (!sourceHash.equals(hash(data))) throw new IOException(FILES[index] + " 原始备份校验失败");
                BitSet occupied = new BitSet(size);
                for (String name : names) {
                    JSONObject component = bundle.getJSONObject(name).getJSONArray("components").getJSONObject(index);
                    if (!FILES[index].equals(component.getString("input_file"))
                            || !sourceHash.equals(component.getString("source_sha256"))) {
                        throw new IOException("外观数据与备份不匹配");
                    }
                    JSONArray edits = component.getJSONArray("edits");
                    for (int i = 0; i < edits.length(); i++) {
                        JSONObject edit = edits.getJSONObject(i);
                        int start = edit.getInt("offset");
                        int length = edit.getInt("length");
                        String hex = edit.getString("after_hex");
                        if (start < 0 || length <= 0 || length > size - start || hex.length() != length * 2) {
                            throw new IOException("外观数据范围无效");
                        }
                        int end = start + length;
                        int next = occupied.nextSetBit(start);
                        if (next >= 0 && next < end) throw new IOException("外观数据范围重叠");
                        for (int j = 0; j < length; j++) {
                            data[start + j] = (byte) Integer.parseInt(hex.substring(j * 2, j * 2 + 2), 16);
                        }
                        occupied.set(start, end);
                    }
                }
                String expected = first.getString(names.length == 2 ? "both_looks_sha256" : "single_look_sha256");
                if (!expected.equals(hash(data))) throw new IOException(FILES[index] + " 输出校验失败");
                zip.putNextEntry(new ZipEntry(FILES[index]));
                zip.write(data);
                zip.closeEntry();
            }
        }
    }

    private static String hash(byte[] data) throws Exception {
        StringBuilder hex = new StringBuilder(64);
        for (byte value : MessageDigest.getInstance("SHA-256").digest(data)) {
            hex.append(Character.forDigit((value >>> 4) & 15, 16));
            hex.append(Character.forDigit(value & 15, 16));
        }
        return hex.toString();
    }
}
