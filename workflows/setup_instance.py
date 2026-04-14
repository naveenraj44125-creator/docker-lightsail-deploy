#!/usr/bin/env python3
"""
Instance setup for Docker deployments on AWS Lightsail
Creates or validates the Lightsail instance and writes GitHub Actions outputs
"""

import yaml
import os
import sys
import boto3
import time
from os_detector import OSDetector

MIN_DOCKER_RAM_GB = 2.0


def main():
    config_file = os.environ.get('CONFIG_FILE', 'deployment-docker.config.yml')
    instance_name_override = os.environ.get('INSTANCE_NAME', '')
    aws_region_override = os.environ.get('AWS_REGION', '')

    print(f"🔧 Loading configuration from {config_file}...")
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    instance_name = instance_name_override or config['lightsail']['instance_name']
    aws_region = aws_region_override or config['aws']['region']
    app_name = config['application']['name']
    app_type = config['application']['type']
    app_version = config['application']['version']

    print(f"✅ Instance: {instance_name} | Region: {aws_region}")
    print(f"✅ App: {app_name} v{app_version} ({app_type})")

    lightsail = boto3.client('lightsail', region_name=aws_region)
    static_ip = ""
    os_type = 'ubuntu'
    package_manager = 'apt'

    try:
        print(f"\n🔍 Checking if instance '{instance_name}' exists...")
        response = lightsail.get_instance(instanceName=instance_name)
        instance = response['instance']
        print(f"✅ Instance exists — state: {instance['state']['name']}")

        blueprint_id = instance.get('blueprintId', '')
        blueprint_name = instance.get('blueprintName', '')
        detector = OSDetector()
        os_type, os_info = detector.detect_os_from_blueprint(blueprint_id)
        package_manager = os_info['package_manager']
        print(f"🖥️  OS: {os_type} | Package manager: {package_manager}")

        # Validate RAM for Docker
        ram_gb = instance.get('hardware', {}).get('ramSizeInGb', 0)
        bundle_id = instance.get('bundleId', '')
        print(f"\n🐳 Docker RAM check: {ram_gb} GB (bundle: {bundle_id})")

        if ram_gb < MIN_DOCKER_RAM_GB:
            print(f"❌ Insufficient RAM: {ram_gb} GB < {MIN_DOCKER_RAM_GB} GB required")
            print("   Upgrade to small_3_0 (2GB), medium_3_0 (4GB), or larger")
            _write_outputs(instance_name, '', aws_region, app_name, app_type, app_version,
                           False, os_type, package_manager)
            sys.exit(1)

        print(f"✅ RAM validated: {ram_gb} GB")

        static_ip = instance.get('publicIpAddress', '')
        print(f"✅ Public IP: {static_ip}")

        # Ensure firewall ports are open
        _open_firewall_ports(lightsail, instance_name, config)

        # Setup bucket if configured
        _setup_bucket(config, instance_name, aws_region)

    except lightsail.exceptions.NotFoundException:
        print(f"⚠️  Instance not found — creating...")

        bundle_id = config.get('lightsail', {}).get('bundle_id', 'medium_3_0')
        blueprint_id = config.get('lightsail', {}).get('blueprint_id', 'ubuntu_22_04')
        print(f"📋 Blueprint: {blueprint_id} | Bundle: {bundle_id}")

        # Validate bundle for Docker
        docker_min_bundles = ['small_3_0', 'medium_3_0', 'large_3_0', 'xlarge_3_0', '2xlarge_3_0']
        if bundle_id not in docker_min_bundles:
            print(f"⚠️  Bundle '{bundle_id}' may be too small for Docker. Recommended: medium_3_0")

        try:
            lightsail.create_instances(
                instanceNames=[instance_name],
                availabilityZone=f'{aws_region}a',
                blueprintId=blueprint_id,
                bundleId=bundle_id,
                tags=[
                    {'key': 'Application', 'value': app_name},
                    {'key': 'ManagedBy', 'value': 'GitHub-Actions'},
                    {'key': 'Type', 'value': 'docker'}
                ]
            )
            print(f"✅ Instance creation initiated")

            # Wait for running state
            print("⏳ Waiting for instance to be running...")
            for elapsed in range(0, 300, 10):
                time.sleep(10)
                try:
                    response = lightsail.get_instance(instanceName=instance_name)
                    instance = response['instance']
                    state = instance['state']['name']
                    print(f"   State: {state} ({elapsed+10}s)")
                    if state == 'running' and 'publicIpAddress' in instance:
                        static_ip = instance['publicIpAddress']
                        print(f"✅ Instance running — IP: {static_ip}")
                        break
                except Exception:
                    pass

            if not static_ip:
                print("❌ Instance did not get a public IP within timeout")
                sys.exit(1)

            # Detect OS
            detector = OSDetector()
            os_type, os_info = detector.detect_os_from_blueprint(blueprint_id)
            package_manager = os_info['package_manager']

            # Open firewall ports
            _open_firewall_ports(lightsail, instance_name, config)

            # Setup bucket if configured
            _setup_bucket(config, instance_name, aws_region)

        except Exception as e:
            print(f"❌ Failed to create instance: {e}")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

    # Verification settings
    verification_port = config.get('monitoring', {}).get('health_check', {}).get('port', 80)
    verification_path = '/'

    print(f"\n✅ Setup complete — IP: {static_ip} | Port: {verification_port}")
    _write_outputs(instance_name, static_ip, aws_region, app_name, app_type, app_version,
                   True, os_type, package_manager, verification_port, verification_path)
    print("✅ Instance setup completed successfully!")


def _open_firewall_ports(lightsail, instance_name: str, config: dict):
    allowed_ports = config.get('deployment', {}).get('firewall', {}).get('allowed_ports', [22, 80, 443])
    port_infos = [{'fromPort': int(p), 'toPort': int(p), 'protocol': 'tcp'} for p in allowed_ports]
    try:
        lightsail.put_instance_public_ports(portInfos=port_infos, instanceName=instance_name)
        print(f"✅ Firewall ports open: {allowed_ports}")
    except Exception as e:
        print(f"⚠️  Could not update firewall: {e}")


def _setup_bucket(config: dict, instance_name: str, aws_region: str):
    bucket_config = config.get('lightsail', {}).get('bucket', {})
    if not bucket_config.get('enabled', False):
        print("ℹ️  Lightsail bucket not configured")
        return
    bucket_name = bucket_config.get('name', '')
    if not bucket_name:
        print("⚠️  Bucket enabled but no name specified")
        return
    try:
        sys.path.insert(0, 'workflows')
        from lightsail_bucket import LightsailBucket
        bm = LightsailBucket(region=aws_region)
        success, message = bm.setup_bucket_for_instance(
            bucket_name=bucket_name,
            instance_name=instance_name,
            access_level=bucket_config.get('access_level', 'read_only'),
            bundle_id=bucket_config.get('bundle_id', 'small_1_0')
        )
        print(f"{'✅' if success else '⚠️ '} {message}")
    except ImportError:
        print("⚠️  lightsail_bucket module not available")


def _write_outputs(instance_name, static_ip, aws_region, app_name, app_type, app_version,
                   should_deploy, os_type, package_manager, verification_port=80, verification_path='/'):
    if 'GITHUB_OUTPUT' not in os.environ:
        return
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f"instance_name={instance_name}\n")
        f.write(f"static_ip={static_ip}\n")
        f.write(f"aws_region={aws_region}\n")
        f.write(f"app_name={app_name}\n")
        f.write(f"app_type={app_type}\n")
        f.write(f"app_version={app_version}\n")
        f.write(f"should_deploy={str(should_deploy).lower()}\n")
        f.write(f"os_type={os_type}\n")
        f.write(f"package_manager={package_manager}\n")
        f.write(f"verification_port={verification_port}\n")
        f.write(f"verification_path={verification_path}\n")


if __name__ == '__main__':
    main()
