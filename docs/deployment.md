# Deploy the dual-WAN lab

The commands below are a lab runbook. Version 0.1.1 has a
[recorded EVE-NG Professional 7.2.0-4 / IOSv 15.9(3)M6 run](live-validation.md).
Other combinations require their own validation; see [validation.md](validation.md).

## 1. Prepare an isolated environment

Use a dedicated EVE-NG lab host with a licensed IOSv L3 image installed under
`/opt/unetlab/addons/qemu/vios-<your-version>/virtioa.qcow2`. Confirm the `vios`
template maps its four adapters to Gi0/0 through Gi0/3.

Configure an isolated management bridge, such as `pnet1`, and attach your Ansible
controller to the same subnet. Bridge existence does not prove isolation: verify
the hypervisor and physical uplink configuration yourself. The tool does not create
or reconfigure host bridges. Do not attach the synthetic management network to a
production VLAN. No management gateway or external route is configured by this version.

## 2. Customize and compile

```bash
cp examples/dual-wan.yml dual-wan.local.yml
```

Edit `image`, `management.network`, `management.bridge` and every node's
`management_ip`. Use a unique `name` for each deployed instance; the lab UUID derives
from that name. Addresses in the committed example are synthetic documentation and
benchmarking addresses, not a discovery of your infrastructure.

```bash
nlf validate dual-wan.local.yml
nlf build dual-wan.local.yml --output build/my-dual-wan
cp ansible/eve-host.example.yml eve-host.local.yml
```

Set your EVE host address and SSH user in `eve-host.local.yml`. Use SSH keys and
verify its host key. Ansible's host-key checking remains enabled.

## 3. Provision with Ansible

Install the dependencies described in the README. From the repository root:

```bash
ansible-playbook -i eve-host.local.yml ansible/provision.yml \
  -e "build_dir=$PWD/build/my-dual-wan" --check

ansible-playbook -i eve-host.local.yml ansible/provision.yml \
  -e "build_dir=$PWD/build/my-dual-wan"
```

The playbook checks the topology hash, installed image and management bridge before
copying the `.unl` into `/opt/unetlab/labs/`. It expects the normal EVE `www-data`
ownership. Existing lab names are rejected, even if the file appears identical.
Choose another scenario name for another instance. A check-mode run does not prove
that the emulator will import or boot successfully.

Alternatively, package the `.unl` in a ZIP and import it with EVE's browser interface
if your version supports that workflow. Verify the four routers and all links before boot.
The generated `.unl` intentionally contains no startup credentials or image binaries.

## 4. Start and bootstrap

Open the new lab in EVE-NG and start the routers. Wait for IOS to finish booting;
decline the initial configuration dialog if it appears.

Generate local console snippets. The password prompt is hidden and credentials are
not passed as command arguments:

```bash
nlf bootstrap dual-wan.local.yml
```

This writes `secrets/bootstrap/<router>.txt` with directory mode 0700 and file mode
0600. **These snippets contain the password in plaintext**, even though IOS stores
it as a secret after applying the configuration. They are excluded from Git. Paste
each snippet into that router's EVE console, then remove the snippets when done.
Use a dedicated lab credential of 12–25 supported characters, never a reused production
password. The upper bound matches the tested IOSv `username ... secret 0` command.
RSA key generation
is intended for fresh routers, not routers with existing keys or production configuration.

Set runtime credentials in the current shell without entering the password into
shell history (these examples use Bash):

```bash
read -r -p 'Lab username: ' LAB_USERNAME
read -r -s -p 'Lab password: ' LAB_PASSWORD
echo
export LAB_USERNAME LAB_PASSWORD
```

The bootstrap account is privilege 15; no separate enable secret is needed for this lab.
Connect to each management address with SSH once, inspect/verify its fingerprint,
and add it to your controller's known-hosts file. Ansible will not silently accept new
device keys. Environment variables are a simple local lab mechanism, not an enterprise
secrets-management solution.

## 5. Configure the data plane

```bash
ansible-playbook -i build/my-dual-wan/inventory.yml ansible/configure.yml --check --diff
ansible-playbook -i build/my-dual-wan/inventory.yml ansible/configure.yml
```

Check mode needs real device connectivity and is not proof of forwarding behavior.
The playbook does not modify Gi0/0. It creates Loopback0 and configures point-to-point
interfaces, OSPF process 1, router IDs, costs and passive defaults. Use only fresh,
dedicated IOSv routers. Changing router IDs in an established OSPF process may need
manual process restart; the playbook does not perform one automatically.

For a fixed design, rerun configure and inspect the change summary. The recorded
IOSv 15.9(3)M6 run reported zero changes on all four routers. If the scenario changes, create
a fresh lab; additive configuration does not remove old interface or OSPF settings.

## 6. Collect live evidence

After OSPF converges:

```bash
nlf verify build/my-dual-wan
```

Reports are saved under `reports/<unique-run>/`. Read `report.md` or `report.json`.
Raw per-router JSON accompanies the report. This contains lab operational information;
review it before sharing. A nonzero exit is intentional when any evidence is absent
or any check fails. ICMP loss during startup can be real transient loss: inspect it,
wait for the network to settle, and create a new run rather than editing an old report.

## 7. Recover and clean up

If you performed the [failover exercise](failover.md), restore its interface before
ending the session. Stop and delete only this dedicated lab through EVE-NG's interface.
No automated destroy command is provided in v0.1. Remove private snippets and unset
the runtime credentials when finished:

```bash
unset LAB_USERNAME LAB_PASSWORD
```

## References

- [EVE-NG documentation](https://www.eve-ng.net/index.php/documentation/)
- [Ansible Cisco IOS collection](https://docs.ansible.com/projects/ansible/latest/collections/cisco/ios/)
- [Ansible network connections](https://docs.ansible.com/projects/ansible/latest/network/getting_started/network_connection_options.html)
