"""Loopback MJPEG preview of the broker's frames; never opens a capture card."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import cv2


class NativePreviewServer:
    def __init__(self, port, client_factory):
        self.stopped = threading.Event()
        stopped = self.stopped

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path != "/mjpeg":
                    self.send_error(404)
                    return
                client = None
                try:
                    self.connection.settimeout(2)
                    client = client_factory()
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    while not stopped.is_set():
                        frame = client.read_array()
                        if frame is not None:
                            frame = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
                            ok, jpeg = cv2.imencode(".jpg", frame)
                            if ok:
                                data = jpeg.tobytes()
                                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                                 + str(len(data)).encode("ascii") + b"\r\n\r\n" + data + b"\r\n")
                                self.wfile.flush()
                        stopped.wait(1 / 30)
                except (OSError, RuntimeError):
                    pass  # A closed monitor or stopped broker ends only this stream.
                finally:
                    if client is not None:
                        client.close()

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.1),
                                       name="native-preview", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.thread.ident is not None:
            self.thread.join(timeout=2)
