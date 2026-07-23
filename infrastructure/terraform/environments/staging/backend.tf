terraform {
  backend "s3" {
    bucket         = "arenarank-tfstate"
    key            = "staging/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "arenarank-tflock"
    encrypt        = true
  }
}
