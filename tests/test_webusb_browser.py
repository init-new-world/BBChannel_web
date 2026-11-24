from __future__ import annotations

from io import BytesIO
import os
import socket
import struct
import threading
import time

from PIL import Image
import pytest

playwright = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.skipif(
    not os.environ.get("BBCHANNEL_TEST_CHROMIUM"),
    reason="Set BBCHANNEL_TEST_CHROMIUM to a local Chromium executable.",
)


def _pack_adb(cmd_str: str, arg0: int = 0, arg1: int = 0, payload: bytes = b"") -> bytes:
    cmd = int.from_bytes(cmd_str.encode("ascii"), "little")
    checksum = sum(payload) & 0xFFFFFFFF
    magic = (cmd ^ 0xFFFFFFFF) & 0xFFFFFFFF
    return struct.pack("<6I", cmd, arg0, arg1, len(payload), checksum, magic) + payload


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise EOFError("Socket closed")
        buf.extend(chunk)
    return bytes(buf)


def _recv_adb(sock: socket.socket) -> tuple[str, int, int, bytes]:
    header = _recv_exact(sock, 24)
    cmd, arg0, arg1, data_len, _chk, _magic = struct.unpack("<6I", header)
    payload = _recv_exact(sock, data_len) if data_len else b""
    return cmd.to_bytes(4, "little").decode("ascii", errors="replace"), arg0, arg1, payload


@pytest.fixture
def webusb_console(tmp_path):
    import uvicorn

    from webapp.app import create_app
    from webapp.core.models import Capability, DeviceInfo, OperationResult
    from webapp.services.devices import DeviceService
    from webapp.services.event_log import EventLog

    assets = tmp_path / "assets"
    data = tmp_path / "data"
    assets.mkdir()
    data.mkdir()

    screen_buf = BytesIO()
    Image.new("RGB", (1280, 720), (32, 68, 112)).save(screen_buf, format="PNG")
    screen_png = screen_buf.getvalue()

    class FakeAdbBackend:
        name = "adb"

        def __init__(self) -> None:
            self._devices: dict[str, DeviceInfo] = {}
            self._lock = threading.Lock()
            self._sockets: list[socket.socket] = []
            self.disconnected: list[str] = []

        def capability(self) -> Capability:
            return Capability(self.name, True)

        def list_devices(self) -> list[DeviceInfo]:
            with self._lock:
                return list(self._devices.values())

        def find_device(self, device_id: str, *, enrich: bool = True) -> DeviceInfo | None:
            with self._lock:
                return self._devices.get(device_id)

        def connect_endpoint(self, endpoint: str) -> DeviceInfo:
            host, port_s = endpoint.rsplit(":", 1)
            sock = socket.create_connection((host, int(port_s)), timeout=5.0)
            self._sockets.append(sock)

            # Send a 512-byte-aligned CNXN payload to exercise ZLP handling in browser JS!
            banner = b"host::" + (b"x" * (512 - 7)) + b"\x00"
            assert len(banner) == 512
            sock.sendall(_pack_adb("CNXN", 0x01000001, 256 * 1024, banner))

            cmd1, arg0_1, _, _ = _recv_adb(sock)
            assert cmd1 == "AUTH" and arg0_1 == 1
            sock.sendall(_pack_adb("AUTH", 2, 0, b"S" * 256))

            cmd2, arg0_2, _, _ = _recv_adb(sock)
            assert cmd2 == "AUTH" and arg0_2 == 1
            sock.sendall(_pack_adb("AUTH", 3, 0, b"QAAAA-test-rsa-pubkey\x00"))

            pending = DeviceInfo("adb", endpoint, name=endpoint, status="unauthorized")
            with self._lock:
                self._devices[endpoint] = pending

            def _await_cnxn() -> None:
                try:
                    cmd_ok, _, _, dev_banner = _recv_adb(sock)
                    if cmd_ok == "CNXN":
                        with self._lock:
                            self._devices[endpoint] = DeviceInfo(
                                "adb",
                                endpoint,
                                name="Google Pixel 9 Pro",
                                status="device",
                                details={"banner": dev_banner.decode("utf-8", errors="ignore")},
                            )
                except Exception:
                    pass

            threading.Thread(target=_await_cnxn, daemon=True).start()
            return pending

        def disconnect_endpoint(self, endpoint: str) -> None:
            self.disconnected.append(endpoint)
            with self._lock:
                self._devices.pop(endpoint, None)
            for s in self._sockets:
                try:
                    s.close()
                except OSError:
                    pass
            self._sockets.clear()

        def snapshot(self, device_id: str) -> bytes:
            return screen_png

        def tap(self, device_id: str, x: int, y: int) -> OperationResult:
            return OperationResult(ok=True, action="tap", message=f"tap {x},{y}")

        def swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> OperationResult:
            return OperationResult(ok=True, action="swipe", message="swipe")

    backend = FakeAdbBackend()
    events = EventLog()
    devices = DeviceService([backend], events)
    app = create_app(
        assets_dir=assets,
        data_dir=data,
        device_service=devices,
        event_log=events,
        runtime_db_path=tmp_path / "runtime.db",
    )

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    pytest.fail("Test server failed to start")
                time.sleep(0.02)
            with playwright.sync_playwright() as driver:
                browser = driver.chromium.launch(
                    executable_path=os.environ["BBCHANNEL_TEST_CHROMIUM"],
                    headless=True,
                    args=["--no-sandbox"],
                )
                try:
                    yield browser, f"http://127.0.0.1:{port}", backend, devices
                finally:
                    browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=5)


def test_webusb_header_fits_all_breakpoints_in_en_and_zh(webusb_console):
    browser, url, _backend, _devices = webusb_console
    page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-US")
    page.goto(url)
    playwright.expect(page.locator("#webusb-adb")).to_be_visible()
    playwright.expect(page.locator("#webusb-adb")).to_have_text("WebUSB")

    for lang, expected_label in (("en", "WebUSB"), ("zh-CN", "USB 直连")):
        page.locator("#language-select").select_option(lang)
        playwright.expect(page.locator("#webusb-adb")).to_have_text(expected_label)
        for width in (1440, 1251, 1250, 901, 900, 561, 560, 390, 360, 320):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.locator(".topbar").evaluate("e => e.scrollWidth <= e.clientWidth"), (lang, width)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (lang, width)
            if width <= 390:
                assert page.locator(".topbar").evaluate("e => e.getBoundingClientRect().height") <= 180
    page.close()


def test_webusb_browser_flow_connects_handles_zlp_and_disconnects_cleanly(webusb_console):
    browser, url, backend, devices = webusb_console
    page = browser.new_page(viewport={"width": 1280, "height": 800}, locale="zh-CN")
    page.add_init_script(
        """
        (() => {
          function packAdb(cmdStr, arg0, arg1, payloadBytes) {
            const cmd = (
              cmdStr.charCodeAt(0)
              | (cmdStr.charCodeAt(1) << 8)
              | (cmdStr.charCodeAt(2) << 16)
              | (cmdStr.charCodeAt(3) << 24)
            ) >>> 0;
            let chk = 0;
            for (const b of payloadBytes) chk = (chk + b) >>> 0;
            const magic = (cmd ^ 0xffffffff) >>> 0;
            const out = new Uint8Array(24 + payloadBytes.length);
            const dv = new DataView(out.buffer);
            dv.setUint32(0, cmd, true);
            dv.setUint32(4, arg0 >>> 0, true);
            dv.setUint32(8, arg1 >>> 0, true);
            dv.setUint32(12, payloadBytes.length >>> 0, true);
            dv.setUint32(16, chk, true);
            dv.setUint32(20, magic, true);
            out.set(payloadBytes, 24);
            return out;
          }

          const state = {
            opened: false,
            claimedInterface: null,
            releasedInterface: null,
            closedCount: 0,
            outTransfers: [],
            inQueue: [],
            pendingResolve: null,
            authStep: 0,
            expectPayloadBytes: 0,
          };

          function pushInChunk(bytes) {
            if (state.pendingResolve) {
              const r = state.pendingResolve;
              state.pendingResolve = null;
              r({ status: "ok", data: new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength) });
            } else {
              state.inQueue.push(bytes);
            }
          }

          window.__mockUsbState = state;
          window.__approveUsbDebuggingOnPhone = () => {
            // Prepend a 0-byte ZLP to verify pumpWebUsbIn skips ZLP before 24-byte header!
            pushInChunk(new Uint8Array(0));
            const enc = new TextEncoder().encode("device::ro.product.model=Pixel_9_Pro\\0");
            const pkt = packAdb("CNXN", 0x01000001, 262144, enc);
            pushInChunk(pkt.slice(0, 24));
            pushInChunk(pkt.slice(24));
          };

          const fakeDevice = {
            manufacturerName: "Google",
            productName: "Pixel 9 Pro",
            serialNumber: "WEBUSB999",
            get opened() { return state.opened; },
            configuration: null,
            configurations: [
              {
                configurationValue: 1,
                interfaces: [
                  {
                    interfaceNumber: 1,
                    alternates: [
                      {
                        alternateSetting: 0,
                        interfaceClass: 0xff,
                        interfaceSubclass: 0x42,
                        interfaceProtocol: 0x01,
                        endpoints: [
                          { endpointNumber: 1, direction: "in", type: "bulk", packetSize: 512 },
                          { endpointNumber: 2, direction: "out", type: "bulk", packetSize: 512 },
                        ],
                      },
                    ],
                  },
                ],
              },
            ],
            async open() { state.opened = true; },
            async selectConfiguration(v) { this.configuration = this.configurations[0]; },
            async claimInterface(num) { state.claimedInterface = num; },
            async selectAlternateInterface() {},
            async releaseInterface(num) { state.releasedInterface = num; },
            async close() { state.opened = false; state.closedCount += 1; },
            async clearHalt() {},
            async transferOut(_ep, data) {
              const copy = new Uint8Array(data.buffer || data, data.byteOffset || 0, data.byteLength);
              state.outTransfers.push(copy.byteLength);
              if (copy.byteLength === 24 && state.expectPayloadBytes === 0) {
                const dv = new DataView(copy.buffer, copy.byteOffset, 24);
                const cmd = dv.getUint32(0, true);
                const arg0 = dv.getUint32(4, true);
                const dlen = dv.getUint32(12, true);
                state.lastCmd = cmd;
                state.lastArg0 = arg0;
                state.expectPayloadBytes = dlen;
              } else if (state.expectPayloadBytes > 0 && copy.byteLength === state.expectPayloadBytes) {
                state.expectPayloadBytes = 0;
                // CNXN = 0x4e584e43, AUTH = 0x48545541
                if (state.lastCmd === 0x4e584e43) {
                  const tok = new Uint8Array(20).fill(0x41);
                  const auth1 = packAdb("AUTH", 1, 0, tok);
                  pushInChunk(auth1.slice(0, 24));
                  pushInChunk(auth1.slice(24));
                } else if (state.lastCmd === 0x48545541 && state.lastArg0 === 2) {
                  const tok2 = new Uint8Array(20).fill(0x42);
                  const auth2 = packAdb("AUTH", 1, 0, tok2);
                  pushInChunk(auth2.slice(0, 24));
                  pushInChunk(auth2.slice(24));
                }
              }
              return { status: "ok", bytesWritten: copy.byteLength };
            },
            transferIn(_ep, _len) {
              if (state.inQueue.length > 0) {
                const next = state.inQueue.shift();
                return Promise.resolve({
                  status: "ok",
                  data: new DataView(next.buffer, next.byteOffset, next.byteLength),
                });
              }
              return new Promise((resolve) => { state.pendingResolve = resolve; });
            },
          };

          const usbMock = {
            async requestDevice() { return fakeDevice; },
            addEventListener() {},
          };
          Object.defineProperty(navigator, "usb", { value: usbMock, configurable: true });
        })();
        """
    )

    page.goto(url)
    webusb_btn = page.locator("#webusb-adb")
    playwright.expect(webusb_btn).to_have_text("USB 直连")

    webusb_btn.click()
    # Host sent AUTH(3, RSAPUBLICKEY) -> button should show authorizing state in zh-CN!
    playwright.expect(webusb_btn).to_have_text("待手机授权…")

    # Verify ZLP (0-byte packet) was emitted right after the 512-byte CNXN payload!
    out_lengths = page.evaluate("window.__mockUsbState.outTransfers")
    assert out_lengths[:3] == [24, 512, 0], out_lengths

    # Simulate user tapping "Allow USB debugging" on their phone screen
    page.evaluate("window.__approveUsbDebuggingOnPhone()")

    playwright.expect(webusb_btn).to_have_text("USB 已连")
    playwright.expect(page.locator("#connection-state")).to_contain_text("adb · 127.0.0.1:")
    assert devices.state().connected is True

    # Switching locale dynamically updates the active WebUSB button text cleanly
    page.locator("#language-select").select_option("en")
    playwright.expect(webusb_btn).to_have_text("USB Active")

    # Clicking Disconnect releases the USB interface, closes USB device, and cleans up backend endpoint
    page.locator("#disconnect-device").click()
    playwright.expect(webusb_btn).to_have_text("WebUSB")
    playwright.expect(page.locator("#connection-state")).to_have_text("Disconnected")

    usb_state = page.evaluate(
        "({ opened: window.__mockUsbState.opened, released: window.__mockUsbState.releasedInterface, closedCount: window.__mockUsbState.closedCount })"
    )
    assert usb_state == {"opened": False, "released": 1, "closedCount": 1}
    assert devices.state().connected is False
    assert len(backend.disconnected) == 1
    page.close()
