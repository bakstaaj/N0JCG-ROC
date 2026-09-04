# Winlink application event logging

The ROC enables LinBPQ application events and installs two handlers in the
LinBPQ working directory:

- `MailNewMsg` records a new-mail event.
- `MailMsgRead` records a message-read event.

Handlers write privacy-safe JSON Lines to
`/var/lib/n0jcg-roc/winlink-application-events.jsonl`. Each record contains a
UTC timestamp, event type, source, argument count, and a numeric message ID
only when LinBPQ supplies one as the first argument. Subject, body, recipients,
passwords, and all other event arguments are intentionally discarded.

The ROC `/api/winlink` status includes aggregate event counts and the last
event. These are application-level observations, not RF reception proof and
are not assigned to a particular KISS session.

After deployment, regenerate the runtime BPQ configuration with
`deploy/configure_winlink_rms.sh`, restart LinBPQ, and verify:

```sh
sudo systemctl restart n0jcg-winlink-rms.service
sudo tail -f /var/lib/n0jcg-roc/winlink-application-events.jsonl
```
