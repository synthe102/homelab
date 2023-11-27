locals {
  velero_bucket_name = "velero-backups-synthe"
}
module "s3_bucket" {
  source = "terraform-aws-modules/s3-bucket/aws"

  bucket = local.velero_bucket_name
}

resource "aws_iam_user" "velero" {
  name = "velero"
}

resource "aws_iam_user_policy_attachment" "velero" {
  user       = aws_iam_user.velero.name
  policy_arn = aws_iam_policy.velero.arn
}

resource "aws_iam_access_key" "velero" {
  user = aws_iam_user.velero.id
}
resource "doppler_secret" "velero_access_key_id" {
  project = "homelab"
  config  = "main"
  name    = "VELERO_ACCESS_KEY_ID"
  value   = aws_iam_access_key.velero.id
}

resource "doppler_secret" "velero_secret_access_key" {
  project = "homelab"
  config  = "main"
  name    = "VELERO_SECRET_ACCESS_KEY"
  value   = aws_iam_access_key.velero.secret
}

resource "aws_iam_policy" "velero" {
  name   = "velero"
  policy = data.aws_iam_policy_document.velero.json
}

data "aws_iam_policy_document" "velero" {
  statement {
    sid       = ""
    effect    = "Allow"
    resources = ["*"]

    actions = [
      "ec2:DescribeVolumes",
      "ec2:DescribeSnapshots",
      "ec2:CreateTags",
      "ec2:CreateVolume",
      "ec2:CreateSnapshot",
      "ec2:DeleteSnapshot",
    ]
  }

  statement {
    sid       = ""
    effect    = "Allow"
    resources = ["arn:aws:s3:::${local.velero_bucket_name}/*"]

    actions = [
      "s3:GetObject",
      "s3:DeleteObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
  }

  statement {
    sid       = ""
    effect    = "Allow"
    resources = ["arn:aws:s3:::${local.velero_bucket_name}"]
    actions   = ["s3:ListBucket"]
  }
}
