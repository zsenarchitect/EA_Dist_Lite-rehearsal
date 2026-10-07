# -*- coding: utf-8 -*-
"""Stage 03: Documentation & Wiki Generation."""

import os
import sys
from ..stage_base import PublishStage, PublishStageError


class DocsWikiStage(PublishStage):
    """Documentation stage: generates toolbars, updates Wiki, and checks file path lengths."""

    @property
    def name(self):
        return "Documentation & Wiki Generation"

    @property
    def description(self):
        return "Generates PDF handbooks, compiles Wiki HTML, updates READMEs, and scans path lengths."

    def execute(self, context):
        self._generate_pdf_handbooks(context)
        self._build_wiki(context)
        self._generate_readmes(context)
        self._check_path_lengths(context)

    def _generate_pdf_handbooks(self, context):
        """Generate PDF handbooks (Revit and Rhino) in Installation folder."""
        apps_lib = os.path.join(context.os_repo_folder, "Apps", "lib")
        if apps_lib not in sys.path:
            sys.path.insert(0, apps_lib)

        print("Generating PDF handbooks (Revit & Rhino)...")
        try:
            from EnneadTab import DOCUMENTATION
            DOCUMENTATION.generate_documentation(debug=False)
            print("[OK] PDF handbooks generated successfully.")
        except Exception as e:
            raise PublishStageError("Documentation PDF generation failed: {}".format(e))


    def _build_wiki(self, context):
        """Invoke WikiBuilder if present."""
        darkside_dir = os.path.normpath(os.path.join(context.os_repo_folder, "DarkSide"))
        if darkside_dir not in sys.path:
            sys.path.insert(0, darkside_dir)

        try:
            from WikiBuilder import wiki_builder
            print("Building Wiki HTML pages...")
            wiki_builder.main()
            print("[OK] Wiki HTML build complete.")
        except ImportError:
            print("Notice: WikiBuilder module not available; skipping Wiki build.")
        except Exception as e:
            raise PublishStageError("Wiki build failed: {}".format(e))

    def _generate_readmes(self, context):
        """Generate repository README.md files."""
        print("Generating repository README.md files...")
        readme_path = os.path.join(context.os_repo_folder, "README.md")
        content = """# EnneadTab-OS

EnneadTab Open Source Ecosystem Core Repository.

## Published Distributions
- **EA_Dist**: Full production release.
- **EA_Dist_Lite**: Lightweight production release.
"""
        try:
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("[OK] Main README.md generated.")
        except Exception as e:
            raise PublishStageError("Failed to write README.md: {}".format(e))

    def _check_path_lengths(self, context):
        """Report how close the publish is to Windows MAX_PATH, per destination root.

        WHAT THIS USED TO MEASURE, AND WHY IT WAS THE WRONG NUMBER
        ----------------------------------------------------------
        It walked the WHOLE repo and compared absolute SOURCE paths against a flat 240.
        Three problems, all of which matter more once this becomes a hard gate (#4692b):

        1. WRONG SCOPE. It scanned everything under os_repo_folder, skipping only .git,
           .claude and .venv -- so DEBUG/ (git-ignored scratch, journal backups, _MEI*
           temp dirs) and node_modules counted, while stage_04 only ever copies
           Apps, Installation and DarkSide. A local scratch file could veto a fleet
           publish. Now scoped to FOLDERS_TO_PROCESS, the set that actually ships.

        2. ONE ROOT. A file's real length differs per destination, and the publisher
           writes to three roots: the source clone it reads from, EA_Dist, and
           EA_Dist_Lite. Measured 2026-08-21, longest relative path 185:
               source clone  prefix 61 -> 247   (19 files over 240)
               EA_Dist_Lite  prefix 46 -> 232   (0)
               EA_Dist       prefix 41 -> 227   (0)
           So the SOURCE root binds, by 15-20 characters. Worth stating plainly because
           the intuitive fix -- "measure the destination, that's where it lands" -- makes
           the scan report 232 instead of 247 and find nothing, which reads as an
           improvement and is blindness. The 2026-08-18 outage was a shutil.copy2 failing
           to READ a source path after the source clone folder was renamed 22 -> 41 chars;
           EA_Dist's prefix never changed. Report the max over all three.

        3. ONE THRESHOLD. Directories and files do not share a limit. Measured on the
           publisher box: os.mkdir refuses at 248, open() refuses at 260. A single ~255
           cut therefore admits trees that pass the file check and then die in
           shutil.copytree with WinError 206. Separate ceilings, separate reports.

        Still WARN-ONLY. Promoting to fatal is #4692b and is deliberately gated on one
        green production publish, because these prefixes are read from context rather
        than measured on the publisher box -- and a false fire here stops all publishing.
        """
        from .stage_04_stage_dist import FOLDERS_TO_PROCESS, path_excluded_from_target

        DIR_LIMIT = 247   # os.mkdir refuses at 248
        FILE_LIMIT = 259  # open() refuses at 260

        roots = [("source clone", context.os_repo_folder),
                 ("EA_Dist", context.dist_folder),
                 ("EA_Dist_Lite", context.dist_lite_folder)]
        print("Scanning staged content against MAX_PATH for {} root(s)...".format(len(roots)))

        # (relative path, is_dir). Relative, so each root can be priced separately.
        entries = []
        for folder in FOLDERS_TO_PROCESS:
            base = os.path.join(context.os_repo_folder, folder)
            if not os.path.isdir(base):
                continue
            for walk_root, dirs, files in os.walk(base):
                for name in dirs:
                    entries.append((os.path.relpath(
                        os.path.join(walk_root, name), context.os_repo_folder), True))
                for name in files:
                    entries.append((os.path.relpath(
                        os.path.join(walk_root, name), context.os_repo_folder), False))

        worst_len, worst_desc, over = 0, "", []
        for rel, is_dir in entries:
            # path_excluded_from_target(rel, is_lite=False) checks ONLY the exclusions
            # that apply unconditionally to every target (DuckMaker.extension today) --
            # the is_lite-specific checks inside it are skipped when is_lite is False,
            # by construction. Those paths are PRUNED from stage_04's os.walk before it
            # descends, for either target, so shutil.copy2 never attempts to read them
            # -- a path that is never read cannot trigger the MAX_PATH failure this scan
            # exists to catch, for ANY root including the source clone. Excluding it
            # here fixes a measurement gap the shared predicate surfaced: EA_Dist (Full)
            # was previously priced as if this content shipped there too. senzhang-todo
            # #4747.
            if path_excluded_from_target(rel, is_lite=False):
                continue
            limit = DIR_LIMIT if is_dir else FILE_LIMIT
            for label, root in roots:
                if not root:
                    continue
                if label == "EA_Dist_Lite" and path_excluded_from_target(rel, is_lite=True):
                    continue
                total = len(root) + 1 + len(rel)
                if total > worst_len:
                    worst_len, worst_desc = total, "{} under {}".format(rel, label)
                if total > limit:
                    over.append((total, limit, label, rel))

        if over:
            over.sort(reverse=True)
            # Count PATHS, not rows. `over` holds one row per (entry, root), so a single
            # file that is over under two roots would otherwise be reported as two paths
            # -- the same wrong-operator-facing-number defect this branch fixes in
            # stage_04's copied-file count. Today source is the only binding root, so the
            # two numbers happen to agree; that is exactly when a miscount goes unnoticed.
            distinct = len({rel for _, _, _, rel in over})
            print("Warning: {} path(s) exceed the Windows limit for their kind, in {} "
                  "root(s):".format(distinct, len({label for _, _, label, _ in over})))
            for total, limit, label, rel in over[:10]:
                print("  [{} > {}] {} -> {}".format(total, limit, label, rel))
            if len(over) > 10:
                # ROW count, and it says so. The ten lines above are rows (one per
                # path-per-root), while the header counts distinct paths. Printing a
                # bare "N more" here mixed the two units in the same block -- in the
                # block whose own fix was about mixing those units.
                print("  ... and {} more row(s).".format(len(over) - 10))
            print("  This is a WARNING today. It becomes a hard refusal under "
                  "senzhang-todo #4692b -- shorten these before then.")
        elif not entries:
            # A scan that measured NOTHING must not print a margin. "[OK] longest path is
            # 0 chars, 259 under the ceiling" is success-shaped output from an empty
            # measurement -- the shape this whole branch exists to remove. Cannot fire in
            # a reset --hard publisher clone (stage_04 raises on a missing source folder
            # first), which is exactly why it would go unnoticed if it ever could.
            print("[WARN] Path-length scan found NO staged entries under {}. That is a "
                  "structural zero, not a clean result -- nothing was measured.".format(
                      ", ".join(FOLDERS_TO_PROCESS)))
        else:
            print("[OK] Longest staged path is {} chars ({}), {} under the {}-char file "
                  "ceiling. {} entries measured across {} root(s).".format(
                      worst_len, worst_desc, FILE_LIMIT - worst_len, FILE_LIMIT,
                      len(entries), len(roots)))
