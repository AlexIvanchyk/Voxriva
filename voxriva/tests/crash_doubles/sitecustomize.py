"""TEST ONLY: observable worker barriers, mounted solely in the crash E2E stack.

The SMTP adapter still sends to real local Mailpit. No success, receipt, lease,
or delivery state is fabricated. The test kills the real worker at a barrier.
"""

import os
import sys

if (
    os.environ.get("VOXRIVA_WORKER_CRASH_TEST") == "1"
    and os.path.basename(sys.argv[0]) == "celery"
):
    import asyncio
    import json
    import threading
    import time
    from pathlib import Path

    from backend.app.features.notifications import delivery
    from backend.app.features.providers.adapters.smtp import SMTPProvider

    state = Path("/crash-state")
    original_render = delivery.render_message
    original_send = SMTPProvider.send

    def enter(phase, **details):
        """Claim a one-shot barrier; retries cannot accidentally block here twice."""
        try:
            descriptor = os.open(
                state / f"{phase}.claimed", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
        except FileExistsError:
            return False
        os.close(descriptor)
        temporary = state / f"{phase}.entered.tmp"
        temporary.write_text(
            json.dumps({"phase": phase, "pid": os.getpid(), **details})
        )
        temporary.replace(state / f"{phase}.entered.json")
        return True

    async def wait_async(phase):
        deadline = time.monotonic() + 100
        while not (state / f"{phase}.release").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Crash E2E did not release {phase}")
            await asyncio.sleep(0.05)

    async def controlled_render(channel, draft, context, **kwargs):
        result = await original_render(channel, draft, context, **kwargs)
        if (
            context.get("marker") == "before-send"
            and result.rendered
            and not result.errors
        ):
            phase = "before-send" if enter("before-send") else "reclaimed-send"
            if phase == "before-send" or enter(phase):
                await wait_async(phase)
        return result

    def controlled_send(self, message):
        result = original_send(self, message)
        if getattr(message, "subject", "") == "Worker crash accepted-send" and enter(
            "accepted-send", message_id=result.message_id
        ):
            deadline = time.monotonic() + 100
            pause = threading.Event()
            while not (state / "accepted-send.release").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Crash E2E did not release accepted-send")
                pause.wait(0.05)
        return result

    delivery.render_message = controlled_render
    SMTPProvider.send = controlled_send
