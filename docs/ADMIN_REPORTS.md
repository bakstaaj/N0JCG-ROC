# Operator operations reports

The ROC can email a periodic, privacy-safe operations summary. The sender is
fixed as `ROC@n0jcg.com`. An authenticated operator chooses the recipient,
enables or disables reports, and sets an interval from 1 through 168 hours in
the dashboard **Configuration** panel.

Each report summarizes the preceding configured interval for APRS and Winlink.
It also includes a current ROC resource, weather-gateway, and connected-
application snapshot. Message bodies, subjects, message recipients, APRS-IS
passcodes, CMS passwords, Cloudflare credentials, and environment variables
are excluded.

## Cloudflare Email Sending credentials

The feature uses the Cloudflare Email Sending REST API. Onboard `n0jcg.com` for
Email Sending and create a narrowly scoped API token with permission to send
email. Install the Cloudflare account ID and API token from a ROC terminal:

```bash
cd /home/n0jcg/sdrdev/N0JCG-ROC
sudo deploy/configure_admin_report_email.sh --check-only
sudo deploy/configure_admin_report_email.sh
```

The installer writes `/etc/n0jcg/admin-report.env` as root with mode `0600`.
Do not put credentials in the repository, dashboard, browser storage, or a
command-line argument. For noninteractive appliance provisioning, the script
accepts `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` as transient
environment variables.

## Schedule and runtime state

The `n0jcg-admin-report.service` worker checks the schedule once per minute.
Enabling reports or changing the interval starts a new full interval; it does
not immediately send a partial report. A failed send is retried after 15
minutes. Settings and delivery state are stored separately under
`/var/lib/n0jcg-roc/`.

Useful checks:

```bash
systemctl status n0jcg-admin-report.service --no-pager
journalctl -u n0jcg-admin-report.service -n 50 --no-pager
sudo deploy/configure_admin_report_email.sh --check-only
```

The dashboard exposes report settings only to an authenticated operator
session and never returns the Cloudflare account ID or API token.
