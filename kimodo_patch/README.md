# Kimodo Patch

These files are a lightweight local patch for an existing NVIDIA Kimodo checkout. They are not a copy of Kimodo itself.

## Files

```text
kimodo/demo/bridge_api.py
scripts/open_kimodo_webui.ps1
scripts/start_kimodo_demo_local_llama.ps1
scripts/start_kimodo_demo_local_llama_logged.ps1
scripts/run_kimodo_demo_logged_child.ps1
```

## Apply

Copy:

```text
kimodo/demo/bridge_api.py -> kimodo-src/kimodo/demo/bridge_api.py
scripts/*.ps1             -> scripts/
```

Then patch `kimodo-src/kimodo/demo/app.py`.

Near the existing imports, change:

```python
from . import generation, ui
```

to:

```python
from . import bridge_api, generation, ui
```

In `KimodoDemo.__init__`, after the Viser client callbacks are registered:

```python
self.server.on_client_connect(self.on_client_connect)
self.server.on_client_disconnect(self.on_client_disconnect)
```

add:

```python
bridge_api.start_bridge_api(self)
```

After startup, the command API should answer:

```text
http://127.0.0.1:7870/health
```

with:

```json
{"ok": true}
```

## Important

Open the Kimodo WebUI once before sending prompts from Blender. The bridge API uses the active WebUI client session to generate motions.
