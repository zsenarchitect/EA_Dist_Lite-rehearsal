# -*- coding: utf-8 -*-
"""Stage 02: Build Assets & Exe Product Mirroring."""

import hashlib
import json
import os
import shutil
from ..stage_base import PublishStage, PublishStageError


class BuildAssetsStage(PublishStage):
    """Build assets stage: mirrors service-factory installers and computes exe hashes."""

    @property
    def name(self):
        return "Build Assets & Installer Mirroring"

    @property
    def description(self):
        return "Mirrors service-factory installers and generates exe integrity hashes."

    def execute(self, context):
        self._mirror_service_factory_installers(context)
        self._generate_exe_hashes(context)

    def _mirror_service_factory_installers(self, context):
        """Mirror installer executables from Installation/ to ExeProducts/."""
        print("Mirroring service-factory installers...")
        installation_dir = os.path.join(context.os_repo_folder, "Installation")
        exe_products_dir = os.path.join(context.os_repo_folder, "Apps", "lib", "ExeProducts")

        if not os.path.isdir(installation_dir) or not os.path.isdir(exe_products_dir):
            print("Notice: Installation or ExeProducts directory missing, skipping installer mirror.")
            return

        copied = 0
        for item in os.listdir(installation_dir):
            if item.lower().endswith(".exe") and "installer" in item.lower():
                src = os.path.join(installation_dir, item)
                dest = os.path.join(exe_products_dir, item)
                try:
                    shutil.copy2(src, dest)
                    copied += 1
                except Exception as e:
                    raise PublishStageError(
                        "Failed to mirror installer {} to ExeProducts: {}".format(item, e)
                    )

        print("[OK] Mirrored {} service-factory installer(s) to ExeProducts.".format(copied))

    def _generate_exe_hashes(self, context):
        """Generate SHA-256 integrity hash json for executable products."""
        print("Generating executable SHA-256 integrity hashes...")
        exe_folder = os.path.join(context.os_repo_folder, "Apps", "lib", "ExeProducts")
        output_file = os.path.join(context.os_repo_folder, "Installation", "exe_hash.json")

        if not os.path.isdir(exe_folder):
            print("ExeProducts folder missing, skipping hash generation.")
            return

        hashes = {}
        for file in sorted(os.listdir(exe_folder)):
            if file.lower().endswith(".exe"):
                path = os.path.join(exe_folder, file)
                try:
                    hasher = hashlib.sha256()
                    with open(path, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            hasher.update(chunk)
                    hashes[file] = hasher.hexdigest()
                except Exception as e:
                    raise PublishStageError("Failed to hash executable {}: {}".format(file, e))

        try:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "w") as f:
                json.dump(hashes, f, indent=4, sort_keys=True)
            print("[OK] Executable hashes written to {} ({} exes hashed).".format(
                os.path.basename(output_file), len(hashes)))
        except Exception as e:
            raise PublishStageError("Failed to write exe_hash.json: {}".format(e))
