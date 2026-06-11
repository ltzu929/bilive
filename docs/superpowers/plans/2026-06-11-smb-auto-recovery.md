# SMB Auto Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically recover the Pi CIFS mount and `bilive.service` after the Windows SMB host returns online.

**Architecture:** A root systemd timer runs a bounded oneshot recovery script every 15 seconds. The existing recorder wrapper remains unprivileged and only waits for storage, while the recovery unit owns mount reset, stale unmount, remount, and recorder restart.

**Tech Stack:** Bash, systemd service/timer units, CIFS, pytest, SSH.

---

### Task 1: Define the recovery contract

**Files:**
- Modify: `tests/test_bilive_service.py`

- [ ] Add assertions that the deployment contains a root oneshot service and a
  15-second timer.
- [ ] Add assertions that the recovery script checks TCP 445, bounds probes with
  `timeout`, resets `mnt-win.mount`, handles stale mounts, and restarts
  `bilive.service`.
- [ ] Change wrapper expectations from 300-second to 15-second recovery.
- [ ] Run `python -m pytest tests/test_bilive_service.py -q` and confirm it fails
  because the recovery files do not yet exist.

### Task 2: Implement the root recovery units

**Files:**
- Create: `deploy/bilive-smb-recover.sh`
- Create: `deploy/bilive-smb-recover.service`
- Create: `deploy/bilive-smb-recover.timer`
- Modify: `deploy/bilive-wrapper.sh`
- Modify: `deploy/bilive.service`

- [ ] Implement a bounded healthy-mount probe for `/mnt/win/bilive`.
- [ ] Return successfully without mount churn while Windows port 445 is offline.
- [ ] Stop recording and detach an unhealthy CIFS mount before remounting.
- [ ] Run `systemctl reset-failed mnt-win.mount` and start the mount unit.
- [ ] Restart `bilive.service` only after the project path is healthy.
- [ ] Set timer cadence and recorder wait/health intervals to 15 seconds.
- [ ] Run `python -m pytest tests/test_bilive_service.py -q`.

### Task 3: Document and package deployment

**Files:**
- Create: `deploy/install-bilive-services.sh`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `D:\alldata\pi\AGENTS.md`

- [ ] Add an idempotent installer that copies scripts/units to Pi-local paths,
  reloads systemd, enables the timer, and restarts recording.
- [ ] Document that `x-systemd.automount` alone does not retry a failed mount and
  that the recovery timer owns remounting.
- [ ] Run `bash -n` for both shell scripts on Pi.

### Task 4: Verify, commit, and deploy

**Files:**
- Modify only files required by failed verification.

- [ ] Run `python -m pytest tests/test_bilive_service.py tests/test_dashboard_service.py -q`.
- [ ] Run `python -m pytest -q`.
- [ ] Run `git diff --check`.
- [ ] Commit with the existing repository identity.
- [ ] Install the scripts and units on Pi.
- [ ] Force `mnt-win.mount` into a failed/inactive state while Windows is online,
  then verify the timer restores it without a manual reset command.
- [ ] Verify `bilive.service` is active and port `2233` is listening.
- [ ] Merge into `main`, rerun focused verification, and clean the worktree.

