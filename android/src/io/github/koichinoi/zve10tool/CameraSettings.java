package io.github.koichinoi.zve10tool;

import java.io.IOException;
import java.nio.*;
import java.util.*;

final class CameraSettings {
    static final int[] KEYS = {0x02a40001, 0x02a4000d};
    static final int[] SIZES = {8192, 28672};
    static final int GROUP = 0x02a4;
    final Map<Long, Property> properties = new HashMap<>();

    static final class Property {
        final int attr;
        final byte[] data, reset;
        Property(int attr, byte[] data, byte[] reset) {
            this.attr = attr;
            this.data = data;
            this.reset = reset;
        }
        boolean same(Property other, byte[] expected, boolean telemetry, long key) {
            if (other == null || attr != other.attr || !Arrays.equals(reset, other.reset)) return false;
            if (Arrays.equals(expected, other.data)) return true;
            if (!telemetry || expected.length != other.data.length) return false;
            int at, length;
            if (key == 0x01070000 && expected.length == 8) { at = 0; length = 8; }
            else if (key == 0x02770015 && expected.length == 4) { at = 0; length = 4; }
            else if (key == 0x02780000 && expected.length == 256) { at = 24; length = 4; }
            else return false;
            for (int i = 0; i < expected.length; i++) {
                if ((i < at || i >= at + length) && expected[i] != other.data[i]) return false;
            }
            ByteBuffer left = ByteBuffer.wrap(expected).order(ByteOrder.LITTLE_ENDIAN);
            ByteBuffer right = ByteBuffer.wrap(other.data).order(ByteOrder.LITTLE_ENDIAN);
            long a = length == 8 ? left.getLong(at) : Integer.toUnsignedLong(left.getInt(at));
            long b = length == 8 ? right.getLong(at) : Integer.toUnsignedLong(right.getInt(at));
            long delta = b - a;
            return Long.compareUnsigned(b, a) >= 0 && delta >= 0 && delta <= 1000000;
        }
    }

    private static final class Record {
        final int end;
        final Map<Integer, Property> values;
        Record(int end, Map<Integer, Property> values) { this.end = end; this.values = values; }
        boolean isCp() {
            for (int i = 0; i < KEYS.length; i++) {
                Property p = values.get(KEYS[i]);
                if (p == null || p.data.length != SIZES[i]) return false;
            }
            return true;
        }
    }

    static CameraSettings parse(byte[] bytes) throws IOException {
        if (bytes.length < 512 || bytes.length > 8 * 1024 * 1024) throw new IOException("设置备份长度异常");
        List<Record> records = new ArrayList<>();
        int previousEnd = 0;
        for (int i = 12; i + 4 <= bytes.length; i++) {
            if (bytes[i] != 'B' || bytes[i + 1] != 'K' || bytes[i + 2] != '4' || bytes[i + 3] != 0) continue;
            int start = i - 12;
            Record record;
            try { record = readRecord(bytes, start); }
            catch (IllegalArgumentException ignored) { continue; }
            if (start < previousEnd) throw new IOException("设置记录重叠");
            records.add(record);
            previousEnd = record.end;
            if (records.size() > 2) throw new IOException("设置记录数量异常");
        }
        if (records.size() != 2 || records.get(0).isCp() == records.get(1).isCp()) {
            throw new IOException("未找到匹配的 AP／CP 设置记录");
        }
        CameraSettings snapshot = new CameraSettings();
        for (Record record : records) {
            long chip = record.isCp() ? (1L << 32) : 0;
            record.values.forEach((key, property) -> snapshot.properties.put(chip | Integer.toUnsignedLong(key), property));
        }
        return snapshot;
    }

    private static Record readRecord(byte[] bytes, int start) {
        if (start > bytes.length - 256) throw new IllegalArgumentException();
        ByteBuffer data = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        int subs = data.getInt(start + 16), props = data.getInt(start + 20);
        int offset = data.getInt(start + 24), length = data.getInt(start + 28);
        long table = 256L + 6L * subs;
        long size = (long) offset + length;
        if (subs < 0 || subs > 65536 || props < 0 || props > 200000 || length < 0
                || offset < table + 6L * props || size > bytes.length - start || size > 8 * 1024 * 1024)
            throw new IllegalArgumentException();
        int checksum = 0;
        for (int i = 0; i < size; i++) if (i < 32 || i >= 36) checksum += bytes[start + i] & 255;
        if (checksum != data.getInt(start + 32)) throw new IllegalArgumentException();
        Map<Integer, Property> values = new HashMap<>();
        for (int s = 0; s < subs; s++) {
            int sub = start + 256 + 6 * s;
            int count = Short.toUnsignedInt(data.getShort(sub)), index = data.getInt(sub + 2);
            if (index < 0 || index > props - count) throw new IllegalArgumentException();
            for (int p = 0; p < count; p++) {
                int entry = start + (int) table + 6 * (index + p);
                int attr = Short.toUnsignedInt(data.getShort(entry)), ptr = data.getInt(entry + 2);
                if (ptr == -1) continue;
                int position = ptr & 0xffffff, n = ptr >>> 24, max = n;
                if (position < offset || position > size) throw new IllegalArgumentException();
                if (n == 0 || n == 255) {
                    int head = n == 0 ? 4 : 2;
                    if (position > size - head) throw new IllegalArgumentException();
                    max = Short.toUnsignedInt(data.getShort(start + position + head - 2));
                    n = Short.toUnsignedInt(data.getShort(start + position));
                    position += head;
                }
                boolean reset = (attr & 0x74) != 0;
                if (n > max || position + max + (reset ? n : 0) > size) throw new IllegalArgumentException();
                int address = start + position;
                values.put(s << 16 | p, new Property(attr, Arrays.copyOfRange(bytes, address, address + n),
                        reset ? Arrays.copyOfRange(bytes, address + max, address + max + n) : new byte[0]));
            }
        }
        return new Record(start + (int) size, values);
    }

    byte[] unit(int index) throws IOException {
        Property property = properties.get((1L << 32) | KEYS[index]);
        if (property == null || property.data.length != SIZES[index]) throw new IOException("色彩设置单元缺失");
        return property.data;
    }

    void verify(CameraSettings after, byte[][] replacements, boolean telemetry) throws IOException {
        if (!properties.keySet().equals(after.properties.keySet())) throw new IOException("相机设置清单发生变化");
        for (Map.Entry<Long, Property> entry : properties.entrySet()) {
            long key = entry.getKey();
            Property before = entry.getValue();
            byte[] expected = before.data;
            if (replacements != null) {
                for (int i = 0; i < KEYS.length; i++) if (key == ((1L << 32) | KEYS[i])) expected = replacements[i];
            }
            if (!before.same(after.properties.get(key), expected, telemetry, key)) {
                throw new IOException("设置回读不匹配 " + Long.toHexString(key));
            }
        }
    }

    void verifySaveScope(CameraSettings stored) throws IOException {
        if (!properties.keySet().equals(stored.properties.keySet())) throw new IOException("实时和已保存设置清单不一致");
        for (Map.Entry<Long, Property> entry : properties.entrySet()) {
            long key = entry.getKey();
            if (((key >>> 16) & 0xffff) != GROUP) continue;
            Property before = entry.getValue();
            if ((key >>> 32) == 0 || !before.same(stored.properties.get(key), before.data, false, key)) {
                throw new IOException("存在其他未保存的色彩设置");
            }
        }
    }
}
