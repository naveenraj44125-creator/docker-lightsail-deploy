#!/usr/bin/env python3
"""
Pre-deployment steps for Docker on AWS Lightsail
Installs Docker + Docker Compose, validates instance RAM, and prepares directories
"""

import os
import sys
import time
import argparse
from lightsail_common import LightsailBase
from config_loader import DeploymentConfig


MIN_DOCKER_RAM_GB = 2.0


class DockerPreDeployer:
    def __init__(self, instance_name=None, region=None, config=None):
        if config is None:
            config = DeploymentConfig()
        self.config = config
        self.client = LightsailBase(
            instance_name or config.get_instance_name(),
            region or config.get_aws_region()
        )

    def prepare_environment(self) -> bool:
        print("=" * 60)
        print("🐳 DOCKER PRE-DEPLOYMENT")
        print("=" * 60)

        # Verify instance is running
        if not self._verify_instance_running():
            return False

        # Validate RAM for Docker
        if not self._validate_instance_ram():
            return False

        # System health check
        self._system_health_check()

        # Install Docker
        if not self._install_docker():
            print("❌ Docker installation failed")
            return False

        # Prepare app directory
        if not self._prepare_app_directory():
            print("❌ Failed to prepare app directory")
            return False

        print("\n✅ Pre-deployment completed successfully")
        return True

    def _verify_instance_running(self) -> bool:
        print("🔍 Verifying instance state...")
        try:
            response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
            instance = response['instance']
            state = instance['state']['name']
            print(f"   State: {state} | IP: {instance.get('publicIpAddress', 'N/A')}")

            if state == 'running':
                print("✅ Instance is running")
                return True

            if state in ['pending', 'rebooting']:
                print("⏳ Waiting for instance to be ready...")
                for i in range(6):
                    time.sleep(30)
                    response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
                    state = response['instance']['state']['name']
                    print(f"   Wait {i+1}/6: {state}")
                    if state == 'running':
                        print("✅ Instance is now running")
                        return True
                print("❌ Instance did not reach running state")
                return False

            print(f"❌ Instance is in unexpected state: {state}")
            return False
        except Exception as e:
            print(f"❌ Cannot access instance: {e}")
            return False

    def _validate_instance_ram(self) -> bool:
        print("\n🔍 Validating instance RAM for Docker...")
        try:
            response = self.client.lightsail.get_instance(instanceName=self.client.instance_name)
            instance = response['instance']
            ram_gb = instance.get('hardware', {}).get('ramSizeInGb', 0)
            bundle_id = instance.get('bundleId', 'unknown')
            print(f"   RAM: {ram_gb} GB | Bundle: {bundle_id}")

            if ram_gb < MIN_DOCKER_RAM_GB:
                print(f"❌ Insufficient RAM: {ram_gb} GB (minimum {MIN_DOCKER_RAM_GB} GB required for Docker)")
                print("   Recommended bundles: small_3_0 (2GB), medium_3_0 (4GB), large_3_0 (8GB)")
                return False

            print(f"✅ RAM validated: {ram_gb} GB is sufficient for Docker")
            return True
        except Exception as e:
            print(f"⚠️  Could not validate RAM: {e} — continuing anyway")
            return True

    def _system_health_check(self):
        print("\n🏥 System health check...")
        script = '''
set +e
echo "Disk: $(df -h / | tail -1 | awk '{print $3"/"$2" ("$5" used)"}')"
echo "Memory: $(free -h | grep Mem | awk '{print $3"/"$2}')"
if sudo dpkg --audit 2>&1 | grep -q "broken"; then
    echo "⚠️  dpkg broken state detected, fixing..."
    sudo dpkg --configure -a
    sudo apt-get install -f -y
fi
echo "✅ Health check done"
'''
        self.client.run_command(script, timeout=120)

    def _install_docker(self) -> bool:
        print("\n🐳 Installing Docker...")

        # Check if already installed
        check_success, _ = self.client.run_command(
            "docker --version && docker compose version", timeout=15, max_retries=1
        )
        if check_success:
            print("✅ Docker already installed, skipping")
            return True

        script = '''
set -e
echo "Installing Docker..."

# Remove old versions
sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Install prerequisites
sudo apt-get update -qq
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Add Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update -qq
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Add ubuntu user to docker group
sudo usermod -aG docker ubuntu || true

# Verify
docker --version
docker compose version

echo "✅ Docker installed successfully"
'''
        success, output = self.client.run_command(script, timeout=300)
        if success:
            print("✅ Docker installation complete")
        return success

    def _prepare_app_directory(self) -> bool:
        app_path = self.config.get_docker_app_path()
        print(f"\n📁 Preparing app directory: {app_path}")
        script = f'''
set -e
sudo mkdir -p {app_path}
sudo chown ubuntu:ubuntu {app_path}
sudo chmod 755 {app_path}
echo "✅ App directory ready: {app_path}"
'''
        success, _ = self.client.run_command(script, timeout=30)
        return success


def main():
    parser = argparse.ArgumentParser(description='Docker pre-deployment for AWS Lightsail')
    parser.add_argument('--instance-name')
    parser.add_argument('--region')
    parser.add_argument('--config-file', default='deployment-docker.config.yml')
    args = parser.parse_args()

    try:
        config = DeploymentConfig(config_file=args.config_file)
        deployer = DockerPreDeployer(args.instance_name, args.region, config)

        if deployer.prepare_environment():
            print("🎉 Pre-deployment steps completed!")
            sys.exit(0)
        else:
            print("❌ Pre-deployment steps failed")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
