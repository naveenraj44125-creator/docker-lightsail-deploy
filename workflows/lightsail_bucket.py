#!/usr/bin/env python3
"""
Lightsail Bucket Management — create, attach, and manage Lightsail S3-compatible buckets
"""

import boto3
import time
from typing import Dict, Optional, Tuple
from botocore.exceptions import ClientError


class LightsailBucket:
    def __init__(self, region: str = 'us-east-1'):
        self.region = region
        self.client = boto3.client('lightsail', region_name=region)

    def bucket_exists(self, bucket_name: str) -> bool:
        try:
            self.client.get_buckets(bucketName=bucket_name)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'NotFoundException':
                return False
            raise

    def create_bucket(self, bucket_name: str, bundle_id: str = 'small_1_0', tags: Optional[Dict] = None) -> Dict:
        print(f"📦 Creating bucket: {bucket_name} ({bundle_id})")
        params = {'bucketName': bucket_name, 'bundleId': bundle_id}
        if tags:
            params['tags'] = [{'key': k, 'value': v} for k, v in tags.items()]
        response = self.client.create_bucket(**params)

        for _ in range(12):
            time.sleep(5)
            info = self.get_bucket_info(bucket_name)
            if info and info.get('state', {}).get('name') == 'OK':
                print("✅ Bucket created successfully")
                return info
        print("⚠️  Bucket creation timeout")
        return response.get('bucket', {})

    def get_bucket_info(self, bucket_name: str) -> Optional[Dict]:
        try:
            response = self.client.get_buckets(bucketName=bucket_name)
            buckets = response.get('buckets', [])
            return buckets[0] if buckets else None
        except ClientError as e:
            if e.response['Error']['Code'] == 'NotFoundException':
                return None
            raise

    def set_instance_access(self, bucket_name: str, instance_name: str, access_level: str = 'read_only') -> bool:
        print(f"🔗 Attaching bucket '{bucket_name}' to instance '{instance_name}' ({access_level})")
        access_map = {'read_only': 'read-only', 'read_write': 'read-write',
                      'read-only': 'read-only', 'read-write': 'read-write'}
        try:
            self.client.set_resource_access_for_bucket(
                resourceName=instance_name,
                bucketName=bucket_name,
                access=access_map.get(access_level, 'read-only')
            )
            print("✅ Instance access configured")
            return True
        except ClientError as e:
            print(f"❌ Error setting access: {e.response['Error']['Message']}")
            return False

    def setup_bucket_for_instance(self, bucket_name: str, instance_name: str,
                                   access_level: str = 'read_only', bundle_id: str = 'small_1_0',
                                   create_if_missing: bool = True) -> Tuple[bool, str]:
        print(f"\n{'='*60}\n🪣 Setting up Lightsail Bucket\n{'='*60}")

        if self.bucket_exists(bucket_name):
            print(f"✅ Bucket already exists: {bucket_name}")
        else:
            if not create_if_missing:
                return False, f"Bucket {bucket_name} does not exist"
            try:
                info = self.create_bucket(bucket_name, bundle_id,
                                          tags={'ManagedBy': 'GitHub-Actions', 'Instance': instance_name})
                if not info:
                    return False, "Failed to create bucket"
            except Exception as e:
                return False, f"Error creating bucket: {str(e)}"

        if not self.set_instance_access(bucket_name, instance_name, access_level):
            return False, "Failed to attach bucket to instance"

        info = self.get_bucket_info(bucket_name)
        if info:
            print(f"\n✅ Bucket Setup Complete")
            print(f"   Name: {bucket_name} | URL: {info.get('url', 'N/A')} | Access: {access_level}")

        return True, f"Bucket {bucket_name} configured successfully"
