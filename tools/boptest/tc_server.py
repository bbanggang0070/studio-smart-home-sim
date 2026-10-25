"""BOPTEST TestCase 최소 HTTP 서버 (docs/11 필수 조치 5) — BOPTEST worker 이미지 안에서 돈다 (pyfmi · Python 3.11).

BOPTEST-Service(web · redis · minio)는 MinIO 공개 이미지가 내려가 띄울 수 없어, worker 의 TestCase 를 직접 감싼다.
FMU · KPI 계산은 BOPTEST 원본 코드 그대로다. 요청 · 응답은 BOPTEST REST API 와 같은 이름 · JSON 을 쓴다.
    POST /initialize {start_time, warmup_period} · PUT /scenario {time_period, electricity_price} · PUT /step {step}
    POST /advance {입력: 값, ..._activate: 1} · GET /measurements · /inputs · /kpis · /name
실행: tools/boptest/run_server.sh
"""

import json
import os
import shutil
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

sys.path.insert(0, "/boptest/lib")
from testcase import TestCase  # noqa: E402

WORK = "/work"
os.makedirs(WORK, exist_ok=True)
os.chdir(WORK)
shutil.copyfile("/version.txt", "./version.txt")
TC = TestCase(os.environ.get("FMU", "/testcase/models/wrapped.fmu"), "/boptest/lib/forecast/forecast_uncertainty_params.json")


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    return x


class H(BaseHTTPRequestHandler):
    def _send(self, out):
        status, message, payload = out if isinstance(out, tuple) and len(out) == 3 else (200, "", out)
        body = json.dumps({"status": status, "message": message, "payload": clean(payload)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        route = {"/measurements": TC.get_measurements, "/inputs": TC.get_inputs, "/kpis": TC.get_kpis,
                 "/name": TC.get_name, "/step": TC.get_step}.get(self.path)
        self._send(route() if route else (404, "없는 경로", None))

    def do_POST(self):
        b = self._body()
        if self.path == "/initialize":
            self._send(TC.initialize(float(b["start_time"]), float(b["warmup_period"])))
        elif self.path == "/advance":
            self._send(TC.advance(b))
        else:
            self._send((404, "없는 경로", None))

    def do_PUT(self):
        b = self._body()
        if self.path == "/scenario":
            self._send(TC.set_scenario(b))
        elif self.path == "/step":
            self._send(TC.set_step(float(b["step"])))
        else:
            self._send((404, "없는 경로", None))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "5000"))), H).serve_forever()
