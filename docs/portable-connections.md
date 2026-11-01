# Portable connections and session credentials

**Preview release: 0.3.0rc2.** The owner approved automated validation with real-lab testing deferred. This preview also includes the [existing-lab addressing assistant](existing-labs.md).

The assistant accepts SSH credentials for EVE-NG and GNS3, plus the separate GNS3 API account. The default new GNS3 connection discovers API v2/v3 and uses the target server's existing templates. It does not require Nexo paths or its administrator credential file.

## What “compatible” means

| Component | Required capability |
| --- | --- |
| GNS3 API | 2.2.x / v2 or 3.x / v3; version and endpoints checked, not just an exact release string |
| Target | Linux server or GNS3 VM; controller and connected `local` compute on this SSH target |
| Remote tools | Python 3, pexpect, telnet; readable RAM information and projects filesystem |
| Appliances | Existing QEMU or VPCS templates, Telnet console, no custom adapter overrides or QEMU options that add external networks/consoles |
| OS family | Must match the recipe's IOSv, IOSvL2, CSR, NX-OS or ASA CLI and interface numbering |
| Storage | Existing absolute projects directory; disk/BIOS images available through the compute API |
| Resources | Selected templates' RAM plus 1 GiB headroom; disk and adapter count checked before creation |

Windows/macOS users may connect to a compatible Linux GNS3 VM; a native Windows compute, a remote/distributed compute, Docker/IOU/Dynamips templates and VNC consoles are not implemented by this transport. The interactive console bridge currently requires a POSIX terminal. A server version in the allowed family does **not** certify every template or image release.

## Configure in six steps

1. Run `nlf wizard`, select **GNS3 · installed templates**.
2. Enter **SSH server**, **User**, and the masked **SSH password**. Blank password uses existing OpenSSH keys/configuration. Set a nonstandard port under **SSH options** if needed.
3. Enter **API username** and masked **API password**. These are GNS3 account credentials, not Linux credentials. API v2 without authentication accepts empty fields; v3 requires credentials.
4. Under **API and storage options**, use the server's API origin, normally `http://127.0.0.1:3080`. Loopback is interpreted on the SSH server. The computer-to-server link is SSH. HTTPS must address the same SSH hostname and uses the SSH server's system CA trust; redirects and insecure certificate overrides are unavailable. The URL must not contain a password, query, fragment or `/v2`/`/v3` suffix.
5. Choose **Check connection**. If the projects directory cannot be discovered (older API or limited `/settings` permission), enter the actual existing directory from your GNS3 server configuration. No default Nexo path is assumed.
6. Select the scenario, then explicitly review the template assigned to every OS family. Template names are convenience suggestions, not compatibility checks. Review the actual memory requirement, destination and topology before typing `DEPLOY`.

A new SSH server must be enrolled in the user's existing `~/.ssh/known_hosts` first. Use OpenSSH with the same host/user/port, verify the displayed fingerprint against the administrator's trusted value, then return to the assistant. NLF never auto-accepts a host key. A changed key requires independent investigation; do not disable host checking.

API v2 uses HTTP Basic authentication inside the SSH-protected server link (or verified HTTPS); v3 authenticates for a bearer token. Auto detection falls back to v2 only when the v3 version endpoint returns 404. On a proxy with unusual routes, select the known API version explicitly.

## Secret lifecycle

- Password fields are masked. Plain mode uses `getpass`; passwords are not command-line flags or environment variables.
- Password SSH uses Paramiko with reject-unknown-host policy. A password is not forwarded to OpenSSH or an `sshpass` process.
- API credentials travel in the encrypted SSH worker's standard input, not its command arguments. No remote credentials file is created by the portable connector.
- Secrets and API tokens exist in process memory for the session. Python cannot promise secure memory erasure; process exit releases the session. Core dumps, a compromised host or an untrusted template/server are outside this protection boundary.
- Saved connection data includes address, user, API origin/version, project path and template IDs/fingerprints. It excludes passwords and tokens. Reopening requests the secrets again.
- HTTP response bodies are not copied into errors; mutation requests are never automatically retried. Credential strings are redacted from returned worker events.
- Existing laboratory evidence can include configurations and console output. Review it before sharing; this feature is not a general-purpose data anonymizer.

No users, keys, permission grants, firewall rules or public console listeners are added. Existing templates are read, not modified. Each new project uses its own identity; subsequent actions check both its path and node composition.

## Recovery

| Symptom | Action |
| --- | --- |
| SSH authentication failed | Check Linux account/password and port, or leave the field blank for a configured key. |
| Unknown or changed host key | Verify the server fingerprint through the normal SSH trust procedure. |
| HTTP 401 / 403 | Check the GNS3 account and its permission to read templates and create projects. |
| API response could not be verified | Check API origin, port, TLS trust and selected API version. Do not disable verification. |
| Projects directory needed | Enter GNS3's configured directory on the SSH target. |
| No usable templates | Install/import compatible appliances in GNS3 first; this tool does not distribute images. |
| Missing image, adapters or resources | Correct the selected template in GNS3 or select another, then reconnect and review. |
| Template changed after review | Reconnect, select templates and review again before deployment. |
| Interrupted creation | Preserve the evidence, inspect the owned project, and reauthenticate to check it. Never assume rollback or retry creation over it. |

## Validation status

Automated tests cover v2/v3 negotiation, authentication, redirect rejection, missing/changed templates, image checks, SSH host-key and password failures, masked UI input, template selection, and reauthentication without deployment. Tests use synthetic accounts and simulated APIs; they are not native GNS3 screenshots or proof of appliance boot success.

The historical 24-scenario EVE/GNS3 campaign remains valid for its documented legacy profiles. The new portable transport needs a fresh real-server campaign; the prior authorized EVE endpoint was unreachable during this change. No historical result is relabeled as a portable-connector test.

API references: [GNS3 v2 controller API](https://api.gns3.net/en/stable/general.html), [v2 node templates](https://api.gns3.net/en/stable/api/v2/controller/template/projectsprojectidtemplatestemplateid.html), [official GNS3 v3 OpenAPI](https://apiv3.gns3.net/).
