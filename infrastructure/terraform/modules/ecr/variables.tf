variable "repository_name" {
  type    = string
  default = "arenarank-backend"
}

variable "image_tag_mutability" {
  type    = string
  default = "IMMUTABLE"
}

variable "keep_last_images" {
  type    = number
  default = 30
}

variable "tags" {
  type    = map(string)
  default = {}
}
