# State must survive between deploys; the runner's disk is ephemeral. The
# bucket name intentionally matches the clipforge-demo-quota* prefix the
# deploy IAM policy already allows. No DynamoDB lock table - deploys are
# manual and rare, so optimistic S3-only locking is accepted here.
terraform {
  backend "s3" {
    bucket = "clipforge-demo-quota-tfstate"
    key    = "clipforge-demo.tfstate"
    region = "us-east-1"
  }
}
