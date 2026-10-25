"""TEST DOUBLE launcher for desktop end-to-end tests. Prints the port, then serves
a fixed, scripted plan for every chat request until killed. Not a model."""

import json
import sys
import time

from tests.conftest import VALID_PLAN
from tests.fake_model_server import FakeModelServer

if __name__ == "__main__":
    with FakeModelServer() as srv:
        srv.default_reply = json.dumps(VALID_PLAN)
        print(srv.port, flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)
