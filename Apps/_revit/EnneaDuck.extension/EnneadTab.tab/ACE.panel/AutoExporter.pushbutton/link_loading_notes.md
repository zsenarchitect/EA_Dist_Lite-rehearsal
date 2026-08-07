Link Loading Verification
=========================

Use this checklist to confirm the AutoExporter link guard is working after deployment:

1. Launch Revit with AutoExporter and open a project that contains at least one Revit link.
2. Manually unload a link via *Manage → Manage Links* (keep the entry in the list, just unload it).
3. Start AutoExporter for that project.
4. Watch the orchestrator heartbeat: steps `3.x` should show the link name being reloaded and then reporting success.
5. Once Revit finishes, reopen *Manage Links* to confirm the link is loaded again.
6. Repeat with a link that has been removed or moved; AutoExporter should fail fast with `Failed to load Revit links before export` in both the console and heartbeat log so the job stops safely.

