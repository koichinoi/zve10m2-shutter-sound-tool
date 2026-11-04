package io.github.koichinoi.zve10tool;

import android.hardware.usb.*;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

final class UsbInquiry {
    private static final int TIMEOUT_MS = 1500;
    private static final int TAG = 0x5a564531;

    static final class InterfaceBusy extends IOException {
        InterfaceBusy() { super("USB 存储接口仍被占用"); }
    }

    static boolean supportsRetry(UsbDevice device) {
        return device.getVendorId() == 0x054c && device.getProductId() == 0x0ee6;
    }

    static String read(UsbManager manager, UsbDevice device, boolean force) throws IOException {
        if (force && !supportsRetry(device)) throw new IOException("设备不支持接管检测");
        UsbDeviceConnection connection = manager.openDevice(device);
        if (connection == null) throw new IOException("安卓未能打开设备");
        try {
            for (int i = 0; i < device.getInterfaceCount(); i++) {
                UsbInterface storage = device.getInterface(i);
                if (storage.getInterfaceClass() != UsbConstants.USB_CLASS_MASS_STORAGE
                        || storage.getInterfaceSubclass() != 6 || storage.getInterfaceProtocol() != 0x50) continue;
                UsbEndpoint in = null, out = null;
                for (int j = 0; j < storage.getEndpointCount(); j++) {
                    UsbEndpoint endpoint = storage.getEndpoint(j);
                    if (endpoint.getType() != UsbConstants.USB_ENDPOINT_XFER_BULK) continue;
                    if (endpoint.getDirection() == UsbConstants.USB_DIR_IN) in = endpoint;
                    else out = endpoint;
                }
                if (in == null || out == null) continue;
                if (!connection.claimInterface(storage, force)) throw new InterfaceBusy();
                try {
                    return inquiry(connection, in, out);
                } finally {
                    connection.releaseInterface(storage);
                }
            }
            throw new IOException("未找到兼容的 USB 存储接口");
        } finally {
            connection.close();
        }
    }

    private static String inquiry(UsbDeviceConnection connection, UsbEndpoint in, UsbEndpoint out)
            throws IOException {
        byte[] response = new byte[36];
        ByteBuffer command = ByteBuffer.allocate(31).order(ByteOrder.LITTLE_ENDIAN);
        command.putInt(0x43425355).putInt(TAG).putInt(response.length);
        command.put((byte) 0x80).put((byte) 0).put((byte) 6);
        command.put(new byte[]{0x12, 0, 0, (byte) (response.length >>> 8), (byte) response.length, 0});
        if (connection.bulkTransfer(out, command.array(), command.capacity(), TIMEOUT_MS) != command.capacity()) {
            throw new IOException("无法发送只读识别请求");
        }
        int count = connection.bulkTransfer(in, response, response.length, TIMEOUT_MS);
        byte[] status = new byte[13];
        int statusCount = connection.bulkTransfer(in, status, status.length, TIMEOUT_MS);
        ByteBuffer result = ByteBuffer.wrap(status).order(ByteOrder.LITTLE_ENDIAN);
        if (statusCount != status.length || result.getInt() != 0x53425355 || result.getInt() != TAG
                || result.getInt() != response.length - count || result.get() != 0 || count != response.length) {
            throw new IOException("设备未返回有效的识别响应");
        }
        String name = new String(response, 8, 24, StandardCharsets.US_ASCII).trim();
        return name.isEmpty() ? "已收到设备识别响应" : name;
    }
}
