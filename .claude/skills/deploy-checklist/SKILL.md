---
name: deploy-checklist
description: Use when deploying to EC2. Walks the secrets and teardown checklist so nothing gets skipped under time pressure.
---

1. Confirm no secret is hardcoded -- grep the repo for your own API keys before committing.
2. Secrets pulled from AWS SSM Parameter Store, not .env, in production.
3. EC2 instance uses an IAM role -- never long-lived AWS credentials on the box.
4. This is a demo deployment, not always-on: after recording/demoing, terminate the instance.
