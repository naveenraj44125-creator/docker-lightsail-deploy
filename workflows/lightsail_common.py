#!/usr/bin/env python3
"""
Common utilities for AWS Lightsail deployment workflows
Provides SSH connections, file operations, and AWS client management
"""

import boto3
import subprocess
import tempfile
import os
import time
import sys
import socket
from botocore.exceptions import ClientError, NoCredentialsError


class LightsailBase:
    """Base class for Lightsail operations with SSH and AWS functionality"""

    def __init__(self, instance_name, region='us-east-1'):
        self.instance_name = instance_name
        self.region = region
        try:
            self.lightsail = boto3.client('lightsail', region_name=region)
        except NoCredentialsError:
            print("❌ AWS credentials not found. Please configure AWS credentials.")
            sys.exit(1)

    def run_command(self, command, timeout=300, max_retries=1, verbose=False):
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    wait_time = min(5 + (attempt * 5), 20) if "GITHUB_ACTIONS" in os.environ else min(15 + (attempt * 10), 60)
                    print(f"🔄 Retry {attempt + 1}/{max_retries} — waiting {wait_time}s...")
                    time.sleep(wait_time)

                ssh_response = self.lightsail.get_instance_access_details(instanceName=self.instance_name)
                ssh_details = ssh_response['accessDetails']

                print(f"📡 Running command on {ssh_details['username']}@{ssh_details['ipAddress']}")

                self._log_command_to_instance(ssh_details, command)
                key_path, cert_path = self.create_ssh_files(ssh_details)

                try:
                    ssh_cmd = self._build_ssh_command(key_path, cert_path, ssh_details, command)
                    result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)

                    if result.returncode == 0:
                        print(f"✅ SUCCESS")
                        if result.stdout.strip():
                            print(result.stdout)
                        if result.stderr.strip():
                            print(result.stderr)
                        return True, result.stdout.strip()
                    else:
                        print(f"❌ FAILED (exit {result.returncode})")
                        if result.stdout.strip():
                            print(result.stdout)
                        if result.stderr.strip():
                            print(result.stderr)
                        error_msg = result.stderr.strip()
                        if max_retries > 1 and self._is_connection_error(error_msg) and attempt < max_retries - 1:
                            continue
                        return False, error_msg
                finally:
                    self._cleanup_ssh_files(key_path, cert_path)

            except subprocess.TimeoutExpired:
                print(f"⏰ Command timed out after {timeout}s")
                if attempt < max_retries - 1:
                    continue
                return False, f"Command timed out after {timeout}s"
            except Exception as e:
                error_msg = str(e)
                print(f"❌ Error: {error_msg}")
                if max_retries > 1 and self._is_connection_error(error_msg) and attempt < max_retries - 1:
                    continue
                return False, error_msg

        return False, "Max retries exceeded"

    def create_ssh_files(self, ssh_details):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False) as key_file:
            key_file.write(ssh_details['privateKey'])
            key_path = key_file.name

        cert_path = key_path + '-cert.pub'
        cert_parts = ssh_details['certKey'].split(' ', 2)
        formatted_cert = f'{cert_parts[0]} {cert_parts[1]}\n' if len(cert_parts) >= 2 else ssh_details['certKey'] + '\n'
        with open(cert_path, 'w') as cert_file:
            cert_file.write(formatted_cert)

        os.chmod(key_path, 0o600)
        os.chmod(cert_path, 0o600)
        return key_path, cert_path

    def copy_file_to_instance(self, local_path, remote_path, timeout=300):
        try:
            print(f"📤 Copying {local_path} to {remote_path}")
            ssh_response = self.lightsail.get_instance_access_details(instanceName=self.instance_name)
            ssh_details = ssh_response['accessDetails']
            key_path, cert_path = self.create_ssh_files(ssh_details)
            try:
                scp_cmd = [
                    'scp', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                    '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=30', '-o', 'IdentitiesOnly=yes',
                    local_path, f'{ssh_details["username"]}@{ssh_details["ipAddress"]}:{remote_path}'
                ]
                result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=timeout)
                if result.returncode == 0:
                    print("✅ File copied successfully")
                    return True
                else:
                    print(f"❌ Failed to copy file: {result.stderr.strip()}")
                    return False
            finally:
                self._cleanup_ssh_files(key_path, cert_path)
        except Exception as e:
            print(f"❌ Error copying file: {str(e)}")
            return False

    def get_instance_info(self):
        try:
            response = self.lightsail.get_instance(instanceName=self.instance_name)
            instance = response['instance']
            return {
                'name': instance['name'],
                'state': instance['state']['name'],
                'public_ip': instance.get('publicIpAddress'),
                'private_ip': instance.get('privateIpAddress'),
                'blueprint': instance.get('blueprintName'),
                'bundle': instance.get('bundleId')
            }
        except ClientError as e:
            print(f"❌ Error getting instance info: {e}")
            return None

    def wait_for_instance_state(self, target_state='running', timeout=300):
        print(f"⏳ Waiting for instance to be {target_state}...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self.lightsail.get_instance(instanceName=self.instance_name)
                current_state = response['instance']['state']['name']
                print(f"Instance state: {current_state}")
                if current_state == target_state:
                    print(f"✅ Instance is {target_state}")
                    return True
                elif current_state in ['stopped', 'stopping', 'terminated'] and target_state == 'running':
                    print(f"❌ Instance is in {current_state} state")
                    return False
                time.sleep(10)
            except ClientError as e:
                print(f"❌ Error checking instance state: {e}")
                return False
        print(f"❌ Timeout waiting for instance to be {target_state}")
        return False

    def test_ssh_connectivity(self, timeout=30, max_retries=3):
        print("🔍 Testing SSH connectivity...")
        if "GITHUB_ACTIONS" in os.environ:
            max_retries = min(max_retries, 3)
            timeout = min(timeout, 45)
        success, _ = self.run_command("echo 'SSH test successful'", timeout=timeout, max_retries=max_retries)
        if success:
            print("✅ SSH connectivity confirmed")
        else:
            print("❌ SSH connectivity failed")
        return success

    def test_network_connectivity(self):
        try:
            ssh_response = self.lightsail.get_instance_access_details(instanceName=self.instance_name)
            ip_address = ssh_response['accessDetails']['ipAddress']
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            result = sock.connect_ex((ip_address, 22))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _build_ssh_command(self, key_path, cert_path, ssh_details, command):
        import base64
        encoded_command = base64.b64encode(command.encode('utf-8')).decode('ascii')
        safe_command = f"echo '{encoded_command}' | base64 -d | bash"
        if "GITHUB_ACTIONS" in os.environ:
            return [
                'ssh', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=60', '-o', 'ServerAliveInterval=30',
                '-o', 'ServerAliveCountMax=6', '-o', 'ConnectionAttempts=3',
                '-o', 'IdentitiesOnly=yes', '-o', 'TCPKeepAlive=yes',
                '-o', 'BatchMode=yes', '-o', 'PreferredAuthentications=publickey',
                f'{ssh_details["username"]}@{ssh_details["ipAddress"]}', safe_command
            ]
        else:
            return [
                'ssh', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                '-o', 'ConnectTimeout=30', '-o', 'ServerAliveInterval=10',
                '-o', 'ServerAliveCountMax=3', '-o', 'IdentitiesOnly=yes',
                '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR',
                f'{ssh_details["username"]}@{ssh_details["ipAddress"]}', safe_command
            ]

    def _is_connection_error(self, error_msg):
        connection_errors = [
            'broken pipe', 'connection refused', 'connection timed out',
            'network unreachable', 'host unreachable', 'no route to host',
            'connection reset', 'ssh_exchange_identification', 'connection lost',
            'operation timed out', 'connect to host', 'timed out after'
        ]
        return any(phrase in error_msg.lower() for phrase in connection_errors)

    def _log_command_to_instance(self, ssh_details, command):
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
            log_entry = f"[{timestamp}] COMMAND: {command[:200]}"
            escaped = log_entry.replace("'", "'\"'\"'")
            log_cmd = f"sudo mkdir -p /var/log && echo '{escaped}' | sudo tee -a /var/log/deployment-commands.log > /dev/null"
            key_path, cert_path = self.create_ssh_files(ssh_details)
            try:
                ssh_cmd = [
                    'ssh', '-i', key_path, '-o', f'CertificateFile={cert_path}',
                    '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR',
                    f'{ssh_details["username"]}@{ssh_details["ipAddress"]}', log_cmd
                ]
                subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=15)
            finally:
                self._cleanup_ssh_files(key_path, cert_path)
        except Exception:
            pass

    def _cleanup_ssh_files(self, key_path, cert_path):
        try:
            if os.path.exists(key_path):
                os.unlink(key_path)
            if os.path.exists(cert_path):
                os.unlink(cert_path)
        except Exception:
            pass

    def get_command_log(self, lines=50):
        log_command = f"sudo tail -n {lines} /var/log/deployment-commands.log 2>/dev/null || echo 'No command log found'"
        return self.run_command(log_command, timeout=30, max_retries=1)
