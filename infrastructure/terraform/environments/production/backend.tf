# Remote state — S3 backend with a DynamoDB lock table. Create the bucket+table
# once out-of-band (or via a bootstrap workspace) before `terraform init`.
# Values are placeholders; pass real ones via `-backend-config` or edit here.
terraform {
  backend "s3" {
    bucket         = "arenarank-tfstate"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "arenarank-tflock"
    encrypt        = true
  }
}
