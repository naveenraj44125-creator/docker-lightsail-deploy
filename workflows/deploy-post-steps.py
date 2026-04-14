#!/usr/bin/env python3
"""
Post-deployment steps for Docker on AWS Lightsail
Uploads the app package, runs docker compose up, and verifies containers
"""

import os
import sys
import argparse
from lightsail_common import LightsailBase
from config_loader import DeploymentConfig


class DockerPostDeployer:
    def __init__(self, instance_name=None, region=None, config=None):
        if config is None:
            config = DeploymentConfig()
        self.config = config
        self.client = LightsailBase(
            instance_name or config.get_instance_name(),
            region or config.get_aws_region()
        )

    def deploy(self, package_file: str, verify: bool = False, cleanup: bool = False,
               env_vars: dict = None) -> bool:
        print("=" * 60)
        print("🐳 DOCKER POST-DEPLOYMENT")
        print("=" * 60)
        print(f"📦 Package: {package_file}")

        app_path = self.config.get_docker_app_path()
        compose_file = self.config.get_docker_compose_file()

        # Upload package
        print("\n📤 Uploading application package...")
        if not self.client.copy_file_to_instance(package_file, f"~/{package_file}"):
            print("❌ Failed to upload package")
            return False

        # Extract package
        print("\n📦 Extracting package...")
        if not self._extract_package(package_file, app_path):
            print("❌ Failed to extract package")
            return False

        # Write .env file if env vars provided
        if env_vars:
            self._write_env_file(app_path, env_vars)

        # Run docker compose
        print("\n🐳 Starting Docker containers...")
        if not self._docker_compose_up(app_path, compose_file):
            print("❌ Docker Compose failed")
            return False

        # Verify
        if verify:
            print("\n🔍 Verifying deployment...")
            self._verify_containers(app_path, compose_file)

        # Cleanup
        if cleanup:
            self._cleanup(package_file)

        print("\n✅ Docker deployment completed successfully!")
        return True

    def _extract_package(self, package_file: str, app_path: str) -> bool:
        script = f'''
set -e
echo "Extracting {package_file} to {app_path}..."

# Backup existing deployment
if [ -d "{app_path}" ] && [ "$(ls -A {app_path} 2>/dev/null)" ]; then
    BACKUP="/var/backups/docker-app/$(date +%Y%m%d_%H%M%S)"
    sudo mkdir -p "$BACKUP"
    sudo cp -r {app_path}/* "$BACKUP/" 2>/dev/null || true
    echo "✅ Backup created at $BACKUP"
fi

# Extract
sudo mkdir -p {app_path}
EXTRACT_TMP=$(mktemp -d)
cd "$EXTRACT_TMP"
tar -xzf ~/{package_file}

# Find the app directory (handles wrapper dirs like example-docker-app/)
APP_DIR=$(find . -maxdepth 1 -type d ! -name "." | head -n 1)
if [ -n "$APP_DIR" ]; then
    echo "Found app directory: $APP_DIR"
    sudo cp -r "$APP_DIR"/. {app_path}/
else
    echo "No subdirectory found, copying all files directly"
    sudo cp -r . {app_path}/
fi

cd ~
rm -rf "$EXTRACT_TMP"

sudo chown -R ubuntu:ubuntu {app_path}
echo "✅ Package extracted to {app_path}"
ls -la {app_path}/ | head -20
'''
        success, _ = self.client.run_command(script, timeout=300)
        return success

    def _write_env_file(self, app_path: str, env_vars: dict):
        print("🌍 Writing environment variables...")
        env_lines = '\n'.join(f'{k}={v}' for k, v in env_vars.items())
        # Write config env vars from config file too
        config_env = self.config.get_environment_variables()
        for k, v in config_env.items():
            if k not in env_vars:
                env_lines += f'\n{k}={v}'

        script = f'''
set -e
cat > /tmp/deploy.env << 'ENVEOF'
{env_lines}
ENVEOF
sudo cp /tmp/deploy.env {app_path}/.env
sudo chown ubuntu:ubuntu {app_path}/.env
sudo chmod 600 {app_path}/.env
rm -f /tmp/deploy.env
echo "✅ .env file written"
'''
        self.client.run_command(script, timeout=30)

    def _docker_compose_up(self, app_path: str, compose_file: str) -> bool:
        script = f'''
set -e
cd {app_path}

# Verify compose file exists
if [ ! -f "{compose_file}" ]; then
    echo "❌ Compose file not found: {compose_file}"
    ls -la
    exit 1
fi

echo "📋 Compose file found: {compose_file}"

# Pull latest images
echo "⬇️  Pulling images..."
docker compose -f {compose_file} pull 2>/dev/null || true

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker compose -f {compose_file} down --remove-orphans 2>/dev/null || true

# Start containers
echo "🚀 Starting containers..."
docker compose -f {compose_file} up -d --build

# Wait for containers to start
echo "⏳ Waiting for containers to initialize..."
sleep 15

# Show container status
echo "📊 Container status:"
docker compose -f {compose_file} ps

echo "✅ Docker Compose up completed"
'''
        success, _ = self.client.run_command(script, timeout=600)
        return success

    def _verify_containers(self, app_path: str, compose_file: str):
        script = f'''
set +e
cd {app_path}
echo "🔍 Verifying containers..."
docker compose -f {compose_file} ps
echo ""
echo "📋 Container logs (last 20 lines each):"
docker compose -f {compose_file} logs --tail=20
echo ""
echo "🌐 Testing HTTP response..."
for i in 1 2 3 4 5; do
    HTTP=$(curl -s -o /dev/null -w "%{{http_code}}" --connect-timeout 5 http://localhost/ 2>/dev/null || echo "000")
    echo "Attempt $i: HTTP $HTTP"
    if [ "$HTTP" = "200" ]; then
        echo "✅ Application is responding"
        exit 0
    fi
    sleep 10
done
echo "⚠️  Application not responding after 5 attempts"
'''
        self.client.run_command(script, timeout=120)

    def _cleanup(self, package_file: str):
        print("🧹 Cleaning up...")
        script = f'''
rm -f ~/{package_file}
docker system prune -f 2>/dev/null || true
echo "✅ Cleanup done"
'''
        self.client.run_command(script, timeout=60)


def main():
    parser = argparse.ArgumentParser(description='Docker post-deployment for AWS Lightsail')
    parser.add_argument('package_file', help='Application package (.tar.gz)')
    parser.add_argument('--instance-name')
    parser.add_argument('--region')
    parser.add_argument('--config-file', default='deployment-docker.config.yml')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--cleanup', action='store_true')
    parser.add_argument('--env', action='append', help='KEY=VALUE env vars')
    args = parser.parse_args()

    try:
        config = DeploymentConfig(config_file=args.config_file)
        deployer = DockerPostDeployer(args.instance_name, args.region, config)

        env_vars = {}
        if args.env:
            for e in args.env:
                if '=' in e:
                    k, v = e.split('=', 1)
                    env_vars[k] = v

        if deployer.deploy(args.package_file, verify=args.verify, cleanup=args.cleanup, env_vars=env_vars):
            print("🎉 Post-deployment completed!")
            sys.exit(0)
        else:
            print("❌ Post-deployment failed")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
