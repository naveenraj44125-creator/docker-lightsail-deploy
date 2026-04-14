#!/usr/bin/env python3
"""
OS Detection Utility — detects OS and package manager from Lightsail blueprint
"""

import re
from typing import Tuple, Dict, Any


class OSDetector:
    OS_PATTERNS = {
        'ubuntu': {
            'patterns': [r'ubuntu'],
            'package_manager': 'apt',
            'service_manager': 'systemd',
            'user': 'ubuntu'
        },
        'amazon_linux': {
            'patterns': [r'amazon.*linux', r'amzn'],
            'package_manager': 'yum',
            'service_manager': 'systemd',
            'user': 'ec2-user'
        },
        'centos': {
            'patterns': [r'centos'],
            'package_manager': 'yum',
            'service_manager': 'systemd',
            'user': 'centos'
        },
        'rhel': {
            'patterns': [r'rhel', r'red.*hat'],
            'package_manager': 'yum',
            'service_manager': 'systemd',
            'user': 'ec2-user'
        }
    }

    @classmethod
    def detect_os_from_blueprint(cls, blueprint_id: str, blueprint_name: str = "") -> Tuple[str, Dict[str, str]]:
        search_text = f"{blueprint_id} {blueprint_name}".lower()
        for os_type, os_config in cls.OS_PATTERNS.items():
            for pattern in os_config['patterns']:
                if re.search(pattern, search_text, re.IGNORECASE):
                    return os_type, {
                        'package_manager': os_config['package_manager'],
                        'service_manager': os_config['service_manager'],
                        'user': os_config['user']
                    }
        # Default to Ubuntu
        return 'ubuntu', {'package_manager': 'apt', 'service_manager': 'systemd', 'user': 'ubuntu'}

    @classmethod
    def get_package_manager_commands(cls, package_manager: str) -> Dict[str, str]:
        if package_manager == 'apt':
            return {
                'update': 'sudo apt-get update -qq',
                'install': 'sudo DEBIAN_FRONTEND=noninteractive apt-get install -y',
                'fix_broken': 'sudo dpkg --configure -a && sudo apt-get install -f -y'
            }
        else:
            return {
                'update': 'sudo yum update -y',
                'install': 'sudo yum install -y',
                'fix_broken': 'sudo yum clean all && sudo yum makecache'
            }

    @classmethod
    def get_service_commands(cls, service_manager: str) -> Dict[str, str]:
        return {
            'start': 'sudo systemctl start',
            'stop': 'sudo systemctl stop',
            'restart': 'sudo systemctl restart',
            'enable': 'sudo systemctl enable',
            'status': 'sudo systemctl status',
            'is_active': 'systemctl is-active --quiet',
            'reload': 'sudo systemctl daemon-reload'
        }

    @classmethod
    def get_user_info(cls, os_type: str, web_server: str = 'docker') -> Dict[str, str]:
        configs = {
            'ubuntu': {'default_user': 'ubuntu', 'web_user': 'ubuntu', 'web_group': 'ubuntu'},
            'amazon_linux': {'default_user': 'ec2-user', 'web_user': 'ec2-user', 'web_group': 'ec2-user'},
            'centos': {'default_user': 'centos', 'web_user': 'centos', 'web_group': 'centos'},
            'rhel': {'default_user': 'ec2-user', 'web_user': 'ec2-user', 'web_group': 'ec2-user'},
        }
        return configs.get(os_type, configs['ubuntu'])
