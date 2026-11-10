package io.github.koichinoi.zve10tool;

import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Converts a 3D .cube to the tone and chroma data used by the desktop installer. */
final class MobileCube {
    static final int MAX_BYTES = 24 * 1024 * 1024;
    private final int size;
    private final double[] table, min, max;

    private MobileCube(int size, double[] table, double[] min, double[] max) {
        this.size = size;
        this.table = table;
        this.min = min;
        this.max = max;
    }

    static MobileCube read(InputStream source) throws IOException {
        ByteArrayOutputStream content = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = source.read(buffer)) != -1) {
            if (content.size() + count > MAX_BYTES) throw new IOException("LUT 文件超过 24 MB");
            content.write(buffer, 0, count);
        }
        int size = 0, written = 0;
        double[] table = null, min = {0, 0, 0}, max = {1, 1, 1};
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                new ByteArrayInputStream(content.toByteArray()), StandardCharsets.UTF_8))) {
            String line;
            boolean first = true;
            while ((line = reader.readLine()) != null) {
                if (first && line.startsWith("\ufeff")) line = line.substring(1);
                first = false;
                int comment = line.indexOf('#');
                line = (comment < 0 ? line : line.substring(0, comment)).trim();
                if (line.isEmpty()) continue;
                String[] fields = line.split("\\s+");
                switch (fields[0].toUpperCase(Locale.ROOT)) {
                    case "TITLE":
                        continue;
                    case "LUT_3D_SIZE":
                        if (table != null || fields.length != 2) throw new IOException("LUT_3D_SIZE 无效");
                        size = Integer.parseInt(fields[1]);
                        if (size < 2 || size > 65) throw new IOException("支持每轴 2–65 点的 3D LUT");
                        table = new double[3 * size * size * size];
                        break;
                    case "LUT_1D_SIZE":
                        throw new IOException("此版本支持纯 3D .cube，暂不支持 1D 曲线");
                    case "DOMAIN_MIN":
                        min = domain(fields);
                        break;
                    case "DOMAIN_MAX":
                        max = domain(fields);
                        break;
                    default:
                        if (fields.length != 3 || table == null || written >= table.length)
                            throw new IOException("LUT 数据格式或采样点数量不匹配");
                        for (String field : fields) table[written++] = number(field);
                }
            }
        } catch (NumberFormatException error) {
            throw new IOException("LUT 包含无效数值", error);
        }
        if (table == null || written != table.length) throw new IOException("LUT 数据点数量不匹配");
        for (int i = 0; i < 3; i++)
            if (max[i] <= min[i]) throw new IOException("LUT 输入范围无效");
        return new MobileCube(size, table, min, max);
    }

    private static double[] domain(String[] fields) throws IOException {
        if (fields.length != 4) throw new IOException("LUT 输入范围无效");
        return new double[]{number(fields[1]), number(fields[2]), number(fields[3])};
    }

    private static double number(String text) throws IOException {
        double value = Double.parseDouble(text);
        if (!Double.isFinite(value) || Math.abs(value) > 1e6) throw new IOException("LUT 数值超出支持范围");
        return value;
    }

    private double[] sample(double red, double green, double blue) {
        double[] point = {red, green, blue};
        int[] low = new int[3];
        for (int axis = 0; axis < 3; axis++) {
            double pos = clamp((point[axis] - min[axis]) / (max[axis] - min[axis]), 0, 1) * (size - 1);
            low[axis] = Math.min((int) pos, size - 2);
            point[axis] = pos - low[axis];
        }
        double[] rgb = new double[3];
        for (int corner = 0; corner < 8; corner++) {
            int r = corner & 1, g = (corner >> 1) & 1, b = (corner >> 2) & 1;
            int at = 3 * (((low[2] + b) * size + low[1] + g) * size + low[0] + r);
            double weight = (r == 0 ? 1 - point[0] : point[0])
                    * (g == 0 ? 1 - point[1] : point[1]) * (b == 0 ? 1 - point[2] : point[2]);
            for (int channel = 0; channel < 3; channel++) rgb[channel] += table[at + channel] * weight;
        }
        for (int channel = 0; channel < 3; channel++) rgb[channel] = clamp(rgb[channel], 0, 1);
        return rgb;
    }

    private static double clamp(double x, double low, double high) {
        return Math.max(low, Math.min(x, high));
    }

    private static double luma(double[] rgb) {
        return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
    }

    byte[][] curves(int[] baseline, int[] maxima) {
        double[] neutral = new double[129], shared = new double[129];
        double black = luma(sample(0, 0, 0)), white = luma(sample(1, 1, 1));
        for (int i = 1; i < 128; i++) {
            double x = clamp((double) baseline[i] / baseline[128], 0, 1);
            double y = luma(sample(x, x, x));
            double anchored = white > black + .0001 ? (y - black) / (white - black) : x;
            double weight = .92 * Math.min(1, Math.min(i, 128 - i) / 4.0);
            neutral[i] = Math.max(neutral[i - 1], clamp(y * weight + anchored * (1 - weight), 0, 1));
        }
        neutral[128] = 1;
        for (int i = 1; i < 128; i++) {
            double x;
            if (i <= 64) x = .5 * i;
            else if (i <= 88) x = 32 + 2.0 * (i - 64);
            else if (i <= 104) x = 80 + .5 * (i - 88);
            else if (i <= 120) x = 88 + 2.0 * (i - 104);
            else x = i;
            int at = Math.min((int) x, 127);
            shared[i] = Math.max(shared[i - 1], neutral[at] * (1 - (x - at)) + neutral[at + 1] * (x - at));
        }
        shared[128] = 1;
        return new byte[][]{quantize(shared, maxima[0]), quantize(neutral, maxima[1]),
                quantize(neutral, maxima[2])};
    }

    private static byte[] quantize(double[] samples, int max) {
        ByteBuffer out = ByteBuffer.allocate(516).order(ByteOrder.LITTLE_ENDIAN);
        for (double sample : samples) out.putInt((int) Math.rint(sample * max));
        return out.array();
    }

    private static final class Fit {
        double a = .015, b, c = .015, d, e;
        void add(double x, double y, double target, double weight) {
            a += weight * x * x;
            b += weight * x * y;
            c += weight * y * y;
            d += weight * x * target;
            e += weight * y * target;
        }
        void solve(double[] result, int offset) {
            double det = a * c - b * b;
            if (Math.abs(det) < 1e-12) return;
            result[offset] = (d * c - e * b) / det;
            result[offset + 1] = (a * e - b * d) / det;
        }
    }

    byte[][] color(byte[] baseMatrix, byte[] baseChroma) {
        double[][] delta = new double[16][6];
        double[] saturation = new double[4];
        int[] counts = new int[4];
        for (int sector = 0; sector < 16; sector++) {
            Fit[] fit = {new Fit(), new Fit(), new Fit()};
            for (int degrees = -18; degrees <= 18; degrees += 6) {
                double angle = Math.toRadians((360 + sector * 22.5 + degrees) % 360);
                double angleWeight = Math.max(.1, 1 - Math.abs(degrees) / 22.5);
                for (double y : new double[]{.25, .40, .55, .70}) {
                    double shift = luma(sample(y, y, y)) - y;
                    for (double chroma : new double[]{.06, .12, .18, .24}) {
                        double cb = chroma * Math.cos(angle), cr = chroma * Math.sin(angle);
                        double r = clamp(y + 1.5748 * cr, 0, 1);
                        double g = clamp(y - .187324 * cb - .468124 * cr, 0, 1);
                        double b = clamp(y + 1.8556 * cb, 0, 1);
                        double[] target = sample(r, g, b);
                        for (int i = 0; i < 3; i++) target[i] = clamp(target[i] - shift, 0, 1);
                        double weight = angleWeight * (chroma / .18);
                        fit[0].add(r - g, r - b, 1024 * (target[0] - r), weight);
                        fit[1].add(g - r, g - b, 1024 * (target[1] - g), weight);
                        fit[2].add(b - r, b - g, 1024 * (target[2] - b), weight);
                        if (degrees == 0) {
                            double luma = luma(target);
                            saturation[sector / 4] += Math.hypot((target[2] - luma) / 1.8556,
                                    (target[0] - luma) / 1.5748) / Math.hypot(cb, cr);
                            counts[sector / 4]++;
                        }
                    }
                }
            }
            for (int row = 0; row < 3; row++) fit[row].solve(delta[sector], row * 2);
        }
        ByteBuffer input = ByteBuffer.wrap(baseMatrix).order(ByteOrder.LITTLE_ENDIAN);
        ByteBuffer matrix = ByteBuffer.allocate(576).order(ByteOrder.LITTLE_ENDIAN);
        for (int group = 0; group < 3; group++) {
            for (int sector = 0; sector < 16; sector++) {
                double[] smooth = new double[6], base = new double[6];
                for (int i = 0; i < 6; i++) {
                    smooth[i] = .15 * delta[(sector + 15) % 16][i] + .70 * delta[sector][i]
                            + .15 * delta[(sector + 1) % 16][i];
                    base[i] = input.getShort();
                }
                double[][] left = matrix(smooth), right = matrix(base);
                for (int row = 0; row < 3; row++) {
                    for (int col = 0; col < 3; col++) {
                        if (row == col) continue;
                        double value = 0;
                        for (int k = 0; k < 3; k++) value += left[row][k] * right[k][col];
                        matrix.putShort((short) clamp(Math.rint(-1024 * value), -512, 768));
                    }
                }
            }
        }
        ByteBuffer chroma = ByteBuffer.wrap(baseChroma.clone()).order(ByteOrder.LITTLE_ENDIAN);
        double total = 0;
        int points = 0;
        for (int q = 0; q < 4; q++) { total += saturation[q]; points += counts[q]; }
        for (int q = 0; q < 4; q++) {
            if (total / points < .05) {
                for (int group = 0; group < 3; group++) chroma.putShort(16 * group + 8 + 2 * q, (short) 0);
            } else {
                double ratio = saturation[q] / counts[q];
                double scale = clamp(Math.pow(ratio, .85), .25, 1.65);
                chroma.putShort(8 + 2 * q, (short) clamp(Math.rint(chroma.getShort(8 + 2 * q) * scale), 64, 960));
                chroma.putShort(2 * q, (short) clamp(chroma.getShort(2 * q) - Math.rint((1 - ratio) * 180), -512, 256));
            }
        }
        return new byte[][]{chroma.array(), matrix.array()};
    }

    private static double[][] matrix(double[] m) {
        return new double[][]{{(1024 + m[0] + m[1]) / 1024, -m[0] / 1024, -m[1] / 1024},
                {-m[2] / 1024, (1024 + m[2] + m[3]) / 1024, -m[3] / 1024},
                {-m[4] / 1024, -m[5] / 1024, (1024 + m[4] + m[5]) / 1024}};
    }
}
