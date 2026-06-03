# ac-server-aws

Spin up an **Assetto Corsa dedicated server on AWS** and drive on it from
**Content Manager** — without shuffling mods around by hand and **without
opening a single port on your home network**.

Two layers:

| Layer | What it is | How often you touch it |
|-------|------------|------------------------|
| **Terraform** (`terraform/`) | Builds the cloud box: one EC2 instance, an Elastic IP, an S3 bucket, a locked-down firewall, and an SSM-managed role. **Content-agnostic.** | Once (`apply`), then rarely. |
| **`ac` CLI** (`ac/`) | A local Python tool that syncs your car/track content, builds the server config from an interactive wizard, and starts/stops/deploys — all over AWS APIs. | Every time you change the lineup. |

You **never choose cars/tracks at `terraform` time** — that's all the `ac` tool,
reconfigurable any time.

---

## How it stays out of your network's way

- **Everything your PC does is outbound** — to AWS S3/SSM and to the server's IP.
  No router port-forwarding, no inbound rules at home, for you *or* your friends.
- **No SSH / no port 22.** The box is managed entirely over **AWS Systems
  Manager** (the agent dials out to AWS). Zero inbound management surface, no SSH
  keys.
- The **only** open ports are on the cloud box's firewall — the game ports
  **9600 TCP/UDP** and **8081 TCP** — isolated from your LAN. `terraform destroy`
  removes everything.

---

## Content: what syncs where

Assetto Corsa checksums content on **both** the server and every client, but:

- **The server** only needs the small **data files** (a car's `data.acd`, a
  track's layout/surface data). `ac sync` extracts and uploads exactly those —
  tiny, and **incremental**: it hashes your content and only uploads what
  changed. Install new mods → run `ac sync` again (or just `ac deploy`) and only
  the new items go up.
- **Clients (you + friends)** must have the **full mod installed locally** for
  **just that server's lineup** — never your whole library. `ac share` lists (or
  copies) exactly what a given server needs.

---

## Prerequisites

Install these once and make sure they're on your `PATH`:

1. **[Terraform](https://developer.hashicorp.com/terraform/install)** (≥ 1.5)
2. **[AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)**,
   then `aws configure` with credentials for an account you control.
3. **[Python](https://www.python.org/downloads/)** 3.9+
4. **Assetto Corsa** installed locally (via Steam) with the mods you want.

> AWS will bill you for the EC2 instance, the Elastic IP, and a little S3. A
> `t3.medium` left on 24/7 is roughly **$30/month**; use `ac stop` between
> sessions and `terraform destroy` when done. See **Cost** below.

---

## Setup, end to end

### 1. Provision the cloud box

```powershell
cd terraform
copy terraform.tfvars.example terraform.tfvars   # optional: edit region etc.
terraform init
terraform apply
```

Note the outputs (`public_ip`, `cm_connect`, …). First boot takes a few minutes
while it installs the server software.

### 2. Install the `ac` tool

From the repo root:

```powershell
py -m pip install -e .
```

This gives you the `ac` command. (Or run it as `py -m ac` without installing.)

### 3. Point the tool at your install + cloud box

```powershell
ac init
```

Auto-detects your Steam AC folder (prompts if it can't) and reads the terraform
outputs. Saved to `.ac/state.json`.

### 4. Sync your content

```powershell
ac sync --all      # whole library's server-side files (recommended once)
# ...or just `ac sync` after you've made a server.yml, to sync only what it uses
```

### 5. Build a server (interactive)

```powershell
ac config
```

Pick **backend**, **track + layout**, **cars + grid slots**, and **sessions**
(practice / qualify / race, plus booking on vanilla). It only offers content you
actually have. Writes `server.yml` (commit it, edit it, reuse it).

### 6. Deploy

```powershell
ac deploy
```

Ensures the referenced content is on S3 (auto-syncs anything new), renders
`server_cfg.ini` + `entry_list.ini`, and restarts the chosen backend over SSM.

### 7. Join in Content Manager

`ac deploy` prints your address (e.g. `203.0.113.10:8081`). In Content Manager →
**Online → add server by IP** → paste it → **Join**. Quick health check from your
browser: `http://<ip>:8081/INFO`.

---

## Everyday use

```powershell
ac status        # EC2 + service state, what's listening
ac logs          # tail the server log (via SSM)
ac restart       # restart the active backend
ac stop          # power off to stop paying for compute (keeps IP + disk)
ac start         # power back on; it auto-refreshes content and starts the server
```

**Added new mods?** Install them in AC, then `ac config` (they now appear) →
`ac deploy`. Only the new content uploads.

**Switching session style?** e.g. an open-practice night on AssettoServer, then a
structured race on acServer — just `ac config` (change backend/sessions) →
`ac deploy`.

**Sharing with friends?**

```powershell
ac share                       # lists the exact track + cars they need
ac share --out .\for-friends   # copies the full content folders to zip & send
```

---

## Two server backends

Both read the same config; choose per server in the wizard.

- **AssettoServer** (default) — installs automatically. Best for freeroam / open
  practice / drift / AI traffic and Content Manager polish. Its Race & Qualify
  sessions are officially **experimental**.
- **Vanilla acServer** — rock-solid Race/Qualify/Booking. Its Linux binary can't
  be downloaded anonymously, so you provide it once:

  ```powershell
  # Obtain the Linux acServer (Steam "Assetto Corsa Dedicated Server", app 302550)
  aws s3 cp .\acServer s3://<your-content-bucket>/bin/acServer
  # then install it on the running box without reprovisioning:
  aws ssm send-command --instance-ids <instance-id> ^
    --document-name AWS-RunShellScript ^
    --parameters "commands=[\"aws s3 cp s3://<bucket>/bin/acServer /opt/ac/server/acServer --region <region>\",\"chmod +x /opt/ac/server/acServer\"]"
  ```

  (Your bucket/instance id are in `terraform output`.) After that the `acserver`
  backend works.

---

## Cost

- **Stop when idle:** `ac stop` halts compute billing. The Elastic IP and disk
  persist (a few cents/day) so your CM bookmark keeps working. `ac start` to
  resume.
- **Tear it all down:** `cd terraform && terraform destroy`. Removes the
  instance, IP, and bucket. Re-`apply` later to rebuild from scratch.

---

## Troubleshooting

- **`ac deploy` says the instance isn't in SSM yet** — right after `apply` or
  `ac start`, give it ~1 minute for the SSM agent to register, then retry.
- **Clients get a checksum/content error joining** — the server's minimal data
  set didn't match. Re-sync that item with the full fallback:
  `ac sync --full` (or `ac deploy` after it). This ships complete folders.
- **Server won't appear / can't connect** — confirm `ac status` shows it
  listening on 9600/8081, and that `http://<ip>:8081/INFO` responds. If you
  restricted `allowed_game_cidrs`, make sure your IP is in the list.
- **See full boot logs** — `ac logs`, or via SSM: `cat /var/log/ac-setup.log`.

---

## Testing

Three tiers, cheapest first:

```powershell
# 1. Offline + mocked-AWS unit tests (free, fast — no AWS account, no game).
#    Covers the config renderer, content/hash/manifest logic, S3 sync,
#    EC2 start/stop, and the SSM layer (mocked with moto + a fake client).
pwsh ./scripts/test.ps1

# 2. Terraform static checks (free — fmt + validate, no AWS touched).
pwsh ./scripts/check-terraform.ps1

# 3. Real deploy smoke test (~a few cents, needs AWS creds; no game needed).
#    apply -> verify the box boots, registers with SSM, and installs the
#    server -> ALWAYS destroys afterward.
pwsh ./scripts/smoke-test.ps1
```

(Bash equivalents: `scripts/smoke-test.sh`. Tiers 1–2 need real Python/Terraform
installed; the Windows Store Python stub won't work.)

What each tier can and can't prove:
- **Tiers 1–2** catch the vast majority of logic/config regressions.
- **Tier 3** proves the infrastructure really boots and self-installs. It checks
  *infra health*, not a live race — a running `/INFO` endpoint needs `ac deploy`
  with real content, which is the manual step.
- **Actually driving on it** (joining from Content Manager) is the final manual
  check only you can do.

## Layout

```
terraform/   # infra: EC2, EIP, S3, SG (game ports only), SSM role, user_data.sh
ac/          # Python CLI: cli, content, awsio, render, remote, wizard, state
tests/       # pytest suite (offline + moto-mocked AWS)
scripts/     # test.ps1, check-terraform.ps1, smoke-test.ps1 / .sh
examples/    # server.example.yml
server-config/  # notes on AssettoServer's auto-generated extra_cfg.yml
```

## Status / known limits

- Minimal-file content sync mirrors Content Manager's "Pack"; if a particular mod
  checksums differently, `--full` is the escape hatch.
- AssettoServer Race/Qualify are upstream-experimental — use acServer for serious
  races.
- Advanced AssettoServer features (AI traffic, dynamic weather) are left to its
  auto-generated `extra_cfg.yml` for now (see `server-config/`).
