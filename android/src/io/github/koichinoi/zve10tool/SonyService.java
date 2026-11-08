package io.github.koichinoi.zve10tool;

import android.hardware.usb.*;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

final class SonyService implements AutoCloseable {
    private static final int TIMEOUT = 5000;
    private static final int AUTH_SIZE = 516;
    private final UsbDeviceConnection connection;
    private final UsbInterface iface;
    private final UsbEndpoint in, out;
    private final boolean switching;
    private int sequence = 1;
    private boolean usable = true;

    static boolean isService(UsbDevice device) {
        return device.getVendorId() == 0x054c && device.getProductId() == 0x0336;
    }

    SonyService(UsbManager manager, UsbDevice device, boolean switching) throws IOException {
        this.switching = switching;
        if (switching ? !UsbInquiry.supportsRetry(device) : !isService(device)) {
            throw new IOException("USB 设备型号不匹配");
        }
        int type = switching ? UsbConstants.USB_CLASS_MASS_STORAGE : UsbConstants.USB_CLASS_VENDOR_SPEC;
        UsbInterface found = null;
        UsbEndpoint input = null, output = null;
        for (int i = 0; i < device.getInterfaceCount(); i++) {
            UsbInterface candidate = device.getInterface(i);
            if (candidate.getInterfaceClass() != type || candidate.getAlternateSetting() != 0) continue;
            UsbEndpoint firstIn = null, firstOut = null;
            for (int j = 0; j < candidate.getEndpointCount(); j++) {
                UsbEndpoint ep = candidate.getEndpoint(j);
                if (ep.getType() != UsbConstants.USB_ENDPOINT_XFER_BULK) continue;
                if (ep.getDirection() == UsbConstants.USB_DIR_IN && firstIn == null) firstIn = ep;
                if (ep.getDirection() == UsbConstants.USB_DIR_OUT && firstOut == null) firstOut = ep;
            }
            if (firstIn != null && firstOut != null) {
                found = candidate;
                input = firstIn;
                output = firstOut;
                break;
            }
        }
        if (found == null) throw new IOException("找不到相机服务所需的 USB 接口");
        connection = manager.openDevice(device);
        if (connection == null) throw new IOException("安卓未能打开相机 USB 连接");
        iface = found;
        in = input;
        out = output;
        if (!connection.claimInterface(iface, switching)) {
            connection.close();
            throw new IOException("无法接管相机 USB 接口");
        }
    }

    void start() {
        // The desktop reference tolerates a stall on this vendor request.
        control(0x37ff, 0xd7aa);
    }

    void stop() {
        control(0xc800, 0x2855);
    }

    private void control(int value, int index) {
        connection.controlTransfer(0x43, 1, value, index, null, 0, TIMEOUT);
    }

    void authenticate(byte[] keys) throws Exception {
        if (keys.length != 3072) throw new IOException("服务认证资源大小不匹配");
        for (int round = 0; round < 3; round++) {
            ByteBuffer challenge = auth(1, new byte[0]);
            int code = authCode(challenge);
            if (code != 8 && code != 2) throw new IOException("认证挑战返回 " + code);
            byte[] input = new byte[switching ? 4 : 1024];
            challenge.get(input, 0, switching ? 4 : 512);
            if (!switching) System.arraycopy(keys, (round + (code == 8 ? 3 : 0)) * 512, input, 512, 512);
            byte[] digest = code == 8 ? MessageDigest.getInstance("SHA-256").digest(input) : serviceSha1(input);
            byte[] answer = new byte[digest.length + 1];
            answer[0] = 1;
            System.arraycopy(digest, 0, answer, 1, digest.length);
            if (authCode(auth(3, answer)) != 4) throw new IOException("第 " + (round + 1) + " 轮服务认证失败");
        }
        ByteBuffer result = auth(5, new byte[0]);
        if (authCode(result) != 6 || result.get() != 1) throw new IOException("相机拒绝服务认证");
    }

    private ByteBuffer auth(int command, byte[] payload) throws IOException {
        ByteBuffer request = ByteBuffer.allocate(AUTH_SIZE);
        request.putShort((short) ~command).putShort((short) 0).put(payload);
        send(request.array());
        return ByteBuffer.wrap(read(AUTH_SIZE));
    }

    private static int authCode(ByteBuffer packet) {
        return (~packet.getShort() & 0xffff) - (packet.getShort() & 0xffff);
    }

    String readFirmware() throws IOException {
        ByteArrayOutputStream version = new ByteArrayOutputStream();
        readFile("/version.txt", 256, version);
        return new String(version.toByteArray(), StandardCharsets.US_ASCII);
    }

    void readFile(String name, int limit, OutputStream target) throws IOException {
        byte[] path = ("\0/tmp/jiritsu/../.." + name + "\0").getBytes(StandardCharsets.US_ASCII);
        ByteBuffer select = ByteBuffer.allocate(4 + path.length).order(ByteOrder.LITTLE_ENDIAN);
        select.putShort((short) 0x1001).putShort((short) 0x0f).put(path);
        exchange(select.array(), 4, null);
        exchange(new byte[]{1, 16, 17, 0, 0, (byte) 0xff, 0}, limit + 4, target);
    }

    void testTemporaryWrite() throws IOException {
        if (switching) throw new IOException("请先进入服务模式");
        String path = "/tmp/jiritsu/zve-mobile-" + java.util.UUID.randomUUID() + ".bin";
        byte[] probe = new byte[15360];
        new java.security.SecureRandom().nextBytes(probe);
        requireAbsent(path, probe.length);
        selectNativePath(path);
        ByteBuffer write = ByteBuffer.allocate(7 + probe.length);
        write.put(new byte[]{1, 16, 16, 0, 0, (byte) 0xff, 0}).put(probe);
        try {
            exchange(write.array(), 4, null);
            ByteArrayOutputStream readback = new ByteArrayOutputStream();
            readFile(path, probe.length, readback);
            if (!java.util.Arrays.equals(probe, readback.toByteArray())) throw new IOException("临时文件回读不一致");
            selectNativePath(path);
            exchange(new byte[]{1, 16, 18, 0, 0, (byte) 0xff}, 4, null);
            requireAbsent(path, probe.length);
        } catch (IOException error) {
            throw new IOException(error.getMessage() + "。临时路径 " + path + "，请保留此提示", error);
        }
    }

    private void selectNativePath(String path) throws IOException {
        byte[] name = ("\0" + path + "\0").getBytes(StandardCharsets.US_ASCII);
        ByteBuffer select = ByteBuffer.allocate(4 + name.length);
        select.put(new byte[]{1, 16, 15, 0}).put(name);
        exchange(select.array(), 4, null);
    }

    private void requireAbsent(String path, int limit) throws IOException {
        try {
            readFile(path, limit, null);
        } catch (ResultError error) {
            if (error.code == 0x10000006) return;
            throw error;
        }
        throw new IOException("临时文件存在，停止检测");
    }

    byte[] readSmall(String path, int limit, boolean optional) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try {
            readFile(path, limit, bytes);
        } catch (ResultError error) {
            if (optional && error.code == 0x10000006) return null;
            throw error;
        }
        return bytes.toByteArray();
    }

    void putFile(String path, byte[] content, boolean nativePath) throws IOException {
        if (switching || content.length > 65536 || (android.os.Build.VERSION.SDK_INT < 28 && content.length > 16365)) {
            throw new IOException("当前 USB 模式或安卓版本无法发送写入数据");
        }
        selectNativePath(nativePath ? path : "/tmp/jiritsu/../.." + path);
        ByteBuffer request = ByteBuffer.allocate(7 + content.length);
        request.put(new byte[]{1, 16, 16, 0, 0, (byte) 0xff, 0}).put(content);
        exchange(request.array(), 4, null);
    }

    void removeHelper(String path, byte[] expected) throws IOException {
        byte[] actual = readSmall(path, 65536, true);
        if (actual == null) return;
        if (!java.util.Arrays.equals(expected, actual)) throw new IOException("辅助文件内容异常");
        selectNativePath(path);
        exchange(new byte[]{1, 16, 18, 0, 0, (byte) 0xff}, 4, null);
        requireAbsent(path, 65536);
    }

    private static final class ResultError extends IOException {
        final int code;
        ResultError(int code) {
            super("相机返回 0x" + Integer.toHexString(code));
            this.code = code;
        }
    }

    private void exchange(byte[] payload, int limit, OutputStream target) throws IOException {
        exchange(payload, limit, target, true);
    }

    byte[] adjust(byte[] payload, int limit) throws IOException {
        if (switching || payload.length < 4 || payload[0] != 3 || payload[1] != 6)
            throw new IOException("相机设置请求无效");
        ByteArrayOutputStream reply = new ByteArrayOutputStream();
        exchange(payload, limit, reply, false);
        return reply.toByteArray();
    }

    private void exchange(byte[] payload, int limit, OutputStream target, boolean jiritsu) throws IOException {
        if (!usable) throw new IOException("USB 会话中断，未重试");
        usable = false;
        ByteBuffer request = ByteBuffer.allocate(12 + payload.length).order(ByteOrder.LITTLE_ENDIAN);
        request.putInt(payload.length).putShort((short) 0x40).putShort((short) sequence).putInt(0).put(payload);
        send(request.array());
        int chunkSize = android.os.Build.VERSION.SDK_INT >= 28 ? 0x8000 : 0x4000;
        int result = readReply(this::read, sequence, limit, chunkSize, target, jiritsu);
        sequence++;
        usable = true;
        if (result != 0) throw new ResultError(result);
    }

    interface PacketReader {
        byte[] read(int count) throws IOException;
    }

    static int readReply(PacketReader reader, int sequence, int limit, int chunkSize, OutputStream target, boolean jiritsu)
            throws IOException {
        int remaining = -1;
        int result = 0;
        do {
            ByteBuffer header = ByteBuffer.wrap(reader.read(12)).order(ByteOrder.LITTLE_ENDIAN);
            int size = header.getInt();
            if (size < 0 || (jiritsu && size == 0) || size > limit || (remaining >= 0 && size != remaining)
                    || header.getShort() != 0x40 || header.getShort() != sequence
                    || (header.getInt() >>> 24) != 0) throw new IOException("服务回复头无效");
            int segment = Math.min(size, 0x100000);
            for (int offset = 0; offset < segment; offset += chunkSize) {
                byte[] chunk = reader.read(Math.min(chunkSize, segment - offset));
                if (jiritsu && remaining < 0 && offset == 0) {
                    if (chunk.length < 4) throw new IOException("服务回复缺少结果");
                    result = ByteBuffer.wrap(chunk).order(ByteOrder.LITTLE_ENDIAN).getInt();
                    if (result == 0 && target != null) target.write(chunk, 4, chunk.length - 4);
                } else if (result == 0 && target != null) {
                    target.write(chunk);
                }
            }
            remaining = size - segment;
        } while (remaining > 0);
        return result;
    }

    private void send(byte[] data) throws IOException {
        if (connection.bulkTransfer(out, data, data.length, TIMEOUT) != data.length) {
            throw new IOException("发送服务请求失败");
        }
    }

    private byte[] read(int size) throws IOException {
        byte[] bytes = new byte[size];
        int offset = 0;
        int empty = 0;
        while (offset < size) {
            int count = connection.bulkTransfer(in, bytes, offset, size - offset, TIMEOUT);
            if (count < 0 || count > size - offset || (count == 0 && ++empty > 4)) {
                throw new IOException("相机服务回复不完整");
            }
            if (count > 0) empty = 0;
            offset += count;
        }
        return bytes;
    }

    // This protocol uses a SHA-1 padding length of (input.length & 31) * 8.
    static byte[] serviceSha1(byte[] input) {
        int length = ((input.length + 72) / 64) * 64;
        ByteBuffer blocks = ByteBuffer.allocate(length);
        blocks.put(input).put((byte) 0x80).putLong(length - 8, (input.length & 31) * 8L).rewind();
        int[] state = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0};
        int[] words = new int[80];
        while (blocks.hasRemaining()) {
            for (int i = 0; i < 16; i++) words[i] = blocks.getInt();
            for (int i = 16; i < 80; i++) {
                words[i] = Integer.rotateLeft(words[i-3] ^ words[i-8] ^ words[i-14] ^ words[i-16], 1);
            }
            int a = state[0], b = state[1], c = state[2], d = state[3], e = state[4];
            for (int i = 0; i < 80; i++) {
                int f, k;
                if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
                else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
                else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
                else { f = b ^ c ^ d; k = 0xca62c1d6; }
                int next = Integer.rotateLeft(a, 5) + f + e + k + words[i];
                e = d; d = c; c = Integer.rotateLeft(b, 30); b = a; a = next;
            }
            state[0] += a; state[1] += b; state[2] += c; state[3] += d; state[4] += e;
        }
        ByteBuffer digest = ByteBuffer.allocate(20);
        for (int word : state) digest.putInt(word);
        return digest.array();
    }

    @Override public void close() {
        try {
            connection.releaseInterface(iface);
        } finally {
            connection.close();
        }
    }
}
