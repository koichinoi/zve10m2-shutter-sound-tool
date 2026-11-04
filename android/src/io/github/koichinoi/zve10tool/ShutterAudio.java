package io.github.koichinoi.zve10tool;

import android.content.Context;
import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.net.Uri;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

final class ShutterAudio {
    private static final int RATE = 24000;
    private static final int LIMIT = 14880;

    static double prepare(Context context, Uri source, int volume, File destination) throws IOException {
        MediaExtractor extractor = new MediaExtractor();
        MediaCodec decoder = null;
        try {
            extractor.setDataSource(context, source, null);
            MediaFormat track = null;
            for (int i = 0; i < extractor.getTrackCount(); i++) {
                MediaFormat candidate = extractor.getTrackFormat(i);
                String type = candidate.getString(MediaFormat.KEY_MIME);
                if (type != null && type.startsWith("audio/")) {
                    extractor.selectTrack(i);
                    track = candidate;
                    break;
                }
            }
            if (track == null) throw new IOException("找不到音轨");
            int rate = track.getInteger(MediaFormat.KEY_SAMPLE_RATE);
            int channels = track.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
            decoder = MediaCodec.createDecoderByType(track.getString(MediaFormat.KEY_MIME));
            track.setInteger(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
            decoder.configure(track, null, null, 0);
            decoder.start();
            short[] mono = new short[125000];
            int count = 0;
            boolean sentEnd = false;
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            long deadline = android.os.SystemClock.elapsedRealtime() + 30000;
            while (android.os.SystemClock.elapsedRealtime() < deadline) {
                if (!sentEnd) {
                    int in = decoder.dequeueInputBuffer(5000);
                    if (in >= 0) {
                        ByteBuffer buffer = decoder.getInputBuffer(in);
                        buffer.clear();
                        int size = extractor.readSampleData(buffer, 0);
                        sentEnd = size < 0;
                        decoder.queueInputBuffer(in, 0, Math.max(0, size),
                                sentEnd ? 0 : extractor.getSampleTime(),
                                sentEnd ? MediaCodec.BUFFER_FLAG_END_OF_STREAM : 0);
                        if (!sentEnd) extractor.advance();
                    }
                }
                int out = decoder.dequeueOutputBuffer(info, 5000);
                if (out == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat format = decoder.getOutputFormat();
                    int nextRate = format.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    int nextChannels = format.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    if (count > 0 && (rate != nextRate || channels != nextChannels)) {
                        throw new IOException("音频格式在解码中发生变化");
                    }
                    rate = nextRate;
                    channels = nextChannels;
                    if (format.containsKey(MediaFormat.KEY_PCM_ENCODING)
                            && format.getInteger(MediaFormat.KEY_PCM_ENCODING) != AudioFormat.ENCODING_PCM_16BIT) {
                        throw new IOException("手机解码器未输出 16 位 PCM");
                    }
                }
                if (out < 0) continue;
                if (info.size > 0) {
                    if (rate < 1 || rate > 192000 || channels < 1 || channels > 32
                            || info.size % (channels * 2) != 0) throw new IOException("解码格式不受支持");
                    ByteBuffer buffer = decoder.getOutputBuffer(out).order(ByteOrder.nativeOrder());
                    buffer.limit(info.offset + info.size);
                    buffer.position(info.offset);
                    while (buffer.remaining() >= channels * 2) {
                        if (count >= (long) LIMIT * rate / RATE) {
                            throw new IOException("音频超过 0.620 秒，请先剪短");
                        }
                        int sum = 0;
                        for (int channel = 0; channel < channels; channel++) sum += buffer.getShort();
                        mono[count++] = (short) (sum / channels);
                    }
                }
                decoder.releaseOutputBuffer(out, false);
                if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                    int frames = (int) Math.round(count * (double) RATE / rate);
                    if (frames < 1 || frames > LIMIT) throw new IOException("音频长度无效");
                    writeWave(destination, mono, count, frames, rate, volume);
                    return frames / (double) RATE;
                }
            }
            throw new IOException("音频解码超时");
        } finally {
            if (decoder != null) decoder.release();
            extractor.release();
        }
    }

    private static void writeWave(File file, short[] mono, int count, int frames, int rate, int volume)
            throws IOException {
        ByteBuffer wave = ByteBuffer.allocate(44 + frames * 2).order(ByteOrder.LITTLE_ENDIAN);
        wave.putInt(0x46464952).putInt(36 + frames * 2).putInt(0x45564157);
        wave.putInt(0x20746d66).putInt(16).putShort((short) 1).putShort((short) 1);
        wave.putInt(RATE).putInt(RATE * 2).putShort((short) 2).putShort((short) 16);
        wave.putInt(0x61746164).putInt(frames * 2);
        for (int i = 0; i < frames; i++) {
            double position = i * (double) rate / RATE;
            int left = Math.min((int) position, count - 1);
            int right = Math.min(left + 1, count - 1);
            double sample = mono[left] + (mono[right] - mono[left]) * (position - left);
            wave.putShort((short) Math.round(sample * volume / 100));
        }
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(wave.array());
        }
    }
}
