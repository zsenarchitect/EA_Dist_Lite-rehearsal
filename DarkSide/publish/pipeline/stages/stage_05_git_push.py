# -*- coding: utf-8 -*-
"""Stage 05: Git Commit, Push, & Remote Verification."""

import os
import subprocess
import time
from ..stage_base import PublishStage, PublishStageError


class GitPushStage(PublishStage):
    """Git push stage: commits staged dist content, force-pushes dist repos, and asserts origin/main parity via ls-remote."""

    @property
    def name(self):
        return "Git Push & Remote Verification"

    @property
    def description(self):
        return "Commits staged content, force-pushes dist repos, and confirms origin/main via ls-remote."

    def execute(self, context):
        # Returns a DEGRADED reason (or None). See _verify_remote_ref: a push that landed
        # but could not be READ BACK is unconfirmed, not failed.
        return self._push_distribution_repos(context)

    def _push_distribution_repos(self, context):
        """Commit staged files, force push EA_Dist and EA_Dist_Lite to origin main, and verify via ls-remote."""
        dist_repos = [
            (context.dist_folder, "EA_Dist"),
            (context.dist_lite_folder, "EA_Dist_Lite"),
        ]

        # Targets whose push exited 0 but whose origin/main could not be read back.
        unverified = []
        # Targets where THIS run produced no new commit, so local HEAD never moved and
        # the force-push below can only re-assert what origin already has. Without this
        # the run printed "[OK] ... successfully advanced" and exited green while the
        # fleet received nothing (senzhang-todo #2836). Not raised: an empty commit is a
        # protected benign case (tools/check_publish_never_silent_on_failure.py 3b) --
        # but it must never be reported as an advance, so it degrades loudly instead.
        not_advanced = []
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        for repo_folder, label in dist_repos:
            if not os.path.isdir(repo_folder):
                raise PublishStageError("Distribution directory missing for {}: {}".format(label, repo_folder))

            print("\nCommitting staged changes in {} ({})".format(label, repo_folder))

            # HEAD before this run's commit, so "did the distribution advance" is
            # measured, not inferred from the commit/push exit codes. None on a repo
            # with no commits yet (any commit then counts as an advance).
            pre_head = self._read_head(context.git_exe, repo_folder)

            # Stage all changes in dist repo
            try:
                subprocess.run(
                    [context.git_exe, "add", "-A"],
                    cwd=repo_folder,
                    check=True,
                    capture_output=True,
                )
            except Exception as e:
                raise PublishStageError("git add failed in {}: {}".format(label, e))

            # Commit staged changes
            commit_msg = "Publish EnneadTab-OS distribution at {}".format(timestamp)
            commit_res = subprocess.run(
                [context.git_exe, "commit", "-m", commit_msg],
                cwd=repo_folder,
                capture_output=True,
                text=True,
            )
            if commit_res.returncode == 0:
                print("    Committed distribution updates in {}".format(label))
            elif "nothing to commit" in (commit_res.stdout or ""):
                # The ONLY known-benign non-zero exit: git itself reports there was
                # nothing staged, in this exact phrase on stdout. Checked by TEXT, not
                # by rc alone -- rc=1 is also what many pre-commit hooks return on
                # REJECTION (index.lock held, bad identity, corrupt object are typically
                # 128, but a hook's own exit code is whatever the hook chose). Blindly
                # trusting "rc != 0 -> nothing to commit" was senzhang-todo #4703: a
                # genuine commit failure printed this same benign line, fell through to
                # force-push the PREVIOUS HEAD, and the verify-landed check then
                # confirmed that SAME old HEAD -- green run, distribution never advanced.
                print("    No new changes to commit in {}".format(label))
            else:
                # A real failure. Raising here (not degrading) is deliberate and matches
                # this function's own pattern: every failure BEFORE the force-push
                # already raises (missing dir, `git add` failure); DEGRADE is reserved
                # for the unreadable-remote case AFTER the push has already landed. A
                # failed commit means the distribution definitely did NOT advance --
                # that is knowable here, not merely unconfirmed, so it gets the loud
                # path. Deliberately NOT adding --no-verify to this commit (unlike the
                # push at :77) -- if a hook is genuinely rejecting, surfacing that is the
                # fix; silently forcing past hooks is a separate, more debatable policy
                # change this item does not make.
                detail = (commit_res.stderr or commit_res.stdout or "").strip()
                raise PublishStageError(
                    "git commit failed in {} (exit {}): {}".format(
                        label, commit_res.returncode, detail[:500] or "no output"))

            # Read local HEAD SHA
            try:
                head_sha = subprocess.check_output(
                    [context.git_exe, "rev-parse", "HEAD"], cwd=repo_folder, text=True
                ).strip()
            except Exception as e:
                raise PublishStageError("Failed to read local HEAD in {}: {}".format(label, e))

            # Force push
            print("Force pushing {} to origin main...".format(label))
            push_cmd = [context.git_exe, "push", "-f", "--no-verify", "--progress", "origin", "main"]
            try:
                push_res = subprocess.run(
                    push_cmd, capture_output=True, text=True, cwd=repo_folder, timeout=300
                )
                if push_res.returncode != 0:
                    print(push_res.stderr)
                    raise PublishStageError(
                        "git push failed for {} with exit code {}".format(label, push_res.returncode)
                    )
            except subprocess.TimeoutExpired:
                raise PublishStageError("git push for {} timed out after 300 seconds".format(label))
            except Exception as e:
                raise PublishStageError("git push for {} failed: {}".format(label, e))

            # Verify remote advanced using git ls-remote (never trust push exit code alone)
            print("Verifying {} origin/main ref via ls-remote...".format(label))
            landed, verified, reason = self._verify_remote_ref(
                context.git_exe, repo_folder, head_sha)

            if not landed and verified:
                # We READ the remote and it disagrees. That is a real failure and it is
                # worth halting on: the distribution did not advance.
                raise PublishStageError(
                    "Remote verification FAILED for {}: {}".format(label, reason))

            if not landed:
                # We could not read the remote. The push itself already exited 0, so the
                # distribution has most likely shipped -- asserting the opposite would be
                # a lie, and halting here would skip stage_06's rollback tags on a publish
                # that probably succeeded. Degrade loudly instead: the operator is told,
                # in the summary and on the phone, that this one is UNCONFIRMED.
                print("Warning: {} could not be verified: {}".format(label, reason))
                unverified.append("{}: {}".format(label, reason))
                continue

            if pre_head is not None and pre_head.lower() == head_sha.lower():
                print("Warning: {} HEAD did NOT move ({}) -- this run committed nothing, "
                      "so origin/main matches only because it already had this commit. "
                      "No new content shipped to the fleet from {}.".format(
                          label, head_sha[:10], label))
                not_advanced.append("{}: HEAD unchanged at {}".format(label, head_sha[:10]))
                continue

            print("[OK] Verified {} origin/main successfully advanced to {}".format(label, head_sha[:10]))

        reasons = []
        if unverified:
            reasons.append(
                "push reported success but origin/main could not be READ back for "
                "{} target(s), so the publish is UNCONFIRMED, not failed -- {}".format(
                    len(unverified), "; ".join(unverified)))
        if not_advanced:
            reasons.append(
                "NOTHING SHIPPED for {} target(s): no new commit was made, so the "
                "distribution did NOT advance -- {}".format(
                    len(not_advanced), "; ".join(not_advanced)))
        if reasons:
            return " | ".join(reasons)

    @staticmethod
    def _read_head(git_exe, repo_folder):
        """Return the current HEAD sha, or None when the repo has no commits yet."""
        res = subprocess.run(
            [git_exe, "rev-parse", "--verify", "-q", "HEAD"],
            cwd=repo_folder, capture_output=True, text=True,
        )
        if res.returncode != 0:
            return None
        return (res.stdout or "").strip() or None

    def _verify_remote_ref(self, git_exe, repo_folder, expected_sha, attempts=3):
        """Confirm origin/main matches expected_sha. Returns (landed, verified, reason).

        THREE outcomes, not two. This used to return a bare False for every unhappy
        path -- a genuine SHA mismatch, an empty listing, a 30s timeout, a network
        error, a GitHub HTTP 500 -- and the caller rendered all of them as the definite
        claim "origin/main does not equal local HEAD". That is absence of evidence
        reported as evidence of absence, and it is not a cosmetic problem here:

          * the check runs AFTER the force-push has already landed, so a transient blip
            reported a publish that DID ship to ~50 machines as a failure
          * that halts the pipeline, so stage_06 never writes the rollback tags
          * and it invites the operator to roll back a good publish

        This repo has documented intermittent GitHub HTTP 500s (see CLAUDE.md -- 2.26 GB,
        server-side receive timeouts), which is exactly the transient being collapsed.

        The dead RepoPublisher._verify_push_landed already had the correct three-way
        logic; this is that logic ported to the live pipeline. The invariant used to be
        enforced only on that dead copy while the live path violated it; it is now pinned
        here by tools/check_live_push_landing.py, and the dead copy is gone.
        senzhang-todo #4701.
        """
        last_reason = "COULD NOT VERIFY: no attempt produced a readable answer"
        for attempt in range(1, attempts + 1):
            # Space the retries. The transient this exists for is an intermittent GitHub
            # HTTP 500, which fails FAST -- so back-to-back retries would all land inside
            # the same blip and buy nothing the docstring claims. Only the timeout path
            # gets natural spacing. Short and bounded: a persistent outage must still
            # surface as COULD NOT VERIFY rather than being waited out.
            if attempt > 1:
                time.sleep(2 * (attempt - 1))
            try:
                listing = subprocess.run(
                    [git_exe, "ls-remote", "origin", "refs/heads/main"],
                    cwd=repo_folder, capture_output=True, text=True, timeout=60,
                )
            except subprocess.TimeoutExpired:
                last_reason = ("COULD NOT VERIFY: git ls-remote timed out after 60s "
                               "(attempt {}/{})".format(attempt, attempts))
                continue
            except Exception as exc:
                last_reason = "COULD NOT VERIFY: git ls-remote failed: {}".format(exc)
                continue

            if listing.returncode != 0:
                last_reason = ("COULD NOT VERIFY: git ls-remote exited {} (attempt {}/{}): "
                               "{}".format(listing.returncode, attempt, attempts,
                                           (listing.stderr or "").strip()[:300]))
                continue

            output = (listing.stdout or "").strip()
            if not output:
                # An empty listing is a READ that succeeded and found nothing. After a
                # push that is a real failure, not an unreadable channel.
                return False, True, ("VERIFIED NOT LANDED: origin has no refs/heads/main "
                                     "after pushing {}".format(expected_sha[:12]))

            remote_sha = output.split()[0].strip()
            if remote_sha.lower() != expected_sha.lower():
                return False, True, ("VERIFIED NOT LANDED: origin/main is {} but pushed "
                                     "HEAD is {}".format(remote_sha[:12], expected_sha[:12]))
            return True, True, ""

        return False, False, last_reason
