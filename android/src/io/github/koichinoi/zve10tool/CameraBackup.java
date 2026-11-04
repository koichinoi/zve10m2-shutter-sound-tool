package io.github.koichinoi.zve10tool;

import java.io.*;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.zip.*;

final class CameraBackup {
    private static final String[] FILES = {"/usr/lib/appFw.so", "/cp/cpapp-b.bin",
            "/cp/SysSound.bin", "/usr/lib/libJiritsu.so"};
    private static final int[] SIZES = {93620512, 17387368, 76992, 237512};

    static void create(SonyService service, File archive) throws Exception {
        byte[][] hashes = new byte[FILES.length][];
        try (ZipOutputStream zip = new ZipOutputStream(new BufferedOutputStream(new FileOutputStream(archive)))) {
            zip.setLevel(1);
            for (int i = 0; i < FILES.length; i++) {
                zip.putNextEntry(new ZipEntry(FILES[i].substring(1)));
                MessageDigest digest = MessageDigest.getInstance("SHA-256");
                service.readFile(FILES[i], SIZES[i], new DigestOutputStream(zip, digest));
                zip.closeEntry();
                hashes[i] = digest.digest();
            }
        }
        try (ZipFile zip = new ZipFile(archive)) {
            if (zip.size() != FILES.length) throw new IOException("备份文件数量不匹配");
            byte[] buffer = new byte[32768];
            for (int i = 0; i < FILES.length; i++) {
                ZipEntry entry = zip.getEntry(FILES[i].substring(1));
                if (entry == null || entry.getSize() != SIZES[i]) throw new IOException(FILES[i] + " 长度不匹配");
                MessageDigest digest = MessageDigest.getInstance("SHA-256");
                try (InputStream input = zip.getInputStream(entry)) {
                    int count;
                    while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
                }
                if (!Arrays.equals(digest.digest(), hashes[i])) throw new IOException(FILES[i] + " 备份校验失败");
            }
        }
    }
}
