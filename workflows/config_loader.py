#!/usr/bin/env python3
"""
Configuration loader for Docker deployment workflows
"""

import os
import yaml
from typing import Dict, Any, List


class DeploymentConfig:
    """Loads and provides access to deployment configuration"""

    def __init__(self, config_file: str = 'deployment-docker.config.yml'):
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        possible_paths = [
            self.config_file,
            os.path.join(os.path.dirname(__file__), '..', self.config_file),
            os.path.join(os.getcwd(), self.config_file)
        ]
        for path in possible_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    config = yaml.safe_load(f)
                    print(f"✅ Configuration loaded from: {path}")
                    return config
        raise FileNotFoundError(f"Config file not found. Searched: {possible_paths}")

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split('.')
        value = self.config
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def get_aws_region(self) -> str:
        return self.get('aws.region', 'us-east-1')

    def get_instance_name(self) -> str:
        return self.get('lightsail.instance_name', 'docker-app')

    def get_package_files(self) -> List[str]:
        return self.get('application.package_files', ['.'])

    def get_environment_variables(self) -> Dict[str, str]:
        return self.get('application.environment_variables', {})

    def get_health_check_config(self) -> Dict[str, Any]:
        return self.get('monitoring.health_check', {
            'endpoint': '/',
            'expected_content': 'OK',
            'max_attempts': 10,
            'wait_between_attempts': 15,
            'initial_wait': 60
        })

    def get_docker_compose_file(self) -> str:
        return self.get('deployment.docker_compose_file', 'docker-compose.yml')

    def get_docker_app_path(self) -> str:
        return self.get('deployment.docker_app_path', '/opt/docker-app')
