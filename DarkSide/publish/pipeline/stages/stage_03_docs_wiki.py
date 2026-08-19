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
        return "Builds toolbars, compiles Wiki HTML, updates READMEs, and scans path lengths."

    def execute(self, context):
        self._build_wiki(context)
        self._generate_readmes(context)
        self._check_path_lengths(context)

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
        """Check for Windows MAX_PATH length violations."""
        print("Scanning repository for long file paths (> 240 chars)...")
        max_len = 240
        long_paths = []

        for root, _, files in os.walk(context.os_repo_folder):
            if "\\.git" in root or "\\.claude" in root or "\\.venv" in root:
                continue
            for file in files:
                full_path = os.path.join(root, file)
                if len(full_path) > max_len:
                    long_paths.append((len(full_path), full_path))

        if long_paths:
            print("Warning: Found {} file(s) exceeding {} characters:".format(len(long_paths), max_len))
            for length, path in long_paths[:10]:
                print("  [{}] {}".format(length, path))
            if len(long_paths) > 10:
                print("  ... and {} more.".format(len(long_paths) - 10))
        else:
            print("[OK] All file paths within allowable Windows path limits.")
