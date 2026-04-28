# Eiswein — AWS Spot Deployment Design

> **Status**: Designed, not implemented. Captured 2026-04-28 for future use.
> Pair with [`DEPLOYMENT_CONTEXT.md`](DEPLOYMENT_CONTEXT.md), which holds the broader app/architecture context to feed into any deployment LLM.

This document is the architectural blueprint for deploying Eiswein to a single AWS Spot EC2 instance via CloudFormation, mirroring (and drastically simplifying) the operational ergonomics of `/Users/cheyulin/Adam/ascone/ascone-cloudformation`. The design assumes the original Phase-7 plan (Oracle Cloud Free Tier + Cloudflare Tunnel) is shelved in favour of the AWS path.

---

## 1. Why AWS Spot?

- **Cost**: ~$7.50/month all-in for a 1-user app — comparable to Oracle Free Tier with more flexibility.
- **Tooling**: reuses the operator's existing AWS account (`173635790352`) and the Ascone `manage-stack.py` ergonomics.
- **Tolerable interruption profile**: Eiswein is a daily-decision tool; an occasional 3-5 min Spot reclaim is invisible to the user as long as data persists.

Hard non-goals (carried forward from `CLAUDE.md`):
- `uvicorn --workers 1` (SQLite single-writer + APScheduler dedup).
- In-process APScheduler — serverless / scale-to-zero is forbidden.
- SQLite WAL persistence across instance termination.
- No plaintext secrets on disk.
- Zero public ingress ports — Cloudflare Tunnel is the canonical ingress.

---

## 2. Decisions locked in

| Choice | Decision | Rationale |
|---|---|---|
| Container runtime | Docker + docker-compose | Reuses Phase-7 multi-stage image work, easy Watchtower-driven CD, cloudflared sidecar |
| Public ingress | Cloudflare Tunnel + CF Access (Google OAuth) | $0/month, zero public ports on the VM, identity gating at edge |
| EBS persistence | Detached `AWS::EC2::Volume` reattached by tag | Zero data lag, simple, AZ-pinned (acceptable for 1-user) |
| Job-rerun guarantee | `SystemMetadata.last_daily_update_at` startup guard | Covers any outage length; small Eiswein code change |
| Image registry | GHCR | Lives inside the GitHub repo, free tier is plenty |
| Region | `us-east-2` (assumption — overridable in parameters file) | Matches existing AWS account |

Alternatives rejected (with reasons) and how-to-revisit notes:
- *AWS ALB + Cognito ingress* — ~$16/month for the ALB alone. Revisit only if dropping Cloudflare.
- *ASG + EBS-snapshot lifecycle for persistence* — adds EventBridge + Lambda + lifecycle policy; trade-off is cross-AZ tolerance, which doesn't matter for 1-user app.
- *systemd instead of Docker* — strictly simpler on the VM but discards the Dockerfile work; revisit only if the image becomes a maintenance burden.
- *ECR instead of GHCR* — fully AWS-native, cleaner IAM; adds OIDC role + ECR repo. Revisit if cross-cloud auth becomes a security concern.

---

## 3. Architecture overview

```
GitHub push to main
  └─> .github/workflows/deploy.yml
        └─> docker buildx (linux/arm64) → ghcr.io/ayou7995/eiswein:latest

CloudFormation stack (single template, us-east-2)
  ├─ Network:  VPC / 1 public subnet / IGW
  ├─ IAM:      Instance role (logs put, ec2 describe/attach own-tag volume,
  │            ssm get-parameter, kms decrypt, ssm session manager core)
  ├─ Secrets:  SSM Parameter Store SecureStrings under /eiswein/*
  ├─ Logs:     CloudWatch Logs group /eiswein/app, 30-day retention
  ├─ Storage:  AWS::EC2::Volume (gp3 30GB, encrypted, AZ-pinned,
  │            tag eiswein:role=data, DeletionPolicy: Retain)
  ├─ Backups:  AWS::DLM::LifecyclePolicy (daily EBS snapshot, 7-day retention)
  ├─ Compute:  AWS::EC2::LaunchTemplate (AL2023 ARM, t4g.small, IMDSv2-only,
  │            user-data inline)
  └─ Scaling:  AWS::AutoScalingGroup (min=0 max=1 desired=1, Spot-only,
               mixed [t4g.small, t4g.micro], capacity-optimized,
               Capacity Rebalancing on)

On Spot launch → user-data runs:
  1. Install docker, ssm-agent, aws-cli
  2. Look up persistent EBS by tag, attach as /dev/sdf, mount /mnt/data
     (mkfs.ext4 only if no FS yet)
  3. Fetch SSM SecureStrings → /opt/eiswein/.env (chmod 600)
  4. docker login ghcr.io with PAT from SSM
  5. Write docker-compose.yml (3 services: app + cloudflared + watchtower)
  6. docker compose up -d

App (FastAPI lifespan) on startup:
  - Existing: configure logging, build engine, seed admin, reap orphan
    BackfillJob rows, start APScheduler
  - NEW: maybe_run_missed_daily_update() — if today is NYSE trading day
    and SystemMetadata.last_daily_update_at < today, schedule a one-shot
    daily_update 30 sec from now
```

---

## 4. CloudFormation resources (concrete shape)

```yaml
# Resources block — abridged
VPC, PublicSubnet, IGW, IGWAttachment, RouteTable, Route, SubnetRouteTableAssoc

InstanceSecurityGroup:
  Egress: all
  Ingress: none  # cloudflared is outbound-only; SSM Session Manager too

InstanceRole + InstanceProfile:
  ManagedPolicies:
    - AmazonSSMManagedInstanceCore        # session manager + patching
    - CloudWatchAgentServerPolicy         # logs + metrics
  Inline:
    - ec2:DescribeVolumes (Resource *)    # tag filter checked at runtime
    - ec2:AttachVolume / DetachVolume     # condition: ResourceTag eiswein:role=data
    - ssm:GetParameter / GetParameters    # /eiswein/*
    - kms:Decrypt                         # the KMS key SSM uses

LogGroup: /eiswein/app  (RetentionInDays: 30)

DataVolume (AWS::EC2::Volume):
  AvailabilityZone: !Ref TargetAZ        # parameter, e.g. us-east-2a
  Size: 30
  VolumeType: gp3
  Encrypted: true
  Tags: eiswein:role=data, eiswein:env=prod
  DeletionPolicy: Retain
  UpdateReplacePolicy: Retain

SnapshotPolicy (AWS::DLM::LifecyclePolicy):
  Schedule: daily 04:00 UTC
  RetainRule: count=7
  TagSelector: eiswein:role=data

LaunchTemplate:
  ImageId: !Sub '{{resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64}}'
  InstanceType: t4g.small
  IamInstanceProfile: !Ref InstanceProfile
  SecurityGroupIds: [!Ref InstanceSecurityGroup]
  MetadataOptions: { HttpTokens: required }       # IMDSv2 only
  UserData: !Base64 [!Sub <bootstrap.sh contents>]
  TagSpecifications: eiswein:role=app

AutoScalingGroup:
  MinSize: 0, MaxSize: 1, DesiredCapacity: 1
  VPCZoneIdentifier: [!Ref PublicSubnet]
  MixedInstancesPolicy:
    LaunchTemplate: !Ref LaunchTemplate
    Overrides: [t4g.small, t4g.micro]
    InstancesDistribution:
      OnDemandPercentageAboveBaseCapacity: 0       # 100 % Spot
      SpotAllocationStrategy: capacity-optimized
  CapacityRebalance: true                          # proactive replace before reclaim
  HealthCheckType: EC2
  HealthCheckGracePeriod: 300
```

---

## 5. SSM Parameter Store layout

| Name | Type | Source / how to mint |
|---|---|---|
| `/eiswein/jwt_secret` | SecureString | `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `/eiswein/encryption_key` | SecureString | `python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` |
| `/eiswein/admin_username` | String | owner-chosen |
| `/eiswein/admin_password_hash` | SecureString | `python scripts/set_password.py` |
| `/eiswein/fred_api_key` | SecureString | https://fred.stlouisfed.org/docs/api |
| `/eiswein/cloudflared_tunnel_token` | SecureString | `cloudflared tunnel token <tunnel-id>` |
| `/eiswein/ghcr_pull_token` | SecureString | GitHub PAT, scope `read:packages` |
| `/eiswein/smtp_*` | SecureString | optional Gmail App Password |
| `/eiswein/schwab_*` | SecureString | optional Schwab developer-portal credentials |

The user-data script reads these into `/opt/eiswein/.env` (chmod 600) at boot. Rotation is a parameter overwrite + instance recycle.

---

## 6. User-data script outline (`infra/userdata/bootstrap.sh`)

1. `dnf update -y && dnf install -y docker docker-compose-plugin amazon-ssm-agent jq awscli`
2. `systemctl enable --now docker amazon-ssm-agent`
3. Read IMDSv2 token → `INSTANCE_ID`, `REGION`, `AZ`
4. `aws ec2 describe-volumes --filters tag:eiswein:role=data Name=availability-zone,Values=$AZ --query 'Volumes[0].VolumeId'`
5. If `State=available`, `aws ec2 attach-volume --device /dev/sdf`; loop until `Attachments[0].State=attached`.
6. Resolve actual NVMe device via `lsblk` matching the volume serial (EBS NVMe device names are non-deterministic).
7. `blkid` → `mkfs.ext4 -L eiswein-data` only if no FS exists.
8. Append `LABEL=eiswein-data /mnt/data ext4 defaults,nofail 0 2` to `/etc/fstab`, `mount /mnt/data`.
9. `aws ssm get-parameters --names /eiswein/...` → write to `/opt/eiswein/.env` (chmod 600).
10. `docker login ghcr.io -u ayou7995 --password-stdin` (token from SSM).
11. Write `/opt/eiswein/docker-compose.yml` (heredoc) with 3 services:
    - `app`: GHCR image, `env_file`, mount `/mnt/data:/app/data`, `awslogs` driver
    - `cloudflared`: `tunnel --no-autoupdate run --token $TOKEN`
    - `watchtower`: poll every 5 min, `--cleanup`, watch only `app`
12. `cd /opt/eiswein && docker compose up -d`.

Idempotency: re-running on a reboot finds the volume already attached, the FS already formatted, and `docker compose up` reconciles without recreating containers.

---

## 7. Eiswein code change required

| File | Change |
|---|---|
| `backend/app/jobs/startup_recovery.py` (NEW) | `maybe_run_missed_daily_update(session, settings, scheduler, data_source)` — reads `KEY_LAST_DAILY_UPDATE_AT` via `SystemMetadataRepository`; checks NYSE today via `pandas_market_calendars.get_calendar("NYSE")`; if missed schedules a `date`-trigger one-shot job at `now + 30 sec`. Reuses the existing `app/jobs/daily_update.py::run` wrapper. |
| `backend/app/main.py` | In `_lifespan`, after `start_scheduler(...)` succeeds, call the helper inside try/except (graceful-degradation per rule 14). |
| `backend/tests/jobs/test_startup_recovery.py` (NEW) | Cases: missed-on-trading-day schedules; weekend skips; already-ran-today skips; scheduler-not-started no-ops. |

Already verified in the codebase:
- `SystemMetadata` table + `SystemMetadataRepository` exist; `KEY_LAST_DAILY_UPDATE_AT` constant defined.
- `app/jobs/daily_update.py` already writes `last_daily_update_at` after a successful market-open run.
- No new migration needed.

---

## 8. CI/CD

`.github/workflows/deploy.yml`:
- Trigger: push to `main` and tag `v*`.
- Jobs:
  1. `tests` — reuse `ci.yml` (ruff, mypy, pytest, eslint, tsc, vitest).
  2. `build-and-push`:
     ```
     docker buildx build \
       --platform linux/arm64 \
       --tag ghcr.io/ayou7995/eiswein:latest \
       --tag ghcr.io/ayou7995/eiswein:${{ github.sha }} \
       --push .
     ```
- Auth: `GITHUB_TOKEN` via `permissions: packages: write` (no PAT needed for *push*; the PAT in SSM is only for *pull* from the instance).
- Watchtower on the instance polls every 5 min and atomically swaps the `app` container when `latest` moves.

---

## 9. File layout (when implementation begins)

```
infra/                                  NEW directory
├── cloudformation/
│   └── eiswein-stack.yaml              single monolithic template
├── parameters/
│   └── prod/
│       └── eiswein-stack-params.yaml   region, AZ, instance types, domain, EBS size
├── userdata/
│   └── bootstrap.sh                    extracted, Fn::Base64 + Fn::Sub'd into LaunchTemplate
├── manage-stack.py                     adapted from ascone — create/update/delete with change-set diff
├── scripts/
│   ├── seed_ssm_params.sh              interactive prompt → aws ssm put-parameter SecureString
│   ├── asg_pause.sh                    set desired=0 to save money
│   └── asg_resume.sh                   set desired=1 to bring app back
└── README.md                           operator runbook (bootstrap → deploy → recover → rollback)

Dockerfile                              NEW — multi-stage Node 20 → Python 3.12-slim ARM
.dockerignore                           NEW
docker-entrypoint.sh                    NEW — alembic upgrade head; exec uvicorn
docker-compose.yml                      NEW (root) — local-dev, single service

.github/workflows/deploy.yml            NEW

backend/app/jobs/startup_recovery.py    NEW
backend/app/main.py                     MODIFIED — lifespan calls startup_recovery
backend/tests/jobs/test_startup_recovery.py   NEW
```

---

## 10. One-time bootstrap runbook (future operator)

1. **AWS account** in region `us-east-2`; install AWS CLI + configure profile.
2. **Cloudflare**:
   - Add domain to Cloudflare (free plan).
   - `cloudflared tunnel create eiswein` → save tunnel ID + token.
   - `cloudflared tunnel route dns eiswein eiswein.<your-domain>`.
   - Cloudflare dashboard → Zero Trust → Access → Applications → create `eiswein.<your-domain>` with policy `include: emails ayou7995@gmail.com`.
3. **GitHub**:
   - Create PAT (`read:packages` only) for the instance to pull from GHCR.
4. **Generate secrets**:
   - `python scripts/set_password.py` (zxcvbn-validated bcrypt hash)
   - `python -c "import secrets; print(secrets.token_urlsafe(64))"` for `JWT_SECRET`
   - `python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"` for `ENCRYPTION_KEY`
5. **Seed SSM**: `bash infra/scripts/seed_ssm_params.sh` — interactively writes all SecureStrings.
6. **First image push**: push to `main` (or run the deploy workflow manually) so `ghcr.io/ayou7995/eiswein:latest` exists before stack creation.
7. **Stack create**: `python infra/manage-stack.py create --env prod --template eiswein-stack`. Wait for `CREATE_COMPLETE` (~5 min).
8. **SSM into the instance** to verify: `aws ssm start-session --target i-...`. Tail `journalctl -u cloud-init` and `docker compose logs -f`.
9. **Smoke test**: visit `https://eiswein.<your-domain>` → CF Access → Google login → app loads.

---

## 11. Verification plan

| Test | Steps | Expected |
|---|---|---|
| Cold launch | `manage-stack.py create` | ASG instance up in ~5 min, CF Access login works, dashboard renders |
| Volume persistence | `aws autoscaling set-desired-capacity --desired 0` then `--desired 1` | New instance comes up with same SQLite (decisions, watchlist intact) |
| Spot reclaim simulation | terminate the instance manually | ASG launches replacement; same volume reattached; app back in ~3-5 min |
| Missed daily_update | Stop ASG before 06:30 ET, restart 09:00 ET | App startup hook runs `daily_update` once; logs show `job_start job_name=daily_update` followed by SystemMetadata write |
| GHCR auto-deploy | git push to main | New image on GHCR; Watchtower swaps the app container within 5 min; `docker compose ps` shows new image SHA |
| DLM snapshots | Wait 24h | One snapshot tagged `eiswein:role=data`; after 8 days, oldest is GC'd |
| Cost (after 1 month) | AWS Cost Explorer | Total < $10; ec2-spot ~$3.65, ebs-volumes ~$2.40, ebs-snapshots ~$0.50, cloudwatch ~$0.50 |

---

## 12. Cost rough cut

| Component | Spec | $/month |
|---|---|---|
| EC2 Spot | t4g.small (2 vCPU, 2 GB) ARM | ~$3.65 |
| EBS gp3 | 30 GB encrypted | ~$2.40 |
| EBS snapshots (DLM) | ~7× incremental ~5 GB delta | ~$0.50 |
| CloudWatch Logs | < 1 GB/mo, 30-day retention | ~$0.50 |
| Data egress | < 5 GB | ~$0.45 |
| SSM Parameter Store | Standard tier, < 10 params | $0.00 |
| KMS (default key for EBS + SSM) | AWS-managed | $0.00 |
| **Total** | | **~$7.50** |

Domain (~$10/yr separate from AWS).

---

## 13. Out of scope (explicit)

- **Cross-AZ Spot fallback** — would force snapshot-restore lifecycle; not worth it for 1-user app.
- **HA / multi-instance** — incompatible with `--workers 1` + SQLite; do not attempt.
- **Off-AWS backup** — recommend later: weekly upload of `data/backups/*.db` to a small S3 bucket; ~$0.02/mo.
- **CloudWatch alarms** — recommend later: `ASG instance launch failure → SNS email`.
- **Production AGE-key/JWT-secret rotation runbooks** — existing `scripts/rotate_*` cover Eiswein-side; AWS-side is a parameter overwrite + instance recycle.
- **TLS at the AWS edge** — not needed; Cloudflare terminates at the tunnel ingress.

---

## 14. Suggested execution order (when work resumes)

1. **Eiswein code change** — write `backend/app/jobs/startup_recovery.py` + tests + wire into `_lifespan`. (No infra needed; testable locally.)
2. **Dockerfile + .dockerignore + entrypoint** — get `docker build` + `docker run` working locally.
3. **`.github/workflows/deploy.yml`** — push first image to GHCR via Actions.
4. **`infra/cloudformation/eiswein-stack.yaml`** + parameters + user-data + `manage-stack.py`. `cfn-lint` then `aws cloudformation validate-template`.
5. **Bootstrap secrets + Cloudflare + GHCR PAT** per runbook (§10).
6. **`manage-stack.py create --env prod`** — ride through `CREATE_COMPLETE`.
7. **Verification table** in order; fix any failure before moving on.
8. **Final security-auditor pass** on the new code + IaC.

---

## 15. References

- Reference IaC: `/Users/cheyulin/Adam/ascone/ascone-cloudformation/{cloudformation,parameters,manage-stack.py,deploy-ecs.py,CLAUDE.md}` — production-grade ECS Fargate IaC across 15 stacks; the source of the operational ergonomics this design borrows.
- Eiswein deployment context: [`DEPLOYMENT_CONTEXT.md`](DEPLOYMENT_CONTEXT.md) — broader app/infra summary suitable for pasting into any deployment LLM.
- Original Phase-7 plan (Cloudflare Tunnel + Oracle Free Tier flavour): [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) lines 814–902.
- Eiswein hard invariants: `CLAUDE.md` "Hard Operational Invariants".
- Verified existing assets in the codebase:
  - `SystemMetadata.KEY_LAST_DAILY_UPDATE_AT` (already written by `app/jobs/daily_update.py`)
  - `scripts/set_password.py`, `scripts/rotate_secrets.py`, `scripts/setup_secrets.sh`
  - `.github/workflows/ci.yml`
