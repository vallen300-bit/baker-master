# SSH Hardening — Mac Mini (Director's Procedure)

**Purpose:** apply `briefs/_drafts/200-hardening.conf` to `macmini` safely.
**Reference:** DECISIONS_PRE_KBL_A_V2_DRAFT.md R1.18, D4 (R3 Task A blocked on sudo).
**Reviewer:** Code Brisen #2 — procedure tested as far as sudo-free verification allows (pubkey auth, current sshd_config state, drop-in include order).
**Risk:** if pubkey auth is broken at reload time, Director loses SSH to Mac Mini. Mitigated by the 3-session safety pattern below. Physical keyboard/mouse at the Mac Mini is the ultimate rollback.

---

## Pre-flight (30 seconds)

Confirm current state. From your workstation:

```bash
ssh -o BatchMode=yes macmini 'echo ok'
```

- **Expected:** prints `ok`. BatchMode disables password prompts, so success here proves pubkey auth already works — the only prerequisite for the hardening to be safe.
- **If this fails** with `Permission denied (publickey)`: STOP. Fix pubkey auth first (you'd otherwise lock yourself out the moment you reload sshd). Not in scope of this procedure.

---

## Step 1 — Stage the drop-in (no reload yet)

From your workstation:

```bash
scp "/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/briefs/_drafts/200-hardening.conf" \
    macmini:/tmp/200-hardening.conf
```

SSH in and install the file to the drop-in directory:

```bash
ssh macmini
```

Then on the Mac Mini (you'll be prompted for your sudo password — this is the only step that needs it):

```bash
sudo cp /tmp/200-hardening.conf /etc/ssh/sshd_config.d/200-hardening.conf
sudo chown root:wheel /etc/ssh/sshd_config.d/200-hardening.conf
sudo chmod 0644       /etc/ssh/sshd_config.d/200-hardening.conf
ls -la /etc/ssh/sshd_config.d/
```

**Expected listing:**
```
-rw-r--r--  1 root  wheel  ...  100-macos.conf
-rw-r--r--  1 root  wheel  ...  200-hardening.conf
```

---

## Step 2 — Validate config BEFORE reloading

Still in the SSH session on Mac Mini:

```bash
sudo /usr/sbin/sshd -t
```

- **Expected:** no output (silent success). Exit code 0.
- **If it prints a parse error:** STOP. Do **not** proceed to Step 3. Remove the file: `sudo rm /etc/ssh/sshd_config.d/200-hardening.conf`. Report the error verbatim to AI Head / Code Brisen #2.

---

## Step 3 — Open a SECOND parallel SSH session (safety net)

From a **different terminal window** on your workstation:

```bash
ssh macmini
```

Leave it open and logged in. Verify with `whoami`. **Do not close this session** until Step 5 confirms success.

This second session is your escape hatch: if the reload breaks new logins, you still have this existing session open and can revert. sshd does not drop already-established sessions when reloading.

---

## Step 4 — Reload sshd

In your ORIGINAL SSH session (the one where you staged the file in Step 1), run:

```bash
sudo launchctl kickstart -k system/com.openssh.sshd
```

- `kickstart -k` stops and restarts the sshd launchd service.
- No output on success.

---

## Step 5 — Verify from a THIRD fresh SSH connection

Open a **third terminal window** on your workstation and run:

```bash
ssh -o BatchMode=yes macmini 'echo HARDENED_OK && id && sudo -n true 2>&1 | head -1'
```

**Expected:**
```
HARDENED_OK
uid=501(dimitry) gid=20(staff) groups=...
sudo: a password is required    <-- harmless; just proves we didn't break anything
```

- **If this succeeds:** the hardening is live and you can still log in. Proceed to Step 6.
- **If it fails** with `Permission denied` or connection drops: the hardening broke login. Go to the **Rollback** section below — your Step 3 session is still valid.

---

## Step 6 — Confirm the hardening took effect

From the third session (or any working session):

```bash
# None of these should currently be possible anyway, but this proves the
# settings are loaded:
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no macmini 'echo should_not_print' 2>&1 | head -3
```

**Expected:**
```
dimitry@macmini: Permission denied (publickey).
```

This proves `PasswordAuthentication no` is live — the server now refuses to even try password auth.

Also verify the AllowUsers rule doesn't accidentally block you:

```bash
ssh -o BatchMode=yes macmini 'echo still_ok'
```

Expected: prints `still_ok`.

---

## Step 7 — Close the safety-net session

You can now close the parallel SSH session from Step 3. Done.

---

## Rollback

If Step 5 fails, use your still-open Step-3 session to revert:

```bash
sudo rm /etc/ssh/sshd_config.d/200-hardening.conf
sudo launchctl kickstart -k system/com.openssh.sshd
```

Then retry a fresh `ssh macmini` from a new terminal. This restores the
prior (macOS default) sshd configuration.

If your Step-3 session was also closed and you're locked out, you need
physical access: connect keyboard + monitor to the Mac Mini, log in
locally, and remove the file with the same two commands above.

---

## Post-hardening checklist

- [ ] `ssh -o BatchMode=yes macmini 'echo ok'` still works
- [ ] Password-fallback test refuses: `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no macmini` → Permission denied (publickey)
- [ ] `sudo -n` still prompts for password (sudo not affected by SSH hardening; rotating to passwordless sudo is a separate decision, see D4 — NOT in scope here)
- [ ] (Optional, for audit) Note the commit SHA of this procedure file so the applied configuration is traceable

---

## What this procedure explicitly does NOT change

- Sudo password requirement (unchanged — you'll still be prompted for sudo)
- Tailscale ACLs (unchanged — out of scope)
- The main `/etc/ssh/sshd_config` file (unchanged — drop-in pattern preserves upstream macOS defaults)
- `100-macos.conf` (unchanged — `UsePAM yes` stays, but `KbdInteractiveAuthentication no` in the new drop-in overrides PAM's password prompt path)

---

**Estimated Director time:** 5–8 minutes total (3 minutes if everything works first try).
