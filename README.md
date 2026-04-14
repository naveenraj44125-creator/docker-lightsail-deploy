# Docker Lightsail Deploy

AWS Lightsail deployment automation for **Docker applications only**, using GitHub Actions with OIDC authentication.

## Quick Start

### 1. Configure

Edit `deployment-docker.config.yml`:

```yaml
lightsail:
  instance_name: my-docker-app   # Lightsail instance name

application:
  name: my-docker-app
  package_files:
    - "example-docker-app/"      # Directory containing your docker-compose.yml
```

### 2. Set up AWS OIDC + IAM

```bash
./setup.sh
```

This creates:
- OIDC provider in AWS
- IAM role with Lightsail access
- `AWS_ROLE_ARN` variable in your GitHub repo

### 3. Deploy

Push to `main` — GitHub Actions handles the rest.

```
git push origin main
```

---

## How It Works

```
Push to main
    ↓
setup job       — provisions Lightsail instance (creates if missing), validates 2GB+ RAM
    ↓
package job     — tars your app files into app.tar.gz
    ↓
pre-deploy job  — installs Docker + Docker Compose on the instance
    ↓
deploy job      — uploads package, runs docker compose up -d --build
    ↓
verify job      — checks HTTP 200 response
```

## Instance Requirements

Docker requires **minimum 2GB RAM**. The workflow blocks deployment on undersized instances.

| Bundle | RAM | vCPU | Storage | Price |
|--------|-----|------|---------|-------|
| `small_3_0` | 2 GB | 2 | 60 GB | $12/mo |
| `medium_3_0` | 4 GB | 2 | 80 GB | $24/mo ← default |
| `large_3_0` | 8 GB | 2 | 160 GB | $44/mo |

Override in config:
```yaml
lightsail:
  bundle_id: large_3_0
```

## Your Docker App

Your app directory must contain a `docker-compose.yml`. The deployment:

1. Extracts your package to `/opt/docker-app/` on the instance
2. Writes a `.env` file from `application.environment_variables` in the config
3. Runs `docker compose up -d --build`

Example structure:
```
my-app/
├── docker-compose.yml   ← required
├── Dockerfile
└── ...
```

## Optional: Lightsail Bucket (S3-compatible storage)

```yaml
lightsail:
  bucket:
    enabled: true
    name: my-app-bucket
    access_level: read_write
    bundle_id: small_1_0   # 250GB
```

## Project Structure

```
docker-lightsail-deploy/
├── .github/workflows/deploy.yml     # GitHub Actions pipeline
├── workflows/
│   ├── setup_instance.py            # Provision Lightsail instance
│   ├── deploy-pre-steps.py          # Install Docker on instance
│   ├── deploy-post-steps.py         # Upload & run docker compose
│   ├── lightsail_common.py          # SSH + AWS utilities
│   ├── lightsail_bucket.py          # Bucket management
│   ├── config_loader.py             # YAML config loader
│   └── os_detector.py               # Blueprint → OS detection
├── example-docker-app/
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── index.html
├── deployment-docker.config.yml     # Main config file
└── setup.sh                         # OIDC + IAM bootstrap script
```
