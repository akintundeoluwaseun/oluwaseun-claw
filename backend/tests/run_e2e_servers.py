"""TEST DOUBLE + TEST FIXTURE launcher for the desktop end-to-end test.

Starts the local test website and the scripted model server, prints their
addresses as one JSON line, then serves until killed. The model replies are a
fixed script in the order the e2e test uses them; nothing here is a real model.
"""

import json
import sys
import time

from tests.conftest import VALID_PLAN
from tests.fake_model_server import FakeModelServer
from tests.site_server import SiteServer


def act(tool, **args):
    return json.dumps({"thought": f"Use {tool}", "action": "tool", "tool": tool, "args": args})


if __name__ == "__main__":
    with SiteServer() as site, FakeModelServer() as model:
        plan = json.dumps(VALID_PLAN)
        model.replies.extend(
            [
                plan,  # 1. "Plan only"
                plan,  # 2. Run: research and save links
                act("web_search", query="motion graphics templates"),
                act("open_search_result", number=1),
                act("save_links", file_name="motion templates",
                    links=[{"title": "Free Motion Graphics Templates 2026", "url": site.base_url + "/articles/motion-templates"}]),
                json.dumps({"thought": "done", "action": "finish", "final_answer": "Saved 1 link to motion templates.md."}),
                plan,  # 3. Run that will be stopped while waiting for approval
                act("open_url", url=site.base_url + "/contact"),
                act("click_button", text="Send message"),
            ]
        )
        model.default_reply = plan
        print(json.dumps({"model_port": model.port, "site_url": site.base_url}), flush=True)
        try:
            while True:
                time.sleep(1)
                if site.form_submissions:
                    print("FORM SUBMITTED", file=sys.stderr, flush=True)
        except KeyboardInterrupt:
            sys.exit(0)
