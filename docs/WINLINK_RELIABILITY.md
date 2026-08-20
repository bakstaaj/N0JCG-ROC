# Winlink reliability controls

The ROC reliability layer observes standard LinBPQ, Dire Wolf, AX.25, KISS,
and Winlink protocol events. It never synthesizes or rewrites Winlink frames.

## Protocol phases

The dashboard reports the last observed phase: AX.25 connection, CMS session,
secure login, mailbox request, proposal generation (`PM`/`FC`), mailbox index
(`F>`), client acknowledgement (`FS`), and transfer.

## Watchdog

`n0jcg-winlink-watchdog.service` writes privacy-safe state to
`/var/lib/n0jcg-roc/winlink-protocol-health.json`. It records phase, age,
stale status, finding, and next action; it does not retain mailbox contents or
credentials. Automatic recovery is disabled by default. If an operator later
enables `WINLINK_AUTO_RECOVER=1`, only the RMS service is restarted after a
stale phase; the modem and its RF configuration are not changed.

For a controlled one-session trace, run `sudo tools/capture_winlink_kiss.sh`.
It captures both directions on port 8010 for ten minutes and retains the ten
newest files under `/var/lib/n0jcg-winlink/diagnostics/`.

## Protected recovery

After confirming the RF channel is clear, an authenticated operator may use
**Recover stalled RMS session**. The helper refuses recovery while an RF
session is active, stops LinBPQ RMS, waits five seconds for the channel to
clear, and starts RMS again. Dire Wolf and the modem are left running.

## Evidence interpretation

- `PM`/`FC` without `F>`: mailbox index generation or delivery before KISS.
- `F>` without `FS`: client receive/acknowledgement path.
- No `PM`/`FC` after CMS: LinBPQ session/application state before proposal
  generation.
- RF modem frames without LinBPQ session counters: investigate AX.25 session
  ownership or stale state; do not change PAT framing first.
