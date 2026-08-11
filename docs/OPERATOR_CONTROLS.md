# Protected operator controls

The ROC dashboard provides four allowlisted administrative operations:

- orderly restart of Dire Wolf and LinBPQ;
- enter maintenance mode by stopping the RMS and modem;
- return the modem and RMS to service;
- run an authenticated, network-only CMS connectivity test.

The CMS test is blocked whenever LinBPQ reports an active RF AX.25 link. The
web API and the root-owned helper each perform the check independently, and an
unavailable or malformed LinBPQ activity response blocks the test. This avoids
opening a competing CMS session during an RF message transfer.

It also provides a privacy-safe diagnostics download. There is no RF test or
general command-execution control in the browser.

## Set or change the administrator password

SSH to the ROC, then run:

```bash
cd /home/n0jcg/sdrdev/N0JCG-ROC
sudo deploy/configure_operator_controls.sh
```

Enter a password of at least 10 characters twice. The script stores only a
PBKDF2-SHA256 password record and a random session-signing key in
`/etc/n0jcg/operator-controls.env`. The file is readable by root and the ROC
service group, not by the browser. Running the script again changes the
password and invalidates existing sessions.

## Security properties

- Administrator sessions expire after 30 minutes.
- The session cookie is `HttpOnly` and `SameSite=Strict`.
- State-changing requests require a session-bound CSRF token.
- Five failed logins in ten minutes temporarily rate-limit the source address.
- The web service has no sudo permission.
- A root-owned helper accepts only the four named operations through a local
  Unix socket.
- Operator events are recorded in
  `/var/lib/n0jcg-roc/operator-audit.jsonl` without passwords or message data.
- Diagnostics exclude credentials, environment variables, message bodies,
  subjects, and recipients.

## Recovery

If the password is lost, run the configuration script again from an SSH or
local ROC terminal. If the gateway is left in maintenance mode, the same
protected dashboard can return it online after login, or the services can be
started from the ROC terminal by an authorized system administrator.
